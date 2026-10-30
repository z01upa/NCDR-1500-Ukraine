from pathlib import Path
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import sqlite3
import struct
import zlib
import hashlib
import math
import json
import os
import time

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"
OUT.mkdir(parents=True, exist_ok=True)

SQLITE = OUT / "mg_overnight.sqlite"
PARTS = OUT / "mg_global_v4_parts"
PARTS.mkdir(parents=True, exist_ok=True)

REPORT = OUT / "mg_global_v4_report.txt"
FULL = OUT / "mg_global_v4_all.json"

FILES = {
    "7185_MG1": Path("/Volumes/CD_7185/DB/IZ.MG1"),
    "7185_MG2": Path("/Volumes/CD_7185/DB/IZ.MG2"),
    "7185_MG3": Path("/Volumes/CD_7185/DB/IZ.MG3"),
    "7186_MG1": Path("/Volumes/CD_7186/DB/SCZ.MG1"),
    "7186_MG2": Path("/Volumes/CD_7186/DB/SCZ.MG2"),
    "7186_MG3": Path("/Volumes/CD_7186/DB/SCZ.MG3"),
}

CROSSVAL = [
    (
        "7185_MG1", "7185_MG2",
        "7186_MG1", "7186_MG2",
    ),
    (
        "7186_MG1", "7186_MG2",
        "7185_MG1", "7185_MG2",
    ),
    (
        "7185_MG2", "7185_MG3",
        "7186_MG2", "7186_MG3",
    ),
    (
        "7186_MG2", "7186_MG3",
        "7185_MG2", "7185_MG3",
    ),
]

HDR = 0x72


def log(*x):
    print(
        time.strftime("%Y-%m-%d %H:%M:%S"),
        *x,
        flush=True,
    )


def save(path, obj):
    tmp = path.with_suffix(".tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(
            obj,
            f,
            indent=2,
            sort_keys=True,
        )

    tmp.replace(path)


def ppath(label):
    return PARTS / (label + ".json")


def open_db():
    return sqlite3.connect(
        f"file:{SQLITE}?mode=ro",
        uri=True,
        timeout=120,
    )


# =========================================================
# MG reader
# =========================================================

def load_directory(path):
    data = path.read_bytes()

    n = struct.unpack_from("<I", data, 0x56)[0]

    bbox_off = HDR
    meta_off = HDR + 16*n

    out = []

    for i in range(n):
        bbox = struct.unpack_from(
            "<4i",
            data,
            bbox_off + 16*i,
        )

        off, rawlen, packed = struct.unpack_from(
            "<IHH",
            data,
            meta_off + 8*i,
        )

        out.append(
            (i, bbox, off, rawlen, packed)
        )

    return data, out


def pages(path):
    data, directory = load_directory(path)

    for i, bbox, off, rawlen, packed in directory:
        raw = zlib.decompress(
            data[off:off+packed]
        )

        if len(raw) != rawlen:
            raise RuntimeError(
                f"{path.name} page {i}: "
                f"{len(raw)} != {rawlen}"
            )

        yield i, bbox, raw


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

    if pos != end:
        raise RuntimeError(
            f"bad chain consume {pos} != {end}"
        )

    return pts, chains


def chain_maps(chains, n):
    cid = [-1] * n
    cpos = [-1] * n

    for c, chain in enumerate(chains):
        for p, idx in enumerate(chain):
            cid[idx] = c
            cpos[idx] = p

    return cid, cpos


def s8(v):
    return v - 256 if v >= 128 else v


# =========================================================
# TASK 1: deep S2/S4
# =========================================================

