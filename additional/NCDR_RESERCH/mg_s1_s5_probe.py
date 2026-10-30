from pathlib import Path
from collections import Counter
import struct
import zlib

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


def unpack_one(data, start):
    d = zlib.decompressobj()
    raw = d.decompress(data[start:])

    if not d.eof:
        raise RuntimeError(f"bad zlib @ 0x{start:X}")

    used = len(data[start:]) - len(d.unused_data)
    raw += d.flush()

    return raw, start + used


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
        raw, end = unpack_one(data, pos)
        physical[pos] = raw
        pos = end

    pages = []

    for i in range(n):
        bbox = struct.unpack_from(
            "<4i", data, bbox_off + 16*i
        )

        stream_off = struct.unpack_from(
            "<I", data, meta_off + 8*i
        )[0]

        pages.append((bbox, physical[stream_off]))

    return pages


def decode_s1(raw, h):
    pos = h[0]
    end = h[2]

    points = []

    chain_index = 0

    while pos < end:
        q = struct.unpack_from("<H", raw, pos)[0]
        x, y = struct.unpack_from("<ii", raw, pos + 2)
        pos += 10

        points.append({
            "x": x,
            "y": y,
            "chain": chain_index,
            "in_chain": 0,
            "dx": None,
            "dy": None,
        })

        for j in range(q):
            dx, dy = struct.unpack_from("<hh", raw, pos)
            pos += 4

            x += dx
            y += dy

            points.append({
                "x": x,
                "y": y,
                "chain": chain_index,
                "in_chain": j + 1,
                "dx": dx,
                "dy": dy,
            })

        chain_index += 1

    if pos != end:
        raise RuntimeError("S1 boundary mismatch")

    return points


report = OUT / "mg_s1_s5_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        pages = load_pages(path)

        total_records = 0

        xy0_exact = 0
        yx0_exact = 0

        xy2_exact = 0
        yx2_exact = 0

        delta_pairs = [0, 0, 0, 0]
        delta_swapped = [0, 0, 0, 0]

        slot_stats = [
            Counter() for _ in range(5)
        ]

        slot_zero = [0] * 5
        slot_lt_h1 = [0] * 5
        slot_lt_h3 = [0] * 5
        slot_lt_h5 = [0] * 5
        slot_lt_h11 = [0] * 5

        slot_eq_index = [0] * 5
        slot_eq_chain = [0] * 5
        slot_eq_inchain = [0] * 5

        s5_size_ok = 0
        point_count_ok = 0

        examples = []

        for page_i, (bbox, raw) in enumerate(pages):

            h = struct.unpack_from("<23H", raw, 0)

            points = decode_s1(raw, h)

            if len(points) == h[1]:
                point_count_ok += 1

            s5_start = h[8]
            s5_end = h[10]

            if s5_end - s5_start != h[9] * 10:
                continue

            s5_size_ok += 1

            if len(points) != h[9]:
                continue

            for i, p in enumerate(points):

                rec = raw[
                    s5_start + 10*i:
                    s5_start + 10*(i+1)
                ]

                total_records += 1

                # ----------------------------------------
                # Does S5 contain exact absolute X/Y?
                # ----------------------------------------

                x0, y0 = struct.unpack_from("<ii", rec, 0)

                xy0_exact += (
                    x0 == p["x"] and y0 == p["y"]
                )

                yx0_exact += (
                    x0 == p["y"] and y0 == p["x"]
                )

                tag, x2, y2 = struct.unpack("<Hii", rec)

                xy2_exact += (
                    x2 == p["x"] and y2 == p["y"]
                )

                yx2_exact += (
                    x2 == p["y"] and y2 == p["x"]
                )

                # ----------------------------------------
                # Five LE u16 slots
                # ----------------------------------------

                u = struct.unpack("<5H", rec)

                for s, value in enumerate(u):

                    slot_stats[s][value] += 1

                    slot_zero[s] += (value == 0)

                    slot_lt_h1[s] += (value < h[1])
                    slot_lt_h3[s] += (value < h[3])
                    slot_lt_h5[s] += (value < h[5])
                    slot_lt_h11[s] += (value < h[11])

                    slot_eq_index[s] += (value == i)

                    slot_eq_chain[s] += (
                        value == p["chain"]
                    )

                    slot_eq_inchain[s] += (
                        value == p["in_chain"]
                    )

                # ----------------------------------------
                # Does any adjacent s16 pair equal the
                # incoming S1 delta?
                # ----------------------------------------

                if p["dx"] is not None:

                    for off_i, off in enumerate(
                        (0, 2, 4, 6)
                    ):

                        a, b = struct.unpack_from(
                            "<hh", rec, off
                        )

                        delta_pairs[off_i] += (
                            a == p["dx"]
                            and b == p["dy"]
                        )

                        delta_swapped[off_i] += (
                            a == p["dy"]
                            and b == p["dx"]
                        )

                if len(examples) < 30 and i < 3:
                    examples.append((
                        page_i,
                        i,
                        p,
                        rec.hex(),
                        u,
                    ))

        print("=" * 90, file=out)
        print("FILE:", name, file=out)
        print("PAGES:", len(pages), file=out)

        print(
            "S5 SIZE == h1*10:",
            s5_size_ok, "/", len(pages),
            file=out,
        )

        print(
            "S1 POINTS == S5 RECORDS:",
            point_count_ok, "/", len(pages),
            file=out,
        )

        print(
            "TOTAL S5 RECORDS:",
            total_records,
            file=out,
        )

        print(file=out)
        print("DIRECT COORDINATE TESTS:", file=out)

        print(
            "s32@0 X,Y exact:",
            xy0_exact, "/", total_records,
            file=out,
        )

        print(
            "s32@0 Y,X exact:",
            yx0_exact, "/", total_records,
            file=out,
        )

        print(
            "u16 + s32 X,Y exact:",
            xy2_exact, "/", total_records,
            file=out,
        )

        print(
            "u16 + s32 Y,X exact:",
            yx2_exact, "/", total_records,
            file=out,
        )

        print(file=out)
        print("S16 DELTA TESTS:", file=out)

        for i, off in enumerate((0, 2, 4, 6)):
            print(
                f"offset {off}: "
                f"dx,dy={delta_pairs[i]} "
                f"dy,dx={delta_swapped[i]}",
                file=out,
            )

        print(file=out)
        print("U16 SLOT STATS:", file=out)

        for s in range(5):

            print(f"SLOT {s}:", file=out)

            print(
                "  zero:",
                slot_zero[s], "/", total_records,
                file=out,
            )

            print(
                "  <h1:",
                slot_lt_h1[s], "/", total_records,
                file=out,
            )

            print(
                "  <h3:",
                slot_lt_h3[s], "/", total_records,
                file=out,
            )

            print(
                "  <h5:",
                slot_lt_h5[s], "/", total_records,
                file=out,
            )

            print(
                "  <h11:",
                slot_lt_h11[s], "/", total_records,
                file=out,
            )

            print(
                "  == flat point index:",
                slot_eq_index[s],
                file=out,
            )

            print(
                "  == chain index:",
                slot_eq_chain[s],
                file=out,
            )

            print(
                "  == point-in-chain:",
                slot_eq_inchain[s],
                file=out,
            )

            print(
                "  TOP:",
                slot_stats[s].most_common(20),
                file=out,
            )

        print(file=out)
        print("EXAMPLES:", file=out)

        for x in examples:
            print(x, file=out)

print("Created:", report)
