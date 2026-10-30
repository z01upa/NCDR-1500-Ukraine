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


def load_pages(path):
    data = path.read_bytes()
    n = struct.unpack_from("<I", data, 0x56)[0]

    bbox_off = HDR
    meta_off = bbox_off + n*16
    zero_off = meta_off + n*8
    payload_off = zero_off + n*4

    physical = {}
    pos = payload_off

    while pos < len(data):
        raw, end = unpack_one(data, pos)
        physical[pos] = raw
        pos = end

    pages = []

    for i in range(n):
        bbox = struct.unpack_from(
            "<4i", data, bbox_off + i*16
        )

        stream_off = struct.unpack_from(
            "<I", data, meta_off + i*8
        )[0]

        pages.append((i, bbox, physical[stream_off]))

    return pages


def decode_multichain(raw, start, end):
    pos = start
    pts = []
    chains = []

    while pos < end:
        q = struct.unpack_from("<H", raw, pos)[0]
        x, y = struct.unpack_from("<ii", raw, pos + 2)
        pos += 10

        chain = [len(pts)]
        pts.append((x, y))

        for _ in range(q):
            dx, dy = struct.unpack_from("<hh", raw, pos)
            pos += 4

            x += dx
            y += dy

            chain.append(len(pts))
            pts.append((x, y))

        chains.append(chain)

    return pts, chains, pos == end


def clean_edges(raw, h):
    start = h[8]
    n = h[9]
    nref = h[11]

    edges = defaultdict(set)

    for i in range(n):
        rec = raw[start+i*10:start+(i+1)*10]

        tag = rec[0] & 7
        fields = S5_RULES.get(tag)

        if fields is None:
            continue

        vals = struct.unpack_from("<4H", rec, 2)
        refs = [vals[j] for j in fields]

        if not all(x < nref for x in refs):
            continue

        for ref in refs:
            edges[ref].add(i)

    return edges