def analyse_link_section(
    raw,
    start,
    count,
    pts,
    chains,
    s6_edges=None,
):
    cid, cpos = chain_maps(
        chains,
        len(pts),
    )

    st = Counter()
    delta_hist = Counter()

    prev_idx = None

    for k in range(count):
        rec = raw[
            start + 3*k:
            start + 3*k + 3
        ]

        idx = struct.unpack_from(
            "<H", rec, 0
        )[0]

        delta = s8(rec[2])

        st["records"] += 1
        delta_hist[delta] += 1

        if idx < len(pts):
            st["idx_valid"] += 1
        else:
            continue

        if prev_idx is not None:
            st["ordered_total"] += 1

            if idx >= prev_idx:
                st["ordered_nondec"] += 1

        prev_idx = idx

        target = idx + delta

        if 0 <= target < len(pts):
            st["target_valid"] += 1
        else:
            continue

        if cid[idx] == cid[target]:
            st["same_chain"] += 1

            pd = (
                cpos[target]
                - cpos[idx]
            )

            if pd == delta:
                st["chain_pos_delta_exact"] += 1

            if abs(pd) == 1:
                st["chain_adjacent"] += 1

        if abs(delta) == 1:
            st["delta_abs1"] += 1

        if delta == 1:
            st["delta_plus1"] += 1

        if delta == -1:
            st["delta_minus1"] += 1

        if s6_edges is not None:
            pair = (
                min(idx, target),
                max(idx, target),
            )

            if pair in s6_edges:
                st["pair_is_s6_edge"] += 1

    return {
        "stats": dict(st),
        "delta_top": delta_hist.most_common(40),
    }


def task_s2s4(dataset):
    result = {
        "kind": "s2s4deep",
        "dataset": dataset,
        "S2": Counter(),
        "S4": Counter(),
        "S2_delta": Counter(),
        "S4_delta": Counter(),
        "pages": 0,
    }

    for page_i, bbox, raw in pages(
        FILES[dataset]
    ):
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

        # Build S6 endpoint-pair set directly.
        s6set = set()

        s6_start = h[10]

        for eid in range(h[11]):
            r = struct.unpack_from(
                "<7H",
                raw,
                s6_start + 14*eid,
            )

            a, b = r[3], r[4]

            if (
                a < len(s1)
                and b < len(s1)
                and a != b
            ):
                s6set.add(
                    (
                        min(a, b),
                        max(a, b),
                    )
                )

        a = analyse_link_section(
            raw,
            h[2],
            h[3],
            s1,
            c1,
            s6set,
        )

        b = analyse_link_section(
            raw,
            h[6],
            h[7],
            s3,
            c3,
            None,
        )

        result["pages"] += 1

        result["S2"].update(
            a["stats"]
        )

        result["S4"].update(
            b["stats"]
        )

        result["S2_delta"].update(
            dict(a["delta_top"])
        )

        result["S4_delta"].update(
            dict(b["delta_top"])
        )

    result["S2"] = dict(
        result["S2"]
    )

    result["S4"] = dict(
        result["S4"]
    )

    result["S2_delta"] = (
        result["S2_delta"].most_common(50)
    )

    result["S4_delta"] = (
        result["S4_delta"].most_common(50)
    )

    return result


# =========================================================
# TASK 2: S11 domain/reference mining
# =========================================================

def point_segment_distance(p, a, b):
    px, py = p
    ax, ay = a
    bx, by = b

    dx = bx-ax
    dy = by-ay

    den = dx*dx + dy*dy

    if den == 0:
        return math.hypot(
            px-ax,
            py-ay
        )

    t = (
        (px-ax)*dx
        + (py-ay)*dy
    ) / den

    t = max(0.0, min(1.0, t))

    qx = ax + t*dx
    qy = ay + t*dy

    return math.hypot(
        px-qx,
        py-qy
    )


def angle_variants(dx, dy):
    e = (
        math.degrees(
            math.atan2(dy, dx)
        )
        % 360
    )

    return {
        "E_CCW": e,
        "E_CW": (-e) % 360,
        "N_CW": (90-e) % 360,
        "N_CCW": (e-90) % 360,
    }


def adiff(a, b):
    d = abs(a-b) % 360
    return min(d, 360-d)


def transforms(v):
    return {
        "raw": v,
        "m15": v & 0x7FFF,
        "m14": v & 0x3FFF,
        "m13": v & 0x1FFF,
        "m12": v & 0x0FFF,
    }


