from pathlib import Path
from collections import Counter, defaultdict
import struct
import zlib
import binascii

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"

FILES = {
    "7185_MG1": Path("/Volumes/CD_7185/DB/IZ.MG1"),
    "7185_MG2": Path("/Volumes/CD_7185/DB/IZ.MG2"),
    "7185_MG3": Path("/Volumes/CD_7185/DB/IZ.MG3"),
    "7186_MG1": Path("/Volumes/CD_7186/DB/SCZ.MG1"),
    "7186_MG2": Path("/Volumes/CD_7186/DB/SCZ.MG2"),
    "7186_MG3": Path("/Volumes/CD_7186/DB/SCZ.MG3"),
}

HDR = 0x72


def unpack_stream(data, start):
    d = zlib.decompressobj()
    raw = d.decompress(data[start:])

    if not d.eof:
        raise RuntimeError(
            f"bad zlib at 0x{start:X}"
        )

    consumed = len(data[start:]) - len(d.unused_data)
    end = start + consumed

    raw += d.flush()

    return raw, end


def load_pages(path):
    data = path.read_bytes()

    n = struct.unpack_from("<I", data, 0x56)[0]

    bbox_off = HDR
    meta_off = bbox_off + n * 16
    zero_off = meta_off + n * 8
    payload_off = zero_off + n * 4

    physical = {}

    pos = payload_off

    while pos < len(data):
        raw, end = unpack_stream(data, pos)

        physical[pos] = {
            "raw": raw,
            "end": end,
            "packed": data[pos:end],
        }

        pos = end

    pages = []

    for i in range(n):

        bbox = struct.unpack_from(
            "<4i",
            data,
            bbox_off + i * 16,
        )

        stream_off, key = struct.unpack_from(
            "<2I",
            data,
            meta_off + i * 8,
        )

        s = physical[stream_off]

        pages.append({
            "index": i,
            "bbox": bbox,
            "offset": stream_off,
            "key": key,
            "raw": s["raw"],
            "packed": s["packed"],
        })

    return pages


report = OUT / "mg_meta1_raw_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        pages = load_pages(path)

        print("=" * 90, file=out)
        print("FILE:", name, file=out)
        print("PAGES:", len(pages), file=out)

        tests = Counter()

        low16_counts = Counter()
        high16_counts = Counter()

        raw_contains_le = 0
        raw_contains_be = 0

        duplicate_keys = defaultdict(list)

        for p in pages:

            raw = p["raw"]
            packed = p["packed"]
            key = p["key"]

            duplicate_keys[key].append(p)

            lo = key & 0xFFFF
            hi = key >> 16

            low16_counts[lo] += 1
            high16_counts[hi] += 1

            crc_raw = zlib.crc32(raw) & 0xFFFFFFFF
            adler_raw = zlib.adler32(raw) & 0xFFFFFFFF

            crc_packed = zlib.crc32(packed) & 0xFFFFFFFF
            adler_packed = zlib.adler32(packed) & 0xFFFFFFFF

            candidates = {
                "crc32(raw)": crc_raw,
                "crc32(raw)&7fffffff": crc_raw & 0x7FFFFFFF,
                "adler32(raw)": adler_raw,
                "adler32(raw)&7fffffff": adler_raw & 0x7FFFFFFF,

                "crc32(packed)": crc_packed,
                "crc32(packed)&7fffffff":
                    crc_packed & 0x7FFFFFFF,

                "adler32(packed)": adler_packed,
                "adler32(packed)&7fffffff":
                    adler_packed & 0x7FFFFFFF,

                "raw_len": len(raw),
                "packed_len": len(packed),
            }

            if len(raw) >= 4:
                candidates["raw_u32le_0"] = \
                    struct.unpack_from("<I", raw, 0)[0]

                candidates["raw_u32be_0"] = \
                    struct.unpack_from(">I", raw, 0)[0]

            if len(raw) >= 8:
                candidates["raw_u32le_4"] = \
                    struct.unpack_from("<I", raw, 4)[0]

                candidates["raw_u32be_4"] = \
                    struct.unpack_from(">I", raw, 4)[0]

            for test_name, value in candidates.items():
                if key == value:
                    tests[test_name] += 1

            kle = struct.pack("<I", key)
            kbe = struct.pack(">I", key)

            if kle in raw:
                raw_contains_le += 1

            if kbe in raw:
                raw_contains_be += 1

        print(file=out)
        print("DIRECT KEY TESTS:", file=out)

        for k, v in tests.most_common():
            print(
                f"  {k}: {v}/{len(pages)}",
                file=out,
            )

        print(
            "META1 LE bytes occur in raw:",
            raw_contains_le,
            "/",
            len(pages),
            file=out,
        )

        print(
            "META1 BE bytes occur in raw:",
            raw_contains_be,
            "/",
            len(pages),
            file=out,
        )

        print(
            "UNIQUE high16:",
            len(high16_counts),
            file=out,
        )

        print(
            "UNIQUE low16:",
            len(low16_counts),
            file=out,
        )

        print(
            "TOP high16:",
            high16_counts.most_common(20),
            file=out,
        )

        print(
            "TOP low16:",
            low16_counts.most_common(20),
            file=out,
        )

        # ------------------------------------------------------------
        # Duplicate meta1 values.
        # ------------------------------------------------------------

        dups = {
            k: v
            for k, v in duplicate_keys.items()
            if len(v) > 1
        }

        print(file=out)
        print(
            "DUPLICATE META1 KEYS:",
            len(dups),
            file=out,
        )

        for key, group in list(dups.items())[:30]:

            print(
                f"  KEY=0x{key:08X} count={len(group)}",
                file=out,
            )

            for p in group:
                print(
                    "    index=",
                    p["index"],
                    "bbox=",
                    p["bbox"],
                    "raw_len=",
                    len(p["raw"]),
                    "crc32=",
                    f"{zlib.crc32(p['raw']) & 0xFFFFFFFF:08X}",
                    file=out,
                )

        # ------------------------------------------------------------
        # Dump first 50 raw headers as words.
        # ------------------------------------------------------------

        print(file=out)
        print("FIRST RAW HEADERS:", file=out)

        for p in pages[:50]:

            raw = p["raw"]

            first = raw[:64]

            le16 = [
                struct.unpack_from("<H", first, i)[0]
                for i in range(0, len(first) - 1, 2)
            ]

            le32 = [
                struct.unpack_from("<I", first, i)[0]
                for i in range(0, len(first) - 3, 4)
            ]

            print(
                f"#{p['index']:04d} "
                f"key=0x{p['key']:08X} "
                f"bbox={p['bbox']} "
                f"raw={len(raw)}",
                file=out,
            )

            print(
                "  HEX:",
                first.hex(),
                file=out,
            )

            print(
                "  LE16:",
                " ".join(f"{x:04X}" for x in le16),
                file=out,
            )

            print(
                "  LE32:",
                " ".join(f"{x:08X}" for x in le32),
                file=out,
            )

print("Created:", report)
