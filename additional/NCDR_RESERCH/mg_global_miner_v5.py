from pathlib import Path
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from bisect import bisect_right
import sqlite3
import struct
import zlib
import hashlib
import json
import math
import os
import time

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"
OUT.mkdir(parents=True, exist_ok=True)

SQLITE = OUT / "mg_overnight.sqlite"
PARTS = OUT / "mg_global_v5_parts"
PARTS.mkdir(parents=True, exist_ok=True)

REPORT = OUT / "mg_global_v5_report.txt"
FULL = OUT / "mg_global_v5_all.json"

FILES = {
    "7185_MG1": Path("/Volumes/CD_7185/DB/IZ.MG1"),
    "7185_MG2": Path("/Volumes/CD_7185/DB/IZ.MG2"),
    "7185_MG3": Path("/Volumes/CD_7185/DB/IZ.MG3"),
    "7186_MG1": Path("/Volumes/CD_7186/DB/SCZ.MG1"),
    "7186_MG2": Path("/Volumes/CD_7186/DB/SCZ.MG2"),
    "7186_MG3": Path("/Volumes/CD_7186/DB/SCZ.MG3"),
}

LOD_PAIRS = [
    ("7185_MG1", "7185_MG2"),
    ("7185_MG2", "7185_MG3"),
    ("7186_MG1", "7186_MG2"),
    ("7186_MG2", "7186_MG3"),
]

METRIC_CV = [
    ("7185_MG1", "7186_MG1"),
    ("7186_MG1", "7185_MG1"),
    ("7185_MG2", "7186_MG2"),
    ("7186_MG2", "7185_MG2"),
    ("7185_MG3", "7186_MG3"),
    ("7186_MG3", "7185_MG3"),
]

BBOX_PAIRS = [
    ("7185_MG2", "7186_MG2"),
    ("7185_MG3", "7186_MG3"),
]

HDR = 0x72


def log(*x):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *x, flush=True)


def open_db():
    return sqlite3.connect(
        f"file:{SQLITE}?mode=ro",
        uri=True,
        timeout=120,
    )


def part_path(label):
    return PARTS / (label + ".json")


def save_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    tmp.replace(path)


def load_mg(path):
    data = path.read_bytes()
    n = struct.unpack_from("<I", data, 0x56)[0]

    bbox_off = HDR
    meta_off = HDR + 16*n

    directory = []

    for i in range(n):
        bbox = struct.unpack_from(
            "<4i", data, bbox_off + 16*i
        )

        off, rawlen, packed = struct.unpack_from(
            "<IHH", data, meta_off + 8*i
        )

        directory.append(
            (i, bbox, off, rawlen, packed)
        )

    return data, directory


def raw_page(data, rec):
    i, bbox, off, rawlen, packed = rec

    raw = zlib.decompress(
        data[off:off+packed]
    )

    if len(raw) != rawlen:
        raise RuntimeError(
            f"page {i}: raw={len(raw)} expected={rawlen}"
        )

    return raw


def decode_chains(raw, start, end):
    pos = start
    pts = []
    chains = []

    while pos < end:
        q = struct.unpack_from("<H", raw, pos)[0]
        x, y = struct.unpack_from("<ii", raw, pos+2)
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

    if pos != end:
        raise RuntimeError("bad chain consume")

    return pts, chains


def s8(x):
    return x-256 if x >= 128 else x


def geom_hash(a, b):
    if b < a:
        a, b = b, a

    raw = struct.pack(
        "<4i",
        a[0], a[1],
        b[0], b[1],
    )

    return hashlib.blake2b(
        raw,
        digest_size=8
    ).hexdigest()


# ============================================================
# 1. S2 / S4 as independent geometry graphs
# ============================================================