def task_s11(dataset):
    st = Counter()

    angle = Counter()

    for page_i, bbox, raw in pages(
        FILES[dataset]
    ):
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

        s6_start = h[10]
        s11_start = h[20]

        diag = math.hypot(
            max(1, bbox[2]-bbox[0]),
            max(1, bbox[3]-bbox[1]),
        )

        domains = {
            "S1": len(s1),
            "S2": h[3],
            "S3": len(s3),
            "S4": h[7],
            "S5": h[9],
            "S6": h[11],
        }

        for eid in range(h[11]):
            r6 = struct.unpack_from(
                "<7H",
                raw,
                s6_start + 14*eid,
            )

            r11 = struct.unpack_from(
                "<4H",
                raw,
                s11_start + 8*eid,
            )

            a, b = r6[3], r6[4]

            if (
                a >= len(s1)
                or b >= len(s1)
            ):
                continue

            pa = s1[a]
            pb = s1[b]

            for slot, angslot in (
                (0, 1),
                (2, 3),
            ):
                rawref = r11[slot]
                av = r11[angslot]

                for tn, ref in transforms(
                    rawref
                ).items():

                    prefix = (
                        f"w{slot}.{tn}"
                    )

                    st[
                        prefix + ".total"
                    ] += 1

                    for dn, limit in domains.items():
                        if ref < limit:
                            st[
                                prefix
                                + ".lt."
                                + dn
                            ] += 1

                    # -------------------------
                    # S1 hypothesis
                    # -------------------------

                    if ref < len(s1):
                        p = s1[ref]

                        st[
                            prefix+".S1.valid"
                        ] += 1

                        if ref == a:
                            st[
                                prefix+".S1.eqA"
                            ] += 1

                        if ref == b:
                            st[
                                prefix+".S1.eqB"
                            ] += 1

                        da = math.hypot(
                            p[0]-pa[0],
                            p[1]-pa[1],
                        ) / diag

                        db = math.hypot(
                            p[0]-pb[0],
                            p[1]-pb[1],
                        ) / diag

                        if min(da, db) <= .01:
                            st[
                                prefix
                                + ".S1.near_endpoint01"
                            ] += 1

                        # Angle from endpoints to ref point.
                        if av != 0:
                            for epn, ep in (
                                ("A", pa),
                                ("B", pb),
                            ):
                                dx = p[0]-ep[0]
                                dy = p[1]-ep[1]

                                if dx == 0 and dy == 0:
                                    continue

                                for cn, target in angle_variants(
                                    dx, dy
                                ).items():
                                    key = (
                                        f"w{slot}/w{angslot}"
                                        f".S1.{tn}.{epn}.{cn}"
                                    )

                                    angle[key+".n"] += 1

                                    if adiff(
                                        av,
                                        target
                                    ) <= 2:
                                        angle[key+".ok2"] += 1

                    # -------------------------
                    # S3 hypothesis
                    # -------------------------

                    if ref < len(s3):
                        p = s3[ref]

                        st[
                            prefix+".S3.valid"
                        ] += 1

                        dseg = point_segment_distance(
                            p,
                            pa,
                            pb,
                        ) / diag

                        if dseg <= .01:
                            st[
                                prefix
                                + ".S3.near_edge01"
                            ] += 1

                        if dseg <= .05:
                            st[
                                prefix
                                + ".S3.near_edge05"
                            ] += 1

                        if av != 0:
                            for epn, ep in (
                                ("A", pa),
                                ("B", pb),
                            ):
                                dx = p[0]-ep[0]
                                dy = p[1]-ep[1]

                                if dx == 0 and dy == 0:
                                    continue

                                for cn, target in angle_variants(
                                    dx, dy
                                ).items():

                                    key = (
                                        f"w{slot}/w{angslot}"
                                        f".S3.{tn}.{epn}.{cn}"
                                    )

                                    angle[key+".n"] += 1

                                    if adiff(
                                        av,
                                        target
                                    ) <= 2:
                                        angle[key+".ok2"] += 1

    best = []

    for k, n in angle.items():
        if not k.endswith(".n"):
            continue

        base = k[:-2]
        ok = angle[
            base+".ok2"
        ]

        if n >= 100:
            best.append(
                (
                    ok/n,
                    n,
                    ok,
                    base,
                )
            )

    best.sort(reverse=True)

    return {
        "kind": "s11deep",
        "dataset": dataset,
        "stats": dict(st),
        "angle_best": [
            {
                "rate": x[0],
                "n": x[1],
                "ok2": x[2],
                "test": x[3],
            }
            for x in best[:100]
        ],
    }


