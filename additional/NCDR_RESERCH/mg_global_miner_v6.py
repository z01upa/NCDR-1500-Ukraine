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
PARTS = OUT / "mg_global_v6_parts"
PARTS.mkdir(parents=True, exist_ok=True)

REPORT = OUT / "mg_global_v6_report.txt"
FULL = OUT / "mg_global_v6_all.json"

FILES = {
    "7185_MG1": Path("/Volumes/CD_7185/DB/IZ.MG1"),
    "7185_MG2": Path("/Volumes/CD_7185/DB/IZ.MG2"),
    "7185_MG3": Path("/Volumes/CD_7185/DB/IZ.MG3"),
    "7186_MG1": Path("/Volumes/CD_7186/DB/SCZ.MG1"),
    "7186_MG2": Path("/Volumes/CD_7186/DB/SCZ.MG2"),
    "7186_MG3": Path("/Volumes/CD_7186/DB/SCZ.MG3"),
}

BBOX_DIFF = [
    ("7185_MG2", "7186_MG2"),
    ("7185_MG3", "7186_MG3"),
]

HDR = 0x72


def log(*x):
    print(
        time.strftime("%Y-%m-%d %H:%M:%S"),
        *x,
        flush=True,
    )


def save_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(
            obj,
            f,
            indent=2,
            sort_keys=True,
        )

    tmp.replace(path)


def part_path(label):
    return PARTS / (label + ".json")


def open_db():
    return sqlite3.connect(
        f"file:{SQLITE}?mode=ro",
        uri=True,
        timeout=120,
    )


# ============================================================
# Basic MG reader
# ============================================================

def load_mg(path):
    data = path.read_bytes()

    n = struct.unpack_from(
        "<I", data, 0x56
    )[0]

    bbox_off = HDR
    meta_off = HDR + n*16

    directory = []

    for i in range(n):
        bbox = struct.unpack_from(
            "<4i",
            data,
            bbox_off + i*16
        )

        off, rawlen, packed = struct.unpack_from(
            "<IHH",
            data,
            meta_off + i*8
        )

        directory.append(
            (i, bbox, off, rawlen, packed)
        )

    return data, directory


def get_raw(data, rec):
    i, bbox, off, rawlen, packed = rec

    raw = zlib.decompress(
        data[off:off+packed]
    )

    if len(raw) != rawlen:
        raise RuntimeError(
            f"page {i}: "
            f"{len(raw)} != {rawlen}"
        )

    return raw


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
            f"bad chain consume "
            f"{pos} != {end}"
        )

    return pts, chains


def s8(v):
    return v - 256 if v >= 128 else v


def sdiff16(a, b):
    return (
        (b - a + 32768)
        & 0xFFFF
    ) - 32768


# ============================================================
# Correlation helper
# ============================================================

class Corr:
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
            return {
                "n": n,
                "r": None,
                "slope": None,
            }

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

        den = (
            self.sxx
            - self.sx*self.sx/n
        )

        slope = None

        if den != 0:
            slope = (
                self.sxy
                - self.sx*self.sy/n
            ) / den

        return {
            "n": n,
            "r": r,
            "slope": slope,
        }


# ============================================================
# Tiny 3x3 solver for affine S11 test
# ============================================================

def solve3(A, b):
    M = [
        [
            float(A[i][0]),
            float(A[i][1]),
            float(A[i][2]),
            float(b[i]),
        ]
        for i in range(3)
    ]

    for col in range(3):
        pivot = max(
            range(col,3),
            key=lambda r:abs(M[r][col])
        )

        if abs(M[pivot][col]) < 1e-12:
            return None

        M[col], M[pivot] = (
            M[pivot], M[col]
        )

        z = M[col][col]

        for j in range(col,4):
            M[col][j] /= z

        for r in range(3):
            if r == col:
                continue

            z = M[r][col]

            for j in range(col,4):
                M[r][j] -= (
                    z * M[col][j]
                )

    return [
        M[i][3]
        for i in range(3)
    ]