def analyse_sparse_graph(raw, start, count, pts, chains, s6_pairs=None):
    chain_id = [-1] * len(pts)
    chain_pos = [-1] * len(pts)

    for ci, chain in enumerate(chains):
        for pos, idx in enumerate(chain):
            chain_id[idx] = ci
            chain_pos[idx] = pos

    directed = Counter()
    degree = Counter()
    hashes = set()

    st = Counter()
    dist_log = Counter()

    touched = set()

    parent = {}

    def find(x):
        parent.setdefault(x, x)

        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]

        return x

    def union(a, b):
        ra, rb = find(a), find(b)

        if ra != rb:
            parent[rb] = ra

    for k in range(count):
        rec = raw[start+3*k:start+3*k+3]

        idx = struct.unpack_from("<H", rec, 0)[0]
        d = s8(rec[2])

        st["records"] += 1

        if idx >= len(pts):
            st["bad_idx"] += 1
            continue

        target = idx + d

        if not (0 <= target < len(pts)):
            st["bad_target"] += 1

            if chain_pos[idx] == 0:
                st["invalid_at_chain_start"] += 1

            if chain_pos[idx] == len(chains[chain_id[idx]])-1:
                st["invalid_at_chain_end"] += 1

            continue

        st["valid"] += 1

        directed[(idx, target)] += 1

        degree[idx] += 1
        degree[target] += 1

        touched.add(idx)
        touched.add(target)

        union(idx, target)

        if chain_id[idx] == chain_id[target]:
            st["same_chain"] += 1

        if chain_pos[idx] == 0:
            st["source_chain_start"] += 1

        if chain_pos[idx] == len(chains[chain_id[idx]])-1:
            st["source_chain_end"] += 1

        if chain_pos[target] == 0:
            st["target_chain_start"] += 1

        if chain_pos[target] == len(chains[chain_id[target]])-1:
            st["target_chain_end"] += 1

        if (target, idx) in directed:
            st["reciprocal_seen"] += 1

        p1 = pts[idx]
        p2 = pts[target]

        dist = math.hypot(
            p2[0]-p1[0],
            p2[1]-p1[1],
        )

        if dist > 0:
            bucket = int(
                math.floor(
                    math.log2(dist + 1)
                )
            )
            dist_log[bucket] += 1

        hashes.add(
            geom_hash(p1, p2)
        )

        if s6_pairs is not None:
            pair = (
                min(idx, target),
                max(idx, target),
            )

            if pair in s6_pairs:
                st["is_s6_edge"] += 1

    comps = defaultdict(list)

    for v in touched:
        comps[find(v)].append(v)

    st["vertices"] = len(touched)
    st["components"] = len(comps)

    for vs in comps.values():
        edges2 = sum(degree[v] for v in vs) // 2

        st["component_vertices"] += len(vs)
        st["component_edges"] += edges2

        if max((degree[v] for v in vs), default=0) <= 2:
            st["chainlike_components"] += 1

        if edges2 >= len(vs):
            st["cycle_or_complex_components"] += 1

        if len(vs) >= 3:
            st["components_ge3"] += 1

        if len(vs) >= 10:
            st["components_ge10"] += 1

    st["unique_directed"] = len(directed)

    undirected = {
        (min(a,b), max(a,b))
        for a,b in directed
    }

    st["unique_undirected"] = len(undirected)

    reciprocal = 0

    for a,b in undirected:
        if (
            (a,b) in directed
            and (b,a) in directed
        ):
            reciprocal += 1

    st["reciprocal_pairs"] = reciprocal

    return {
        "stats": dict(st),
        "distance_log2": sorted(dist_log.items()),
        "geometry_hashes": sorted(hashes),
        "degree_top": Counter(degree.values()).most_common(20),
    }


def task_sparse(dataset):
    data, directory = load_mg(
        FILES[dataset]
    )

    total2 = Counter()
    total4 = Counter()

    h2 = set()
    h4 = set()

    dist2 = Counter()
    dist4 = Counter()

    for rec in directory:
        raw = raw_page(data, rec)

        h = struct.unpack_from(
            "<23H", raw, 0
        )

        s1, c1 = decode_chains(
            raw, h[0], h[2]
        )

        s3, c3 = decode_chains(
            raw, h[4], h[6]
        )

        s6_pairs = set()

        for eid in range(h[11]):
            r = struct.unpack_from(
                "<7H",
                raw,
                h[10] + 14*eid
            )

            a, b = r[3], r[4]

            if (
                a < len(s1)
                and b < len(s1)
                and a != b
            ):
                s6_pairs.add(
                    (min(a,b), max(a,b))
                )

        a = analyse_sparse_graph(
            raw,
            h[2],
            h[3],
            s1,
            c1,
            s6_pairs,
        )

        b = analyse_sparse_graph(
            raw,
            h[6],
            h[7],
            s3,
            c3,
            None,
        )

        total2.update(a["stats"])
        total4.update(b["stats"])

        h2.update(a["geometry_hashes"])
        h4.update(b["geometry_hashes"])

        dist2.update(dict(a["distance_log2"]))
        dist4.update(dict(b["distance_log2"]))

    return {
        "kind": "sparse",
        "dataset": dataset,
        "S2": dict(total2),
        "S4": dict(total4),
        "S2_hashes": sorted(h2),
        "S4_hashes": sorted(h4),
        "S2_distance_log2": sorted(dist2.items()),
        "S4_distance_log2": sorted(dist4.items()),
    }


