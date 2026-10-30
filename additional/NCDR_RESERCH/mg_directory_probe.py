from pathlib import Path
from collections import Counter
import struct
import zlib

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"

SETS = {
    "7185": (
        Path("/Volumes/CD_7185/DB"),
        ["IZ.MG1", "IZ.MG2", "IZ.MG3"],
    ),
    "7186": (
        Path("/Volumes/CD_7186/DB"),
        ["SCZ.MG1", "SCZ.MG2", "SCZ.MG3"],
    ),
}

HEADER_SIZE = 0x72
ENTRY_SIZE = 0x1C


def valid_header(data, off):
    if off + 2 > len(data):
        return False

    cmf = data[off]
    flg = data[off + 1]

    return (
        (cmf & 0x0F) == 8
        and (cmf >> 4) <= 7
        and ((cmf << 8) | flg) % 31 == 0
    )


def parse_stream(data, start):
    d = zlib.decompressobj()
    raw = d.decompress(data[start:])

    if not d.eof:
        raise RuntimeError(
            f"stream at 0x{start:X} did not terminate"
        )

    consumed = len(data[start:]) - len(d.unused_data)
    end = start + consumed

    raw += d.flush()

    return {
        "start": start,
        "end": end,
        "packed": end - start,
        "raw": len(raw),
        "adler": int.from_bytes(data[end-4:end], "big"),
    }


def enumerate_streams(data, start):
    streams = []
    pos = start

    while pos < len(data):

        if not valid_header(data, pos):
            raise RuntimeError(
                f"expected zlib at 0x{pos:X}, "
                f"got {data[pos:pos+8].hex()}"
            )

        s = parse_stream(data, pos)
        streams.append(s)
        pos = s["end"]

    return streams


def values_for_stream(s, first_stream):
    return {
        "start_abs": s["start"],
        "end_abs": s["end"],
        "start_rel": s["start"] - first_stream,
        "end_rel": s["end"] - first_stream,
        "packed": s["packed"],
        "raw": s["raw"],
        "adler": s["adler"],
    }


