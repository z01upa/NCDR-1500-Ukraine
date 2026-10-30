from pathlib import Path
from collections import defaultdict, Counter
from itertools import combinations
import sqlite3
import struct
import zlib
import math
import json
import re
import time

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"
OUT.mkdir(parents=True, exist_ok=True)

DB_PATH = OUT / "mg_overnight.sqlite"
REPORT = OUT / "mg_overnight_report.txt"

DATASETS = {
    "7185_MG1": Path("/Volumes/CD_7185/DB/IZ.MG1"),
    "7185_MG2": Path("/Volumes/CD_7185/DB/IZ.MG2"),
    "7185_MG3": Path("/Volumes/CD_7185/DB/IZ.MG3"),
    "7186_MG1": Path("/Volumes/CD_7186/DB/SCZ.MG1"),
    "7186_MG2": Path("/Volumes/CD_7186/DB/SCZ.MG2"),
    "7186_MG3": Path("/Volumes/CD_7186/DB/SCZ.MG3"),
}

DB_DIRS = [
    Path("/Volumes/CD_7185/DB"),
    Path("/Volumes/CD_7186/DB"),
]

HDR = 0x72

S5_RULES = {
    2: (0, 1),
    3: (0, 1, 2),
    4: (0, 1, 2, 3),
}


def log(*x):
    print(
        time.strftime("%Y-%m-%d %H:%M:%S"),
        *x,
        flush=True,
    )


def canon_points(p, q):
    if p <= q:
        return p[0], p[1], q[0], q[1]
    return q[0], q[1], p[0], p[1]


def decode_multichain(raw, start, end):
    pos = start
    pts = []
    chains = []

    try:
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

    except Exception:
        return [], [], False


def iter_mg_pages(path):
    with path.open("rb") as f:
        hdr = f.read(HDR)

        if len(hdr) != HDR:
            raise RuntimeError(f"short MG header: {path}")

        n = struct.unpack_from("<I", hdr, 0x56)[0]

        f.seek(HDR)
        bbox_raw = f.read(n * 16)
        meta_raw = f.read(n * 8)

        for i in range(n):
            bbox = struct.unpack_from(
                "<4i", bbox_raw, i * 16
            )

            stream_off, raw_size, packed_len = struct.unpack_from(
                "<IHH", meta_raw, i * 8
            )

            f.seek(stream_off)
            packed = f.read(packed_len)

            raw = zlib.decompress(packed)

            if len(raw) != raw_size:
                raise RuntimeError(
                    f"{path.name} page {i}: "
                    f"raw {len(raw)} != {raw_size}"
                )

            yield i, bbox, raw


def parse_clean_s5(raw, h):
    start = h[8]
    n = h[9]
    nref = h[11]

    records = []
    edges = defaultdict(list)

    for i in range(n):
        rec = raw[start+i*10:start+(i+1)*10]

        if len(rec) != 10:
            records.append(None)
            continue

        b0 = rec[0]
        b1 = rec[1]
        tag = b0 & 7

        vals = struct.unpack_from("<4H", rec, 2)

        fields = S5_RULES.get(tag)

        if fields is None:
            records.append(None)
            continue

        refs = tuple(vals[j] for j in fields)

        if not all(x < nref for x in refs):
            records.append(None)
            continue

        records.append((b0, b1, tag, vals, refs))

        for slot, ref in enumerate(refs):
            edges[ref].append((i, slot))

    return records, edges


def angle_conventions(dx, dy):
    theta = math.degrees(math.atan2(dy, dx)) % 360.0

    return {
        "E_CCW": theta,
        "E_CW": (-theta) % 360.0,
        "N_CW": (90.0 - theta) % 360.0,
        "N_CCW": (theta - 90.0) % 360.0,
    }


def circular_diff(a, b):
    d = abs(float(a) - float(b)) % 360.0
    return min(d, 360.0 - d)


def score_angle(stats, key, raw_value, target):
    if not (0 <= raw_value <= 359):
        return

    stats[key + ".n"] += 1

    d = circular_diff(raw_value, target)

    if d <= 0.5:
        stats[key + ".exact"] += 1

    if d <= 1:
        stats[key + ".d1"] += 1

    if d <= 2:
        stats[key + ".d2"] += 1

    if d <= 5:
        stats[key + ".d5"] += 1


