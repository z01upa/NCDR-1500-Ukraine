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

# Only the strongest S5 layouts.
S5_RULES = {
    2: (0, 1),
    3: (0, 1, 2),
    4: (0, 1, 2, 3),
}


def unpack_one(data, start):
    d = zlib.decompressobj()
    raw = d.decompress(data[start:])

    if not d.eof:
        raise RuntimeError(f"bad zlib @ 0x{start:X}")

    used = len(data[start:]) - len(d.unused_data)
    raw += d.flush()

    return raw, start + used


def load_file(path):
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
            "<4i",
            data,
            bbox_off + i*16
        )

        stream_off = struct.unpack_from(
            "<I",
            data,
            meta_off + i*8
        )[0]

        pages.append({
            "page": i,
            "bbox": bbox,
            "raw": physical[stream_off],
        })

    return pages


def decode_multichain(raw, start, end):
    pos = start
    pts = []
    chains = []

    try:
        while pos < end:
            q = struct.unpack_from("<H", raw, pos)[0]
            x, y = struct.unpack_from("<ii", raw, pos + 2)
            pos += 10

            chain = []
            idx = len(pts)

            pts.append((x, y))
            chain.append(idx)

            for _ in range(q):
                dx, dy = struct.unpack_from(
                    "<hh", raw, pos
                )
                pos += 4

                x += dx
                y += dy

                idx = len(pts)
                pts.append((x, y))
                chain.append(idx)

            chains.append(chain)

        return (
            pos == end,
            pts,
            chains
        )

    except Exception:
        return False, [], []


def parse_s5(raw, h):
    s5_start = h[8]
    n5 = h[9]
    nref = h[11]

    result = []
    edges = defaultdict(list)

    for i in range(n5):
        rec = raw[
            s5_start + i*10:
            s5_start + (i+1)*10
        ]

        if len(rec) != 10:
            result.append(None)
            continue

        b0 = rec[0]
        b1 = rec[1]
        tag = b0 & 7

        vals = struct.unpack_from("<4H", rec, 2)

        fields = S5_RULES.get(tag)

        if fields is None:
            result.append(None)
            continue

        refs = tuple(vals[j] for j in fields)

        if not all(r < nref for r in refs):
            result.append(None)
            continue

        info = {
            "b0": b0,
            "b1": b1,
            "tag": tag,
            "vals": vals,
            "refs": refs,
        }

        result.append(info)

        for slot, ref in enumerate(refs):
            edges[ref].append((i, slot))

    return result, edges


def percentile(a, p):
    if not a:
        return None

    a = sorted(a)
    x = (len(a)-1)*p
    lo = int(x)
    hi = min(lo+1, len(a)-1)
    f = x-lo

    return a[lo]*(1-f) + a[hi]*f


def edge_key(p1, p2):
    if p1 <= p2:
        return p1 + p2
    return p2 + p1


