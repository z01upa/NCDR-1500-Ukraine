from pathlib import Path
from collections import defaultdict, Counter
import struct
import zlib
import math

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

BASE_RULES = {
    2: (0, 1),
    3: (0, 1, 2),
    4: (0, 1, 2, 3),
}

# Conservative expanded model.
#
# tag5 uses v1..v3 only when all three are valid h11 refs.
# tag6 deliberately gets only v0 for now.
EXP_RULES = {
    0: (0,),
    1: (0,),
    2: (0, 1),
    3: (0, 1, 2),
    4: (0, 1, 2, 3),
    5: (1, 2, 3),
    6: (0,),
    7: (0,),
}


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


def parse_refs(rec, nref, rules):
    tag = rec[0] & 7

    fields = rules.get(tag)

    if fields is None:
        return None

    vals = struct.unpack_from("<4H", rec, 2)

    # Require the entire proposed layout to be valid.
    if not all(vals[j] < nref for j in fields):
        return None

    return tuple(vals[j] for j in fields)


def percentile(values, p):
    if not values:
        return None

    a = sorted(values)
    x = (len(a) - 1) * p

    lo = int(x)
    hi = min(lo + 1, len(a) - 1)
    f = x - lo

    return a[lo] * (1 - f) + a[hi] * f


def graph_stats(edge_map, pts, diag):
    fanin = Counter()
    d2 = []

    for ref, ids in edge_map.items():
        ids = sorted(set(ids))
        fanin[len(ids)] += 1

        if len(ids) == 2:
            a, b = ids

            xa, ya = pts[a]
            xb, yb = pts[b]

            d2.append(
                math.hypot(
                    xb - xa,
                    yb - ya,
                ) / diag
            )

    return fanin, d2