def point_segment_distance(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b

    vx = bx - ax
    vy = by - ay

    if vx == 0 and vy == 0:
        return math.hypot(px-ax, py-ay)

    t = (
        (px-ax)*vx + (py-ay)*vy
    ) / (vx*vx + vy*vy)

    t = max(0.0, min(1.0, t))

    qx = ax + t*vx
    qy = ay + t*vy

    return math.hypot(px-qx, py-qy)


class Corr:
    def __init__(self):
        self.n = 0
        self.sx = self.sy = 0.0
        self.sxx = self.syy = self.sxy = 0.0

    def add(self, x, y):
        x = float(x)
        y = float(y)

        self.n += 1
        self.sx += x
        self.sy += y
        self.sxx += x*x
        self.syy += y*y
        self.sxy += x*y

    def value(self):
        n = self.n

        if n < 2:
            return None

        vx = n*self.sxx - self.sx*self.sx
        vy = n*self.syy - self.sy*self.sy

        if vx <= 0 or vy <= 0:
            return None

        return (
            n*self.sxy - self.sx*self.sy
        ) / math.sqrt(vx*vy)


report = OUT / "mg_global_correlator_v2.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        print("=" * 100, file=out)
        print("FILE:", name, file=out)

        s3_total = 0
        s3_inside = 0
        s3_in_s1 = 0

        s3_chain_start_in_s1 = 0
        s3_chain_end_in_s1 = 0
        s3_chain_count = 0

        endpoint3_ok = 0
        endpoint4_ok = 0
        edge_total = 0

        f5_valid_s3 = 0
        f5_exact_endpoint = 0
        f5_near_segment_01 = 0
        f5_near_segment_05 = 0

        f6 = Counter()

        object_groups = 0
        object_multi = 0
        object_connected = 0
        object_chainlike = 0

        s11_w0_lt_s3 = 0
        s11_w1_lt_s3 = 0
        s11_w2_lt_s3 = 0
        s11_w3_lt_s3 = 0

        bearing_tests = Counter()

        corr_u32diff_len = Corr()
        corr_u16diff_len = Corr()

        q_order = Counter()

        for page_i, bbox, raw in load_pages(path):

            h = struct.unpack_from("<23H", raw, 0)

            s1, c1, ok1 = decode_multichain(
                raw, h[0], h[2]
            )

            s3, c3, ok3 = decode_multichain(
                raw, h[4], h[6]
            )

            if not ok1 or not ok3:
                continue

            s1set = set(s1)

            x0, y0, x1, y1 = bbox

            for p in s3:
                s3_total += 1

                x, y = p

                if x0 <= x <= x1 and y0 <= y <= y1:
                    s3_inside += 1

                if p in s1set:
                    s3_in_s1 += 1

            for chain in c3:
                s3_chain_count += 1

                if s3[chain[0]] in s1set:
                    s3_chain_start_in_s1 += 1

                if s3[chain[-1]] in s1set:
                    s3_chain_end_in_s1 += 1

            edges = clean_edges(raw, h)

            s6_start = h[10]
            s11_start = h[20]

            diag = math.hypot(
                max(1, x1-x0),
                max(1, y1-y0),
            )

            # field5 groups inside this page
            groups = defaultdict(list)

            for eid, ids in edges.items():

                ids = sorted(ids)

                if len(ids) != 2:
                    continue

                a, b = ids

                if a >= len(s1) or b >= len(s1):
                    continue

                edge_total += 1

                r6 = struct.unpack_from(
                    "<7H",
                    raw,
                    s6_start + eid*14
                )

                r11 = struct.unpack_from(
                    "<4H",
                    raw,
                    s11_start + eid*8
                )

                if r6[3] == a:
                    endpoint3_ok += 1

                if r6[4] == b:
                    endpoint4_ok += 1

                f5 = r6[5]
                f6[r6[6]] += 1

                groups[f5].append((a, b))

                pa = s1[a]
                pb = s1[b]

                # -----------------------------
                # S6[5] -> S3 ?
                # -----------------------------

                if f5 < len(s3):
                    f5_valid_s3 += 1

                    p = s3[f5]

                    if p == pa or p == pb:
                        f5_exact_endpoint += 1

                    d = point_segment_distance(
                        p, pa, pb
                    ) / diag

                    if d <= .01:
                        f5_near_segment_01 += 1

                    if d <= .05:
                        f5_near_segment_05 += 1

                # -----------------------------
                # S11 raw u16 range tests
                # -----------------------------

                if r11[0] < len(s3):
                    s11_w0_lt_s3 += 1
                if r11[1] < len(s3):
                    s11_w1_lt_s3 += 1
                if r11[2] < len(s3):
                    s11_w2_lt_s3 += 1
                if r11[3] < len(s3):
                    s11_w3_lt_s3 += 1

                # -----------------------------
                # S11 as 2 x u32
                # -----------------------------

                q0 = r11[0] | (r11[1] << 16)
                q1 = r11[2] | (r11[3] << 16)

                q_order[
                    "q1>q0" if q1 > q0
                    else "q1<q0" if q1 < q0
                    else "equal"
                ] += 1

                edge_len = math.hypot(
                    pb[0]-pa[0],
                    pb[1]-pa[1]
                )

                corr_u32diff_len.add(
                    abs(q1-q0),
                    edge_len
                )

                corr_u16diff_len.add(
                    abs(r11[2]-r11[0]),
                    edge_len
                )

                # -----------------------------
                # S11[1]/[3] as bearings
                # -----------------------------

                dx = pb[0]-pa[0]
                dy = pb[1]-pa[1]

                bearing = (
                    math.degrees(math.atan2(dy, dx))
                    + 360.0
                ) % 360.0

                reverse = (
                    bearing + 180.0
                ) % 360.0

                bround = int(round(bearing)) % 360
                rround = int(round(reverse)) % 360

                bearing_tests["n"] += 1

                if r11[1] == bround:
                    bearing_tests["w1_forward_exact"] += 1

                if r11[1] == rround:
                    bearing_tests["w1_reverse_exact"] += 1

                if r11[3] == bround:
                    bearing_tests["w3_forward_exact"] += 1

                if r11[3] == rround:
                    bearing_tests["w3_reverse_exact"] += 1

                def adiff(v, angle):
                    d = abs(v-angle) % 360
                    return min(d, 360-d)

                if adiff(r11[1], bearing) <= 2:
                    bearing_tests["w1_forward_2deg"] += 1

                if adiff(r11[3], reverse) <= 2:
                    bearing_tests["w3_reverse_2deg"] += 1

            # -----------------------------
            # Do equal S6[5] groups form
            # connected edge chains?
            # -----------------------------

            for f5, es in groups.items():

                object_groups += 1

                if len(es) < 2:
                    continue

                object_multi += 1

                adj = defaultdict(set)

                for a, b in es:
                    adj[a].add(b)
                    adj[b].add(a)

                start = next(iter(adj))
                seen = {start}
                stack = [start]

                while stack:
                    u = stack.pop()

                    for v in adj[u]:
                        if v not in seen:
                            seen.add(v)
                            stack.append(v)

                if len(seen) == len(adj):
                    object_connected += 1

                    if max(
                        (len(x) for x in adj.values()),
                        default=0
                    ) <= 2:
                        object_chainlike += 1

        print("S3 TOTAL:", s3_total, file=out)

        print(
            "S3 INSIDE PAGE BBOX:",
            s3_inside,
            "/",
            s3_total,
            (
                f"({100*s3_inside/s3_total:.4f}%)"
                if s3_total else ""
            ),
            file=out,
        )

        print(
            "S3 EXACTLY MATCHES S1 POINT:",
            s3_in_s1,
            "/",
            s3_total,
            file=out,
        )

        print(
            "S3 CHAIN START IN S1:",
            s3_chain_start_in_s1,
            "/",
            s3_chain_count,
            file=out,
        )

        print(
            "S3 CHAIN END IN S1:",
            s3_chain_end_in_s1,
            "/",
            s3_chain_count,
            file=out,
        )

        print()
        print("EDGE TOTAL:", edge_total, file=out)

        print(
            "S6[3] == endpoint A:",
            endpoint3_ok,
            "/",
            edge_total,
            file=out,
        )

        print(
            "S6[4] == endpoint B:",
            endpoint4_ok,
            "/",
            edge_total,
            file=out,
        )

        print()
        print(
            "S6[5] < S3 count:",
            f5_valid_s3,
            "/",
            edge_total,
            file=out,
        )

        print(
            "S6[5] S3 point == endpoint:",
            f5_exact_endpoint,
            file=out,
        )

        print(
            "S6[5] S3 point distance to edge <=.01:",
            f5_near_segment_01,
            file=out,
        )

        print(
            "S6[5] S3 point distance to edge <=.05:",
            f5_near_segment_05,
            file=out,
        )

        print(
            "S6[6] VALUES:",
            f6.most_common(),
            file=out,
        )

        print()
        print(
            "S6[5] GROUPS:",
            object_groups,
            file=out,
        )

        print(
            "MULTI-EDGE GROUPS:",
            object_multi,
            file=out,
        )

        print(
            "CONNECTED:",
            object_connected,
            "/",
            object_multi,
            file=out,
        )

        print(
            "CONNECTED + DEGREE<=2:",
            object_chainlike,
            "/",
            object_multi,
            file=out,
        )

        print()
        print("S11 FIELD < S3 COUNT:", file=out)
        print(" w0:", s11_w0_lt_s3, "/", edge_total, file=out)
        print(" w1:", s11_w1_lt_s3, "/", edge_total, file=out)
        print(" w2:", s11_w2_lt_s3, "/", edge_total, file=out)
        print(" w3:", s11_w3_lt_s3, "/", edge_total, file=out)

        print()
        print(
            "S11 U32 ORDER:",
            q_order,
            file=out,
        )

        print(
            "corr(|u32_1-u32_0|, edge_length):",
            corr_u32diff_len.value(),
            file=out,
        )

        print(
            "corr(|w2-w0|, edge_length):",
            corr_u16diff_len.value(),
            file=out,
        )

        print()
        print(
            "S11 BEARING TESTS:",
            bearing_tests,
            file=out,
        )

print("Created:", report)