# ============================================================
# 2. S11 as 2 x uint32; test global-node-ID hypothesis
# ============================================================

def task_s11_u32(dataset):
    conn = open_db()

    data, directory = load_mg(
        FILES[dataset]
    )

    stream_starts = [
        rec[2]
        for rec in directory
    ]

    stream_ends = [
        rec[2] + rec[4]
        for rec in directory
    ]

    st = Counter()
    diff_hist = Counter()

    query = """
    SELECT
        page,eid,
        va,vb,
        w0,w1,w2,w3
    FROM edges
    WHERE dataset=?
    ORDER BY page,eid
    """

    current_page = None
    page_edges = []

    def finish_page(rows):
        if not rows:
            return

        # Two possible q-to-endpoint orientations.
        maps0 = defaultdict(list)
        maps1 = defaultdict(list)

        unordered = defaultdict(list)

        for (
            page,eid,
            va,vb,
            w0,w1,w2,w3
        ) in rows:

            q0 = w0 | (w1 << 16)
            q1 = w2 | (w3 << 16)

            maps0[va].append(q0)
            maps0[vb].append(q1)

            maps1[va].append(q1)
            maps1[vb].append(q0)

            unordered[va].append((q0,q1))
            unordered[vb].append((q0,q1))

        for name, mp in (
            ("orient01", maps0),
            ("orient10", maps1),
        ):
            for vertex, vals in mp.items():
                if len(vals) < 2:
                    continue

                st[name+".vertices_deg2"] += 1

                c = Counter(vals)
                dominant = c.most_common(1)[0][1]

                if len(c) == 1:
                    st[name+".all_same"] += 1

                st[name+".assigned_values"] += len(vals)
                st[name+".dominant_values"] += dominant

        for vertex, pairs in unordered.items():
            if len(pairs) < 2:
                continue

            st["unordered.vertices_deg2"] += 1

            common = set(pairs[0])

            for pair in pairs[1:]:
                common &= set(pair)

                if not common:
                    break

            if common:
                st["unordered.has_common_q"] += 1

    for row in conn.execute(
        query,
        (dataset,)
    ):
        (
            page,eid,
            va,vb,
            w0,w1,w2,w3
        ) = row

        if current_page is None:
            current_page = page

        if page != current_page:
            finish_page(page_edges)
            page_edges = []
            current_page = page

        page_edges.append(row)

        q0 = w0 | (w1 << 16)
        q1 = w2 | (w3 << 16)

        st["records"] += 1

        if q1 >= q0:
            st["q1_ge_q0"] += 1

        if q0 == q1:
            st["q_equal"] += 1

        d = q1-q0
        diff_hist[d] += 1

        for name, q in (
            ("q0", q0),
            ("q1", q1),
        ):
            if 0 <= q < len(data):
                st[name+".inside_mg_file"] += 1

            j = bisect_right(
                stream_starts, q
            ) - 1

            if (
                0 <= j < len(stream_starts)
                and q < stream_ends[j]
            ):
                st[name+".inside_packed_stream"] += 1

                if j == page:
                    st[name+".inside_own_packed_stream"] += 1

            if q in stream_starts:
                st[name+".equals_stream_start"] += 1

            for align in (
                2,4,8,10,14,16,24,28,32
            ):
                if q % align == 0:
                    st[
                        f"{name}.align{align}"
                    ] += 1

    finish_page(page_edges)

    conn.close()

    return {
        "kind": "s11u32",
        "dataset": dataset,
        "stats": dict(st),
        "qdiff_top": diff_hist.most_common(60),
    }


# ============================================================
# 3. Same-bbox section differential
# ============================================================