report = OUT / "mg_s5_rule_graph_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        base_fanin_total = Counter()
        exp_fanin_total = Counter()

        base_dist = []
        exp_dist = []

        tag_total = Counter()
        tag_rule_valid = Counter()

        base_domain = 0
        exp_domain = 0
        total_domain = 0

        completed_1_to_2 = 0
        completed_dist = []

        created_0_to_2 = 0
        created_dist = []

        conflicts_to_3plus = 0

        examples_conflict = []

        for page_i, (bbox, raw) in enumerate(load_pages(path)):

            h = struct.unpack_from("<23H", raw, 0)

            pts = decode_s1(raw, h)
            nref = h[11]

            if len(pts) != h[9]:
                raise RuntimeError(
                    f"{name} page {page_i}: "
                    f"S1={len(pts)} S5={h[9]}"
                )

            total_domain += nref

            s5_start = h[8]

            base = defaultdict(list)
            expanded = defaultdict(list)

            for i in range(h[9]):

                rec = raw[
                    s5_start + 10*i:
                    s5_start + 10*(i+1)
                ]

                tag = rec[0] & 7
                tag_total[tag] += 1

                br = parse_refs(
                    rec,
                    nref,
                    BASE_RULES,
                )

                if br is not None:
                    for ref in set(br):
                        base[ref].append(i)

                er = parse_refs(
                    rec,
                    nref,
                    EXP_RULES,
                )

                if er is not None:
                    tag_rule_valid[tag] += 1

                    for ref in set(er):
                        expanded[ref].append(i)

            base_domain += len(base)
            exp_domain += len(expanded)

            w = max(1, bbox[2] - bbox[0])
            hh = max(1, bbox[3] - bbox[1])
            diag = math.hypot(w, hh)

            bf, bd = graph_stats(
                base, pts, diag
            )

            ef, ed = graph_stats(
                expanded, pts, diag
            )

            base_fanin_total.update(bf)
            exp_fanin_total.update(ef)

            base_dist.extend(bd)
            exp_dist.extend(ed)

            all_refs = set(base) | set(expanded)

            for ref in all_refs:

                b_ids = sorted(set(base.get(ref, [])))
                e_ids = sorted(set(expanded.get(ref, [])))

                bn = len(b_ids)
                en = len(e_ids)

                if bn == 1 and en == 2:
                    completed_1_to_2 += 1

                    a, b = e_ids
                    xa, ya = pts[a]
                    xb, yb = pts[b]

                    completed_dist.append(
                        math.hypot(
                            xb - xa,
                            yb - ya,
                        ) / diag
                    )

                if bn == 0 and en == 2:
                    created_0_to_2 += 1

                    a, b = e_ids
                    xa, ya = pts[a]
                    xb, yb = pts[b]

                    created_dist.append(
                        math.hypot(
                            xb - xa,
                            yb - ya,
                        ) / diag
                    )

                if bn <= 2 and en >= 3:
                    conflicts_to_3plus += 1

                    if len(examples_conflict) < 30:
                        examples_conflict.append(
                            (
                                page_i,
                                ref,
                                b_ids,
                                e_ids,
                                [pts[x] for x in e_ids],
                            )
                        )

        print("=" * 100, file=out)
        print("FILE:", name, file=out)

        print(
            "DOMAIN:",
            total_domain,
            file=out,
        )

        print(
            "BASE DOMAIN COVERAGE:",
            base_domain,
            "/",
            total_domain,
            f"({100*base_domain/total_domain:.6f}%)",
            file=out,
        )

        print(
            "EXPANDED DOMAIN COVERAGE:",
            exp_domain,
            "/",
            total_domain,
            f"({100*exp_domain/total_domain:.6f}%)",
            file=out,
        )

        print(file=out)
        print("RULE VALIDITY:", file=out)

        for tag in range(8):

            n = tag_total[tag]

            if not n:
                continue

            v = tag_rule_valid[tag]

            print(
                f" tag={tag}: "
                f"{v}/{n} "
                f"({100*v/n:.6f}%)",
                file=out,
            )

        print(file=out)

        print(
            "BASE FAN-IN:",
            base_fanin_total.most_common(20),
            file=out,
        )

        print(
            "EXPANDED FAN-IN:",
            exp_fanin_total.most_common(20),
            file=out,
        )

        print(file=out)

        print(
            "BASE FANIN2 MEDIAN DIST:",
            percentile(base_dist, 0.5),
            file=out,
        )

        print(
            "EXPANDED FANIN2 MEDIAN DIST:",
            percentile(exp_dist, 0.5),
            file=out,
        )

        for t in (0.01, 0.02, 0.05, 0.10):

            b = sum(x <= t for x in base_dist)
            e = sum(x <= t for x in exp_dist)

            print(
                f"DIST <= {t:.2f}: "
                f"base={b}/{len(base_dist)} "
                f"({100*b/len(base_dist):.4f}%) "
                f"expanded={e}/{len(exp_dist)} "
                f"({100*e/len(exp_dist):.4f}%)",
                file=out,
            )

        print(file=out)

        print(
            "BASE FANIN1 -> EXPANDED FANIN2:",
            completed_1_to_2,
            file=out,
        )

        if completed_dist:
            print(
                "  median distance:",
                percentile(completed_dist, 0.5),
                file=out,
            )

            print(
                "  <=.02:",
                sum(x <= .02 for x in completed_dist),
                "/",
                len(completed_dist),
                file=out,
            )

            print(
                "  <=.05:",
                sum(x <= .05 for x in completed_dist),
                "/",
                len(completed_dist),
                file=out,
            )

        print(
            "BASE ABSENT -> EXPANDED FANIN2:",
            created_0_to_2,
            file=out,
        )

        if created_dist:
            print(
                "  median distance:",
                percentile(created_dist, 0.5),
                file=out,
            )

            print(
                "  <=.02:",
                sum(x <= .02 for x in created_dist),
                "/",
                len(created_dist),
                file=out,
            )

            print(
                "  <=.05:",
                sum(x <= .05 for x in created_dist),
                "/",
                len(created_dist),
                file=out,
            )

        print(
            "NEW FANIN>=3 CONFLICTS:",
            conflicts_to_3plus,
            file=out,
        )

        print(file=out)
        print("CONFLICT EXAMPLES:", file=out)

        for e in examples_conflict:
            print(e, file=out)

print("Created:", report)
