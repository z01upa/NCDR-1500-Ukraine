from pathlib import Path
from collections import Counter, defaultdict
import struct
import zlib

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"
OUT.mkdir(parents=True, exist_ok=True)

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
    meta_off = bbox_off + 16*n
    zero_off = meta_off + 8*n
    payload_off = zero_off + 4*n

    physical = {}
    pos = payload_off

    while pos < len(data):
        raw, end = unpack_one(data, pos)
        physical[pos] = raw
        pos = end

    pages = []

    for i in range(n):
        stream_off = struct.unpack_from(
            "<I", data, meta_off + 8*i
        )[0]

        pages.append(physical[stream_off])

    return pages


def decode_s1(raw, h):
    pos = h[0]
    end = h[2]

    points = []
    chains = []

    chain_id = 0

    while pos < end:
        q = struct.unpack_from("<H", raw, pos)[0]
        x, y = struct.unpack_from("<ii", raw, pos + 2)
        pos += 10

        chain = []

        idx = len(points)
        points.append((x, y, chain_id, 0))
        chain.append(idx)

        for j in range(q):
            dx, dy = struct.unpack_from("<hh", raw, pos)
            pos += 4

            x += dx
            y += dy

            idx = len(points)
            points.append((x, y, chain_id, j + 1))
            chain.append(idx)

        chains.append(chain)
        chain_id += 1

    return points, chains


def parse_clean_refs(rec, nref):
    b0 = rec[0]
    tag = b0 & 7

    vals = struct.unpack_from("<4H", rec, 2)

    # Only forms strongly established so far.
    if tag == 2:
        use = (0, 1)
    elif tag == 3:
        use = (0, 1, 2)
    elif tag == 4:
        use = (0, 1, 2, 3)
    else:
        return None

    refs = tuple(vals[j] for j in use)

    if not all(v < nref for v in refs):
        return None

    return {
        "tag": tag,
        "refs": refs,
        "unique": set(refs),
    }


report = OUT / "mg_s5_topology_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        pages = load_pages(path)

        clean_points = 0
        duplicate_ref_points = 0

        pair_total = 0
        pair_both_clean = 0

        intersections = Counter()

        pair_exact1 = 0
        pair_exact1_same_edge_repeat = 0

        # Edge -> points referring to it.
        fanin = Counter()

        edge_two_points = 0
        edge_two_consecutive = 0
        edge_two_same_chain_nonconsecutive = 0
        edge_two_different_chain = 0

        examples_zero = []
        examples_multi = []
        examples_nonconsecutive = []

        for page_i, raw in enumerate(pages):

            h = struct.unpack_from("<23H", raw, 0)

            points, chains = decode_s1(raw, h)

            nref = h[11]
            s5_start = h[8]

            parsed = []

            edge_points = defaultdict(list)

            for i in range(h[9]):

                rec = raw[
                    s5_start + 10*i:
                    s5_start + 10*(i+1)
                ]

                r = parse_clean_refs(rec, nref)
                parsed.append(r)

                if r is None:
                    continue

                clean_points += 1

                if len(r["refs"]) != len(r["unique"]):
                    duplicate_ref_points += 1

                for ref in r["unique"]:
                    edge_points[ref].append(i)

            # ---------------------------------------
            # Test consecutive points inside S1 chain
            # ---------------------------------------

            for chain in chains:

                for a, b in zip(chain, chain[1:]):

                    pair_total += 1

                    ra = parsed[a]
                    rb = parsed[b]

                    if ra is None or rb is None:
                        continue

                    pair_both_clean += 1

                    common = (
                        ra["unique"]
                        & rb["unique"]
                    )

                    intersections[len(common)] += 1

                    if len(common) == 1:
                        pair_exact1 += 1
                    elif len(common) == 0:
                        if len(examples_zero) < 40:
                            examples_zero.append(
                                (
                                    page_i,
                                    a,
                                    b,
                                    points[a],
                                    points[b],
                                    ra,
                                    rb,
                                )
                            )
                    else:
                        if len(examples_multi) < 40:
                            examples_multi.append(
                                (
                                    page_i,
                                    a,
                                    b,
                                    points[a],
                                    points[b],
                                    sorted(common),
                                    ra,
                                    rb,
                                )
                            )

            # ---------------------------------------
            # Reverse test:
            # edge referenced by exactly 2 points
            # -> are these points consecutive?
            # ---------------------------------------

            for ref, ids in edge_points.items():

                fanin[len(ids)] += 1

                if len(ids) != 2:
                    continue

                edge_two_points += 1

                a, b = sorted(ids)

                xa, ya, ca, pa = points[a]
                xb, yb, cb, pb = points[b]

                if ca == cb and abs(pa - pb) == 1:
                    edge_two_consecutive += 1

                elif ca == cb:
                    edge_two_same_chain_nonconsecutive += 1

                    if len(examples_nonconsecutive) < 40:
                        examples_nonconsecutive.append(
                            (
                                page_i,
                                ref,
                                a,
                                b,
                                points[a],
                                points[b],
                            )
                        )

                else:
                    edge_two_different_chain += 1

        print("=" * 100, file=out)
        print("FILE:", name, file=out)

        print(
            "CLEAN TAG2/3/4 POINTS:",
            clean_points,
            file=out,
        )

        print(
            "POINTS WITH DUPLICATE REFS:",
            duplicate_ref_points,
            file=out,
        )

        print()
        print("FORWARD: CONSECUTIVE S1 POINTS", file=out)

        print(
            "TOTAL CONSECUTIVE PAIRS:",
            pair_total,
            file=out,
        )

        print(
            "BOTH ENDS CLEAN:",
            pair_both_clean,
            file=out,
        )

        print(
            "INTERSECTION SIZE:",
            intersections.most_common(),
            file=out,
        )

        print(
            "EXACTLY ONE COMMON REF:",
            pair_exact1,
            "/",
            pair_both_clean,
            (
                f"({100*pair_exact1/pair_both_clean:.6f}%)"
                if pair_both_clean else ""
            ),
            file=out,
        )

        print()
        print("REVERSE: REF -> POINTS", file=out)

        print(
            "FAN-IN:",
            fanin.most_common(20),
            file=out,
        )

        print(
            "REFS WITH EXACTLY 2 POINTS:",
            edge_two_points,
            file=out,
        )

        print(
            "TWO POINTS ARE CONSECUTIVE IN SAME CHAIN:",
            edge_two_consecutive,
            "/",
            edge_two_points,
            (
                f"({100*edge_two_consecutive/edge_two_points:.6f}%)"
                if edge_two_points else ""
            ),
            file=out,
        )

        print(
            "SAME CHAIN BUT NONCONSECUTIVE:",
            edge_two_same_chain_nonconsecutive,
            file=out,
        )

        print(
            "DIFFERENT CHAINS:",
            edge_two_different_chain,
            file=out,
        )

        print()
        print("ZERO-INTERSECTION EXAMPLES:", file=out)

        for e in examples_zero:
            print(e, file=out)

        print()
        print("MULTI-INTERSECTION EXAMPLES:", file=out)

        for e in examples_multi:
            print(e, file=out)

        print()
        print("NONCONSECUTIVE EDGE EXAMPLES:", file=out)

        for e in examples_nonconsecutive:
            print(e, file=out)

print("Created:", report)