def section_hashes(raw):
    h = struct.unpack_from(
        "<23H", raw, 0
    )

    sections = {
        "S1": raw[h[0]:h[2]],
        "S2": raw[h[2]:h[4]],
        "S3": raw[h[4]:h[6]],
        "S4": raw[h[6]:h[8]],
        "S5": raw[h[8]:h[10]],
        "S6": raw[h[10]:h[12]],
        "S11": raw[h[20]:],
    }

    out = {}

    for name, data in sections.items():
        out[name] = hashlib.blake2b(
            data,
            digest_size=12
        ).digest()

    return h, out


def task_bboxdiff(a, b):
    da, dira = load_mg(FILES[a])
    db, dirb = load_mg(FILES[b])

    A = {
        tuple(rec[1]): rec
        for rec in dira
    }

    B = {
        tuple(rec[1]): rec
        for rec in dirb
    }

    common = sorted(
        set(A) & set(B)
    )

    st = Counter()
    qdelta0 = Counter()
    qdelta1 = Counter()

    for bbox in common:
        ra = raw_page(da, A[bbox])
        rb = raw_page(db, B[bbox])

        ha, sa = section_hashes(ra)
        hb, sb = section_hashes(rb)

        st["pages"] += 1

        if ra == rb:
            st["raw_exact"] += 1

        if ha == hb:
            st["header_exact"] += 1

        for sec in (
            "S1","S2","S3",
            "S4","S5","S6","S11"
        ):
            if sa[sec] == sb[sec]:
                st[sec+".exact"] += 1

        if (
            sa["S1"] == sb["S1"]
            and sa["S5"] == sb["S5"]
            and sa["S6"] == sb["S6"]
        ):
            st["topology_exact"] += 1

            if sa["S11"] != sb["S11"]:
                st[
                    "topology_exact_s11_diff"
                ] += 1

                if ha[11] == hb[11]:
                    n = ha[11]

                    deltas0 = []
                    deltas1 = []

                    for eid in range(n):
                        wa = struct.unpack_from(
                            "<4H",
                            ra,
                            ha[20] + 8*eid
                        )

                        wb = struct.unpack_from(
                            "<4H",
                            rb,
                            hb[20] + 8*eid
                        )

                        qa0 = (
                            wa[0] | (wa[1] << 16)
                        )

                        qa1 = (
                            wa[2] | (wa[3] << 16)
                        )

                        qb0 = (
                            wb[0] | (wb[1] << 16)
                        )

                        qb1 = (
                            wb[2] | (wb[3] << 16)
                        )

                        if qa0 == qb0:
                            st["q0_equal"] += 1
                        else:
                            d = qb0-qa0
                            qdelta0[d] += 1
                            deltas0.append(d)

                        if qa1 == qb1:
                            st["q1_equal"] += 1
                        else:
                            d = qb1-qa1
                            qdelta1[d] += 1
                            deltas1.append(d)

                    if (
                        deltas0
                        and len(set(deltas0)) == 1
                    ):
                        st["page_q0_const_shift"] += 1

                    if (
                        deltas1
                        and len(set(deltas1)) == 1
                    ):
                        st["page_q1_const_shift"] += 1

    return {
        "kind": "bboxdiff",
        "a": a,
        "b": b,
        "stats": dict(st),
        "q0_delta_top": qdelta0.most_common(50),
        "q1_delta_top": qdelta1.most_common(50),
    }


# ============================================================
# 4. Exact LOD lookup tables
# ============================================================

def task_lod(src, dst):
    conn = open_db()

    groups = {
        "low3": defaultdict(lambda:[0,0]),
        "low8": defaultdict(lambda:[0,0]),
        "low3_s61hi": defaultdict(lambda:[0,0]),
        "low8_s61hi": defaultdict(lambda:[0,0]),
    }

    sql = """
    SELECT
        a.s60,a.s61,
        CASE
            WHEN b.dataset IS NULL
            THEN 0 ELSE 1
        END
    FROM geom_unique a
    LEFT JOIN geom_unique b
      ON b.dataset=?
     AND b.ax=a.ax
     AND b.ay=a.ay
     AND b.bx=a.bx
     AND b.by=a.by
    WHERE a.dataset=?
    """

    for s60, s61, y in conn.execute(
        sql,
        (dst,src)
    ):
        keys = {
            "low3": (s60 & 7,),
            "low8": (s60 & 255,),
            "low3_s61hi": (
                s60 & 7,
                (s61 >> 8) & 255,
            ),
            "low8_s61hi": (
                s60 & 255,
                (s61 >> 8) & 255,
            ),
        }

        for name, key in keys.items():
            groups[name][key][0] += 1
            groups[name][key][1] += y

    conn.close()

    out = {}

    for name, g in groups.items():
        rows = []

        for key,(n,s) in g.items():
            rows.append({
                "key": list(key),
                "n": n,
                "survive": s,
                "rate": s/n,
            })

        rows.sort(
            key=lambda x: (
                x["key"],
                -x["n"],
            )
        )

        out[name] = rows

    return {
        "kind": "lodtable",
        "src": src,
        "dst": dst,
        "tables": out,
    }