# =========================================================
# TASK 3: S6[5] class-conditioned metric
# =========================================================

class Reg:
    def __init__(self):
        self.n = 0
        self.sx = self.sy = 0.0
        self.sxx = self.syy = 0.0
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

    def result(self):
        n = self.n

        if n < 2:
            return None

        vx = (
            n*self.sxx
            - self.sx*self.sx
        )

        vy = (
            n*self.syy
            - self.sy*self.sy
        )

        cov = (
            n*self.sxy
            - self.sx*self.sy
        )

        r = None

        if vx > 0 and vy > 0:
            r = cov / math.sqrt(
                vx*vy
            )

        slope = None
        intercept = None

        den = (
            self.sxx
            - self.sx*self.sx/n
        )

        if den != 0:
            slope = (
                self.sxy
                - self.sx*self.sy/n
            ) / den

            intercept = (
                self.sy
                - slope*self.sx
            ) / n

        return {
            "n": n,
            "r": r,
            "slope": slope,
            "intercept": intercept,
        }


def task_metric(dataset):
    conn = open_db()

    global_reg = Reg()

    groups = defaultdict(Reg)

    ratios = defaultdict(
        lambda: [0, 0.0, 0.0]
    )

    sql = """
    SELECT
        ax,ay,bx,by,
        s60,s61,s62,s65
    FROM edges
    WHERE dataset=?
    """

    for (
        ax, ay, bx, by,
        s60, s61, s62, f5
    ) in conn.execute(
        sql,
        (dataset,)
    ):
        d = math.hypot(
            bx-ax,
            by-ay,
        )

        if d <= 0:
            continue

        global_reg.add(d, f5)

        keys = [
            (
                "s60low",
                s60 & 0xFF,
            ),
            (
                "s60low_s61hi",
                s60 & 0xFF,
                (s61 >> 8) & 0xFF,
            ),
            (
                "fullclass",
                s60 & 0xFF,
                (s61 >> 8) & 0xFF,
                s62 & 0xFF,
                (s62 >> 8) & 0xFF,
            ),
        ]

        for key in keys:
            groups[key].add(
                d, f5
            )

            r = f5/d
            z = ratios[key]

            z[0] += 1
            z[1] += r
            z[2] += r*r

    conn.close()

    good = []

    for key, reg in groups.items():
        q = reg.result()

        if not q or q["n"] < 500:
            continue

        n, sr, sr2 = ratios[key]

        mean = sr/n

        var = max(
            0.0,
            sr2/n - mean*mean
        )

        cv = (
            math.sqrt(var)/mean
            if mean else None
        )

        good.append({
            "key": list(key),
            **q,
            "ratio_mean": mean,
            "ratio_cv": cv,
        })

    good.sort(
        key=lambda x: (
            -(x["r"] or -1),
            -x["n"],
        )
    )

    biggest = sorted(
        good,
        key=lambda x: x["n"],
        reverse=True,
    )[:100]

    return {
        "kind": "metricclass",
        "dataset": dataset,
        "global": global_reg.result(),
        "best_r": good[:100],
        "largest_groups": biggest,
    }


# =========================================================
# TASK 4: cross-disc LOD rule generalization
# =========================================================

