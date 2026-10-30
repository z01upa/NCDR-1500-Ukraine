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
    return x0 <= x <= x1 and y0 <= y <= y1


def decode_candidate(sec, q, split, mode, bbox):

    # Header
    qq = struct.unpack_from("<H", sec, 0)[0]
    x, y = struct.unpack_from("<ii", sec, 2)

    if qq != q:
        return None

    points = [(x, y)]

    pos = 10

    # ordinary records before long record
    for _ in range(split):
        dx, dy = struct.unpack_from("<hh", sec, pos)
        pos += 4

        x += dx
        y += dy
        points.append((x, y))

    long_start = pos
    long = sec[pos:pos+10]

    if len(long) != 10:
        return None

    # -------------------------------------------------
    # Candidate layouts:
    #
    # prefix_delta:
    #   u16 tag
    #   s32 dx
    #   s32 dy
    #
    # prefix_abs:
    #   u16 tag
    #   s32 x
    #   s32 y
    #
    # suffix_delta:
    #   s32 dx
    #   s32 dy
    #   u16 tag
    #
    # suffix_abs:
    #   s32 x
    #   s32 y
    #   u16 tag
    # -------------------------------------------------

    if mode == "prefix_delta":
        tag, dx, dy = struct.unpack("<Hii", long)
        x += dx
        y += dy

    elif mode == "prefix_abs":
        tag, x, y = struct.unpack("<Hii", long)

    elif mode == "suffix_delta":
        dx, dy, tag = struct.unpack("<iiH", long)
        x += dx
        y += dy

    elif mode == "suffix_abs":
        x, y, tag = struct.unpack("<iiH", long)

    elif mode == "prefix_delta_swapped":
        tag, dy, dx = struct.unpack("<Hii", long)
        x += dx
        y += dy

    elif mode == "prefix_abs_swapped":
        tag, y, x = struct.unpack("<Hii", long)

    else:
        raise ValueError(mode)

    pos += 10
    points.append((x, y))

    # remaining ordinary records
    remain = q - split - 1

    for _ in range(remain):
        dx, dy = struct.unpack_from("<hh", sec, pos)
        pos += 4

        x += dx
        y += dy
        points.append((x, y))

    if pos != len(sec):
        return None

    hits = sum(
        inside(px, py, bbox)
        for px, py in points
    )

    return {
        "hits": hits,
        "all": hits == len(points),
        "tag": tag,
        "split": split,
        "long_hex": long.hex(),
        "points": len(points),
    }


MODES = [
    "prefix_delta",
    "prefix_abs",
    "suffix_delta",
    "suffix_abs",
    "prefix_delta_swapped",
    "prefix_abs_swapped",
]


report = OUT / "mg_s1_extended_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        pages = load_pages(path)

        k1_pages = 0

        perfect_by_mode = Counter()
        unique_mode = Counter()
        tag_counts = {
            mode: Counter()
            for mode in MODES
        }

        examples = []

        for page_i, (bbox, raw) in enumerate(pages):

            h = struct.unpack_from("<23H", raw, 0)

            start = h[0]
            end = h[2]
            count = h[1]

            if count <= 0:
                continue

            sec_len = end - start

            extra = (
                sec_len
                - (6 + 4*count)
            )

            if extra != 6:
                continue

            k1_pages += 1

            sec = raw[start:end]

            q = count - 1

            per_page = []

            for mode in MODES:

                perfect = []

                for split in range(q):

                    r = decode_candidate(
                        sec,
                        q,
                        split,
                        mode,
                        bbox,
                    )

                    if r and r["all"]:
                        perfect.append(r)

                if perfect:
                    perfect_by_mode[mode] += 1

                    for r in perfect:
                        tag_counts[mode][
                            r["tag"]
                        ] += 1

                    per_page.append(
                        (mode, perfect)
                    )

            # exactly one mode and exactly one split
            exact = []

            for mode, rs in per_page:
                if len(rs) == 1:
                    exact.append(
                        (mode, rs[0])
                    )

            if len(exact) == 1:
                mode, r = exact[0]
                unique_mode[mode] += 1

                if len(examples) < 80:
                    examples.append(
                        (
                            page_i,
                            bbox,
                            count,
                            mode,
                            r["split"],
                            r["tag"],
                            r["long_hex"],
                        )
                    )

        print("=" * 90, file=out)
        print("FILE:", name, file=out)
        print("K=1 PAGES:", k1_pages, file=out)

        print(file=out)
        print("PERFECT PAGE BY MODE:", file=out)

        for mode in MODES:
            print(
                f"  {mode:24s}",
                perfect_by_mode[mode],
                "/",
                k1_pages,
                file=out,
            )

        print(file=out)
        print("UNIQUE MODE+SPLIT SOLUTIONS:", file=out)

        for mode in MODES:
            print(
                f"  {mode:24s}",
                unique_mode[mode],
                file=out,
            )

        print(file=out)
        print("TOP TAGS:", file=out)

        for mode in MODES:
            print(
                mode,
                tag_counts[mode].most_common(20),
                file=out,
            )

        print(file=out)
        print("EXAMPLES:", file=out)

        for x in examples:
            print(x, file=out)

print("Created:", report)