# ============================================================
# 5. Cross-disc prediction of S6[5]
# ============================================================

class LR:
    def __init__(self):
        self.n=0
        self.sx=self.sy=0.0
        self.sxx=self.sxy=0.0

    def add(self,x,y):
        x=float(x); y=float(y)

        self.n += 1
        self.sx += x
        self.sy += y
        self.sxx += x*x
        self.sxy += x*y

    def fit(self):
        if self.n < 2:
            return None

        den = (
            self.sxx
            - self.sx*self.sx/self.n
        )

        if den == 0:
            return None

        slope = (
            self.sxy
            - self.sx*self.sy/self.n
        ) / den

        intercept = (
            self.sy
            - slope*self.sx
        ) / self.n

        return slope,intercept


def attr_key(s60,s61,s62):
    return (
        s60 & 255,
        (s61 >> 8) & 255,
        s62 & 255,
        (s62 >> 8) & 255,
    )


def task_metric_cv(train, test):
    conn = open_db()

    regs = defaultdict(LR)

    sql = """
    SELECT
        ax,ay,bx,by,
        s60,s61,s62,s65
    FROM edges
    WHERE dataset=?
    """

    for (
        ax,ay,bx,by,
        s60,s61,s62,s65
    ) in conn.execute(sql,(train,)):

        d = math.hypot(
            bx-ax,
            by-ay
        )

        if d <= 0:
            continue

        regs[
            attr_key(
                s60,s61,s62
            )
        ].add(d,s65)

    model = {}

    for key,reg in regs.items():
        if reg.n < 500:
            continue

        fit = reg.fit()

        if fit:
            model[key] = (
                fit[0],
                fit[1],
                reg.n,
            )

    st = Counter()

    sum_abs = 0.0
    sum_rel = 0.0

    for (
        ax,ay,bx,by,
        s60,s61,s62,s65
    ) in conn.execute(sql,(test,)):

        key = attr_key(
            s60,s61,s62
        )

        if key not in model:
            st["uncovered"] += 1
            continue

        d = math.hypot(
            bx-ax,
            by-ay
        )

        slope, intercept, ntrain = (
            model[key]
        )

        pred = (
            intercept
            + slope*d
        )

        err = abs(pred-s65)

        st["covered"] += 1

        sum_abs += err
        sum_rel += (
            err/max(1.0,abs(s65))
        )

        for t in (
            1,2,5,10,20,50,100
        ):
            if err <= t:
                st[f"within_{t}"] += 1

    conn.close()

    n = st["covered"]

    return {
        "kind": "metriccv",
        "train": train,
        "test": test,
        "classes": len(model),
        "stats": dict(st),
        "mae": (
            sum_abs/n if n else None
        ),
        "mean_relative_error": (
            sum_rel/n if n else None
        ),
    }


# ============================================================
# Worker / report
# ============================================================

def worker(task):
    kind = task[0]

    label = "_".join(task)

    p = part_path(label)

    if p.exists():
        return label, True, 0.0

    t0 = time.time()

    if kind == "sparse":
        result = task_sparse(task[1])

    elif kind == "s11":
        result = task_s11_u32(task[1])

    elif kind == "bbox":
        result = task_bboxdiff(
            task[1],task[2]
        )

    elif kind == "lod":
        result = task_lod(
            task[1],task[2]
        )

    elif kind == "metric":
        result = task_metric_cv(
            task[1],task[2]
        )

    else:
        raise ValueError(task)

    result["elapsed"] = time.time()-t0

    save_json(p,result)

    return (
        label,
        False,
        result["elapsed"],
    )