report = OUT / "mg_directory_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for dataset, (root, names) in SETS.items():

        print("=" * 90, file=out)
        print("DATASET:", dataset, file=out)

        for name in names:

            path = root / name
            data = path.read_bytes()

            # First 78 DA after directory/header.
            first = data.find(b"\x78\xDA")

            if first < 0:
                raise RuntimeError(f"{name}: no 78 DA")

            n_from_prefix = (first - HEADER_SIZE) // ENTRY_SIZE

            expected_first = (
                HEADER_SIZE
                + n_from_prefix * ENTRY_SIZE
            )

            print(file=out)
            print("-" * 90, file=out)
            print("FILE:", name, file=out)
            print("SIZE:", len(data), file=out)
            print(
                f"FIRST STREAM: 0x{first:X}",
                file=out,
            )
            print(
                f"HEADER SIZE: 0x{HEADER_SIZE:X}",
                file=out,
            )
            print(
                f"ENTRY SIZE: 0x{ENTRY_SIZE:X}",
                file=out,
            )
            print(
                "DIRECTORY ENTRIES:",
                n_from_prefix,
                file=out,
            )
            print(
                "FORMULA CHECK:",
                first == expected_first,
                file=out,
            )

            print(
                "GLOBAL HEADER HEX:",
                data[:HEADER_SIZE].hex(),
                file=out,
            )

            printable = "".join(
                chr(x) if 32 <= x < 127 else "."
                for x in data[:HEADER_SIZE]
            )

            print(
                "GLOBAL HEADER ASCII:",
                printable,
                file=out,
            )

            streams = enumerate_streams(data, first)

            print(
                "ACTUAL STREAMS:",
                len(streams),
                file=out,
            )

            print(
                "COUNT MATCH:",
                len(streams) == n_from_prefix,
                file=out,
            )

            # ----------------------------------------------------------------
            # Treat each 28-byte directory entry as seven 32-bit words.
            # Test both endiannesses against stream metadata.
            # ----------------------------------------------------------------

            matches = Counter()

            for i, s in enumerate(streams):

                off = HEADER_SIZE + i * ENTRY_SIZE
                rec = data[off:off + ENTRY_SIZE]

                le = struct.unpack("<7I", rec)
                be = struct.unpack(">7I", rec)

                targets = values_for_stream(s, first)

                for endian_name, words in (
                    ("LE", le),
                    ("BE", be),
                ):
                    for slot, value in enumerate(words):
                        for target_name, target in targets.items():

                            if value == target:
                                matches[
                                    (
                                        endian_name,
                                        slot,
                                        target_name,
                                    )
                                ] += 1

            print(file=out)
            print("32-BIT FIELD CORRELATIONS:", file=out)

            for (
                endian,
                slot,
                target,
            ), count in matches.most_common():

                if count < 3:
                    continue

                pct = 100.0 * count / len(streams)

                print(
                    f"  {endian} u32[{slot}] "
                    f"== {target:10s}: "
                    f"{count}/{len(streams)} "
                    f"({pct:.2f}%)",
                    file=out,
                )

            # ----------------------------------------------------------------
            # Dump first 20 directory records with corresponding stream.
            # ----------------------------------------------------------------

            print(file=out)
            print("FIRST DIRECTORY RECORDS:", file=out)

            for i, s in enumerate(streams[:20]):

                off = HEADER_SIZE + i * ENTRY_SIZE
                rec = data[off:off + ENTRY_SIZE]

                le32 = struct.unpack("<7I", rec)
                be32 = struct.unpack(">7I", rec)
                le16 = struct.unpack("<14H", rec)

                print(file=out)
                print(
                    f"#{i:04d} DIR=0x{off:X} "
                    f"STREAM=0x{s['start']:X}..0x{s['end']:X}",
                    file=out,
                )

                print(
                    "  RAW28:",
                    rec.hex(),
                    file=out,
                )

                print(
                    "  LE32:",
                    " ".join(
                        f"{x:08X}" for x in le32
                    ),
                    file=out,
                )

                print(
                    "  BE32:",
                    " ".join(
                        f"{x:08X}" for x in be32
                    ),
                    file=out,
                )

                print(
                    "  LE16:",
                    " ".join(
                        f"{x:04X}" for x in le16
                    ),
                    file=out,
                )

                print(
                    "  STREAM:",
                    f"packed={s['packed']} "
                    f"raw={s['raw']} "
                    f"adler={s['adler']:08X}",
                    file=out,
                )

            # ----------------------------------------------------------------
            # Per-slot statistics.
            # ----------------------------------------------------------------

            slots_le32 = [
                Counter()
                for _ in range(7)
            ]

            slots_le16 = [
                Counter()
                for _ in range(14)
            ]

            for i in range(len(streams)):

                off = HEADER_SIZE + i * ENTRY_SIZE
                rec = data[off:off + ENTRY_SIZE]

                for j, x in enumerate(
                    struct.unpack("<7I", rec)
                ):
                    slots_le32[j][x] += 1

                for j, x in enumerate(
                    struct.unpack("<14H", rec)
                ):
                    slots_le16[j][x] += 1

            print(file=out)
            print("LE32 SLOT STATS:", file=out)

            for j, c in enumerate(slots_le32):
                print(
                    f"  slot{j}: "
                    f"unique={len(c)} "
                    f"top={c.most_common(8)}",
                    file=out,
                )

            print(file=out)
            print("LE16 SLOT STATS:", file=out)

            for j, c in enumerate(slots_le16):
                print(
                    f"  slot{j:02d}: "
                    f"unique={len(c)} "
                    f"top={c.most_common(8)}",
                    file=out,
                )

print("Created:", report)