def fit_affine(samples, diag):
    if len(samples) < 20:
        return None

    suu = suv = su = 0.0
    svv = sv = 0.0
    n = 0.0

    sux = svx = sx = 0.0
    suy = svy = sy = 0.0

    for u,v,x,y in samples:
        u=float(u)
        v=float(v)
        x=float(x)
        y=float(y)

        n += 1

        suu += u*u
        suv += u*v
        su += u

        svv += v*v
        sv += v

        sux += u*x
        svx += v*x
        sx += x

        suy += u*y
        svy += v*y
        sy += y

    A = [
        [suu,suv,su],
        [suv,svv,sv],
        [su, sv, n],
    ]

    bx = [sux,svx,sx]
    by = [suy,svy,sy]

    cx = solve3(A,bx)
    cy = solve3(A,by)

    if cx is None or cy is None:
        return None

    err2 = 0.0

    for u,v,x,y in samples:
        px = (
            cx[0]*u
            + cx[1]*v
            + cx[2]
        )

        py = (
            cy[0]*u
            + cy[1]*v
            + cy[2]
        )

        err2 += (
            (px-x)**2
            + (py-y)**2
        )

    rmse = math.sqrt(
        err2 / len(samples)
    )

    return {
        "n": len(samples),
        "rmse": rmse,
        "norm_rmse": (
            rmse / max(1.0,diag)
        ),
        "xcoef": cx,
        "ycoef": cy,
    }


# ============================================================
# TASK A: S11 as two 16-bit geometry pairs
# ============================================================

def task_s11vec(dataset):
    data, directory = load_mg(
        FILES[dataset]
    )

    corr = {
        "du_dx": Corr(),
        "du_dy": Corr(),
        "dv_dx": Corr(),
        "dv_dy": Corr(),

        "du_absdx": Corr(),
        "dv_absdy": Corr(),

        "s65_du": Corr(),
        "s65_dv": Corr(),
    }

    scale_tests = {
        str(k): Corr()
        for k in (
            0.03125,
            0.0625,
            0.125,
            0.25,
            0.5,
            1.0,
            2.0,
            4.0,
            8.0,
            16.0,
            32.0,
            64.0,
            128.0,
            256.0,
        )
    }

    delta_pairs = Counter()
    equal_delta = Counter()

    aff01 = []
    aff10 = []

    st = Counter()

    for rec in directory:
        page_i,bbox,*_ = rec

        raw = get_raw(
            data, rec
        )

        h = struct.unpack_from(
            "<23H", raw, 0
        )

        s1, chains = decode_chains(
            raw,
            h[0],
            h[2],
        )

        diag = math.hypot(
            max(1,bbox[2]-bbox[0]),
            max(1,bbox[3]-bbox[1]),
        )

        samples01 = []
        samples10 = []

        for eid in range(h[11]):
            r6 = struct.unpack_from(
                "<7H",
                raw,
                h[10] + eid*14
            )

            r11 = struct.unpack_from(
                "<4H",
                raw,
                h[20] + eid*8
            )

            a,b = r6[3],r6[4]

            if (
                a >= len(s1)
                or b >= len(s1)
            ):
                continue

            pa=s1[a]
            pb=s1[b]

            w0,w1,w2,w3=r11

            du=sdiff16(w0,w2)
            dv=sdiff16(w1,w3)

            dx=pb[0]-pa[0]
            dy=pb[1]-pa[1]

            st["edges"] += 1

            delta_pairs[(du,dv)] += 1

            if du == dv:
                st["du_eq_dv"] += 1
                equal_delta[du] += 1

            if du == -dv:
                st["du_eq_minus_dv"] += 1

            if du == 0:
                st["du_zero"] += 1

            if dv == 0:
                st["dv_zero"] += 1

            corr["du_dx"].add(du,dx)
            corr["du_dy"].add(du,dy)
            corr["dv_dx"].add(dv,dx)
            corr["dv_dy"].add(dv,dy)

            corr["du_absdx"].add(
                abs(du),abs(dx)
            )

            corr["dv_absdy"].add(
                abs(dv),abs(dy)
            )

            corr["s65_du"].add(
                abs(du),r6[5]
            )

            corr["s65_dv"].add(
                abs(dv),r6[5]
            )

            for k,c in scale_tests.items():
                kk=float(k)

                d=math.hypot(
                    du,
                    kk*dv,
                )

                c.add(d,r6[5])

            samples01.append(
                (
                    w0,w1,
                    pa[0],pa[1]
                )
            )

            samples01.append(
                (
                    w2,w3,
                    pb[0],pb[1]
                )
            )

            samples10.append(
                (
                    w0,w1,
                    pb[0],pb[1]
                )
            )

            samples10.append(
                (
                    w2,w3,
                    pa[0],pa[1]
                )
            )

        f01=fit_affine(
            samples01,
            diag
        )

        f10=fit_affine(
            samples10,
            diag
        )

        if f01:
            aff01.append(
                f01["norm_rmse"]
            )

        if f10:
            aff10.append(
                f10["norm_rmse"]
            )

    def hist(values):
        c=Counter()

        for x in values:
            if x <= 0:
                b=-99
            else:
                b=round(
                    math.log10(x),
                    1
                )

            c[b] += 1

        return sorted(
            c.items()
        )

    return {
        "kind":"s11vec",
        "dataset":dataset,
        "stats":dict(st),

        "corr":{
            k:v.result()
            for k,v in corr.items()
        },

        "scale_tests":{
            k:v.result()
            for k,v in scale_tests.items()
        },

        "delta_pairs_top":[
            [a,b,n]
            for (a,b),n
            in delta_pairs.most_common(100)
        ],

        "equal_delta_top":
            equal_delta.most_common(60),

        "affine01_hist":
            hist(aff01),

        "affine10_hist":
            hist(aff10),

        "affine01_best":
            sorted(aff01)[:50],

        "affine10_best":
            sorted(aff10)[:50],
    }