def pct(a,b):
    return 100*a/b if b else 0.0


def render(parts):
    kinds = defaultdict(list)

    for x in parts:
        kinds[x["kind"]].append(x)

    with REPORT.open(
        "w",
        encoding="utf-8"
    ) as out:

        print(
            "NCDR MG GLOBAL MINER V5",
            file=out
        )

        print(
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            file=out
        )

        # --------------------------------------------------
        print("\n"+"="*100,file=out)
        print("S2 / S4 GRAPH SEMANTICS",file=out)

        sparse = {
            x["dataset"]:x
            for x in kinds["sparse"]
        }

        for ds,x in sorted(sparse.items()):
            print("\nDATASET",ds,file=out)

            for sec in ("S2","S4"):
                s=x[sec]
                n=s.get("valid",0)

                print("\n",sec,file=out)

                for key in (
                    "records",
                    "valid",
                    "bad_idx",
                    "bad_target",
                    "same_chain",
                    "unique_directed",
                    "unique_undirected",
                    "reciprocal_pairs",
                    "vertices",
                    "components",
                    "chainlike_components",
                    "cycle_or_complex_components",
                    "components_ge3",
                    "components_ge10",
                    "is_s6_edge",
                    "source_chain_start",
                    "source_chain_end",
                    "target_chain_start",
                    "target_chain_end",
                    "invalid_at_chain_start",
                    "invalid_at_chain_end",
                ):
                    if key in s:
                        print(
                            key,
                            s[key],
                            (
                                f"({pct(s[key],n):.4f}% of valid)"
                                if n and key not in (
                                    "records","valid"
                                )
                                else ""
                            ),
                            file=out
                        )

        names=sorted(sparse)

        print(
            "\nEXACT GEOMETRY INTERSECTIONS",
            file=out
        )

        for sec in ("S2","S4"):
            print("\n",sec,file=out)

            for i,a in enumerate(names):
                A=set(
                    sparse[a][
                        sec+"_hashes"
                    ]
                )

                for b in names[i+1:]:
                    B=set(
                        sparse[b][
                            sec+"_hashes"
                        ]
                    )

                    inter=len(A&B)

                    if inter:
                        print(
                            a,"<->",b,
                            "common=",inter,
                            "A%=",
                            f"{pct(inter,len(A)):.3f}",
                            "B%=",
                            f"{pct(inter,len(B)):.3f}",
                            file=out
                        )

        # --------------------------------------------------
        print("\n"+"="*100,file=out)
        print("S11 AS 2 x UINT32",file=out)

        for x in sorted(
            kinds["s11u32"],
            key=lambda q:q["dataset"]
        ):
            s=x["stats"]
            n=s.get("records",0)

            print(
                "\nDATASET",x["dataset"],
                "records",n,
                file=out
            )

            for key in (
                "q1_ge_q0",
                "q_equal",
                "q0.inside_mg_file",
                "q1.inside_mg_file",
                "q0.inside_packed_stream",
                "q1.inside_packed_stream",
                "q0.inside_own_packed_stream",
                "q1.inside_own_packed_stream",
                "q0.equals_stream_start",
                "q1.equals_stream_start",
            ):
                v=s.get(key,0)

                print(
                    key,
                    v,
                    "/",
                    n,
                    f"({pct(v,n):.6f}%)",
                    file=out
                )

            for orient in (
                "orient01",
                "orient10",
            ):
                v=s.get(
                    orient+".vertices_deg2",
                    0
                )

                same=s.get(
                    orient+".all_same",
                    0
                )

                dom=s.get(
                    orient+".dominant_values",
                    0
                )

                tot=s.get(
                    orient+".assigned_values",
                    0
                )

                print(
                    orient,
                    "vertices all-same:",
                    same,"/",v,
                    f"({pct(same,v):.6f}%)",
                    "dominant assigned:",
                    dom,"/",tot,
                    f"({pct(dom,tot):.6f}%)",
                    file=out
                )

            v=s.get(
                "unordered.vertices_deg2",
                0
            )

            c=s.get(
                "unordered.has_common_q",
                0
            )

            print(
                "unordered endpoint common q:",
                c,"/",v,
                f"({pct(c,v):.6f}%)",
                file=out
            )

            print(
                "q1-q0 top:",
                x["qdiff_top"][:30],
                file=out
            )

        # --------------------------------------------------
        print("\n"+"="*100,file=out)
        print("SAME-BBOX SECTION DIFFERENTIAL",file=out)

        for x in kinds["bboxdiff"]:
            s=x["stats"]
            n=s.get("pages",0)

            print(
                "\n",x["a"],"<->",x["b"],
                "common pages",n,
                file=out
            )

            for key in (
                "raw_exact",
                "header_exact",
                "S1.exact",
                "S2.exact",
                "S3.exact",
                "S4.exact",
                "S5.exact",
                "S6.exact",
                "S11.exact",
                "topology_exact",
                "topology_exact_s11_diff",
                "page_q0_const_shift",
                "page_q1_const_shift",
            ):
                v=s.get(key,0)

                print(
                    key,
                    v,
                    "/",
                    n,
                    f"({pct(v,n):.4f}%)",
                    file=out
                )

            print(
                "q0 delta top:",
                x["q0_delta_top"][:20],
                file=out
            )

            print(
                "q1 delta top:",
                x["q1_delta_top"][:20],
                file=out
            )

        # --------------------------------------------------
        print("\n"+"="*100,file=out)
        print("LOD LOOKUP TABLES",file=out)

        for x in kinds["lodtable"]:
            print(
                "\n",
                x["src"],"->",x["dst"],
                file=out
            )

            for name in (
                "low3",
                "low3_s61hi",
            ):
                print("\n",name,file=out)

                for row in x[
                    "tables"
                ][name]:
                    if row["n"] >= 100:
                        print(
                            row["key"],
                            "n=",row["n"],
                            "survival=",
                            f"{100*row['rate']:.6f}%",
                            file=out
                        )

        # --------------------------------------------------
        print("\n"+"="*100,file=out)
        print("S6[5] CROSS-DISC PREDICTION",file=out)

        for x in kinds["metriccv"]:
            s=x["stats"]
            n=s.get("covered",0)

            print(
                "\nTRAIN",x["train"],
                "TEST",x["test"],
                "classes",x["classes"],
                "covered",n,
                "uncovered",s.get("uncovered",0),
                file=out
            )

            print(
                "MAE",x["mae"],
                "mean relative error",
                x["mean_relative_error"],
                file=out
            )

            for t in (
                1,2,5,10,20,50,100
            ):
                v=s.get(
                    f"within_{t}",0
                )

                print(
                    f"within {t}:",
                    v,"/",n,
                    f"({pct(v,n):.6f}%)",
                    file=out
                )


