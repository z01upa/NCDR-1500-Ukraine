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
    end = start + used

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
        raw, end = unpack_one(data, pos)
        physical[pos] = raw
        pos = end

    pages = []

    for i in range(n):

        bbox = struct.unpack_from(
            "<4i",
            data,
            bbox_off + i * 16
        )

        stream_off = struct.unpack_from(
            "<I",
            data,
            meta_off + i * 8
        )[0]

        pages.append((bbox, physical[stream_off]))

    return pages


def inside(x, y, bbox):
    x0, y0, x1, y1 = bbox

    return (
        x0 <= x <= x1
        and y0 <= y <= y1
    )


def decode_simple(sec, count, bbox):

    expected = 6 + 4 * count

    if len(sec) != expected:
        return None

    q = struct.unpack_from("<H", sec, 0)[0]

    if q != count - 1:
        return None

    x, y = struct.unpack_from("<ii", sec, 2)

    hits = int(inside(x, y, bbox))

    if not inside(x, y, bbox):
        return {
            "all": False,
            "hits": hits,
            "points": count,
        }

    pos = 10

    for _ in range(q):

        dx, dy = struct.unpack_from(
            "<hh",
            sec,
            pos
        )

        pos += 4

        x += dx
        y += dy

        hits += int(inside(x, y, bbox))

    return {
        "all": hits == count,
        "hits": hits,
        "points": count,
    }


report = OUT / "mg_s1_remove6_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        pages = load_pages(path)

        k1_pages = 0
        pages_with_solution = 0
        pages_unique_solution = 0

        rel_positions = Counter()
        exact_positions = Counter()

        examples = []

        for page_i, (bbox, raw) in enumerate(pages):

            h = struct.unpack_from("<23H", raw, 0)

            start = h[0]
            end = h[2]
            count = h[1]

            sec = raw[start:end]

            extra = (
                len(sec)
                - (6 + 4 * count)
            )

            if extra != 6:
                continue

            k1_pages += 1

            solutions = []

            # Try removing every possible 6-byte chunk.
            for cut in range(0, len(sec) - 5):

                reduced = (
                    sec[:cut]
                    + sec[cut+6:]
                )

                r = decode_simple(
                    reduced,
                    count,
                    bbox,
                )

                if r and r["all"]:
                    solutions.append(cut)

            if solutions:
                pages_with_solution += 1

            if len(solutions) == 1:
                pages_unique_solution += 1

            for cut in solutions:

                exact_positions[cut] += 1

                # position relative to important boundaries
                if cut == 0:
                    rel_positions["at_start"] += 1

                if cut == 2:
                    rel_positions["after_q"] += 1

                if cut == 10:
                    rel_positions["after_anchor"] += 1

                if cut == len(sec) - 6:
                    rel_positions["at_end"] += 1

                if cut >= 10 and (cut - 10) % 4 == 0:
                    rel_positions[
                        "on_delta_boundary"
                    ] += 1

            if len(examples) < 80:
                examples.append(
                    (
                        page_i,
                        count,
                        len(sec),
                        solutions[:30],
                        sec.hex(),
                    )
                )

        print("=" * 90, file=out)
        print("FILE:", name, file=out)
        print("K=1 PAGES:", k1_pages, file=out)

        print(
            "PAGES WITH >=1 VALID REMOVAL:",
            pages_with_solution,
            "/",
            k1_pages,
            file=out,
        )

        print(
            "PAGES WITH UNIQUE REMOVAL:",
            pages_unique_solution,
            "/",
            k1_pages,
            file=out,
        )

        print(
            "RELATIVE POSITION COUNTS:",
            rel_positions,
            file=out,
        )

        print(
            "TOP EXACT CUT OFFSETS:",
            exact_positions.most_common(30),
            file=out,
        )

        print()
        print("EXAMPLES:", file=out)

        for x in examples:
            print(x, file=out)

print("Created:", report)
