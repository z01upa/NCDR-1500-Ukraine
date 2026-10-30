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

HDR = 0x72
CHUNK = 65536


def parse_streams(data, start):
    result = []
    pos = start

    while pos < len(data):
        d = zlib.decompressobj()
        p = pos
        raw_len = 0

        while True:
            chunk = data[p:min(p + CHUNK, len(data))]

            if not chunk:
                raise RuntimeError(
                    f"unterminated zlib at 0x{pos:X}"
                )

            raw = d.decompress(chunk)
            raw_len += len(raw)

            if d.eof:
                consumed = len(chunk) - len(d.unused_data)
                p += consumed
                break

            p += len(chunk)

        result.append({
            "start_abs": pos,
            "end_abs": p,
            "packed": p - pos,
            "raw": raw_len,
            "adler": int.from_bytes(data[p-4:p], "big"),
        })

        pos = p

    return result


def score(values, targets):
    exact = sum(
        a == b
        for a, b in zip(values, targets)
    )

    target_set = set(targets)

    anywhere = sum(
        v in target_set
        for v in values
    )

    return exact, anywhere


report = OUT / "mg_sections_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for dataset, (root, names) in SETS.items():

        print("=" * 90, file=out)
        print("DATASET:", dataset, file=out)

        for name in names:

            data = (root / name).read_bytes()

            n = struct.unpack_from("<I", data, 0x56)[0]

            gx0, gy0, gx1, gy1 = struct.unpack_from(
                "<4i", data, 0x5E
            )

            bbox_off = HDR
            meta_off = bbox_off + n * 16
            zero_off = meta_off + n * 8
            stream_off = zero_off + n * 4

            print(file=out)
            print("-" * 90, file=out)
            print("FILE:", name, file=out)
            print("N:", n, file=out)

            print(
                "SECTION A bbox:",
                f"0x{bbox_off:X}..0x{meta_off:X}",
                file=out,
            )

            print(
                "SECTION B meta:",
                f"0x{meta_off:X}..0x{zero_off:X}",
                file=out,
            )

            print(
                "SECTION C zero:",
                f"0x{zero_off:X}..0x{stream_off:X}",
                file=out,
            )

            print(
                "ZLIB AREA:",
                f"0x{stream_off:X}..0x{len(data):X}",
                file=out,
            )

            # --------------------------------------------------
            # TABLE A: N x 4 signed int32
            # --------------------------------------------------

            boxes = []

            contained = 0
            ordered = 0
            perfect = 0

            widths = Counter()
            heights = Counter()

            for i in range(n):
                off = bbox_off + i * 16

                x0, y0, x1, y1 = struct.unpack_from(
                    "<4i", data, off
                )

                boxes.append((x0, y0, x1, y1))

                c = (
                    gx0 <= x0 <= gx1
                    and gx0 <= x1 <= gx1
                    and gy0 <= y0 <= gy1
                    and gy0 <= y1 <= gy1
                )

                o = (
                    x0 <= x1
                    and y0 <= y1
                )

                contained += int(c)
                ordered += int(o)
                perfect += int(c and o)

                if o:
                    widths[x1 - x0] += 1
                    heights[y1 - y0] += 1

            print(file=out)
            print("BBOX TEST:", file=out)
            print(
                "contained:",
                contained, "/", n,
                file=out,
            )
            print(
                "ordered x0<=x1 y0<=y1:",
                ordered, "/", n,
                file=out,
            )
            print(
                "contained+ordered:",
                perfect, "/", n,
                file=out,
            )

            print(
                "zero-width:",
                widths[0],
                file=out,
            )

            print(
                "zero-height:",
                heights[0],
                file=out,
            )

            print(
                "top widths:",
                widths.most_common(15),
                file=out,
            )

            print(
                "top heights:",
                heights.most_common(15),
                file=out,
            )

            print("FIRST BOXES:", file=out)

            for i, box in enumerate(boxes[:10]):
                print(
                    f"  #{i:04d}",
                    box,
                    file=out,
                )

            # --------------------------------------------------
            # TABLE B: N x 2 uint32
            # --------------------------------------------------

            meta = []

            for i in range(n):
                off = meta_off + i * 8
                meta.append(
                    struct.unpack_from("<2I", data, off)
                )

            m0 = [x[0] for x in meta]
            m1 = [x[1] for x in meta]

            # --------------------------------------------------
            # TABLE C
            # --------------------------------------------------

            zero_data = data[zero_off:stream_off]

            print(file=out)
            print(
                "TABLE C ALL ZERO:",
                not any(zero_data),
                file=out,
            )

            # --------------------------------------------------
            # Parse real zlib sequence.
            # --------------------------------------------------

            streams = parse_streams(
                data,
                stream_off
            )

            print(
                "STREAM COUNT:",
                len(streams),
                file=out,
            )

            print(
                "STREAM COUNT MATCH:",
                len(streams) == n,
                file=out,
            )

            abs_start = [
                s["start_abs"]
                for s in streams
            ]

            rel_start = [
                s["start_abs"] - stream_off
                for s in streams
            ]

            abs_end = [
                s["end_abs"]
                for s in streams
            ]

            rel_end = [
                s["end_abs"] - stream_off
                for s in streams
            ]

            packed = [
                s["packed"]
                for s in streams
            ]

            rawlen = [
                s["raw"]
                for s in streams
            ]

            adler = [
                s["adler"]
                for s in streams
            ]

            targets = {
                "start_abs": abs_start,
                "start_rel": rel_start,
                "end_abs": abs_end,
                "end_rel": rel_end,
                "packed": packed,
                "raw_len": rawlen,
                "adler": adler,
            }

            print(file=out)
            print("META CORRELATIONS:", file=out)

            for field_name, values in (
                ("meta0", m0),
                ("meta1", m1),
            ):
                print(field_name, file=out)

                for target_name, target in targets.items():
                    exact, anywhere = score(
                        values,
                        target
                    )

                    print(
                        f"  {target_name:10s} "
                        f"same-index={exact}/{n} "
                        f"anywhere={anywhere}/{n}",
                        file=out,
                    )

            # If meta0 is a permutation of stream offsets,
            # recover stream index.
            rel_lookup = {
                v: i
                for i, v in enumerate(rel_start)
            }

            abs_lookup = {
                v: i
                for i, v in enumerate(abs_start)
            }

            print(file=out)
            print("FIRST META:", file=out)

            for i, (a, b) in enumerate(meta[:30]):

                rel_i = rel_lookup.get(a)
                abs_i = abs_lookup.get(a)

                print(
                    f"  #{i:04d} "
                    f"meta0={a:10d} 0x{a:08X} "
                    f"meta1={b:10d} 0x{b:08X} "
                    f"rel_stream={rel_i} "
                    f"abs_stream={abs_i}",
                    file=out,
                )

            print(
                "meta0 <= compressed-area-size:",
                sum(
                    x <= len(data) - stream_off
                    for x in m0
                ),
                "/",
                n,
                file=out,
            )

            print(
                "meta0 unique:",
                len(set(m0)),
                "/",
                n,
                file=out,
            )

            print(
                "meta1 unique:",
                len(set(m1)),
                "/",
                n,
                file=out,
            )

print("Created:", report)