def main():
    if not SQLITE.exists():
        raise SystemExit(
            f"Missing {SQLITE}"
        )

    for p in FILES.values():
        if not p.exists():
            raise SystemExit(
                f"Missing {p}"
            )

    tasks=[]

    for ds in FILES:
        tasks.append(
            ("sparse",ds)
        )

        tasks.append(
            ("s11",ds)
        )

    for a,b in BBOX_PAIRS:
        tasks.append(
            ("bbox",a,b)
        )

    for a,b in LOD_PAIRS:
        tasks.append(
            ("lod",a,b)
        )

    for a,b in METRIC_CV:
        tasks.append(
            ("metric",a,b)
        )

    cpu=os.cpu_count() or 4
    workers=max(2,cpu-1)

    log(
        "CPU",cpu,
        "workers",workers,
        "tasks",len(tasks)
    )

    t0=time.time()

    with ProcessPoolExecutor(
        max_workers=workers
    ) as ex:

        futs={
            ex.submit(worker,t):t
            for t in tasks
        }

        done=0

        for f in as_completed(futs):
            done += 1

            label,cached,elapsed=(
                f.result()
            )

            log(
                f"[{done}/{len(tasks)}]",
                label,
                "CACHED"
                if cached
                else f"{elapsed:.1f}s"
            )

    parts=[]

    for p in sorted(
        PARTS.glob("*.json")
    ):
        with p.open(
            "r",
            encoding="utf-8"
        ) as f:
            parts.append(
                json.load(f)
            )

    save_json(
        FULL,
        {"results":parts}
    )

    render(parts)

    log(
        "ALL DONE",
        f"{(time.time()-t0)/60:.2f} min"
    )

    log("REPORT",REPORT)


if __name__ == "__main__":
    main()
