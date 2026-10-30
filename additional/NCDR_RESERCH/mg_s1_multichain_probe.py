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
            bbox_off + i * 16,
        )

        stream_off = struct.unpack_from(
            "<I",
            data,
            meta_off + i * 8,
        )[0]

        pages.append((bbox, physical[stream_off]))

    return pages


def inside(x, y, bbox):
    x0, y0, x1, y1 = bbox
    return x0 <= x <= x1 and y0 <= y <= y1


def decode_multichain(sec, expected_points, bbox):

    pos = 0
    chains = []
    total_points = 0
    total_hits = 0

    while pos < len(sec):

        if pos + 10 > len(sec):
            return None

        q = struct.unpack_from("<H", sec, pos)[0]
        x, y = struct.unpack_from("<ii", sec, pos + 2)

        pos += 10

        chain = [(x, y)]

        total_points += 1
        total_hits += inside(x, y, bbox)

        need = q * 4

        if pos + need > len(sec):
            return None

        for _ in range(q):

            dx, dy = struct.unpack_from(
                "<hh",
                sec,
                pos,
            )

            pos += 4

            x += dx
            y += dy

            chain.append((x, y))

            total_points += 1
            total_hits += inside(x, y, bbox)

        chains.append(chain)

    return {
        "chains": chains,
        "chain_count": len(chains),
        "points": total_points,
        "hits": total_hits,
        "all_inside": total_hits == total_points,
        "point_count_ok": total_points == expected_points,
    }


report = OUT / "mg_s1_multichain_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        pages = load_pages(path)

        parsed = 0
        point_count_ok = 0
        all_inside = 0
        chain_formula_ok = 0
        perfect = 0

        total_points = 0
        total_hits = 0

        chain_counts = Counter()
        k_counts = Counter()

        bad = []

        for page_i, (bbox, raw) in enumerate(pages):

            h = struct.unpack_from("<23H", raw, 0)

            start = h[0]
            end = h[2]
            count = h[1]

            sec = raw[start:end]

            extra = len(sec) - (6 + 4*count)

            if extra < 0 or extra % 6:
                if len(bad) < 30:
                    bad.append(
                        (page_i, "bad_size", count, len(sec))
                    )
                continue

            K = extra // 6
            expected_chains = K + 1

            r = decode_multichain(
                sec,
                count,
                bbox,
            )

            if r is None:
                if len(bad) < 30:
                    bad.append(
                        (page_i, "parse_fail", count, len(sec), K)
                    )
                continue

            parsed += 1

            point_count_ok += int(
                r["point_count_ok"]
            )

            all_inside += int(
                r["all_inside"]
            )

            chain_formula_ok += int(
                r["chain_count"] == expected_chains
            )

            is_perfect = (
                r["point_count_ok"]
                and r["all_inside"]
                and r["chain_count"] == expected_chains
            )

            perfect += int(is_perfect)

            total_points += r["points"]
            total_hits += r["hits"]

            chain_counts[r["chain_count"]] += 1
            k_counts[K] += 1

            if not is_perfect and len(bad) < 30:
                bad.append(
                    (
                        page_i,
                        bbox,
                        count,
                        len(sec),
                        K,
                        expected_chains,
                        r["chain_count"],
                        r["points"],
                        r["hits"],
                    )
                )

        print("=" * 90, file=out)
        print("FILE:", name, file=out)
        print("PAGES:", len(pages), file=out)

        print(
            "PARSED:",
            parsed, "/", len(pages),
            file=out,
        )

        print(
            "TOTAL POINT COUNT == h1:",
            point_count_ok, "/", len(pages),
            file=out,
        )

        print(
            "CHAIN COUNT == K+1:",
            chain_formula_ok, "/", len(pages),
            file=out,
        )

        print(
            "ALL POINTS INSIDE BBOX:",
            all_inside, "/", len(pages),
            file=out,
        )

        print(
            "PERFECT ALL CONDITIONS:",
            perfect, "/", len(pages),
            file=out,
        )

        print(
            "GLOBAL POINT HITS:",
            total_hits, "/", total_points,
            (
                f"({100*total_hits/total_points:.6f}%)"
                if total_points else ""
            ),
            file=out,
        )

        print(
            "CHAIN COUNT DISTRIBUTION:",
            chain_counts.most_common(50),
            file=out,
        )

        print(
            "K DISTRIBUTION:",
            k_counts.most_common(50),
            file=out,
        )

        print("FIRST FAILURES:", file=out)

        for x in bad:
            print(" ", x, file=out)

print("Created:", report)