# ============================================================
# TASK B: S6[5] versus chord, compression-chain path,
#         and S2-chain path
# ============================================================

def task_metricpaths(dataset):
    data,directory=load_mg(
        FILES[dataset]
    )

    corr = {
        "all_chord":Corr(),

        "same_compression_chord":Corr(),
        "same_compression_path":Corr(),

        "same_s2_chord":Corr(),
        "same_s2_path":Corr(),
    }

    st=Counter()

    for rec in directory:
        raw=get_raw(
            data,rec
        )

        h=struct.unpack_from(
            "<23H",raw,0
        )

        s1,chains=decode_chains(
            raw,
            h[0],
            h[2],
        )

        cid=[-1]*len(s1)
        cpos=[-1]*len(s1)

        prefix=[]

        for ci,chain in enumerate(chains):
            p=[0.0]

            for j,idx in enumerate(chain):
                cid[idx]=ci
                cpos[idx]=j

                if j:
                    a=s1[chain[j-1]]
                    b=s1[idx]

                    p.append(
                        p[-1]
                        + math.hypot(
                            b[0]-a[0],
                            b[1]-a[1],
                        )
                    )

            prefix.append(p)

        # ---------------------------------------------
        # S2 undirected graph
        # ---------------------------------------------

        adj=defaultdict(set)

        for k in range(h[3]):
            r=raw[
                h[2]+3*k:
                h[2]+3*k+3
            ]

            idx=struct.unpack_from(
                "<H",r,0
            )[0]

            d=s8(r[2])

            target=idx+d

            if (
                idx < len(s1)
                and 0 <= target < len(s1)
                and idx != target
            ):
                adj[idx].add(target)
                adj[target].add(idx)

        compid={}
        pathcoord={}

        seen=set()
        cc=0

        for start in list(adj):
            if start in seen:
                continue

            stack=[start]
            vs=[]
            seen.add(start)

            while stack:
                u=stack.pop()
                vs.append(u)

                for v in adj[u]:
                    if v not in seen:
                        seen.add(v)
                        stack.append(v)

            if max(
                (
                    len(adj[v])
                    for v in vs
                ),
                default=0
            ) > 2:
                continue

            endpoints=[
                v for v in vs
                if len(adj[v]) <= 1
            ]

            if not endpoints:
                continue

            cur=endpoints[0]
            prev=None
            dist=0.0

            while True:
                compid[cur]=cc
                pathcoord[cur]=dist

                nxt=[
                    v for v in adj[cur]
                    if v != prev
                ]

                if not nxt:
                    break

                v=nxt[0]

                a=s1[cur]
                b=s1[v]

                dist += math.hypot(
                    b[0]-a[0],
                    b[1]-a[1],
                )

                prev,cur=cur,v

            cc += 1

        # ---------------------------------------------
        # Test all S6 records
        # ---------------------------------------------

        for eid in range(h[11]):
            r6=struct.unpack_from(
                "<7H",
                raw,
                h[10]+eid*14
            )

            a,b=r6[3],r6[4]

            if (
                a >= len(s1)
                or b >= len(s1)
                or a == b
            ):
                continue

            pa=s1[a]
            pb=s1[b]

            chord=math.hypot(
                pb[0]-pa[0],
                pb[1]-pa[1],
            )

            f5=r6[5]

            st["edges"] += 1

            corr[
                "all_chord"
            ].add(chord,f5)

            if cid[a] == cid[b]:
                st[
                    "same_compression_chain"
                ] += 1

                ci=cid[a]

                path=abs(
                    prefix[ci][cpos[b]]
                    - prefix[ci][cpos[a]]
                )

                corr[
                    "same_compression_chord"
                ].add(chord,f5)

                corr[
                    "same_compression_path"
                ].add(path,f5)

            if (
                a in compid
                and b in compid
                and compid[a] == compid[b]
            ):
                st["same_s2_component"] += 1

                path=abs(
                    pathcoord[b]
                    - pathcoord[a]
                )

                corr[
                    "same_s2_chord"
                ].add(chord,f5)

                corr[
                    "same_s2_path"
                ].add(path,f5)

    return {
        "kind":"metricpaths",
        "dataset":dataset,
        "stats":dict(st),

        "corr":{
            k:v.result()
            for k,v in corr.items()
        },
    }