def ref_transforms(v):
    out = {
        "raw": v,
        "mask15": v & 0x7FFF,
        "mask14": v & 0x3FFF,
        "mask12": v & 0x0FFF,
    }

    if v > 0:
        out["minus1"] = v - 1

    out["plus1"] = v + 1

    return out


def other_endpoint(s6, eid, node):
    if not (0 <= eid < len(s6)):
        return None

    a = s6[eid][3]
    b = s6[eid][4]

    if a == node:
        return b

    if b == node:
        return a

    return None


def analyse_page(dataset, page_i, bbox, raw):
    stats = Counter()
    edge_rows = []

    h = struct.unpack_from("<23H", raw, 0)

    s1, s1_chains, ok1 = decode_multichain(
        raw, h[0], h[2]
    )

    s3, s3_chains, ok3 = decode_multichain(
        raw, h[4], h[6]
    )

    stats["pages"] = 1
    stats["s1_parse_ok"] = int(ok1)
    stats["s3_parse_ok"] = int(ok3)

    if not ok1 or len(s1) != h[1]:
        stats["bad_s1"] = 1
        return stats, edge_rows

    if not ok3 or len(s3) != h[5]:
        stats["bad_s3"] = 1

    stats["s1_points"] = len(s1)
    stats["s3_points"] = len(s3)
    stats["s3_chains"] = len(s3_chains)

    s1set = set(s1)

    stats["s3_points_equal_s1"] = sum(
        p in s1set for p in s3
    )

    for chain in s3_chains:
        if chain:
            stats["s3_chain_start_equal_s1"] += (
                s3[chain[0]] in s1set
            )

            stats["s3_chain_end_equal_s1"] += (
                s3[chain[-1]] in s1set
            )

    s5, edge_users = parse_clean_s5(raw, h)

    nedge = h[11]
    s6_start = h[10]
    s11_start = h[20]

    if s6_start + nedge * 14 > len(raw):
        stats["bad_s6_bounds"] = 1
        return stats, edge_rows

    if s11_start + nedge * 8 > len(raw):
        stats["bad_s11_bounds"] = 1
        return stats, edge_rows

    s6 = [
        struct.unpack_from(
            "<7H",
            raw,
            s6_start + i*14
        )
        for i in range(nedge)
    ]

    s11 = [
        struct.unpack_from(
            "<4H",
            raw,
            s11_start + i*8
        )
        for i in range(nedge)
    ]

    clean_edges = {}

    for eid, users in edge_users.items():
        ids = sorted(set(x[0] for x in users))

        if len(ids) != 2:
            continue

        a, b = ids

        if a >= len(s1) or b >= len(s1):
            continue

        clean_edges[eid] = (a, b)

    stats["clean_edges2"] = len(clean_edges)

    # ------------------------------------------------
    # S3 segment <-> clean S6 edge geometry
    # ------------------------------------------------

    edge_geom = set()

    for eid, (a, b) in clean_edges.items():
        edge_geom.add(
            canon_points(s1[a], s1[b])
        )

    for chain in s3_chains:
        for x, y in zip(chain, chain[1:]):
            stats["s3_segments"] += 1

            if canon_points(
                s3[x], s3[y]
            ) in edge_geom:
                stats["s3_segments_equal_clean_edge"] += 1

    # ------------------------------------------------
    # Main edge analysis
    # ------------------------------------------------

    for eid, (a, b) in clean_edges.items():
        r6 = s6[eid]
        r11 = s11[eid]

        stats["edge_total"] += 1

        stats["s6_3_eq_a"] += (r6[3] == a)
        stats["s6_4_eq_b"] += (r6[4] == b)

        f5 = r6[5]

        for key, limit in (
            ("h1", h[1]),
            ("h3", h[3]),
            ("h5", h[5]),
            ("h7", h[7]),
            ("h11", h[11]),
            ("s3chains", len(s3_chains)),
        ):
            stats[f"s65_lt_{key}"] += (
                f5 < limit
            )

        if f5 < len(s3):
            p = s3[f5]

            stats["s65_s3_exact_endpoint"] += (
                p == s1[a] or p == s1[b]
            )

        stats[f"s66_value_{r6[6]}"] += 1

        # --------------------------------------------
        # S11[0], S11[2] as local edge references
        # --------------------------------------------

        for slot_name, value in (
            ("w0", r11[0]),
            ("w2", r11[2]),
        ):
            for tname, ref in ref_transforms(value).items():
                base = f"ref.{slot_name}.{tname}"

                stats[base + ".total"] += 1

                if not (0 <= ref < nedge):
                    continue

                stats[base + ".inrange"] += 1
                stats[base + ".self"] += (ref == eid)

                ra = s6[ref][3]
                rb = s6[ref][4]

                if (
                    ra >= len(s1)
                    or rb >= len(s1)
                ):
                    continue

                stats[base + ".valid_endpoints"] += 1

                share_a = (
                    ra == a or rb == a
                )

                share_b = (
                    ra == b or rb == b
                )

                stats[base + ".share_a"] += share_a
                stats[base + ".share_b"] += share_b
                stats[base + ".share_any"] += (
                    share_a or share_b
                )

        pa = s1[a]
        pb = s1[b]

        dx = pb[0] - pa[0]
        dy = pb[1] - pa[1]

        # --------------------------------------------
        # S11[1]/[3] as endpoint bearings
        # --------------------------------------------

        ab = angle_conventions(dx, dy)
        ba = angle_conventions(-dx, -dy)

        for conv, ang in ab.items():
            score_angle(
                stats,
                f"angle.own.w1.AB.{conv}",
                r11[1],
                ang,
            )

            score_angle(
                stats,
                f"angle.own.w3.AB.{conv}",
                r11[3],
                ang,
            )

        for conv, ang in ba.items():
            score_angle(
                stats,
                f"angle.own.w1.BA.{conv}",
                r11[1],
                ang,
            )

            score_angle(
                stats,
                f"angle.own.w3.BA.{conv}",
                r11[3],
                ang,
            )

        # --------------------------------------------
        # S11 raw ref + corresponding angle.
        # Test all endpoint assignments.
        # --------------------------------------------

        for slot_name, ref_value, angle_value in (
            ("w0w1", r11[0], r11[1]),
            ("w2w3", r11[2], r11[3]),
        ):
            if not (0 <= ref_value < nedge):
                continue

            for node_name, node in (
                ("A", a),
                ("B", b),
            ):
                other = other_endpoint(
                    s6,
                    ref_value,
                    node
                )

                if other is None:
                    continue

                if not (0 <= other < len(s1)):
                    continue

                stats[
                    f"neighbor.{slot_name}.{node_name}.n"
                ] += 1

                p0 = s1[node]
                p1 = s1[other]

                ndx = p1[0] - p0[0]
                ndy = p1[1] - p0[1]

                nang = angle_conventions(
                    ndx, ndy
                )

                for conv, ang in nang.items():
                    score_angle(
                        stats,
                        f"angle.neighbor."
                        f"{slot_name}.{node_name}.{conv}",
                        angle_value,
                        ang,
                    )

                # Turn angle, invariant to absolute rotation.
                cur_other = b if node == a else a

                cp = s1[cur_other]

                cdx = cp[0] - p0[0]
                cdy = cp[1] - p0[1]

                cur = (
                    math.degrees(
                        math.atan2(cdy, cdx)
                    ) % 360.0
                )

                refang = (
                    math.degrees(
                        math.atan2(ndy, ndx)
                    ) % 360.0
                )

                cw = (cur - refang) % 360.0
                ccw = (refang - cur) % 360.0
                small = min(cw, ccw)

                score_angle(
                    stats,
                    f"angle.turn.{slot_name}.{node_name}.CW",
                    angle_value,
                    cw,
                )

                score_angle(
                    stats,
                    f"angle.turn.{slot_name}.{node_name}.CCW",
                    angle_value,
                    ccw,
                )

                score_angle(
                    stats,
                    f"angle.turn.{slot_name}.{node_name}.SMALL",
                    angle_value,
                    small,
                )

        ax, ay, bx, by = canon_points(
            pa, pb
        )

        edge_rows.append((
            dataset,
            page_i,
            eid,

            ax, ay, bx, by,

            a, b,

            r6[0],
            r6[1],
            r6[2],
            r6[3],
            r6[4],
            r6[5],
            r6[6],

            r11[0],
            r11[1],
            r11[2],
            r11[3],
        ))

    return stats, edge_rows


