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

    pts = []

    while pos < end:
        q = struct.unpack_from("<H", raw, pos)[0]
        x, y = struct.unpack_from("<ii", raw, pos + 2)

        pos += 10
        pts.append((x, y))

        for _ in range(q):
            dx, dy = struct.unpack_from("<hh", raw, pos)
            pos += 4

            x += dx
            y += dy
            pts.append((x, y))

    return pts


def inside(x, y, bbox):
    x0, y0, x1, y1 = bbox
    return x0 <= x <= x1 and y0 <= y <= y1


MASKS = [
    ("raw", 0xFFFF),
    ("7fff", 0x7FFF),
    ("3fff", 0x3FFF),
    ("1fff", 0x1FFF),
    ("0fff", 0x0FFF),
]


report = OUT / "mg_s5_ref_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        pages = load_pages(path)

        total_s5 = 0
        total_s6 = 0
        total_s11 = 0

        # ----------------------------------------
        # raw slot1/slot2 relationships
        # ----------------------------------------

        ref_valid = {
            slot: Counter()
            for slot in (1, 2, 3, 4)
        }

        pair_equal = 0
        pair_plus1 = 0
        pair_minus1 = 0
        pair_adjacent = 0

        invalid_high = {
            1: Counter(),
            2: Counter(),
        }

        # ----------------------------------------
        # S11 as direct coordinate records
        # ----------------------------------------

        s11_inside = 0
        s11_exact_s1 = 0

        # S6 candidate coordinate pair offsets
        s6_inside = Counter()
        s6_exact_s1 = Counter()

        # ----------------------------------------
        # refs slot1/slot2 -> S11 coords
        # ----------------------------------------

        ref_s11_exact = Counter()

        # refs slot1/slot2 -> S6 coordinate candidates
        ref_s6_exact = Counter()

        examples = []

        for page_i, (bbox, raw) in enumerate(pages):

            h = struct.unpack_from("<23H", raw, 0)

            s1 = decode_s1(raw, h)
            s1_set = set(s1)

            # ----------------------------
            # S5
            # ----------------------------

            s5_start = h[8]
            n5 = h[9]

            # ----------------------------
            # S6: h11 x 14 bytes
            # ----------------------------

            s6_start = h[10]
            n6 = h[11]

            # ----------------------------
            # S11: h21 x 8 bytes
            # starts at h20 (= h12 here)
            # ----------------------------

            s11_start = h[20]
            n11 = h[21]

            if n6 != n11:
                raise RuntimeError(
                    f"page {page_i}: h11 != h21"
                )

            total_s5 += n5
            total_s6 += n6
            total_s11 += n11

            # ------------------------------------
            # Decode S11 as candidate <ii>
            # ------------------------------------

            s11_xy = []

            for j in range(n11):

                off = s11_start + 8*j

                x, y = struct.unpack_from(
                    "<ii", raw, off
                )

                s11_xy.append((x, y))

                s11_inside += inside(x, y, bbox)
                s11_exact_s1 += ((x, y) in s1_set)

            # ------------------------------------
            # S6 candidate coordinate views
            # ------------------------------------

            s6_xy = {
                off: []
                for off in (0, 2, 4, 6)
            }

            for j in range(n6):

                base = s6_start + 14*j

                for off in (0, 2, 4, 6):

                    x, y = struct.unpack_from(
                        "<ii",
                        raw,
                        base + off,
                    )

                    s6_xy[off].append((x, y))

                    s6_inside[off] += inside(
                        x, y, bbox
                    )

                    s6_exact_s1[off] += (
                        (x, y) in s1_set
                    )

            # ------------------------------------
            # S5 records
            # ------------------------------------

            for i in range(n5):

                rec = raw[
                    s5_start + 10*i:
                    s5_start + 10*(i+1)
                ]

                u = struct.unpack("<5H", rec)

                a = u[1]
                b = u[2]

                pair_equal += (a == b)
                pair_plus1 += (b == a + 1)
                pair_minus1 += (a == b + 1)
                pair_adjacent += (abs(a - b) == 1)

                for slot in (1, 2, 3, 4):

                    v = u[slot]

                    for label, mask in MASKS:
                        vv = v & mask

                        ref_valid[slot][label] += (
                            vv < n6
                        )

                if a >= n6:
                    invalid_high[1][a >> 8] += 1

                if b >= n6:
                    invalid_high[2][b >> 8] += 1

                # Current geometry point
                if i >= len(s1):
                    continue

                px, py = s1[i]

                # ------------------------------
                # raw refs -> S11
                # ------------------------------

                for slot, ref in (
                    (1, a),
                    (2, b),
                ):
                    if ref < n11:
                        ref_s11_exact[slot] += (
                            s11_xy[ref] == (px, py)
                        )

                    # --------------------------
                    # raw refs -> S6 candidate
                    # coordinates
                    # --------------------------

                    if ref < n6:
                        for off in (0, 2, 4, 6):

                            ref_s6_exact[
                                (slot, off)
                            ] += (
                                s6_xy[off][ref]
                                == (px, py)
                            )

                if len(examples) < 30 and i < 3:

                    examples.append({
                        "page": page_i,
                        "point": i,
                        "xy": (px, py),
                        "s5": u,
                        "h11": n6,
                        "s11_a": (
                            s11_xy[a]
                            if a < n11 else None
                        ),
                        "s11_b": (
                            s11_xy[b]
                            if b < n11 else None
                        ),
                    })

        print("=" * 90, file=out)
        print("FILE:", name, file=out)

        print(
            "TOTAL S5/S6/S11:",
            total_s5,
            total_s6,
            total_s11,
            file=out,
        )

        print(file=out)
        print("S5 SLOT RANGE TESTS:", file=out)

        for slot in (1, 2, 3, 4):

            print(f"SLOT {slot}", file=out)

            for label, _ in MASKS:

                print(
                    f"  {label:5s} < h11:",
                    ref_valid[slot][label],
                    "/",
                    total_s5,
                    file=out,
                )

        print(file=out)
        print("SLOT1 / SLOT2 RELATION:", file=out)

        print(
            "equal:",
            pair_equal,
            "/",
            total_s5,
            file=out,
        )

        print(
            "slot2 = slot1+1:",
            pair_plus1,
            "/",
            total_s5,
            file=out,
        )

        print(
            "slot1 = slot2+1:",
            pair_minus1,
            "/",
            total_s5,
            file=out,
        )

        print(
            "abs(diff)==1:",
            pair_adjacent,
            "/",
            total_s5,
            file=out,
        )

        print(
            "slot1 invalid high-byte:",
            invalid_high[1].most_common(30),
            file=out,
        )

        print(
            "slot2 invalid high-byte:",
            invalid_high[2].most_common(30),
            file=out,
        )

        print(file=out)
        print("S11 AS <s32 X,s32 Y>:", file=out)

        print(
            "inside bbox:",
            s11_inside,
            "/",
            total_s11,
            file=out,
        )

        print(
            "exact S1 point:",
            s11_exact_s1,
            "/",
            total_s11,
            file=out,
        )

        print(file=out)
        print("S6 COORDINATE CANDIDATES:", file=out)

        for off in (0, 2, 4, 6):

            print(
                f"offset {off}: "
                f"inside={s6_inside[off]}/{total_s6} "
                f"exact_s1={s6_exact_s1[off]}/{total_s6}",
                file=out,
            )

        print(file=out)
        print("S5 REF -> S11 CURRENT S1 POINT:", file=out)

        for slot in (1, 2):

            print(
                f"slot{slot}:",
                ref_s11_exact[slot],
                "/",
                total_s5,
                file=out,
            )

        print(file=out)
        print("S5 REF -> S6 CURRENT S1 POINT:", file=out)

        for slot in (1, 2):

            for off in (0, 2, 4, 6):

                print(
                    f"slot{slot} / off{off}:",
                    ref_s6_exact[(slot, off)],
                    "/",
                    total_s5,
                    file=out,
                )

        print(file=out)
        print("EXAMPLES:", file=out)

        for e in examples:
            print(e, file=out)

print("Created:", report)