# ============================================================
# TASK C: exact three-level LOD presence pattern
# ============================================================

def task_lod3(disc):
    mg1=disc+"_MG1"
    mg2=disc+"_MG2"
    mg3=disc+"_MG3"

    conn=open_db()

    groups=defaultdict(Counter)
    full=Counter()

    sql="""
    SELECT
      a.s60,
      a.s61,

      CASE WHEN b.dataset IS NULL
           THEN 0 ELSE 1 END,

      CASE WHEN c.dataset IS NULL
           THEN 0 ELSE 1 END

    FROM geom_unique a

    LEFT JOIN geom_unique b
      ON b.dataset=?
     AND b.ax=a.ax
     AND b.ay=a.ay
     AND b.bx=a.bx
     AND b.by=a.by

    LEFT JOIN geom_unique c
      ON c.dataset=?
     AND c.ax=a.ax
     AND c.ay=a.ay
     AND c.bx=a.bx
     AND c.by=a.by

    WHERE a.dataset=?
    """

    for s60,s61,in2,in3 in conn.execute(
        sql,
        (mg2,mg3,mg1)
    ):
        pattern=(
            "1"
            + str(int(in2))
            + str(int(in3))
        )

        low3=s60 & 7
        hi1=(s61 >> 8) & 255

        full[pattern] += 1

        groups[
            ("low3",low3)
        ][pattern] += 1

        groups[
            ("low3_s61hi",low3,hi1)
        ][pattern] += 1

    conn.close()

    rows=[]

    for key,c in groups.items():
        n=sum(c.values())

        if n < 100:
            continue

        rows.append({
            "key":list(key),
            "n":n,
            "patterns":dict(c),
        })

    rows.sort(
        key=lambda x:(
            x["key"][0],
            x["key"][1:],
        )
    )

    return {
        "kind":"lod3",
        "disc":disc,
        "overall":dict(full),
        "groups":rows,
    }


# ============================================================
# TASK D: same-bbox positional S6 / S11 differences
# ============================================================

def section(raw,h,a,b):
    return raw[h[a]:h[b]]