def init_db():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-200000")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS edges (
            dataset TEXT NOT NULL,
            page INTEGER NOT NULL,
            eid INTEGER NOT NULL,

            ax INTEGER,
            ay INTEGER,
            bx INTEGER,
            by INTEGER,

            va INTEGER,
            vb INTEGER,

            s60 INTEGER,
            s61 INTEGER,
            s62 INTEGER,
            s63 INTEGER,
            s64 INTEGER,
            s65 INTEGER,
            s66 INTEGER,

            w0 INTEGER,
            w1 INTEGER,
            w2 INTEGER,
            w3 INTEGER,

            PRIMARY KEY(dataset, page, eid)
        ) WITHOUT ROWID
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS page_stats (
            dataset TEXT NOT NULL,
            page INTEGER NOT NULL,
            stats_json TEXT NOT NULL,

            PRIMARY KEY(dataset, page)
        ) WITHOUT ROWID
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS cross_summary (
            a TEXT,
            b TEXT,
            summary_json TEXT,
            PRIMARY KEY(a,b)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_summary (
            path TEXT PRIMARY KEY,
            summary_json TEXT
        )
    """)

    conn.commit()
    return conn


def process_datasets(conn):
    sql = """
        INSERT OR REPLACE INTO edges VALUES (
            ?,?,?,?,?,?,?,?,?,?,
            ?,?,?,?,?,?,?,?,?,?
        )
    """

    for dataset, path in DATASETS.items():
        if not path.exists():
            raise FileNotFoundError(path)

        done = {
            row[0]
            for row in conn.execute(
                "SELECT page FROM page_stats "
                "WHERE dataset=?",
                (dataset,)
            )
        }

        log(
            dataset,
            "already completed pages:",
            len(done)
        )

        pending = 0

        conn.execute("BEGIN")

        try:
            for page_i, bbox, raw in iter_mg_pages(path):

                if page_i in done:
                    continue

                stats, rows = analyse_page(
                    dataset,
                    page_i,
                    bbox,
                    raw,
                )

                if rows:
                    conn.executemany(
                        sql,
                        rows
                    )

                conn.execute(
                    """
                    INSERT OR REPLACE INTO page_stats
                    VALUES (?,?,?)
                    """,
                    (
                        dataset,
                        page_i,
                        json.dumps(
                            dict(stats),
                            sort_keys=True
                        ),
                    )
                )

                pending += 1

                if pending % 50 == 0:
                    conn.commit()
                    log(
                        dataset,
                        "checkpoint page",
                        page_i
                    )
                    conn.execute("BEGIN")

            conn.commit()
            log(dataset, "DONE")

        except Exception:
            conn.rollback()
            raise


def meta_get(conn, key):
    row = conn.execute(
        "SELECT value FROM meta WHERE key=?",
        (key,)
    ).fetchone()

    return row[0] if row else None


def meta_set(conn, key, value):
    conn.execute(
        "INSERT OR REPLACE INTO meta VALUES (?,?)",
        (key, str(value))
    )
    conn.commit()


def build_indexes(conn):
    if meta_get(conn, "indexes_done") == "1":
        return

    log("Building edge indexes...")

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_edges_geom
        ON edges(dataset, ax, ay, bx, by)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_edges_sig
        ON edges(s60,s61,s62,s65,s66)
    """)

    conn.commit()
    meta_set(conn, "indexes_done", 1)