all_datasets = {}
report = OUT / "mg_global_semantics_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        print("=" * 100, file=out)
        print("FILE:", name, file=out)

        pages = load_file(path)

        # --------------------------------------
        # GLOBAL COUNTERS
        # --------------------------------------

        s3_pages = 0
        s3_parse_ok = 0
        s3_count_ok = 0
        s3_points = 0

        graph_edges2 = 0

        s6_stats = [
            Counter() for _ in range(7)
        ]

        s11_stats = [
            Counter() for _ in range(4)
        ]

        edge_lengths = []

        exact_geometry_edges = {}

        # Relations:
        # field -> endpoint-index relationships
        relation_s6 = [
            Counter() for _ in range(7)
        ]

        relation_s11 = [
            Counter() for _ in range(4)
        ]

        lowbyte_s6 = [
            Counter() for _ in range(7)
        ]

        highbyte_s6 = [
            Counter() for _ in range(7)
        ]

        lowbyte_s11 = [
            Counter() for _ in range(4)
        ]

        highbyte_s11 = [
            Counter() for _ in range(4)
        ]

        for page in pages:

            raw = page["raw"]
            bbox = page["bbox"]
            page_i = page["page"]

            h = struct.unpack_from(
                "<23H", raw, 0
            )

            # ==================================
            # S1
            # ==================================

            ok1, s1, chains1 = decode_multichain(
                raw,
                h[0],
                h[2],
            )

            if not ok1 or len(s1) != h[1]:
                continue

            # ==================================
            # S3 GLOBAL TEST
            # ==================================

            s3_pages += 1

            ok3, s3, chains3 = decode_multichain(
                raw,
                h[4],
                h[6],
            )

            if ok3:
                s3_parse_ok += 1
                s3_points += len(s3)

                if len(s3) == h[5]:
                    s3_count_ok += 1

            # ==================================
            # S5 GRAPH
            # ==================================

            s5, edges = parse_s5(raw, h)

            nedge = h[11]

            s6_start = h[10]
            s11_start = h[20]

            diag = math.hypot(
                max(1, bbox[2]-bbox[0]),
                max(1, bbox[3]-bbox[1]),
            )

            for edge_id, users in edges.items():

                # unique point endpoints
                point_ids = sorted(
                    set(x[0] for x in users)
                )

                if len(point_ids) != 2:
                    continue

                a, b = point_ids

                if a >= len(s1) or b >= len(s1):
                    continue

                p1 = s1[a]
                p2 = s1[b]

                graph_edges2 += 1

                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]

                dist = math.hypot(dx, dy)
                edge_lengths.append(
                    dist / diag
                )

                # Endpoint S5 slot positions.
                positions = {}

                for point_id, slot in users:
                    if point_id in (a, b):
                        positions.setdefault(
                            point_id, slot
                        )

                slot_a = positions.get(a, -1)
                slot_b = positions.get(b, -1)

                tag_a = (
                    s5[a]["tag"]
                    if s5[a] else -1
                )

                tag_b = (
                    s5[b]["tag"]
                    if s5[b] else -1
                )

                # ==================================
                # S6 edge record = 7*u16
                # ==================================

                off6 = s6_start + edge_id*14

                if off6 + 14 <= len(raw):

                    v6 = struct.unpack_from(
                        "<7H", raw, off6
                    )

                    for k, v in enumerate(v6):

                        s6_stats[k][v] += 1
                        lowbyte_s6[k][v & 0xFF] += 1
                        highbyte_s6[k][v >> 8] += 1

                        r = relation_s6[k]

                        r["total"] += 1
                        r["eq_edge"] += (v == edge_id)
                        r["eq_a"] += (v == a)
                        r["eq_b"] += (v == b)
                        r["eq_min"] += (
                            v == min(a, b)
                        )
                        r["eq_max"] += (
                            v == max(a, b)
                        )

                        r["eq_abs_index_delta"] += (
                            v == abs(a-b)
                        )

                        r["eq_slot_a"] += (
                            v == slot_a
                        )

                        r["eq_slot_b"] += (
                            v == slot_b
                        )

                        r["eq_tag_a"] += (
                            v == tag_a
                        )

                        r["eq_tag_b"] += (
                            v == tag_b
                        )

                        if -32768 <= dx <= 32767:
                            r["eq_dx_u16"] += (
                                v == (dx & 0xFFFF)
                            )

                        if -32768 <= dy <= 32767:
                            r["eq_dy_u16"] += (
                                v == (dy & 0xFFFF)
                            )

                        rounded_len = int(
                            round(dist)
                        )

                        r["eq_round_length"] += (
                            v == rounded_len
                        )

                # ==================================
                # S11 edge record = 4*u16
                # ==================================

                off11 = s11_start + edge_id*8

                if off11 + 8 <= len(raw):

                    v11 = struct.unpack_from(
                        "<4H", raw, off11
                    )

                    for k, v in enumerate(v11):

                        s11_stats[k][v] += 1
                        lowbyte_s11[k][v & 0xFF] += 1
                        highbyte_s11[k][v >> 8] += 1

                        r = relation_s11[k]

                        r["total"] += 1
                        r["eq_edge"] += (v == edge_id)
                        r["eq_a"] += (v == a)
                        r["eq_b"] += (v == b)
                        r["eq_min"] += (
                            v == min(a, b)
                        )
                        r["eq_max"] += (
                            v == max(a, b)
                        )

                        r["eq_abs_index_delta"] += (
                            v == abs(a-b)
                        )

                        r["eq_slot_a"] += (
                            v == slot_a
                        )

                        r["eq_slot_b"] += (
                            v == slot_b
                        )

                        r["eq_tag_a"] += (
                            v == tag_a
                        )

                        r["eq_tag_b"] += (
                            v == tag_b
                        )

                        if -32768 <= dx <= 32767:
                            r["eq_dx_u16"] += (
                                v == (dx & 0xFFFF)
                            )

                        if -32768 <= dy <= 32767:
                            r["eq_dy_u16"] += (
                                v == (dy & 0xFFFF)
                            )

                        rounded_len = int(
                            round(dist)
                        )

                        r["eq_round_length"] += (
                            v == rounded_len
                        )

                # ==================================
                # Cross-LOD geometry key
                # ==================================

                rec6 = (
                    raw[
                        s6_start + edge_id*14:
                        s6_start + edge_id*14 + 14
                    ]
                )

                rec11 = (
                    raw[
                        s11_start + edge_id*8:
                        s11_start + edge_id*8 + 8
                    ]
                )

                key = edge_key(p1, p2)

                # Keep only first occurrence.
                exact_geometry_edges.setdefault(
                    key,
                    (
                        rec6,
                        rec11,
                        page_i,
                        edge_id,
                    )
                )

        # Save for cross-file comparison.
        all_datasets[name] = exact_geometry_edges

        # ======================================
        # REPORT PER FILE
        # ======================================

        print(file=out)
        print("S3 MULTICHAIN TEST:", file=out)

        print(
            "pages:", s3_pages,
            file=out,
        )

        print(
            "parse exact:",
            s3_parse_ok,
            "/",
            s3_pages,
            file=out,
        )

        print(
            "point count == h5:",
            s3_count_ok,
            "/",
            s3_pages,
            file=out,
        )

        print(
            "decoded S3 points:",
            s3_points,
            file=out,
        )

        print(file=out)

        print(
            "CLEAN FANIN2 EDGES:",
            graph_edges2,
            file=out,
        )

        print(
            "EDGE DIST MEDIAN:",
            percentile(edge_lengths, .5),
            file=out,
        )

        print(
            "EDGE DIST P95:",
            percentile(edge_lengths, .95),
            file=out,
        )

        print(file=out)
        print("S6 FIELD ANALYSIS:", file=out)

        for k in range(7):

            r = relation_s6[k]
            n = r["total"]

            print(
                f"S6[{k}] total={n} "
                f"unique={len(s6_stats[k])} "
                f"top={s6_stats[k].most_common(12)}",
                file=out,
            )

            print(
                " relations:",
                r.most_common(),
                file=out,
            )

            print(
                " low8:",
                lowbyte_s6[k].most_common(12),
                file=out,
            )

            print(
                " high8:",
                highbyte_s6[k].most_common(12),
                file=out,
            )

        print(file=out)
        print("S11 FIELD ANALYSIS:", file=out)

        for k in range(4):

            r = relation_s11[k]
            n = r["total"]

            print(
                f"S11[{k}] total={n} "
                f"unique={len(s11_stats[k])} "
                f"top={s11_stats[k].most_common(12)}",
                file=out,
            )

            print(
                " relations:",
                r.most_common(),
                file=out,
            )

            print(
                " low8:",
                lowbyte_s11[k].most_common(12),
                file=out,
            )

            print(
                " high8:",
                highbyte_s11[k].most_common(12),
                file=out,
            )

    # ==================================================
    # CROSS-LOD / CROSS-FILE
    # ==================================================

    print("=" * 100, file=out)
    print("CROSS-LOD EXACT GEOMETRY EDGE MATCHES", file=out)

    pairs = [
        ("7185_MG1", "7185_MG2"),
        ("7185_MG1", "7185_MG3"),
        ("7185_MG2", "7185_MG3"),
        ("7186_MG1", "7186_MG2"),
        ("7186_MG1", "7186_MG3"),
        ("7186_MG2", "7186_MG3"),
    ]

    for a_name, b_name in pairs:

        A = all_datasets[a_name]
        B = all_datasets[b_name]

        common = set(A) & set(B)

        s6_exact = 0
        s11_exact = 0

        s6_field_equal = Counter()
        s11_field_equal = Counter()

        for key in common:

            a6, a11, _, _ = A[key]
            b6, b11, _, _ = B[key]

            if len(a6) == 14 and len(b6) == 14:
                if a6 == b6:
                    s6_exact += 1

                ua = struct.unpack("<7H", a6)
                ub = struct.unpack("<7H", b6)

                for i in range(7):
                    s6_field_equal[i] += (
                        ua[i] == ub[i]
                    )

            if len(a11) == 8 and len(b11) == 8:
                if a11 == b11:
                    s11_exact += 1

                ua = struct.unpack("<4H", a11)
                ub = struct.unpack("<4H", b11)

                for i in range(4):
                    s11_field_equal[i] += (
                        ua[i] == ub[i]
                    )

        print(file=out)

        print(
            a_name,
            "<->",
            b_name,
            file=out,
        )

        print(
            "COMMON EXACT GEOMETRY EDGES:",
            len(common),
            file=out,
        )

        if common:
            print(
                "S6 exact record:",
                s6_exact,
                "/",
                len(common),
                file=out,
            )

            print(
                "S6 field equality:",
                [
                    (
                        i,
                        s6_field_equal[i],
                        len(common),
                        100*s6_field_equal[i]/len(common)
                    )
                    for i in range(7)
                ],
                file=out,
            )

            print(
                "S11 exact record:",
                s11_exact,
                "/",
                len(common),
                file=out,
            )

            print(
                "S11 field equality:",
                [
                    (
                        i,
                        s11_field_equal[i],
                        len(common),
                        100*s11_field_equal[i]/len(common)
                    )
                    for i in range(4)
                ],
                file=out,
            )

print("Created:", report)