def task_bboxfields(a,b):
    da,A=load_mg(FILES[a])
    db,B=load_mg(FILES[b])

    AA={
        tuple(r[1]):r
        for r in A
    }

    BB={
        tuple(r[1]):r
        for r in B
    }

    st=Counter()

    s6_trans=[
        Counter()
        for _ in range(7)
    ]

    s11_trans=[
        Counter()
        for _ in range(4)
    ]

    for bbox in (
        set(AA)
        & set(BB)
    ):
        ra=get_raw(
            da,AA[bbox]
        )

        rb=get_raw(
            db,BB[bbox]
        )

        ha=struct.unpack_from(
            "<23H",ra,0
        )

        hb=struct.unpack_from(
            "<23H",rb,0
        )

        if ha[11] != hb[11]:
            st["different_h11"] += 1
            continue

        if section(
            ra,ha,0,2
        ) != section(
            rb,hb,0,2
        ):
            continue

        st["same_S1_pages"] += 1

        n=ha[11]

        for eid in range(n):
            A6=struct.unpack_from(
                "<7H",
                ra,
                ha[10]+14*eid
            )

            B6=struct.unpack_from(
                "<7H",
                rb,
                hb[10]+14*eid
            )

            A11=struct.unpack_from(
                "<4H",
                ra,
                ha[20]+8*eid
            )

            B11=struct.unpack_from(
                "<4H",
                rb,
                hb[20]+8*eid
            )

            st["records"] += 1

            for j in range(7):
                if A6[j] == B6[j]:
                    st[
                        f"s6_{j}_equal"
                    ] += 1
                else:
                    s6_trans[j][
                        (
                            A6[j],
                            B6[j],
                        )
                    ] += 1

            for j in range(4):
                if A11[j] == B11[j]:
                    st[
                        f"s11_{j}_equal"
                    ] += 1
                else:
                    s11_trans[j][
                        (
                            A11[j],
                            B11[j],
                        )
                    ] += 1

    return {
        "kind":"bboxfields",
        "a":a,
        "b":b,
        "stats":dict(st),

        "s6_trans":[
            [
                [x,y,n]
                for (x,y),n
                in c.most_common(50)
            ]
            for c in s6_trans
        ],

        "s11_trans":[
            [
                [x,y,n]
                for (x,y),n
                in c.most_common(30)
            ]
            for c in s11_trans
        ],
    }


# ============================================================
# Worker
# ============================================================

def worker(task):
    kind=task[0]
    label="_".join(task)

    p=part_path(label)

    if p.exists():
        return label,True,0.0

    t0=time.time()

    if kind=="s11vec":
        r=task_s11vec(
            task[1]
        )

    elif kind=="metricpaths":
        r=task_metricpaths(
            task[1]
        )

    elif kind=="lod3":
        r=task_lod3(
            task[1]
        )

    elif kind=="bboxfields":
        r=task_bboxfields(
            task[1],
            task[2],
        )

    else:
        raise ValueError(task)

    r["elapsed"]=time.time()-t0

    save_json(p,r)

    return (
        label,
        False,
        r["elapsed"]
    )


# ============================================================
# Report
# ============================================================

def pct(a,b):
    return (
        100*a/b
        if b else 0.0
    )