def build_geom_unique(conn):
    if meta_get(conn, "geom_unique_done") == "1":
        return

    log("Building unique-geometry table...")

    conn.execute(
        "DROP TABLE IF EXISTS geom_unique"
    )

    conn.execute("""
        CREATE TABLE geom_unique AS
        SELECT *
        FROM edges
        GROUP BY dataset, ax, ay, bx, by
        HAVING COUNT(*) = 1
    """)

    conn.execute("""
        CREATE INDEX idx_gu_geom
        ON geom_unique(
            dataset, ax, ay, bx, by
        )
    """)

    conn.commit()
    meta_set(conn, "geom_unique_done", 1)


def cross_sql():
    fields = [
        "s60","s61","s62",
        "s63","s64","s65","s66",
        "w0","w1","w2","w3",
    ]

    sums = []

    for f in fields:
        sums.append(
            f"SUM(CASE WHEN a.{f}=b.{f} "
            f"THEN 1 ELSE 0 END)"
        )

    sums.append("""
        SUM(
            CASE WHEN
                a.s60=b.s60 AND
                a.s61=b.s61 AND
                a.s62=b.s62 AND
                a.s63=b.s63 AND
                a.s64=b.s64 AND
                a.s65=b.s65 AND
                a.s66=b.s66
            THEN 1 ELSE 0 END
        )
    """)

    sums.append("""
        SUM(
            CASE WHEN
                a.w0=b.w0 AND
                a.w1=b.w1 AND
                a.w2=b.w2 AND
                a.w3=b.w3
            THEN 1 ELSE 0 END
        )
    """)

    return (
        "SELECT COUNT(*),"
        + ",".join(sums)
        + """
        FROM geom_unique a
        JOIN geom_unique b
          ON a.ax=b.ax
         AND a.ay=b.ay
         AND a.bx=b.bx
         AND a.by=b.by
        WHERE a.dataset=? AND b.dataset=?
        """
    )


