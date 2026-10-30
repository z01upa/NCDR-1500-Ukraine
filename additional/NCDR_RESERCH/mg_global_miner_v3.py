from pathlib import Path
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import sqlite3
import struct
import zlib
import math
import json
import os
import re
import time

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"
OUT.mkdir(parents=True, exist_ok=True)

SRCDB = OUT / "mg_overnight.sqlite"
PARTS = OUT / "mg_global_v3_parts"
PARTS.mkdir(parents=True, exist_ok=True)

REPORT = OUT / "mg_global_v3_report.txt"
ALLJSON = OUT / "mg_global_v3_all.json"

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
    ("7185_MG1", "7185_MG3"),
    ("7186_MG1", "7186_MG2"),
    ("7186_MG2", "7186_MG3"),
    ("7186_MG1", "7186_MG3"),
]

CROSS_DISC = [
    ("7185_MG1", "7186_MG1"),
    ("7185_MG2", "7186_MG2"),
    ("7185_MG3", "7186_MG3"),
]

HDR = 0x72


def log(*args):
    print(
        time.strftime("%Y-%m-%d %H:%M:%S"),
        *args,
        flush=True,
    )


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)


def part_path(label):
    return PARTS / (safe_name(label) + ".json")


def save_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(
            obj,
            f,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

    tmp.replace(path)


class Corr:
    def __init__(self):
        self.n = 0
        self.sx = 0.0
        self.sy = 0.0
        self.sxx = 0.0
        self.syy = 0.0
        self.sxy = 0.0

    def add(self, x, y):
        x = float(x)
        y = float(y)

        self.n += 1
        self.sx += x
        self.sy += y
        self.sxx += x*x
        self.syy += y*y
        self.sxy += x*y

    def summary(self):
        n = self.n

        if n < 2:
            return {
                "n": n,
                "r": None,
                "slope": None,
            }

        vx = n*self.sxx - self.sx*self.sx
        vy = n*self.syy - self.sy*self.sy
        cov = n*self.sxy - self.sx*self.sy

        r = None

        if vx > 0 and vy > 0:
            r = cov / math.sqrt(vx*vy)

        slope = None

        den = (
            self.sxx
            - self.sx*self.sx/n
        )

        if den != 0:
            slope = (
                self.sxy
                - self.sx*self.sy/n
            ) / den

        return {
            "n": n,
            "r": r,
            "slope_y_on_x": slope,
        }


def open_db():
    return sqlite3.connect(
        f"file:{SRCDB}?mode=ro",
        uri=True,
        timeout=120,
    )


# ============================================================
# PHASE A
# Massive LOD survival mining.
# ============================================================

def lod_task(src, dst):
    label = f"lod_{src}_to_{dst}"

    conn = open_db()

    fields = [
        "s60",
        "s61",
        "s62",
        "s65",
        "s66",
    ]

    field_counts = {
        f: defaultdict(lambda: [0, 0])
        for f in fields
    }

    byte_counts = {
        f: {
            "lo": [[0, 0] for _ in range(256)],
            "hi": [[0, 0] for _ in range(256)],
        }
        for f in fields
    }

    bit_counts = {
        f: [
            [0, 0, 0, 0]
            for _ in range(16)
        ]
        for f in fields
    }

    signatures = defaultdict(lambda: [0, 0])
    length_bins = defaultdict(lambda: [0, 0])

    total = 0
    survive = 0

    sql = """
    SELECT
        a.s60,a.s61,a.s62,a.s65,a.s66,
        a.ax,a.ay,a.bx,a.by,
        CASE WHEN b.dataset IS NULL THEN 0 ELSE 1 END
    FROM geom_unique a
    LEFT JOIN geom_unique b
      ON b.dataset=?
     AND b.ax=a.ax
     AND b.ay=a.ay
     AND b.bx=a.bx
     AND b.by=a.by
    WHERE a.dataset=?
    """

    for row in conn.execute(sql, (dst, src)):
        values = row[:5]
        ax, ay, bx, by = row[5:9]
        y = int(row[9])

        total += 1
        survive += y

        for f, v in zip(fields, values):
            z = field_counts[f][int(v)]
            z[0] += 1
            z[1] += y

            lo = v & 0xFF
            hi = (v >> 8) & 0xFF

            byte_counts[f]["lo"][lo][0] += 1
            byte_counts[f]["lo"][lo][1] += y

            byte_counts[f]["hi"][hi][0] += 1
            byte_counts[f]["hi"][hi][1] += y

            for bit in range(16):
                if v & (1 << bit):
                    bit_counts[f][bit][0] += 1
                    bit_counts[f][bit][1] += y
                else:
                    bit_counts[f][bit][2] += 1
                    bit_counts[f][bit][3] += y

        sig = (
            int(values[0]),
            int(values[1]),
            int(values[2]),
            int(values[4]),
        )

        z = signatures[sig]
        z[0] += 1
        z[1] += y

        dist = math.hypot(
            bx - ax,
            by - ay,
        )

        lb = int(
            math.floor(
                math.log2(dist + 1.0)
            )
        )

        z = length_bins[lb]
        z[0] += 1
        z[1] += y

    conn.close()

    base = survive / total if total else 0.0

    field_top = {}

    for f in fields:
        rows = []

        for v, (n, s) in field_counts[f].items():
            if n < 100:
                continue

            rate = s / n

            rows.append({
                "value": v,
                "n": n,
                "survive": s,
                "rate": rate,
                "delta_from_base": rate - base,
            })

        rows.sort(
            key=lambda x: (
                abs(x["delta_from_base"])
                * math.sqrt(x["n"])
            ),
            reverse=True,
        )

        field_top[f] = rows[:50]

    byte_top = {}

    for f in fields:
        byte_top[f] = {}

        for side in ("lo", "hi"):
            rows = []

            for value, (n, s) in enumerate(
                byte_counts[f][side]
            ):
                if n < 500:
                    continue

                rate = s/n

                rows.append({
                    "value": value,
                    "n": n,
                    "survive": s,
                    "rate": rate,
                    "delta_from_base": rate-base,
                })

            rows.sort(
                key=lambda x: (
                    abs(x["delta_from_base"])
                    * math.sqrt(x["n"])
                ),
                reverse=True,
            )

            byte_top[f][side] = rows[:30]

    bit_top = []

    for f in fields:
        for bit in range(16):
            n1, s1, n0, s0 = bit_counts[f][bit]

            if n1 < 500 or n0 < 500:
                continue

            r1 = s1/n1
            r0 = s0/n0

            bit_top.append({
                "field": f,
                "bit": bit,
                "n1": n1,
                "rate1": r1,
                "n0": n0,
                "rate0": r0,
                "delta": r1-r0,
            })

    bit_top.sort(
        key=lambda x: abs(x["delta"]),
        reverse=True,
    )

    sig_rows = []

    for sig, (n, s) in signatures.items():
        if n < 100:
            continue

        rate = s/n

        sig_rows.append({
            "signature": list(sig),
            "n": n,
            "survive": s,
            "rate": rate,
            "delta_from_base": rate-base,
        })

    sig_rows.sort(
        key=lambda x: (
            abs(x["delta_from_base"])
            * math.sqrt(x["n"])
        ),
        reverse=True,
    )

    return {
        "kind": "lod",
        "label": label,
        "src": src,
        "dst": dst,
        "total": total,
        "survive": survive,
        "base_rate": base,
        "bit_top": bit_top[:80],
        "field_top": field_top,
        "byte_top": byte_top,
        "signature_top": sig_rows[:100],
        "length_bins": {
            str(k): {
                "n": v[0],
                "survive": v[1],
                "rate": v[1]/v[0],
            }
            for k, v in sorted(length_bins.items())
        },
    }


# ============================================================
# PHASE B
# S6[5] metric / S11 global correlations.
# ============================================================

def metric_task(dataset):
    label = f"metric_{dataset}"

    conn = open_db()

    corr = {
        "f5_euclid": Corr(),
        "f5_manhattan": Corr(),
        "f5_chebyshev": Corr(),
        "f5_absdx": Corr(),
        "f5_absdy": Corr(),

        "w0_euclid": Corr(),
        "w2_euclid": Corr(),

        "w0_f5": Corr(),
        "w2_f5": Corr(),

        "w0_w2": Corr(),
    }

    anisotropic = {
        "dy025": Corr(),
        "dy050": Corr(),
        "dy075": Corr(),
        "dy100": Corr(),
        "dy150": Corr(),
        "dy200": Corr(),
        "dy400": Corr(),
    }

    factors = {
        "dy025": 0.25,
        "dy050": 0.50,
        "dy075": 0.75,
        "dy100": 1.00,
        "dy150": 1.50,
        "dy200": 2.00,
        "dy400": 4.00,
    }

    delta_angle = Counter()
    sum_angle = Counter()
    ratio_hist = Counter()

    s66 = Counter()

    n = 0
    zero_f5 = 0

    sql = """
    SELECT
        ax,ay,bx,by,
        s65,s66,
        w0,w1,w2,w3
    FROM edges
    WHERE dataset=?
    """

    for (
        ax, ay, bx, by,
        f5, f6,
        w0, w1, w2, w3
    ) in conn.execute(sql, (dataset,)):

        n += 1

        dx = abs(bx-ax)
        dy = abs(by-ay)

        eu = math.hypot(dx, dy)
        man = dx + dy
        cheb = max(dx, dy)

        corr["f5_euclid"].add(eu, f5)
        corr["f5_manhattan"].add(man, f5)
        corr["f5_chebyshev"].add(cheb, f5)
        corr["f5_absdx"].add(dx, f5)
        corr["f5_absdy"].add(dy, f5)

        corr["w0_euclid"].add(eu, w0)
        corr["w2_euclid"].add(eu, w2)

        corr["w0_f5"].add(f5, w0)
        corr["w2_f5"].add(f5, w2)
        corr["w0_w2"].add(w0, w2)

        for key, factor in factors.items():
            d = math.sqrt(
                dx*dx
                + factor*dy*dy
            )

            anisotropic[key].add(d, f5)

        if f5 == 0:
            zero_f5 += 1

        if eu > 0 and f5 > 0:
            q = math.log2(f5/eu)

            bucket = round(q*20)/20
            ratio_hist[bucket] += 1

        delta_angle[
            (w3-w1) % 360
        ] += 1

        sum_angle[
            (w3+w1) % 360
        ] += 1

        s66[int(f6)] += 1

    conn.close()

    return {
        "kind": "metric",
        "label": label,
        "dataset": dataset,
        "n": n,
        "zero_f5": zero_f5,
        "corr": {
            k: v.summary()
            for k, v in corr.items()
        },
        "anisotropic": {
            k: v.summary()
            for k, v in anisotropic.items()
        },
        "ratio_log2_top": [
            [k, v]
            for k, v in ratio_hist.most_common(50)
        ],
        "s11_delta_top": delta_angle.most_common(50),
        "s11_sum_top": sum_angle.most_common(50),
        "s66": s66.most_common(),
    }


# ============================================================
# PHASE C
# Cross-disc differences for identical geometry.
# ============================================================

def crossdiff_task(a, b):
    label = f"crossdiff_{a}_{b}"

    conn = open_db()

    fields = [
        "s60",
        "s61",
        "s62",
        "s65",
        "s66",
        "w0",
        "w1",
        "w2",
        "w3",
    ]

    diffs = Counter()
    pairs = {
        f: Counter()
        for f in fields
    }

    xors = {
        f: Counter()
        for f in (
            "s60",
            "s61",
            "s62",
            "s65",
            "s66",
        )
    }

    total = 0

    sql = """
    SELECT
        a.s60,a.s61,a.s62,a.s65,a.s66,
        a.w0,a.w1,a.w2,a.w3,
        b.s60,b.s61,b.s62,b.s65,b.s66,
        b.w0,b.w1,b.w2,b.w3
    FROM geom_unique a
    JOIN geom_unique b
      ON b.ax=a.ax
     AND b.ay=a.ay
     AND b.bx=a.bx
     AND b.by=a.by
    WHERE a.dataset=?
      AND b.dataset=?
    """

    for row in conn.execute(sql, (a, b)):
        total += 1

        A = row[:9]
        B = row[9:]

        for f, va, vb in zip(fields, A, B):
            if va != vb:
                diffs[f] += 1
                pairs[f][(int(va), int(vb))] += 1

                if f in xors:
                    xors[f][
                        int(va) ^ int(vb)
                    ] += 1

    conn.close()

    return {
        "kind": "crossdiff",
        "label": label,
        "a": a,
        "b": b,
        "total": total,
        "diffs": dict(diffs),
        "top_pairs": {
            f: [
                [x, y, n]
                for (x, y), n
                in pairs[f].most_common(40)
            ]
            for f in fields
        },
        "top_xor": {
            f: xors[f].most_common(40)
            for f in xors
        },
    }


# ============================================================
# MG reader / S2 + S4 structural mining.
# ============================================================

def iter_pages(path):
    with path.open("rb") as f:
        hdr = f.read(HDR)

        n = struct.unpack_from(
            "<I", hdr, 0x56
        )[0]

        f.seek(HDR)
        bbox_raw = f.read(n*16)
        meta_raw = f.read(n*8)

        for i in range(n):
            stream_off, raw_size, packed_len = struct.unpack_from(
                "<IHH",
                meta_raw,
                i*8,
            )

            f.seek(stream_off)
            packed = f.read(packed_len)

            raw = zlib.decompress(packed)

            if len(raw) != raw_size:
                raise RuntimeError(
                    f"{path.name} page {i}: "
                    f"{len(raw)} != {raw_size}"
                )

            yield i, raw


def decode_chains(raw, start, end):
    pos = start
    pts = []
    chains = []

    while pos < end:
        q = struct.unpack_from(
            "<H", raw, pos
        )[0]

        x, y = struct.unpack_from(
            "<ii", raw, pos+2
        )

        pos += 10

        chain = [len(pts)]
        pts.append((x, y))

        for _ in range(q):
            dx, dy = struct.unpack_from(
                "<hh", raw, pos
            )

            pos += 4

            x += dx
            y += dy

            chain.append(len(pts))
            pts.append((x, y))

        chains.append(chain)

    return pts, chains


def values3(rec):
    b0, b1, b2 = rec

    return {
        "le24": b0 | (b1 << 8) | (b2 << 16),
        "be24": (b0 << 16) | (b1 << 8) | b2,

        "le16_01": b0 | (b1 << 8),
        "le16_12": b1 | (b2 << 8),

        "be16_01": (b0 << 8) | b1,
        "be16_12": (b1 << 8) | b2,

        "b0": b0,
        "b1": b1,
        "b2": b2,
    }


def analyse_3byte_section(
    raw,
    start,
    count,
    point_count,
    chains,
    h11,
):
    stats = Counter()

    bytepos = [
        Counter(),
        Counter(),
        Counter(),
    ]

    starts = {
        c[0]
        for c in chains
        if c
    }

    ends = {
        c[-1]
        for c in chains
        if c
    }

    vals_by_name = defaultdict(list)

    recs = []

    for i in range(count):
        rec = raw[
            start+i*3:
            start+(i+1)*3
        ]

        if len(rec) != 3:
            continue

        recs.append(rec)

        for k in range(3):
            bytepos[k][rec[k]] += 1

        vv = values3(rec)

        for name, v in vv.items():
            vals_by_name[name].append(v)

            stats[f"{name}.total"] += 1
            stats[f"{name}.lt_points"] += (
                v < point_count
            )
            stats[f"{name}.lt_chains"] += (
                v < len(chains)
            )
            stats[f"{name}.lt_h11"] += (
                v < h11
            )

            stats[f"{name}.is_chain_start"] += (
                v in starts
            )

            stats[f"{name}.is_chain_end"] += (
                v in ends
            )

    for name, arr in vals_by_name.items():
        if len(arr) >= 2:
            stats[f"{name}.monotonic_inc"] += int(
                all(
                    arr[i] <= arr[i+1]
                    for i in range(len(arr)-1)
                )
            )

            stats[f"{name}.strict_inc"] += int(
                all(
                    arr[i] < arr[i+1]
                    for i in range(len(arr)-1)
                )
            )

    if count == len(chains):
        stats["count_eq_chains"] += 1

        for i, rec in enumerate(recs):
            if i >= len(chains):
                break

            vv = values3(rec)

            start_idx = chains[i][0]
            end_idx = chains[i][-1]
            clen = len(chains[i])

            for name, v in vv.items():
                stats[f"{name}.pos_eq_start"] += (
                    v == start_idx
                )

                stats[f"{name}.pos_eq_end"] += (
                    v == end_idx
                )

                stats[f"{name}.pos_eq_len"] += (
                    v == clen
                )

    return stats, [
        x.most_common(30)
        for x in bytepos
    ]


def s2s4_task(dataset):
    label = f"s2s4_{dataset}"

    path = FILES[dataset]

    total = Counter()

    corr_s2 = Corr()
    corr_s4 = Corr()

    byte_s2 = [
        Counter(),
        Counter(),
        Counter(),
    ]

    byte_s4 = [
        Counter(),
        Counter(),
        Counter(),
    ]

    for page_i, raw in iter_pages(path):
        h = struct.unpack_from(
            "<23H", raw, 0
        )

        s1, c1 = decode_chains(
            raw,
            h[0],
            h[2],
        )

        s3, c3 = decode_chains(
            raw,
            h[4],
            h[6],
        )

        total["pages"] += 1

        total["s2_records"] += h[3]
        total["s4_records"] += h[7]

        total["s2_count_eq_c1"] += (
            h[3] == len(c1)
        )

        total["s2_count_eq_c1_minus1"] += (
            h[3] == max(0, len(c1)-1)
        )

        total["s2_count_eq_c1_plus1"] += (
            h[3] == len(c1)+1
        )

        total["s4_count_eq_c3"] += (
            h[7] == len(c3)
        )

        total["s4_count_eq_c3_minus1"] += (
            h[7] == max(0, len(c3)-1)
        )

        total["s4_count_eq_c3_plus1"] += (
            h[7] == len(c3)+1
        )

        corr_s2.add(len(c1), h[3])
        corr_s4.add(len(c3), h[7])

        st2, bp2 = analyse_3byte_section(
            raw,
            h[2],
            h[3],
            len(s1),
            c1,
            h[11],
        )

        st4, bp4 = analyse_3byte_section(
            raw,
            h[6],
            h[7],
            len(s3),
            c3,
            h[11],
        )

        for k, v in st2.items():
            total["S2."+k] += v

        for k, v in st4.items():
            total["S4."+k] += v

        for p in range(3):
            byte_s2[p].update(
                dict(bp2[p])
            )

            byte_s4[p].update(
                dict(bp4[p])
            )

    candidates = {}

    for section in ("S2", "S4"):
        rows = []

        for name in (
            "le24",
            "be24",
            "le16_01",
            "le16_12",
            "be16_01",
            "be16_12",
            "b0",
            "b1",
            "b2",
        ):
            n = total[f"{section}.{name}.total"]

            if not n:
                continue

            rows.append({
                "field": name,
                "n": n,
                "lt_points": total[
                    f"{section}.{name}.lt_points"
                ],
                "lt_chains": total[
                    f"{section}.{name}.lt_chains"
                ],
                "lt_h11": total[
                    f"{section}.{name}.lt_h11"
                ],
                "chain_start_hits": total[
                    f"{section}.{name}.is_chain_start"
                ],
                "chain_end_hits": total[
                    f"{section}.{name}.is_chain_end"
                ],
                "pos_eq_start": total[
                    f"{section}.{name}.pos_eq_start"
                ],
                "pos_eq_end": total[
                    f"{section}.{name}.pos_eq_end"
                ],
                "pos_eq_len": total[
                    f"{section}.{name}.pos_eq_len"
                ],
                "pages_monotonic": total[
                    f"{section}.{name}.monotonic_inc"
                ],
                "pages_strict": total[
                    f"{section}.{name}.strict_inc"
                ],
            })

        candidates[section] = rows

    return {
        "kind": "s2s4",
        "label": label,
        "dataset": dataset,
        "pages": total["pages"],
        "s2_records": total["s2_records"],
        "s4_records": total["s4_records"],

        "s2_count_eq_c1": total[
            "s2_count_eq_c1"
        ],
        "s2_count_eq_c1_minus1": total[
            "s2_count_eq_c1_minus1"
        ],
        "s2_count_eq_c1_plus1": total[
            "s2_count_eq_c1_plus1"
        ],

        "s4_count_eq_c3": total[
            "s4_count_eq_c3"
        ],
        "s4_count_eq_c3_minus1": total[
            "s4_count_eq_c3_minus1"
        ],
        "s4_count_eq_c3_plus1": total[
            "s4_count_eq_c3_plus1"
        ],

        "corr_s1chains_s2count": corr_s2.summary(),
        "corr_s3chains_s4count": corr_s4.summary(),

        "candidates": candidates,

        "S2_byte_top": [
            x.most_common(30)
            for x in byte_s2
        ],

        "S4_byte_top": [
            x.most_common(30)
            for x in byte_s4
        ],
    }


# ============================================================
# Worker wrapper with checkpoint.
# ============================================================

def worker(task):
    kind = task[0]

    if kind == "lod":
        _, src, dst = task
        label = f"lod_{src}_to_{dst}"

    elif kind == "metric":
        _, ds = task
        label = f"metric_{ds}"

    elif kind == "crossdiff":
        _, a, b = task
        label = f"crossdiff_{a}_{b}"

    elif kind == "s2s4":
        _, ds = task
        label = f"s2s4_{ds}"

    else:
        raise ValueError(task)

    path = part_path(label)

    if path.exists():
        return {
            "label": label,
            "cached": True,
        }

    t0 = time.time()

    if kind == "lod":
        result = lod_task(src, dst)

    elif kind == "metric":
        result = metric_task(ds)

    elif kind == "crossdiff":
        result = crossdiff_task(a, b)

    elif kind == "s2s4":
        result = s2s4_task(ds)

    result["elapsed_sec"] = (
        time.time() - t0
    )

    save_json(path, result)

    return {
        "label": label,
        "cached": False,
        "elapsed_sec": result[
            "elapsed_sec"
        ],
    }


# ============================================================
# Report.
# ============================================================

def pct(a, b):
    return 100*a/b if b else 0.0


def load_parts():
    data = []

    for p in sorted(PARTS.glob("*.json")):
        with p.open(
            "r",
            encoding="utf-8"
        ) as f:
            data.append(json.load(f))

    return data


def render_report(parts):
    bykind = defaultdict(list)

    for d in parts:
        bykind[d["kind"]].append(d)

    with REPORT.open(
        "w",
        encoding="utf-8"
    ) as out:

        print(
            "NCDR MG GLOBAL MINER V3",
            file=out
        )

        print(
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            file=out
        )

        print("\n" + "="*100, file=out)
        print("LOD SURVIVAL / ATTRIBUTE MINING", file=out)

        for d in sorted(
            bykind["lod"],
            key=lambda x: x["label"]
        ):
            print("\n", d["src"], "->", d["dst"], file=out)

            print(
                "survive:",
                d["survive"],
                "/",
                d["total"],
                f"({100*d['base_rate']:.6f}%)",
                file=out
            )

            print("\nTOP DISCRIMINATING BITS:", file=out)

            for x in d["bit_top"][:30]:
                print(
                    f"{x['field']} bit{x['bit']:02d}: "
                    f"rate1={100*x['rate1']:.3f}% "
                    f"rate0={100*x['rate0']:.3f}% "
                    f"delta={100*x['delta']:+.3f}% "
                    f"n1={x['n1']} n0={x['n0']}",
                    file=out
                )

            print("\nTOP VALUES PER FIELD:", file=out)

            for f, rows in d["field_top"].items():
                print("FIELD", f, file=out)

                for x in rows[:15]:
                    print(
                        f"  {x['value']:5d} "
                        f"n={x['n']:8d} "
                        f"survival={100*x['rate']:.3f}% "
                        f"delta={100*x['delta_from_base']:+.3f}%",
                        file=out
                    )

            print("\nLENGTH BINS:", file=out)

            for k, x in d["length_bins"].items():
                print(
                    k,
                    x["n"],
                    f"{100*x['rate']:.4f}%",
                    file=out
                )

        print("\n" + "="*100, file=out)
        print("S6[5] / S11 GLOBAL METRICS", file=out)

        for d in sorted(
            bykind["metric"],
            key=lambda x: x["dataset"]
        ):
            print("\nDATASET:", d["dataset"], file=out)
            print("edges:", d["n"], file=out)
            print("S6[5]==0:", d["zero_f5"], file=out)

            print("\nCORRELATIONS:", file=out)

            for k, x in d["corr"].items():
                print(
                    k,
                    "r=", x["r"],
                    "slope=", x.get(
                        "slope_y_on_x"
                    ),
                    "n=", x["n"],
                    file=out
                )

            print("\nANISOTROPIC LENGTH TEST:", file=out)

            for k, x in d["anisotropic"].items():
                print(
                    k,
                    "r=", x["r"],
                    "slope=", x.get(
                        "slope_y_on_x"
                    ),
                    file=out
                )

            print(
                "\nTOP log2(S6[5]/geometric_length):",
                d["ratio_log2_top"][:20],
                file=out
            )

            print(
                "S11 (w3-w1)%360:",
                d["s11_delta_top"][:30],
                file=out
            )

            print(
                "S11 (w3+w1)%360:",
                d["s11_sum_top"][:20],
                file=out
            )

            print(
                "S6[6]:",
                d["s66"],
                file=out
            )

        print("\n" + "="*100, file=out)
        print("S2 / S4 STRUCTURAL MINING", file=out)

        for d in sorted(
            bykind["s2s4"],
            key=lambda x: x["dataset"]
        ):
            print("\nDATASET:", d["dataset"], file=out)
            print("pages:", d["pages"], file=out)

            print(
                "S2 records:",
                d["s2_records"],
                file=out
            )

            print(
                "S4 records:",
                d["s4_records"],
                file=out
            )

            print(
                "S2 count == S1 chains:",
                d["s2_count_eq_c1"],
                "/",
                d["pages"],
                file=out
            )

            print(
                "S2 count == S1 chains-1:",
                d["s2_count_eq_c1_minus1"],
                "/",
                d["pages"],
                file=out
            )

            print(
                "S4 count == S3 chains:",
                d["s4_count_eq_c3"],
                "/",
                d["pages"],
                file=out
            )

            print(
                "S4 count == S3 chains-1:",
                d["s4_count_eq_c3_minus1"],
                "/",
                d["pages"],
                file=out
            )

            print(
                "corr(chain1,S2count):",
                d["corr_s1chains_s2count"],
                file=out
            )

            print(
                "corr(chain3,S4count):",
                d["corr_s3chains_s4count"],
                file=out
            )

            for section in ("S2", "S4"):
                print(
                    "\n",
                    section,
                    "3-BYTE INTERPRETATIONS",
                    file=out
                )

                for x in d["candidates"][section]:
                    n = x["n"]

                    print(
                        x["field"],
                        "n=", n,
                        "lt_points=",
                        f"{pct(x['lt_points'],n):.3f}%",
                        "lt_chains=",
                        f"{pct(x['lt_chains'],n):.3f}%",
                        "lt_h11=",
                        f"{pct(x['lt_h11'],n):.3f}%",
                        "chain_start=",
                        f"{pct(x['chain_start_hits'],n):.3f}%",
                        "chain_end=",
                        f"{pct(x['chain_end_hits'],n):.3f}%",
                        "pos_start=",
                        x["pos_eq_start"],
                        "pos_end=",
                        x["pos_eq_end"],
                        "pos_len=",
                        x["pos_eq_len"],
                        file=out
                    )

                print(
                    section,
                    "byte tops:",
                    d[f"{section}_byte_top"],
                    file=out
                )

        print("\n" + "="*100, file=out)
        print("CROSS-DISC DIFFERENTIAL", file=out)

        for d in sorted(
            bykind["crossdiff"],
            key=lambda x: x["label"]
        ):
            print(
                "\n",
                d["a"],
                "<->",
                d["b"],
                "matches=",
                d["total"],
                file=out
            )

            print("diff counts:", d["diffs"], file=out)

            for f in (
                "s60",
                "s61",
                "s62",
                "s65",
                "s66",
            ):
                print(
                    f,
                    "top value pairs:",
                    d["top_pairs"][f][:20],
                    file=out
                )

                print(
                    f,
                    "top XOR:",
                    d["top_xor"][f][:20],
                    file=out
                )


def main():
    if not SRCDB.exists():
        raise SystemExit(
            f"Missing {SRCDB}"
        )

    for name, path in FILES.items():
        if not path.exists():
            raise SystemExit(
                f"Missing mounted MG: {path}"
            )

    cpu = os.cpu_count() or 4
    workers = max(2, cpu-1)

    log("logical CPUs:", cpu)
    log("workers:", workers)
    log("source DB:", SRCDB)

    tasks = []

    for a, b in LOD_PAIRS:
        tasks.append(
            ("lod", a, b)
        )

    for ds in FILES:
        tasks.append(
            ("metric", ds)
        )

    for a, b in CROSS_DISC:
        tasks.append(
            ("crossdiff", a, b)
        )

    for ds in FILES:
        tasks.append(
            ("s2s4", ds)
        )

    log("tasks:", len(tasks))

    t0 = time.time()

    with ProcessPoolExecutor(
        max_workers=workers
    ) as pool:

        futs = {
            pool.submit(worker, task): task
            for task in tasks
        }

        done = 0

        for fut in as_completed(futs):
            task = futs[fut]

            try:
                r = fut.result()
                done += 1

                if r.get("cached"):
                    log(
                        f"[{done}/{len(tasks)}]",
                        r["label"],
                        "CACHED"
                    )
                else:
                    log(
                        f"[{done}/{len(tasks)}]",
                        r["label"],
                        "DONE",
                        f"{r['elapsed_sec']:.1f}s"
                    )

            except Exception as e:
                log(
                    "FAILED",
                    task,
                    repr(e)
                )
                raise

    parts = load_parts()

    save_json(
        ALLJSON,
        {
            "generated": time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "results": parts,
        }
    )

    render_report(parts)

    elapsed = time.time()-t0

    log(
        "ALL DONE in",
        f"{elapsed/60:.1f} min"
    )

    log("REPORT:", REPORT)
    log("FULL JSON:", ALLJSON)


if __name__ == "__main__":
    main()