def render(parts):
    K=defaultdict(list)

    for x in parts:
        K[x["kind"]].append(x)

    with REPORT.open(
        "w",
        encoding="utf-8"
    ) as out:

        print(
            "NCDR MG GLOBAL MINER V6",
            file=out
        )

        print(
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            file=out
        )

        # ------------------------------------------------
        print(
            "\n"+"="*100,
            file=out
        )
        print(
            "S11 AS TWO 16-BIT PAIRS",
            file=out
        )

        for x in sorted(
            K["s11vec"],
            key=lambda q:q["dataset"]
        ):
            print(
                "\nDATASET",
                x["dataset"],
                file=out
            )

            print(
                "STATS",
                x["stats"],
                file=out
            )

            print(
                "\nVECTOR CORRELATIONS",
                file=out
            )

            for k,v in x[
                "corr"
            ].items():
                print(
                    k,v,
                    file=out
                )

            print(
                "\nS6[5] vs "
                "S11 vector distance",
                file=out
            )

            rows=sorted(
                x[
                    "scale_tests"
                ].items(),
                key=lambda kv:
                    abs(
                        kv[1]["r"]
                        or 0
                    ),
                reverse=True
            )

            for k,v in rows:
                print(
                    "scale_v",
                    k,
                    v,
                    file=out
                )

            print(
                "DELTA PAIRS TOP",
                x[
                    "delta_pairs_top"
                ][:40],
                file=out
            )

            print(
                "DU==DV TOP",
                x[
                    "equal_delta_top"
                ][:30],
                file=out
            )

            print(
                "AFFINE 01 HIST",
                x[
                    "affine01_hist"
                ],
                file=out
            )

            print(
                "AFFINE 10 HIST",
                x[
                    "affine10_hist"
                ],
                file=out
            )

            print(
                "AFFINE 01 BEST",
                x[
                    "affine01_best"
                ][:20],
                file=out
            )

            print(
                "AFFINE 10 BEST",
                x[
                    "affine10_best"
                ][:20],
                file=out
            )

        # ------------------------------------------------
        print(
            "\n"+"="*100,
            file=out
        )
        print(
            "S6[5] PATH-LENGTH TEST",
            file=out
        )

        for x in sorted(
            K["metricpaths"],
            key=lambda q:q["dataset"]
        ):
            print(
                "\nDATASET",
                x["dataset"],
                file=out
            )

            print(
                "STATS",
                x["stats"],
                file=out
            )

            for k,v in x[
                "corr"
            ].items():
                print(
                    k,v,
                    file=out
                )

        # ------------------------------------------------
        print(
            "\n"+"="*100,
            file=out
        )
        print(
            "THREE-LEVEL LOD PRESENCE",
            file=out
        )

        for x in sorted(
            K["lod3"],
            key=lambda q:q["disc"]
        ):
            print(
                "\nDISC",
                x["disc"],
                file=out
            )

            print(
                "OVERALL",
                x["overall"],
                file=out
            )

            for row in x[
                "groups"
            ]:
                print(
                    row,
                    file=out
                )

        # ------------------------------------------------
        print(
            "\n"+"="*100,
            file=out
        )
        print(
            "SAME-BBOX POSITIONAL FIELD DIFF",
            file=out
        )

        for x in K[
            "bboxfields"
        ]:
            print(
                "\n",
                x["a"],
                "<->",
                x["b"],
                file=out
            )

            s=x["stats"]
            n=s.get(
                "records",0
            )

            print(
                "same_S1_pages",
                s.get(
                    "same_S1_pages",0
                ),
                file=out
            )

            print(
                "records",
                n,
                file=out
            )

            for j in range(7):
                v=s.get(
                    f"s6_{j}_equal",
                    0
                )

                print(
                    f"S6[{j}] equal:",
                    v,"/",n,
                    f"({pct(v,n):.6f}%)",
                    file=out
                )

                print(
                    " top transitions:",
                    x[
                        "s6_trans"
                    ][j][:15],
                    file=out
                )

            for j in range(4):
                v=s.get(
                    f"s11_{j}_equal",
                    0
                )

                print(
                    f"S11[{j}] equal:",
                    v,"/",n,
                    f"({pct(v,n):.6f}%)",
                    file=out
                )

                print(
                    " top transitions:",
                    x[
                        "s11_trans"
                    ][j][:15],
                    file=out
                )


# ============================================================
# Main
# ============================================================

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
            ("s11vec",ds)
        )

        tasks.append(
            ("metricpaths",ds)
        )

    tasks.append(
        ("lod3","7185")
    )

    tasks.append(
        ("lod3","7186")
    )

    for a,b in BBOX_DIFF:
        tasks.append(
            (
                "bboxfields",
                a,b
            )
        )

    cpu=os.cpu_count() or 4
    workers=max(
        2,
        cpu-1
    )

    log(
        "CPU",cpu,
        "workers",workers,
        "tasks",len(tasks)
    )

    t0=time.time()

    with ProcessPoolExecutor(
        max_workers=workers
    ) as ex:

        fs={
            ex.submit(
                worker,t
            ):t
            for t in tasks
        }

        done=0

        for f in as_completed(fs):
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
        {
            "results":parts
        }
    )

    render(parts)

    log(
        "ALL DONE",
        f"{(time.time()-t0)/60:.2f} min"
    )

    log(
        "REPORT",
        REPORT
    )


if __name__=="__main__":
    main()