def run_cross_matches(conn):
    names = list(DATASETS)

    sql = cross_sql()

    fields = [
        "s60","s61","s62",
        "s63","s64","s65","s66",
        "w0","w1","w2","w3",
    ]

    for a, b in combinations(names, 2):

        exists = conn.execute(
            """
            SELECT 1 FROM cross_summary
            WHERE a=? AND b=?
            """,
            (a, b)
        ).fetchone()

        if exists:
            continue

        log("Cross-match", a, "<->", b)

        row = conn.execute(
            sql,
            (a, b)
        ).fetchone()

        total = row[0]

        summary = {
            "total": total,
            "field_equal": {
                f: row[1+i]
                for i, f in enumerate(fields)
            },
            "s6_exact": row[1+len(fields)],
            "s11_exact": row[2+len(fields)],
        }

        conn.execute(
            """
            INSERT OR REPLACE INTO cross_summary
            VALUES (?,?,?)
            """,
            (
                a,
                b,
                json.dumps(summary)
            )
        )

        conn.commit()


def aggregate_dataset(conn, dataset):
    total = Counter()

    for (js,) in conn.execute(
        """
        SELECT stats_json
        FROM page_stats
        WHERE dataset=?
        """,
        (dataset,)
    ):
        d = json.loads(js)

        for k, v in d.items():
            total[k] += v

    return total


def iter_logical_chunks(path, target=1024*1024):
    with path.open("rb") as f:
        head = f.read(16)

        if head[:4] == b"zip\x01":
            block_size, total_size, _ = struct.unpack_from(
                "<III", head, 4
            )

            n = (
                total_size + block_size - 1
            ) // block_size

            f.seek(0x10)

            offsets = struct.unpack(
                "<" + "I"*(n+1),
                f.read(4*(n+1))
            )

            buf = bytearray()

            for i in range(n):
                a = offsets[i]
                b = offsets[i+1]

                f.seek(a)
                packed = f.read(b-a)

                raw = zlib.decompress(packed)
                buf.extend(raw)

                if len(buf) >= target:
                    yield bytes(buf)
                    buf.clear()

            if buf:
                yield bytes(buf)

        else:
            f.seek(0)

            while True:
                data = f.read(target)

                if not data:
                    break

                yield data


def top_signatures(conn, limit=512):
    rows = conn.execute(
        """
        SELECT
            s60,s61,s62,s65,s66,
            COUNT(*) AS n
        FROM edges
        GROUP BY
            s60,s61,s62,s65,s66
        ORDER BY n DESC
        LIMIT ?
        """,
        (limit,)
    ).fetchall()

    return rows


