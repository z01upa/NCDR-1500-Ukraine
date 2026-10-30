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

SPECIAL = {0, 1, 5, 6, 7}


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


def dist_norm(a, b, pts, diag):
    xa, ya = pts[a]
    xb, yb = pts[b]

    return math.hypot(
        xb - xa,
        yb - ya,
    ) / diag


def make_stats():
    return Counter()


report = OUT / "mg_s5_candidate_attribution_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        by_tag_slot = defaultdict(make_stats)
        by_code_slot = defaultdict(make_stats)

        conflict_examples = []
        completion_examples = []

        for page_i, (bbox, raw) in enumerate(load_pages(path)):

            h = struct.unpack_from("<23H", raw, 0)

            pts = decode_s1(raw, h)

            nref = h[11]
            s5_start = h[8]

            diag = math.hypot(
                max(1, bbox[2] - bbox[0]),
                max(1, bbox[3] - bbox[1]),
            )

            records = []
            base = defaultdict(set)

            # ----------------------------------------
            # Pass 1: confirmed tag2/3/4 topology
            # ----------------------------------------

            for i in range(h[9]):

                rec = raw[
                    s5_start + 10*i:
                    s5_start + 10*(i+1)
                ]

                b0 = rec[0]
                b1 = rec[1]
                tag = b0 & 7

                vals = struct.unpack_from(
                    "<4H", rec, 2
                )

                records.append(
                    (b0, b1, tag, vals, rec)
                )

                fields = BASE_RULES.get(tag)

                if fields is None:
                    continue

                if not all(
                    vals[j] < nref
                    for j in fields
                ):
                    continue

                for j in fields:
                    base[vals[j]].add(i)

            # ----------------------------------------
            # Pass 2:
            # judge EVERY slot of EVERY special record
            # independently.
            # ----------------------------------------

            for i, (b0, b1, tag, vals, rec) in enumerate(records):

                if tag not in SPECIAL:
                    continue

                code = b0 | (b1 << 8)

                for slot, ref in enumerate(vals):

                    keys = [
                        ("tag", tag, slot),
                        ("code", code, slot),
                    ]

                    stats_objs = [
                        by_tag_slot[(tag, slot)],
                        by_code_slot[(code, slot)],
                    ]

                    for s in stats_objs:
                        s["total"] += 1

                    if ref >= nref:
                        for s in stats_objs:
                            s["out_range"] += 1
                        continue

                    for s in stats_objs:
                        s["in_range"] += 1

                    base_ids = sorted(base.get(ref, set()))

                    if i in base_ids:
                        for s in stats_objs:
                            s["already_present"] += 1
                        continue

                    bn = len(base_ids)

                    if bn == 0:
                        for s in stats_objs:
                            s["base0"] += 1
                        continue

                    if bn == 1:
                        d = dist_norm(
                            i,
                            base_ids[0],
                            pts,
                            diag,
                        )

                        for s in stats_objs:
                            s["completion"] += 1
                            s["dist_sum"] += d

                            if d <= .01:
                                s["completion_01"] += 1
                            if d <= .02:
                                s["completion_02"] += 1
                            if d <= .05:
                                s["completion_05"] += 1
                            if d <= .10:
                                s["completion_10"] += 1

                        if (
                            d <= .02
                            and len(completion_examples) < 100
                        ):
                            completion_examples.append(
                                (
                                    page_i,
                                    i,
                                    f"code=0x{code:04X}",
                                    f"tag={tag}",
                                    f"slot={slot}",
                                    ref,
                                    base_ids,
                                    d,
                                    rec.hex(),
                                )
                            )

                    elif bn == 2:

                        d0 = dist_norm(
                            i,
                            base_ids[0],
                            pts,
                            diag,
                        )

                        d1 = dist_norm(
                            i,
                            base_ids[1],
                            pts,
                            diag,
                        )

                        dmin = min(d0, d1)

                        for s in stats_objs:
                            s["conflict"] += 1
                            s["conflict_min_sum"] += dmin

                            if dmin <= .01:
                                s["conflict_near_01"] += 1
                            if dmin <= .02:
                                s["conflict_near_02"] += 1
                            if dmin <= .05:
                                s["conflict_near_05"] += 1

                        if (
                            dmin > .05
                            and len(conflict_examples) < 100
                        ):
                            conflict_examples.append(
                                (
                                    page_i,
                                    i,
                                    f"code=0x{code:04X}",
                                    f"tag={tag}",
                                    f"slot={slot}",
                                    ref,
                                    base_ids,
                                    d0,
                                    d1,
                                    rec.hex(),
                                )
                            )

                    else:
                        for s in stats_objs:
                            s["base3plus"] += 1

        print("=" * 100, file=out)
        print("FILE:", name, file=out)

        print(file=out)
        print("TAG/SLOT SUMMARY:", file=out)

        for (tag, slot), s in sorted(by_tag_slot.items()):

            c = s["completion"]
            cf = s["conflict"]

            good = s["completion_05"]

            precision = (
                good / (good + cf)
                if good + cf else 0
            )

            print(
                f"tag={tag} slot={slot} "
                f"total={s['total']} "
                f"in={s['in_range']} "
                f"base0={s['base0']} "
                f"completion={c} "
                f"c01={s['completion_01']} "
                f"c02={s['completion_02']} "
                f"c05={s['completion_05']} "
                f"conflict={cf} "
                f"conf_near05={s['conflict_near_05']} "
                f"score={precision:.6f}",
                file=out,
            )

        print(file=out)
        print("EXACT CODE/SLOT SUMMARY:", file=out)

        ordered = sorted(
            by_code_slot.items(),
            key=lambda x: x[1]["completion"],
            reverse=True,
        )

        for (code, slot), s in ordered:

            # Ignore tiny samples unless interesting.
            evidence = (
                s["completion"]
                + s["conflict"]
            )

            if evidence < 5:
                continue

            good = s["completion_05"]
            bad = s["conflict"]

            score = (
                good / (good + bad)
                if good + bad else 0
            )

            print(
                f"code=0x{code:04X} "
                f"slot={slot} "
                f"in={s['in_range']} "
                f"base0={s['base0']} "
                f"completion={s['completion']} "
                f"c02={s['completion_02']} "
                f"c05={good} "
                f"conflict={bad} "
                f"conf_near05={s['conflict_near_05']} "
                f"score={score:.6f}",
                file=out,
            )

        print(file=out)
        print("GOOD COMPLETION EXAMPLES:", file=out)

        for e in completion_examples:
            print(e, file=out)

        print(file=out)
        print("FAR CONFLICT EXAMPLES:", file=out)

        for e in conflict_examples:
            print(e, file=out)

print("Created:", report)