def labelled_rows(src, dst):
    conn = open_db()

    sql = """
    SELECT
        a.s60,a.s61,a.s62,a.s65,
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

    rows = list(
        conn.execute(
            sql,
            (dst, src)
        )
    )

    conn.close()
    return rows


def keyfuncs():
    return {
        "s60_low3":
            lambda a,b,c,d:
            (a & 7,),

        "s60_low4":
            lambda a,b,c,d:
            (a & 15,),

        "s60_low5":
            lambda a,b,c,d:
            (a & 31,),

        "s60_low8":
            lambda a,b,c,d:
            (a & 255,),

        "s60_full":
            lambda a,b,c,d:
            (a,),

        "s60low_s61hi":
            lambda a,b,c,d:
            (
                a & 255,
                (b >> 8) & 255,
            ),

        "class4":
            lambda a,b,c,d:
            (
                a & 255,
                (b >> 8) & 255,
                c & 255,
                (c >> 8) & 255,
            ),

        "class4_lenbin":
            lambda a,b,c,d:
            (
                a & 255,
                (b >> 8) & 255,
                c & 255,
                (c >> 8) & 255,
                int(math.log2(max(1, d))),
            ),
    }


def train_lookup(rows, fn):
    z = defaultdict(
        lambda: [0, 0]
    )

    ones = 0

    for a,b,c,d,y in rows:
        k = fn(a,b,c,d)

        z[k][0] += 1
        z[k][1] += y
        ones += y

    base = (
        1 if ones*2 >= len(rows)
        else 0
    )

    model = {
        k: (
            1 if s*2 >= n
            else 0
        )
        for k, (n,s) in z.items()
    }

    return model, base


def test_lookup(rows, fn, model, base):
    tp=tn=fp=fnn=unk=0

    for a,b,c,d,y in rows:
        k = fn(a,b,c,d)

        if k not in model:
            pred = base
            unk += 1
        else:
            pred = model[k]

        if pred and y:
            tp += 1
        elif pred and not y:
            fp += 1
        elif not pred and not y:
            tn += 1
        else:
            fnn += 1

    n = tp+tn+fp+fnn

    acc = (
        (tp+tn)/n
        if n else 0
    )

    precision = (
        tp/(tp+fp)
        if tp+fp else 0
    )

    recall = (
        tp/(tp+fnn)
        if tp+fnn else 0
    )

    return {
        "n": n,
        "accuracy": acc,
        "precision": precision,
        "recall": recall,
        "unknown": unk,
        "unknown_rate": (
            unk/n if n else 0
        ),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fnn,
    }


def task_crossval(
    trsrc, trdst,
    tesrc, tedst,
):
    train = labelled_rows(
        trsrc, trdst
    )

    test = labelled_rows(
        tesrc, tedst
    )

    results = {}

    for name, fn in keyfuncs().items():
        model, base = train_lookup(
            train, fn
        )

        results[name] = test_lookup(
            test,
            fn,
            model,
            base,
        )

    return {
        "kind": "crossval",
        "train": [trsrc, trdst],
        "test": [tesrc, tedst],
        "train_n": len(train),
        "test_n": len(test),
        "models": results,
    }


# =========================================================
# TASK 5: tile/page structure
# =========================================================

def gcd_all(values):
    g = 0

    for x in values:
        x = abs(int(x))

        if x:
            g = math.gcd(g, x)

    return g


def task_pages(dataset):
    data, directory = load_directory(
        FILES[dataset]
    )

    widths = Counter()
    heights = Counter()

    bboxes = []
    hashes = {}

    xs = []
    ys = []

    for i, bbox, off, rawlen, packed in directory:
        x0,y0,x1,y1 = bbox

        widths[x1-x0] += 1
        heights[y1-y0] += 1

        xs += [x0, x1]
        ys += [y0, y1]

        raw = zlib.decompress(
            data[off:off+packed]
        )

        h = hashlib.blake2b(
            raw,
            digest_size=12,
        ).hexdigest()

        key = ",".join(
            str(x) for x in bbox
        )

        hashes[key] = h
        bboxes.append(bbox)

    xsu = sorted(set(xs))
    ysu = sorted(set(ys))

    xdiff = [
        b-a
        for a,b in zip(
            xsu, xsu[1:]
        )
        if b != a
    ]

    ydiff = [
        b-a
        for a,b in zip(
            ysu, ysu[1:]
        )
        if b != a
    ]

    return {
        "kind": "pages",
        "dataset": dataset,
        "n": len(directory),
        "width_top":
            widths.most_common(50),
        "height_top":
            heights.most_common(50),
        "width_gcd":
            gcd_all(widths.keys()),
        "height_gcd":
            gcd_all(heights.keys()),
        "x_boundary_step_gcd":
            gcd_all(xdiff),
        "y_boundary_step_gcd":
            gcd_all(ydiff),
        "hashes": hashes,
    }


# =========================================================
# Workers/checkpoint
# =========================================================

def worker(task):
    kind = task[0]

    if kind == "s2s4":
        label = (
            "s2s4_" + task[1]
        )

    elif kind == "s11":
        label = (
            "s11_" + task[1]
        )

    elif kind == "metric":
        label = (
            "metric_" + task[1]
        )

    elif kind == "pages":
        label = (
            "pages_" + task[1]
        )

    elif kind == "crossval":
        label = (
            "crossval_"
            + "_".join(task[1:])
        )

    else:
        raise ValueError(task)

    path = ppath(label)

    if path.exists():
        return label, 0.0, True

    t0 = time.time()

    if kind == "s2s4":
        result = task_s2s4(
            task[1]
        )

    elif kind == "s11":
        result = task_s11(
            task[1]
        )

    elif kind == "metric":
        result = task_metric(
            task[1]
        )

    elif kind == "pages":
        result = task_pages(
            task[1]
        )

    elif kind == "crossval":
        result = task_crossval(
            *task[1:]
        )

    result["elapsed"] = (
        time.time()-t0
    )

    save(path, result)

    return (
        label,
        result["elapsed"],
        False,
    )


# =========================================================
# Report
# =========================================================

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
            "NCDR MG GLOBAL MINER V4",
            file=out
        )

        print(
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            file=out
        )

        # -----------------------------------------
        print(
            "\n"+"="*100,
            file=out
        )

        print(
            "S2/S4 DEEP DECODE",
            file=out
        )

        for x in sorted(
            kinds["s2s4deep"],
            key=lambda z:z["dataset"]
        ):
            print(
                "\nDATASET:",
                x["dataset"],
                file=out
            )

            for sec in (
                "S2", "S4"
            ):
                s = x[sec]
                n = s.get(
                    "records", 0
                )

                print(
                    "\n",
                    sec,
                    "records=", n,
                    file=out
                )

                for k in (
                    "idx_valid",
                    "target_valid",
                    "same_chain",
                    "chain_pos_delta_exact",
                    "chain_adjacent",
                    "delta_abs1",
                    "delta_plus1",
                    "delta_minus1",
                    "pair_is_s6_edge",
                    "ordered_nondec",
                ):
                    v = s.get(k,0)

                    print(
                        f"{k}: "
                        f"{v}/{n} "
                        f"({pct(v,n):.6f}%)",
                        file=out
                    )

                print(
                    "delta:",
                    x[
                        sec+"_delta"
                    ][:30],
                    file=out
                )

        # -----------------------------------------
        print(
            "\n"+"="*100,
            file=out
        )

        print(
            "S11 DOMAIN / GEOMETRY",
            file=out
        )

        for x in sorted(
            kinds["s11deep"],
            key=lambda z:z["dataset"]
        ):
            print(
                "\nDATASET:",
                x["dataset"],
                file=out
            )

            s = x["stats"]

            for slot in (
                "w0", "w2"
            ):
                for tr in (
                    "raw",
                    "m15",
                    "m14",
                    "m13",
                    "m12",
                ):
                    p = (
                        slot+"."+tr
                    )

                    n = s.get(
                        p+".total",0
                    )

                    if not n:
                        continue

                    vals = []

                    for d in (
                        "S1","S2","S3",
                        "S4","S5","S6",
                    ):
                        v = s.get(
                            p+".lt."+d,
                            0
                        )

                        vals.append(
                            f"{d}="
                            f"{pct(v,n):.2f}%"
                        )

                    print(
                        p,
                        " ".join(vals),
                        "eqA=",
                        s.get(
                            p+".S1.eqA",0
                        ),
                        "eqB=",
                        s.get(
                            p+".S1.eqB",0
                        ),
                        "S3edge01=",
                        s.get(
                            p+".S3.near_edge01",
                            0
                        ),
                        file=out
                    )

            print(
                "\nBEST ANGLE MODELS:",
                file=out
            )

            for a in x[
                "angle_best"
            ][:30]:
                print(
                    f"{100*a['rate']:.5f}% "
                    f"{a['ok2']}/{a['n']} "
                    f"{a['test']}",
                    file=out
                )

        # -----------------------------------------
        print(
            "\n"+"="*100,
            file=out
        )

        print(
            "S6[5] CLASS-CONDITIONED METRIC",
            file=out
        )

        for x in sorted(
            kinds["metricclass"],
            key=lambda z:z["dataset"]
        ):
            print(
                "\nDATASET:",
                x["dataset"],
                file=out
            )

            print(
                "GLOBAL:",
                x["global"],
                file=out
            )

            print(
                "BEST CLASS REGRESSIONS:",
                file=out
            )

            for q in x[
                "best_r"
            ][:40]:
                print(
                    q,
                    file=out
                )

        # -----------------------------------------
        print(
            "\n"+"="*100,
            file=out
        )

        print(
            "LOD CROSS-DISC GENERALIZATION",
            file=out
        )

        for x in kinds["crossval"]:
            print(
                "\nTRAIN",
                x["train"],
                "TEST",
                x["test"],
                file=out
            )

            rows = sorted(
                x["models"].items(),
                key=lambda kv:
                    kv[1]["accuracy"],
                reverse=True
            )

            for name, r in rows:
                print(
                    f"{name:22s} "
                    f"acc={100*r['accuracy']:.5f}% "
                    f"precision={100*r['precision']:.5f}% "
                    f"recall={100*r['recall']:.5f}% "
                    f"unknown={100*r['unknown_rate']:.5f}% "
                    f"fp={r['fp']} fn={r['fn']}",
                    file=out
                )

        # -----------------------------------------
        print(
            "\n"+"="*100,
            file=out
        )

        print(
            "PAGE/TILE STRUCTURE",
            file=out
        )

        pages_by_ds = {
            x["dataset"]:x
            for x in kinds["pages"]
        }

        for ds, x in sorted(
            pages_by_ds.items()
        ):
            print(
                "\n",
                ds,
                "pages=",x["n"],
                file=out
            )

            print(
                "width gcd:",
                x["width_gcd"],
                "height gcd:",
                x["height_gcd"],
                file=out
            )

            print(
                "boundary gcd:",
                x["x_boundary_step_gcd"],
                x["y_boundary_step_gcd"],
                file=out
            )

            print(
                "width top:",
                x["width_top"][:20],
                file=out
            )

            print(
                "height top:",
                x["height_top"][:20],
                file=out
            )

        for level in (
            "MG1","MG2","MG3"
        ):
            a = pages_by_ds[
                "7185_"+level
            ]

            b = pages_by_ds[
                "7186_"+level
            ]

            common = (
                set(a["hashes"])
                & set(b["hashes"])
            )

            exact = sum(
                a["hashes"][k]
                == b["hashes"][k]
                for k in common
            )

            print(
                f"\n7185_{level} <-> "
                f"7186_{level}: "
                f"same_bbox={len(common)} "
                f"exact_raw={exact}",
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

    tasks = []

    for ds in FILES:
        tasks += [
            ("s2s4", ds),
            ("s11", ds),
            ("metric", ds),
            ("pages", ds),
        ]

    for x in CROSSVAL:
        tasks.append(
            ("crossval",) + x
        )

    cpu = os.cpu_count() or 4

    # Keep only one logical CPU free.
    workers = max(
        2,
        cpu-1
    )

    log(
        "CPU:", cpu,
        "workers:", workers,
        "tasks:", len(tasks)
    )

    t0 = time.time()

    with ProcessPoolExecutor(
        max_workers=workers
    ) as ex:

        fs = {
            ex.submit(
                worker, t
            ):t
            for t in tasks
        }

        done = 0

        for f in as_completed(fs):
            done += 1

            label, sec, cached = (
                f.result()
            )

            log(
                f"[{done}/{len(tasks)}]",
                label,
                "CACHED"
                if cached
                else f"{sec:.1f}s"
            )

    parts = []

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

    save(
        FULL,
        {"results":parts}
    )

    render(parts)

    log(
        "ALL DONE",
        f"{(time.time()-t0)/60:.2f} min"
    )

    log(
        "REPORT:",
        REPORT
    )


if __name__ == "__main__":
    main()