def build_patterns(signatures):
    sig10_map = {}
    sig14_map = {}
    prefix_map = defaultdict(list)

    for a,b,c,d,e,n in signatures:
        prefix = struct.pack("<3H", a,b,c)
        suffix = struct.pack("<2H", d,e)

        ten = prefix + suffix
        key14 = prefix + suffix

        sig = (
            a,b,c,d,e,n
        )

        sig10_map[ten] = sig
        sig14_map[key14] = sig
        prefix_map[prefix].append(sig)

    p10 = re.compile(
        b"|".join(
            re.escape(x)
            for x in sig10_map
        )
    )

    p14 = re.compile(
        b"|".join(
            re.escape(k[:6])
            + b".{4}"
            + re.escape(k[6:])
            for k in sig14_map
        ),
        re.DOTALL
    )

    pprefix = re.compile(
        b"|".join(
            re.escape(x)
            for x in prefix_map
        )
    )

    return (
        sig10_map,
        sig14_map,
        prefix_map,
        p10,
        p14,
        pprefix,
    )


def scan_file(path, patterns):
    (
        sig10_map,
        sig14_map,
        prefix_map,
        p10,
        p14,
        pprefix,
    ) = patterns

    counts10 = Counter()
    counts14 = Counter()
    counts6 = Counter()

    examples = []

    carry = b""
    logical_pos = 0

    for chunk in iter_logical_chunks(path):
        buf = carry + chunk
        base = logical_pos - len(carry)

        # Count match only if it reaches newly read bytes.
        cutoff = logical_pos

        for m in p10.finditer(buf):
            gs = base + m.start()
            ge = base + m.end()

            if ge <= cutoff:
                continue

            raw = m.group()
            sig = sig10_map.get(raw)

            if sig:
                key = "%04X/%04X/%04X/%04X/%04X" % sig[:5]
                counts10[key] += 1

                if len(examples) < 40:
                    examples.append(
                        ("exact10", gs, key)
                    )

        for m in p14.finditer(buf):
            gs = base + m.start()
            ge = base + m.end()

            if ge <= cutoff:
                continue

            raw = m.group()

            keyraw = raw[:6] + raw[10:14]

            sig = sig14_map.get(keyraw)

            if sig:
                key = "%04X/%04X/%04X/%04X/%04X" % sig[:5]
                counts14[key] += 1

                if len(examples) < 40:
                    examples.append(
                        ("wild14", gs, key)
                    )

        for m in pprefix.finditer(buf):
            gs = base + m.start()
            ge = base + m.end()

            if ge <= cutoff:
                continue

            counts6[m.group().hex()] += 1

        logical_pos += len(chunk)
        carry = buf[-32:]

    return {
        "logical_size": logical_pos,
        "exact10_total": sum(counts10.values()),
        "wild14_total": sum(counts14.values()),
        "prefix6_total": sum(counts6.values()),

        "top_exact10": counts10.most_common(50),
        "top_wild14": counts14.most_common(50),
        "top_prefix6": counts6.most_common(50),

        "examples": examples,
    }


def run_signature_scan(conn):
    signatures = top_signatures(
        conn,
        limit=512
    )

    patterns = build_patterns(signatures)

    paths = []

    for dbdir in DB_DIRS:
        if not dbdir.exists():
            continue

        for p in sorted(dbdir.iterdir()):
            if not p.is_file():
                continue

            if p.suffix.upper() in (
                ".MG1",
                ".MG2",
                ".MG3",
            ):
                continue

            paths.append(p)

    for path in paths:
        key = str(path)

        exists = conn.execute(
            """
            SELECT 1
            FROM scan_summary
            WHERE path=?
            """,
            (key,)
        ).fetchone()

        if exists:
            continue

        log("Signature scan:", path)

        try:
            result = scan_file(
                path,
                patterns
            )

            result["ok"] = True

        except Exception as e:
            result = {
                "ok": False,
                "error": repr(e),
            }

        conn.execute(
            """
            INSERT OR REPLACE INTO scan_summary
            VALUES (?,?)
            """,
            (
                key,
                json.dumps(result)
            )
        )

        conn.commit()


def percentage(a, b):
    if not b:
        return 0.0

    return 100.0 * a / b


def best_angle_tests(stats, limit=25):
    rows = []

    for key, n in stats.items():
        if not key.startswith("angle."):
            continue

        if not key.endswith(".n"):
            continue

        base = key[:-2]

        d2 = stats.get(
            base + ".d2", 0
        )

        if n >= 20:
            rows.append(
                (
                    percentage(d2, n),
                    n,
                    d2,
                    base,
                )
            )

    rows.sort(reverse=True)

    return rows[:limit]


def write_report(conn):
    with REPORT.open(
        "w",
        encoding="utf-8"
    ) as out:

        print(
            "NCDR MG OVERNIGHT MEGAPROBE",
            file=out
        )

        print(
            time.strftime("%Y-%m-%d %H:%M:%S"),
            file=out
        )

        for dataset in DATASETS:
            s = aggregate_dataset(
                conn,
                dataset
            )

            print("\n" + "="*100, file=out)
            print("DATASET:", dataset, file=out)

            print(
                "pages:",
                s["pages"],
                file=out
            )

            print(
                "S1 exact:",
                s["s1_parse_ok"],
                "/",
                s["pages"],
                file=out
            )

            print(
                "S3 exact:",
                s["s3_parse_ok"],
                "/",
                s["pages"],
                file=out
            )

            print(
                "S3 points equal S1:",
                s["s3_points_equal_s1"],
                "/",
                s["s3_points"],
                f"({percentage(s['s3_points_equal_s1'], s['s3_points']):.6f}%)",
                file=out
            )

            print(
                "S3 segments equal clean edge:",
                s["s3_segments_equal_clean_edge"],
                "/",
                s["s3_segments"],
                f"({percentage(s['s3_segments_equal_clean_edge'], s['s3_segments']):.6f}%)",
                file=out
            )

            print(
                "clean fanin2 edges:",
                s["edge_total"],
                file=out
            )

            print(
                "S6[3] == vertex A:",
                s["s6_3_eq_a"],
                "/",
                s["edge_total"],
                f"({percentage(s['s6_3_eq_a'], s['edge_total']):.6f}%)",
                file=out
            )

            print(
                "S6[4] == vertex B:",
                s["s6_4_eq_b"],
                "/",
                s["edge_total"],
                f"({percentage(s['s6_4_eq_b'], s['edge_total']):.6f}%)",
                file=out
            )

            print("\nS6[5] RANGE TESTS:", file=out)

            for k in (
                "h1","h3","h5",
                "h7","h11","s3chains"
            ):
                v = s[f"s65_lt_{k}"]

                print(
                    k,
                    v,
                    "/",
                    s["edge_total"],
                    f"({percentage(v, s['edge_total']):.6f}%)",
                    file=out
                )

            print(
                "S6[5] as S3 endpoint exact:",
                s["s65_s3_exact_endpoint"],
                file=out
            )

            print("\nS11 EDGE-REF TESTS:", file=out)

            for slot in ("w0", "w2"):
                for transform in (
                    "raw",
                    "minus1",
                    "plus1",
                    "mask15",
                    "mask14",
                    "mask12",
                ):
                    base = (
                        f"ref.{slot}.{transform}"
                    )

                    valid = s[
                        base + ".valid_endpoints"
                    ]

                    if not valid:
                        continue

                    print(
                        slot,
                        transform,
                        "valid=", valid,
                        "shareA=",
                        s[base+".share_a"],
                        f"({percentage(s[base+'.share_a'], valid):.3f}%)",
                        "shareB=",
                        s[base+".share_b"],
                        f"({percentage(s[base+'.share_b'], valid):.3f}%)",
                        "shareAny=",
                        s[base+".share_any"],
                        f"({percentage(s[base+'.share_any'], valid):.3f}%)",
                        "self=",
                        s[base+".self"],
                        file=out
                    )

            print("\nBEST ANGLE TESTS (<=2 deg):", file=out)

            for score, n, good, key in best_angle_tests(s):
                print(
                    f"{score:9.5f}% "
                    f"{good}/{n} "
                    f"{key}",
                    file=out
                )

            # Basic S11 distributions directly from DB.
            row = conn.execute(
                """
                SELECT
                  MIN(w1), MAX(w1),
                  COUNT(DISTINCT w1),
                  SUM(CASE WHEN w1<=359 THEN 1 ELSE 0 END),
                  MIN(w3), MAX(w3),
                  COUNT(DISTINCT w3),
                  SUM(CASE WHEN w3<=359 THEN 1 ELSE 0 END),
                  COUNT(*)
                FROM edges
                WHERE dataset=?
                """,
                (dataset,)
            ).fetchone()

            print("\nS11 ANGLE-LIKE RANGE:", file=out)
            print(
                "w1 min/max/distinct/<=359:",
                row[0], row[1], row[2], row[3],
                "/", row[8],
                file=out
            )

            print(
                "w3 min/max/distinct/<=359:",
                row[4], row[5], row[6], row[7],
                "/", row[8],
                file=out
            )

            print("\nTOP INVARIANT S6 SIGNATURES:", file=out)

            for r in conn.execute(
                """
                SELECT
                    s60,s61,s62,s65,s66,
                    COUNT(*) n
                FROM edges
                WHERE dataset=?
                GROUP BY
                    s60,s61,s62,s65,s66
                ORDER BY n DESC
                LIMIT 30
                """,
                (dataset,)
            ):
                print(r, file=out)

        print("\n" + "="*100, file=out)
        print("CROSS-DATASET EXACT GEOMETRY", file=out)

        for a, b, js in conn.execute(
            """
            SELECT a,b,summary_json
            FROM cross_summary
            ORDER BY a,b
            """
        ):
            d = json.loads(js)
            n = d["total"]

            print("\n", a, "<->", b, file=out)
            print("matches:", n, file=out)

            if not n:
                continue

            for f, eq in d["field_equal"].items():
                print(
                    f,
                    eq,
                    "/",
                    n,
                    f"({percentage(eq,n):.6f}%)",
                    file=out
                )

            print(
                "S6 exact:",
                d["s6_exact"],
                "/",
                n,
                f"({percentage(d['s6_exact'],n):.6f}%)",
                file=out
            )

            print(
                "S11 exact:",
                d["s11_exact"],
                "/",
                n,
                f"({percentage(d['s11_exact'],n):.6f}%)",
                file=out
            )

        print("\n" + "="*100, file=out)
        print("NON-MG SIGNATURE SCAN", file=out)

        for path, js in conn.execute(
            """
            SELECT path,summary_json
            FROM scan_summary
            ORDER BY path
            """
        ):
            d = json.loads(js)

            print("\nFILE:", path, file=out)

            if not d.get("ok"):
                print(
                    "ERROR:",
                    d.get("error"),
                    file=out
                )
                continue

            print(
                "logical size:",
                d["logical_size"],
                file=out
            )

            print(
                "S6 prefix6 hits:",
                d["prefix6_total"],
                file=out
            )

            print(
                "S6 packed10 hits:",
                d["exact10_total"],
                file=out
            )

            print(
                "S6 prefix + any4 + suffix hits:",
                d["wild14_total"],
                file=out
            )

            print(
                "top packed10:",
                d["top_exact10"][:20],
                file=out
            )

            print(
                "top wild14:",
                d["top_wild14"][:20],
                file=out
            )

            if d["examples"]:
                print(
                    "examples:",
                    d["examples"][:20],
                    file=out
                )


def main():
    log("DB:", DB_PATH)
    log("REPORT:", REPORT)

    conn = init_db()

    try:
        log("PHASE 1: MG extraction + S3/S6/S11 semantics")
        process_datasets(conn)

        log("PHASE 2: indexes")
        build_indexes(conn)

        log("PHASE 3: unique geometry")
        build_geom_unique(conn)

        log("PHASE 4: all-pairs cross-dataset mining")
        run_cross_matches(conn)

        log("PHASE 5: non-MG stable-S6 signature scan")
        run_signature_scan(conn)

        log("PHASE 6: report")
        write_report(conn)

        log("ALL DONE")
        log("Report:", REPORT)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
