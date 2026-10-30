#!/usr/bin/env python3

from pathlib import Path
from collections import defaultdict, Counter
from multiprocessing import get_context

import hashlib
import json
import math
import mmap
import os
import sqlite3
import struct
import subprocess
import time
import traceback
import zlib


ROOT = Path.home() / "Desktop" / "NCDR_RESERCH"

B1 = ROOT / "bridge_v1"

OUT = ROOT / "bridge24"
OUT.mkdir(parents=True, exist_ok=True)

STATE = OUT / "state.sqlite"
MASTER = OUT / "master_report.txt"
HEARTBEAT = OUT / "heartbeat.json"

MGDB = ROOT / "mg_overnight.sqlite"
BRIDGEDB = B1 / "bridge.sqlite"

PREREQ = B1 / "02_selective_scan.py"
CACHE = B1 / "cache"

HOURS = float(
    os.environ.get(
        "NCDR_HOURS",
        "23.5",
    )
)

WORKERS = max(
    1,
    min(
        int(
            os.environ.get(
                "NCDR_CPU_WORKERS",
                "10",
            )
        ),
        12,
    ),
)

BATCH = 80

START = time.time()
DEADLINE = START + HOURS * 3600.0


# inherited by fork workers
MM = {}
ENT = defaultdict(list)
GOLD = defaultdict(list)


def log(*parts):
    print(
        time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        *parts,
        flush=True,
    )


def table_exists(conn, name):
    return (
        conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type='table'
              AND name=?
            """,
            (name,),
        ).fetchone()
        is not None
    )


# ============================================================
# PREREQUISITE
# ============================================================

def ensure_selective_scan():
    ready = False

    if BRIDGEDB.exists():
        c = sqlite3.connect(BRIDGEDB)

        try:
            if (
                table_exists(
                    c,
                    "selective_anchors",
                )
                and table_exists(
                    c,
                    "selective_signature_stats",
                )
            ):
                n = c.execute(
                    """
                    SELECT COUNT(*)
                    FROM selective_anchors
                    """
                ).fetchone()[0]

                ready = n > 0

        finally:
            c.close()

    if ready:
        log(
            "PREREQ READY:",
            "selective anchors exist",
        )
        return

    if not PREREQ.exists():
        raise SystemExit(
            f"Missing prerequisite: {PREREQ}"
        )

    log(
        "PREREQ:",
        "running selective scan",
    )

    logfile = (
        OUT
        / "00_selective_scan.log"
    )

    with logfile.open(
        "ab"
    ) as f:

        p = subprocess.run(
            [
                "python3",
                "-u",
                str(PREREQ),
            ],
            cwd=str(ROOT),
            stdout=f,
            stderr=subprocess.STDOUT,
        )

    if p.returncode != 0:
        raise SystemExit(
            "Selective scan failed. "
            f"See {logfile}"
        )

    c = sqlite3.connect(
        BRIDGEDB
    )

    try:
        if not table_exists(
            c,
            "selective_anchors",
        ):
            raise RuntimeError(
                "selective_anchors missing"
            )

        n = c.execute(
            """
            SELECT COUNT(*)
            FROM selective_anchors
            """
        ).fetchone()[0]

        if n <= 0:
            raise RuntimeError(
                "selective scan produced "
                "zero anchors"
            )

        log(
            "PREREQ DONE:",
            n,
            "anchors",
        )

    finally:
        c.close()


# ============================================================
# DATA FILES
# ============================================================

def locate_source(key):
    choices = {
        "7185_RD": [
            Path(
                "/Volumes/CD_7185/DB/I.RD"
            ),
            ROOT
            / "DEEPSEEK_BRIDGE_INPUT"
            / "CD_7185_I.RD",
        ],

        "7185_RT": [
            CACHE
            / "7185_RT.logical",

            Path(
                "/Volumes/CD_7185/DB/IZ.RT"
            ),

            ROOT
            / "DEEPSEEK_BRIDGE_INPUT"
            / "CD_7185_IZ.RT",
        ],

        "7185_RL": [
            CACHE
            / "7185_RL.logical",

            Path(
                "/Volumes/CD_7185/DB/IZ.RL"
            ),

            ROOT
            / "DEEPSEEK_BRIDGE_INPUT"
            / "CD_7185_IZ.RL",
        ],

        "7186_RD": [
            Path(
                "/Volumes/CD_7186/DB/SC.RD"
            ),

            ROOT
            / "DEEPSEEK_BRIDGE_INPUT"
            / "CD_7186_SC.RD",
        ],

        "7186_RT": [
            CACHE
            / "7186_RT.logical",

            Path(
                "/Volumes/CD_7186/DB/SCZ.RT"
            ),

            ROOT
            / "DEEPSEEK_BRIDGE_INPUT"
            / "CD_7186_SCZ.RT",
        ],

        "7186_RL": [
            CACHE
            / "7186_RL.logical",

            Path(
                "/Volumes/CD_7186/DB/SCZ.RL"
            ),

            ROOT
            / "DEEPSEEK_BRIDGE_INPUT"
            / "CD_7186_SCZ.RL",
        ],
    }

    for p in choices[key]:
        if p.is_file():
            return p

    return None


def logical_file(key, src):
    with src.open("rb") as f:
        head = f.read(16)

    if head[:4] != b"zip\x01":
        return src

    block_size, total, _ = (
        struct.unpack_from(
            "<III",
            head,
            4,
        )
    )

    n = (
        total
        + block_size
        - 1
    ) // block_size

    cache_dir = OUT / "cache"
    cache_dir.mkdir(exist_ok=True)

    dst = (
        cache_dir
        / f"{key}.logical"
    )

    if (
        dst.exists()
        and dst.stat().st_size
        == total
    ):
        return dst

    log(
        "DECOMPRESS",
        key,
        "logical=",
        total,
        "blocks=",
        n,
    )

    tmp = (
        cache_dir
        / f"{key}.tmp"
    )

    produced = 0

    with src.open("rb") as f:
        f.seek(16)

        offsets = struct.unpack(
            "<"
            + "I" * (n + 1),
            f.read(
                4 * (n + 1)
            ),
        )

        with tmp.open(
            "wb"
        ) as out:

            for i in range(n):
                f.seek(
                    offsets[i]
                )

                packed = f.read(
                    offsets[i + 1]
                    - offsets[i]
                )

                raw = zlib.decompress(
                    packed
                )

                out.write(raw)

                produced += len(raw)

    if produced != total:
        raise RuntimeError(
            f"{key}: "
            f"{produced} != {total}"
        )

    tmp.replace(dst)

    return dst


def open_files():
    paths = {}

    for key in (
        "7185_RD",
        "7185_RT",
        "7185_RL",
        "7186_RD",
        "7186_RT",
        "7186_RL",
    ):
        src = locate_source(key)

        if src is None:
            raise SystemExit(
                f"Missing source: {key}"
            )

        p = logical_file(
            key,
            src,
        )

        paths[key] = p

        fh = p.open("rb")

        mm = mmap.mmap(
            fh.fileno(),
            0,
            access=mmap.ACCESS_READ,
        )

        MM[key] = (
            fh,
            mm,
        )

        log(
            "DATA",
            key,
            p,
            len(mm),
        )

    return paths


# ============================================================
# LOAD SELECTIVE ANCHORS
# ============================================================

def samples_from_json(text):
    if not text:
        return []

    try:
        return [
            int(x)
            for x in json.loads(
                text
            )
        ][:8]

    except Exception:
        return []


def load_entities():
    c = sqlite3.connect(
        BRIDGEDB
    )

    c.row_factory = (
        sqlite3.Row
    )

    stats = {}

    for r in c.execute(
        """
        SELECT
            country,
            file_key,
            sig,
            kind,
            s65,
            s66,
            mg_count,
            lod_count,
            hit_count,
            samples
        FROM selective_signature_stats
        """
    ):
        stats[
            (
                r["country"],
                r["file_key"],
                int(r["sig"]),
                r["kind"],
            )
        ] = {
            "hits":
                int(
                    r["hit_count"]
                ),

            "samples":
                samples_from_json(
                    r["samples"]
                ),
        }

    for a in c.execute(
        """
        SELECT *
        FROM selective_anchors
        """
    ):
        country = a["country"]
        sig = int(a["sig"])

        e = {
            "country":
                country,

            "sig":
                sig,

            "s65":
                int(a["s65"]),

            "s66":
                int(a["s66"]),

            "mg_count":
                int(
                    a["mg_count"]
                ),

            "lod_count":
                int(
                    a["lod_count"]
                ),

            "files": {},
        }

        for suffix in (
            "RD",
            "RT",
            "RL",
        ):
            key = (
                country
                + "_"
                + suffix
            )

            q = stats.get(
                (
                    country,
                    key,
                    sig,
                    "real",
                )
            )

            if q:
                e["files"][
                    suffix
                ] = q

        if (
            "RD"
            in e["files"]
            and (
                "RT"
                in e["files"]
                or "RL"
                in e["files"]
            )
        ):
            ENT[
                country
            ].append(e)

    c.close()

    for country in (
        "7185",
        "7186",
    ):
        ENT[country].sort(
            key=lambda e: (
                e["mg_count"],

                e["files"][
                    "RD"
                ]["hits"],

                e["files"].get(
                    "RT",
                    {"hits": 10**9},
                )["hits"]
                +
                e["files"].get(
                    "RL",
                    {"hits": 10**9},
                )["hits"],
            )
        )

        log(
            "ANCHORS",
            country,
            len(
                ENT[country]
            ),
        )


def load_gold_geometry():
    mg = sqlite3.connect(
        f"file:{MGDB}?mode=ro",
        uri=True,
        timeout=120,
    )

    mg.row_factory = sqlite3.Row

    mg.execute(
        """
        CREATE TEMP TABLE IF NOT EXISTS wanted_gold (
            s65 INTEGER NOT NULL,
            s66 INTEGER NOT NULL,
            PRIMARY KEY(s65,s66)
        )
        """
    )

    mg.execute(
        "PRAGMA temp_store=MEMORY"
    )

    for country in (
        "7185",
        "7186",
    ):
        wanted = {
            (
                int(e["s65"]),
                int(e["s66"]),
            ): e
            for e in ENT[country]
            if e["mg_count"] == 1
        }

        if not wanted:
            log(
                "GOLD UNIQUE",
                country,
                0,
            )
            continue

        mg.execute(
            "DELETE FROM wanted_gold"
        )

        mg.executemany(
            """
            INSERT OR IGNORE INTO wanted_gold(
                s65,
                s66
            )
            VALUES(?,?)
            """,
            list(wanted.keys()),
        )

        datasets = (
            country + "_MG1",
            country + "_MG2",
            country + "_MG3",
        )

        counts = defaultdict(int)
        first = {}

        log(
            "GOLD SCAN",
            country,
            "wanted=",
            len(wanted),
        )

        rows = mg.execute(
            """
            SELECT
                e.dataset,
                (e.s65 & 65535) AS s65v,
                (e.s66 & 65535) AS s66v,
                e.ax,
                e.ay,
                e.bx,
                e.by
            FROM edges AS e
            CROSS JOIN wanted_gold AS w
            WHERE e.dataset IN (?,?,?)
              AND (e.s65 & 65535) = w.s65
              AND (e.s66 & 65535) = w.s66
            """,
            datasets,
        )

        for r in rows:
            key = (
                int(r["s65v"]),
                int(r["s66v"]),
            )

            counts[key] += 1

            if key not in first:
                first[key] = (
                    int(r["ax"]),
                    int(r["ay"]),
                    int(r["bx"]),
                    int(r["by"]),
                )

        accepted = 0

        for key, n in counts.items():
            if n != 1:
                continue

            e = wanted.get(key)

            if e is None:
                continue

            e["geom"] = first[key]

            GOLD[country].append(e)

            accepted += 1

        log(
            "GOLD UNIQUE",
            country,
            accepted,
        )

    mg.close()



# ============================================================
# STATE / TASK QUEUE
# ============================================================

def init_state():
    c = sqlite3.connect(
        STATE
    )

    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY,
            task_key TEXT UNIQUE,
            family TEXT,
            params TEXT,
            priority REAL,
            status TEXT DEFAULT 'pending',
            created REAL,
            started REAL,
            finished REAL,
            score REAL,
            summary TEXT,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS findings (
            id INTEGER PRIMARY KEY,
            task_id INTEGER,
            family TEXT,
            finding_key TEXT,
            score REAL,
            evidence TEXT,
            created REAL,
            UNIQUE(
                family,
                finding_key
            )
        );

        CREATE TABLE IF NOT EXISTS rejected (
            id INTEGER PRIMARY KEY,
            task_id INTEGER,
            family TEXT,
            reason TEXT,
            evidence TEXT,
            created REAL
        );

        CREATE TABLE IF NOT EXISTS meta (
            k TEXT PRIMARY KEY,
            v TEXT
        );
        """
    )

    # crash recovery
    c.execute(
        """
        UPDATE tasks
        SET status='pending',
            started=NULL
        WHERE status='running'
        """
    )

    c.execute(
        """
        INSERT OR REPLACE
        INTO meta(k,v)
        VALUES('deadline',?)
        """,
        (
            str(DEADLINE),
        ),
    )

    c.commit()

    return c


def make_task_key(
    family,
    params,
):
    raw = (
        family
        + "|"
        + json.dumps(
            params,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )
    )

    return hashlib.sha256(
        raw.encode()
    ).hexdigest()


def add_task(
    c,
    family,
    params,
    priority,
):
    c.execute(
        """
        INSERT OR IGNORE
        INTO tasks(
            task_key,
            family,
            params,
            priority,
            created
        )
        VALUES(?,?,?,?,?)
        """,
        (
            make_task_key(
                family,
                params,
            ),

            family,

            json.dumps(
                params,
                sort_keys=True,
            ),

            float(priority),

            time.time(),
        ),
    )


def seed_tasks(c):
    filters = [
        (1,   1,    4),
        (2,   2,    8),
        (4,   4,   16),
        (8,   8,   32),
        (16, 16,   64),
        (64, 64,  256),
        (256,512,1024),
    ]

    # Main cross-file structural search.
    #
    # Each task itself tests many RD-offset
    # x routing-offset hypotheses.
    for country in (
        "7185",
        "7186",
    ):
        for target in (
            "RT",
            "RL",
        ):
            for width in (
                2,3,4,5,6,8
            ):
                for radius in (
                    24,
                    32,
                    48,
                    64,
                    96,
                    128,
                ):
                    for (
                        max_mg,
                        max_rd,
                        max_route,
                    ) in filters:

                        for reverse in (
                            0,
                            1,
                        ):
                            for occ_cap in (
                                1,
                                2,
                                4,
                            ):
                                for anchor_cap in (
                                    80,
                                    200,
                                ):

                                    # prioritize
                                    # selective / cheap
                                    # hypotheses first
                                    priority = 20.0

                                    if width in (
                                        3,
                                        4,
                                    ):
                                        priority += 5

                                    priority -= (
                                        radius
                                        / 100.0
                                    )

                                    priority -= (
                                        math.log2(
                                            max_mg
                                            + 1
                                        )
                                        / 4
                                    )

                                    if (
                                        occ_cap
                                        == 1
                                    ):
                                        priority += 2

                                    if (
                                        anchor_cap
                                        == 80
                                    ):
                                        priority += 1

                                    add_task(
                                        c,
                                        "crosscorr",
                                        {
                                            "country":
                                                country,

                                            "target":
                                                target,

                                            "width":
                                                width,

                                            "radius":
                                                radius,

                                            "max_mg":
                                                max_mg,

                                            "max_rd":
                                                max_rd,

                                            "max_route":
                                                max_route,

                                            "reverse":
                                                reverse,

                                            "occ_cap":
                                                occ_cap,

                                            "anchor_cap":
                                                anchor_cap,
                                        },
                                        priority,
                                    )

    # Fixed record/alignment hypotheses.
    for country in (
        "7185",
        "7186",
    ):
        for suffix in (
            "RD",
            "RT",
            "RL",
        ):
            for (
                max_mg,
                max_rd,
                max_route,
            ) in filters:

                add_task(
                    c,
                    "alignment",
                    {
                        "country":
                            country,

                        "file":
                            suffix,

                        "max_mg":
                            max_mg,

                        "max_rd":
                            max_rd,

                        "max_route":
                            max_route,
                    },
                    25,
                )

    # Routing-topology validation using
    # unique MG geometry anchors.
    for country in (
        "7185",
        "7186",
    ):
        for target in (
            "RT",
            "RL",
        ):
            for width in (
                2,3,4,5,6,8
            ):
                for radius in (
                    32,
                    64,
                    96,
                    128,
                ):
                    add_task(
                        c,
                        "topology",
                        {
                            "country":
                                country,

                            "target":
                                target,

                            "width":
                                width,

                            "radius":
                                radius,
                        },
                        18,
                    )

    c.commit()


# ============================================================
# STRUCTURAL HELPERS
# ============================================================

def fi(e, suffix):
    return e[
        "files"
    ].get(suffix)


def qualifies(
    e,
    target,
    max_mg,
    max_rd,
    max_route,
):
    rd = fi(
        e,
        "RD",
    )

    tr = fi(
        e,
        target,
    )

    if (
        not rd
        or not tr
        or not rd["samples"]
        or not tr["samples"]
    ):
        return False

    if (
        e["mg_count"]
        > max_mg
    ):
        return False

    if (
        rd["hits"]
        > max_rd
    ):
        return False

    if (
        tr["hits"]
        > max_route
    ):
        return False

    return True


def overlaps_anchor(
    delta,
    width,
):
    return (
        delta < 4
        and delta + width > 0
    )


def get_token(
    mm,
    pos,
    width,
):
    if (
        pos < 0
        or pos + width
        > len(mm)
    ):
        return None

    b = bytes(
        mm[
            pos:
            pos + width
        ]
    )

    if len(b) != width:
        return None

    # Reject ultra-low-information
    # 00 00 / FF FF / etc.
    if all(
        x == b[0]
        for x in b
    ):
        return None

    return b


# ============================================================
# CROSS-CONTEXT MINER
# ============================================================

def pair_support_for_entity(
    rd_entity,
    target_entity,
    target,
    width,
    radius,
    reverse,
    occ_cap,
):
    country = (
        rd_entity["country"]
    )

    rd = fi(
        rd_entity,
        "RD",
    )

    tr = fi(
        target_entity,
        target,
    )

    if not rd or not tr:
        return set()

    mm_rd = MM[
        country + "_RD"
    ][1]

    mm_tr = MM[
        country
        + "_"
        + target
    ][1]

    found = set()

    for roff in (
        rd["samples"]
        [:occ_cap]
    ):
        rmap = defaultdict(
            list
        )

        for dr in range(
            -radius,
            radius + 1,
        ):
            if overlaps_anchor(
                dr,
                width,
            ):
                continue

            value = get_token(
                mm_rd,
                roff + dr,
                width,
            )

            if value is not None:
                rmap[
                    value
                ].append(dr)

        for toff in (
            tr["samples"]
            [:occ_cap]
        ):
            tmap = defaultdict(
                list
            )

            for dt in range(
                -radius,
                radius + 1,
            ):
                if overlaps_anchor(
                    dt,
                    width,
                ):
                    continue

                value = get_token(
                    mm_tr,
                    toff + dt,
                    width,
                )

                if value is None:
                    continue

                if reverse:
                    value = (
                        value[::-1]
                    )

                tmap[
                    value
                ].append(dt)

            for value, drs in (
                rmap.items()
            ):
                dts = tmap.get(
                    value
                )

                if not dts:
                    continue

                for dr in drs:
                    for dt in dts:
                        found.add(
                            (
                                dr,
                                dt,
                            )
                        )

    return found


def task_crosscorr(p):
    country = p[
        "country"
    ]

    target = p[
        "target"
    ]

    chosen = [
        e
        for e in ENT[country]
        if qualifies(
            e,
            target,
            p["max_mg"],
            p["max_rd"],
            p["max_route"],
        )
    ]

    chosen = chosen[
        :p["anchor_cap"]
    ]

    n = len(chosen)

    if n < 6:
        return {
            "score": 0,
            "summary":
                f"too few anchors={n}",
            "findings": [],
            "reject":
                "too few selective anchors",
        }

    real = Counter()
    control = Counter()

    # real pairings
    for e in chosen:
        pairs = (
            pair_support_for_entity(
                e,
                e,
                target,
                p["width"],
                p["radius"],
                bool(
                    p["reverse"]
                ),
                p["occ_cap"],
            )
        )

        for pair in pairs:
            real[pair] += 1

    # matched controls:
    # RD context from one real anchor
    # vs routing context from another.
    shifts = (
        7,
        13,
        29,
    )

    for shift in shifts:
        if n <= shift:
            continue

        for i, e in enumerate(
            chosen
        ):
            other = chosen[
                (i + shift) % n
            ]

            pairs = (
                pair_support_for_entity(
                    e,
                    other,
                    target,
                    p["width"],
                    p["radius"],
                    bool(
                        p["reverse"]
                    ),
                    p["occ_cap"],
                )
            )

            for pair in pairs:
                control[
                    pair
                ] += 1

    control_n = (
        n
        * sum(
            1
            for shift
            in shifts
            if n > shift
        )
    )

    findings = []
    ranked = []

    for pair, support in (
        real.items()
    ):
        if support < 3:
            continue

        control_support = (
            control.get(
                pair,
                0,
            )
        )

        real_frac = (
            support / n
        )

        # Laplace smoothing.
        real_smoothed = (
            support + 1
        ) / (
            n + 2
        )

        ctrl_smoothed = (
            control_support
            + 1
        ) / (
            max(
                control_n,
                1,
            )
            + 2
        )

        enrichment = (
            real_smoothed
            / ctrl_smoothed
        )

        score = (
            real_frac
            * math.log2(
                1
                + enrichment
            )
            * math.log2(
                support
                + 2
            )
        )

        ranked.append(
            (
                score,
                pair,
                support,
                control_support,
                enrichment,
            )
        )

    ranked.sort(
        reverse=True
    )

    for (
        score,
        (
            rd_delta,
            target_delta,
        ),
        support,
        control_support,
        enrichment,
    ) in ranked[:30]:

        key = (
            f"{country}:"
            f"{target}:"
            f"w{p['width']}:"
            f"rev{p['reverse']}:"
            f"rd{rd_delta}:"
            f"tg{target_delta}"
        )

        findings.append({
            "key":
                key,

            "score":
                score,

            "evidence": {
                "country":
                    country,

                "target":
                    target,

                "width":
                    p["width"],

                "reverse":
                    p["reverse"],

                "rd_delta":
                    rd_delta,

                "target_delta":
                    target_delta,

                "real_support":
                    support,

                "real_n":
                    n,

                "control_support":
                    control_support,

                "control_n":
                    control_n,

                "enrichment":
                    enrichment,

                "radius":
                    p["radius"],

                "occ_cap":
                    p["occ_cap"],

                "anchor_cap":
                    p["anchor_cap"],

                "filter": [
                    p["max_mg"],
                    p["max_rd"],
                    p["max_route"],
                ],
            },
        })

    best = (
        ranked[0][0]
        if ranked
        else 0.0
    )

    reject = None

    if (
        not ranked
        or best < 0.8
    ):
        reject = (
            "no relative RD-routing "
            "field offset exceeded "
            "minimum signal"
        )

    return {
        "score":
            best,

        "summary":
            (
                f"anchors={n} "
                f"pairs={len(ranked)}"
            ),

        "findings":
            findings,

        "reject":
            reject,
    }


# ============================================================
# ALIGNMENT / RECORD WIDTH
# ============================================================

def task_alignment(p):
    country = p[
        "country"
    ]

    suffix = p[
        "file"
    ]

    offsets = []

    for e in ENT[country]:
        rd = fi(
            e,
            "RD",
        )

        rt = fi(
            e,
            "RT",
        )

        rl = fi(
            e,
            "RL",
        )

        q = fi(
            e,
            suffix,
        )

        if (
            not rd
            or not q
        ):
            continue

        route_hits = (
            (
                rt["hits"]
                if rt
                else 0
            )
            +
            (
                rl["hits"]
                if rl
                else 0
            )
        )

        if (
            e["mg_count"]
            > p["max_mg"]
        ):
            continue

        if (
            rd["hits"]
            > p["max_rd"]
        ):
            continue

        if (
            route_hits
            > p["max_route"]
        ):
            continue

        offsets.extend(
            q["samples"]
        )

        if (
            len(offsets)
            >= 600
        ):
            break

    offsets = offsets[:600]

    if len(offsets) < 10:
        return {
            "score": 0,
            "summary":
                f"offsets={len(offsets)}",
            "findings": [],
            "reject":
                "too few offsets",
        }

    # deterministic pseudo-random
    # offsets are the control.
    file_size = len(
        MM[
            country
            + "_"
            + suffix
        ][1]
    )

    controls = [
        (
            (
                x
                * 2654435761
                + 1013904223
            )
            % file_size
        )
        for x in offsets
    ]

    ranked = []

    for width in range(
        2,
        257,
    ):
        rh = [0] * width
        ch = [0] * width

        for x in offsets:
            rh[
                x % width
            ] += 1

        for x in controls:
            ch[
                x % width
            ] += 1

        rmax = max(rh)
        cmax = max(ch)

        rf = (
            rmax
            / len(offsets)
        )

        cf = (
            cmax
            / len(controls)
        )

        score = (
            (rf - cf)
            * math.sqrt(
                len(offsets)
            )
            * math.log2(
                width + 1
            )
        )

        ranked.append(
            (
                score,
                width,
                rh.index(
                    rmax
                ),
                rf,
                cf,
            )
        )

    ranked.sort(
        reverse=True
    )

    findings = []

    for (
        score,
        width,
        residue,
        rf,
        cf,
    ) in ranked[:25]:

        findings.append({
            "key":
                (
                    f"{country}:"
                    f"{suffix}:"
                    f"width{width}:"
                    f"res{residue}"
                ),

            "score":
                score,

            "evidence": {
                "country":
                    country,

                "file":
                    suffix,

                "width":
                    width,

                "residue":
                    residue,

                "real_fraction":
                    rf,

                "control_fraction":
                    cf,

                "n":
                    len(offsets),

                "filter": [
                    p["max_mg"],
                    p["max_rd"],
                    p["max_route"],
                ],
            },
        })

    best = ranked[0][0]

    return {
        "score":
            best,

        "summary":
            f"offsets={len(offsets)}",

        "findings":
            findings,

        "reject":
            (
                None
                if best >= 1.0
                else
                "no useful alignment enrichment"
            ),
    }


# ============================================================
# TOPOLOGY VALIDATION
# ============================================================

def routing_token_set(
    e,
    target,
    width,
    radius,
):
    q = fi(
        e,
        target,
    )

    if not q:
        return set()

    mm = MM[
        e["country"]
        + "_"
        + target
    ][1]

    out = set()

    for off in q[
        "samples"
    ][:4]:

        for delta in range(
            -radius,
            radius + 1,
        ):
            if overlaps_anchor(
                delta,
                width,
            ):
                continue

            v = get_token(
                mm,
                off + delta,
                width,
            )

            if v is not None:
                out.add(v)

    return out


def task_topology(p):
    country = p[
        "country"
    ]

    target = p[
        "target"
    ]

    edges = [
        e
        for e in GOLD[country]
        if (
            fi(
                e,
                target,
            )
            and fi(
                e,
                target,
            )["samples"]
        )
    ]

    edges = edges[:220]

    if len(edges) < 10:
        return {
            "score": 0,
            "summary":
                f"gold={len(edges)}",
            "findings": [],
            "reject":
                "too few uniquely mapped MG anchors",
        }

    at_vertex = defaultdict(
        list
    )

    for i, e in enumerate(
        edges
    ):
        (
            ax,
            ay,
            bx,
            by,
        ) = e["geom"]

        at_vertex[
            (ax, ay)
        ].append(i)

        at_vertex[
            (bx, by)
        ].append(i)

    neighbors = set()

    for ids in (
        at_vertex.values()
    ):
        for a in range(
            len(ids)
        ):
            for b in range(
                a + 1,
                len(ids),
            ):
                i = ids[a]
                j = ids[b]

                if i != j:
                    neighbors.add(
                        tuple(
                            sorted(
                                (
                                    i,
                                    j,
                                )
                            )
                        )
                    )

    if len(neighbors) < 4:
        return {
            "score": 0,
            "summary":
                (
                    f"gold={len(edges)} "
                    f"neighbors={len(neighbors)}"
                ),
            "findings": [],
            "reject":
                "too few adjacent unique MG edges",
        }

    tokens = [
        routing_token_set(
            e,
            target,
            p["width"],
            p["radius"],
        )
        for e in edges
    ]

    def shared(pair):
        a, b = pair

        return len(
            tokens[a]
            & tokens[b]
        )

    real_pairs = list(
        neighbors
    )[:1200]

    real_values = [
        shared(x)
        for x in real_pairs
    ]

    # non-neighbor controls
    controls = []

    n = len(edges)

    for shift in (
        7,
        13,
        29,
        47,
    ):
        for i in range(n):
            j = (
                i + shift
            ) % n

            q = tuple(
                sorted(
                    (
                        i,
                        j,
                    )
                )
            )

            if (
                i != j
                and q
                not in neighbors
            ):
                controls.append(q)

            if (
                len(controls)
                >= len(
                    real_pairs
                )
            ):
                break

        if (
            len(controls)
            >= len(
                real_pairs
            )
        ):
            break

    control_values = [
        shared(x)
        for x in controls[
            :len(
                real_pairs
            )
        ]
    ]

    real_any = (
        sum(
            x > 0
            for x in real_values
        )
        / len(real_values)
    )

    control_any = (
        sum(
            x > 0
            for x
            in control_values
        )
        / max(
            len(
                control_values
            ),
            1,
        )
    )

    real_mean = (
        sum(real_values)
        / len(real_values)
    )

    control_mean = (
        sum(
            control_values
        )
        / max(
            len(
                control_values
            ),
            1,
        )
    )

    score = (
        (real_any - control_any)
        * math.sqrt(
            len(real_values)
        )
        * math.log2(
            2
            + real_mean
        )
    )

    evidence = {
        "country":
            country,

        "target":
            target,

        "width":
            p["width"],

        "radius":
            p["radius"],

        "gold_edges":
            len(edges),

        "neighbor_pairs":
            len(
                real_values
            ),

        "control_pairs":
            len(
                control_values
            ),

        "neighbor_any":
            real_any,

        "control_any":
            control_any,

        "neighbor_mean":
            real_mean,

        "control_mean":
            control_mean,
    }

    findings = []

    if score > 0:
        findings.append({
            "key":
                (
                    f"{country}:"
                    f"{target}:"
                    f"w{p['width']}:"
                    f"r{p['radius']}"
                ),

            "score":
                score,

            "evidence":
                evidence,
        })

    return {
        "score":
            score,

        "summary":
            json.dumps(
                evidence,
                separators=(
                    ",",
                    ":",
                ),
            ),

        "findings":
            findings,

        "reject":
            (
                None
                if score >= 1
                else
                "MG-neighbor routing contexts "
                "did not exceed random controls"
            ),
    }


# ============================================================
# WORKER
# ============================================================

def execute_task(row):
    task_id, family, params = (
        row
    )

    p = json.loads(
        params
    )

    try:
        if family == "crosscorr":
            result = task_crosscorr(
                p
            )

        elif family == "alignment":
            result = task_alignment(
                p
            )

        elif family == "topology":
            result = task_topology(
                p
            )

        else:
            raise ValueError(
                family
            )

        return (
            task_id,
            family,
            result,
            None,
        )

    except Exception:
        return (
            task_id,
            family,
            None,
            traceback.format_exc(),
        )


def store_result(
    c,
    item,
):
    (
        task_id,
        family,
        result,
        error,
    ) = item

    if error:
        c.execute(
            """
            UPDATE tasks
            SET status='error',
                finished=?,
                error=?
            WHERE id=?
            """,
            (
                time.time(),
                error,
                task_id,
            ),
        )

        return

    c.execute(
        """
        UPDATE tasks
        SET status='done',
            finished=?,
            score=?,
            summary=?
        WHERE id=?
        """,
        (
            time.time(),

            float(
                result.get(
                    "score",
                    0,
                )
            ),

            result.get(
                "summary",
                "",
            ),

            task_id,
        ),
    )

    for finding in result.get(
        "findings",
        [],
    ):
        # Keep the strongest observation
        # of the same structural hypothesis.
        c.execute(
            """
            INSERT INTO findings(
                task_id,
                family,
                finding_key,
                score,
                evidence,
                created
            )
            VALUES(?,?,?,?,?,?)

            ON CONFLICT(
                family,
                finding_key
            )
            DO UPDATE SET
                task_id =
                    excluded.task_id,
                score =
                    excluded.score,
                evidence =
                    excluded.evidence,
                created =
                    excluded.created

            WHERE
                excluded.score
                > findings.score
            """,
            (
                task_id,

                family,

                finding[
                    "key"
                ],

                float(
                    finding[
                        "score"
                    ]
                ),

                json.dumps(
                    finding[
                        "evidence"
                    ],
                    sort_keys=True,
                ),

                time.time(),
            ),
        )

    reject = result.get(
        "reject"
    )

    if reject:
        c.execute(
            """
            INSERT INTO rejected(
                task_id,
                family,
                reason,
                evidence,
                created
            )
            VALUES(?,?,?,?,?)
            """,
            (
                task_id,
                family,
                reject,
                result.get(
                    "summary",
                    "",
                ),
                time.time(),
            ),
        )


# ============================================================
# ADAPTIVE EXPANSION
# ============================================================

def expand_queue(
    c,
    level,
):
    log(
        "ADAPTIVE EXPANSION",
        level,
    )

    # Wider contexts, but still directly
    # testing RD <-> routing structure.
    filters = [
        (1,2,8),
        (2,4,16),
        (4,8,32),
        (8,16,64),
        (32,128,512),
        (128,1024,4096),
    ]

    for country in (
        "7185",
        "7186",
    ):
        for target in (
            "RT",
            "RL",
        ):
            for width in (
                2,3,4,5,6,7,8
            ):
                for radius in (
                    160,
                    192,
                    256,
                    320,
                ):
                    for (
                        max_mg,
                        max_rd,
                        max_route,
                    ) in filters:

                        for reverse in (
                            0,
                            1,
                        ):
                            for occ_cap in (
                                1,
                                2,
                                4,
                            ):
                                for anchor_cap in (
                                    80,
                                    200,
                                ):

                                    add_task(
                                        c,
                                        "crosscorr",
                                        {
                                            "country":
                                                country,

                                            "target":
                                                target,

                                            "width":
                                                width,

                                            "radius":
                                                radius,

                                            "max_mg":
                                                max_mg,

                                            "max_rd":
                                                max_rd,

                                            "max_route":
                                                max_route,

                                            "reverse":
                                                reverse,

                                            "occ_cap":
                                                occ_cap,

                                            "anchor_cap":
                                                anchor_cap,
                                        },
                                        8,
                                    )

    # Additional routing-topology scales.
    for country in (
        "7185",
        "7186",
    ):
        for target in (
            "RT",
            "RL",
        ):
            for width in (
                2,3,4,5,6,7,8
            ):
                for radius in (
                    160,
                    192,
                    256,
                    320,
                ):
                    add_task(
                        c,
                        "topology",
                        {
                            "country":
                                country,

                            "target":
                                target,

                            "width":
                                width,

                            "radius":
                                radius,
                        },
                        6,
                    )

    c.execute(
        """
        INSERT OR REPLACE
        INTO meta(k,v)
        VALUES('expand_level',?)
        """,
        (
            str(level),
        ),
    )

    c.commit()


# ============================================================
# REPORTING
# ============================================================

def write_report(c):
    counts = dict(
        c.execute(
            """
            SELECT status,COUNT(*)
            FROM tasks
            GROUP BY status
            """
        ).fetchall()
    )

    total = c.execute(
        """
        SELECT COUNT(*)
        FROM tasks
        """
    ).fetchone()[0]

    findings = c.execute(
        """
        SELECT COUNT(*)
        FROM findings
        """
    ).fetchone()[0]

    strong = c.execute(
        """
        SELECT COUNT(*)
        FROM findings
        WHERE score >= 2
        """
    ).fetchone()[0]

    rejected = c.execute(
        """
        SELECT COUNT(*)
        FROM rejected
        """
    ).fetchone()[0]

    top = c.execute(
        """
        SELECT
            family,
            finding_key,
            score,
            evidence
        FROM findings
        ORDER BY score DESC
        LIMIT 40
        """
    ).fetchall()

    # Same structural relation replicated
    # independently on 7185 and 7186.
    replicated = defaultdict(
        list
    )

    for (
        family,
        key,
        score,
        evidence,
    ) in c.execute(
        """
        SELECT
            family,
            finding_key,
            score,
            evidence
        FROM findings
        WHERE family='crosscorr'
          AND score>=1
        """
    ):
        parts = key.split(
            ":",
            1,
        )

        if len(parts) != 2:
            continue

        replicated[
            parts[1]
        ].append(
            (
                parts[0],
                score,
                evidence,
            )
        )

    cross = []

    for key, values in (
        replicated.items()
    ):
        countries = {
            x[0]
            for x in values
        }

        if (
            "7185"
            in countries
            and "7186"
            in countries
        ):
            cross.append(
                (
                    min(
                        x[1]
                        for x
                        in values
                    ),
                    key,
                    values,
                )
            )

    cross.sort(
        reverse=True,
        key=lambda x:
            x[0],
    )

    remaining = max(
        0,
        DEADLINE
        - time.time(),
    )

    with MASTER.open(
        "w",
        encoding="utf-8",
    ) as f:

        print(
            "NCDR BRIDGE24 AUTORESEARCH",
            file=f,
        )

        print(
            "updated:",
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            file=f,
        )

        print(
            "workers:",
            WORKERS,
            file=f,
        )

        print(
            "hours_remaining:",
            remaining / 3600.0,
            file=f,
        )

        print(
            "tasks_total:",
            total,
            file=f,
        )

        print(
            "task_status:",
            counts,
            file=f,
        )

        print(
            "findings:",
            findings,
            file=f,
        )

        print(
            "strong_score_ge_2:",
            strong,
            file=f,
        )

        print(
            "rejected:",
            rejected,
            file=f,
        )

        print(
            "\nTOP FINDINGS",
            file=f,
        )

        for (
            family,
            key,
            score,
            evidence,
        ) in top:

            print(
                f"{score:10.4f} "
                f"{family:12s} "
                f"{key}",
                file=f,
            )

            print(
                "   ",
                evidence,
                file=f,
            )

        print(
            "\nCROSS-DISC REPLICATED "
            "RD->RT/RL STRUCTURES",
            file=f,
        )

        for (
            score,
            key,
            values,
        ) in cross[:40]:

            print(
                f"{score:10.4f} "
                f"{key}",
                file=f,
            )

            print(
                "   ",
                [
                    (
                        x[0],
                        x[1],
                    )
                    for x
                    in values
                ],
                file=f,
            )

    HEARTBEAT.write_text(
        json.dumps(
            {
                "time":
                    time.time(),

                "deadline":
                    DEADLINE,

                "hours_remaining":
                    remaining
                    / 3600.0,

                "tasks":
                    counts,

                "findings":
                    findings,

                "strong":
                    strong,

                "rejected":
                    rejected,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


# ============================================================
# MAIN
# ============================================================

def main():
    log(
        "BRIDGE24 START",
        "hours=",
        HOURS,
        "workers=",
        WORKERS,
    )

    ensure_selective_scan()

    open_files()

    load_entities()

    load_gold_geometry()

    c = init_state()

    seed_tasks(c)

    try:
        row = c.execute(
            """
            SELECT v
            FROM meta
            WHERE k='expand_level'
            """
        ).fetchone()

        expand_level = (
            int(row[0])
            if row
            else 0
        )

    except Exception:
        expand_level = 0

    write_report(c)

    ctx = get_context(
        "fork"
    )

    while (
        time.time()
        < DEADLINE
    ):
        pending = c.execute(
            """
            SELECT
                id,
                family,
                params
            FROM tasks
            WHERE status='pending'
            ORDER BY
                priority DESC,
                id
            LIMIT ?
            """,
            (
                BATCH,
            ),
        ).fetchall()

        if not pending:
            expand_level += 1

            expand_queue(
                c,
                expand_level,
            )

            pending = c.execute(
                """
                SELECT
                    id,
                    family,
                    params
                FROM tasks
                WHERE status='pending'
                ORDER BY
                    priority DESC,
                    id
                LIMIT ?
                """,
                (
                    BATCH,
                ),
            ).fetchall()

        if not pending:
            # No useful new structural
            # hypotheses were generated.
            # Stay alive and retry later;
            # do not manufacture CPU burn.
            log(
                "QUEUE EMPTY;",
                "sleeping 60 sec",
            )

            write_report(c)

            time.sleep(60)

            continue

        ids = [
            x[0]
            for x in pending
        ]

        started = time.time()

        c.executemany(
            """
            UPDATE tasks
            SET status='running',
                started=?
            WHERE id=?
            """,
            [
                (
                    started,
                    task_id,
                )
                for task_id
                in ids
            ],
        )

        c.commit()

        left = (
            DEADLINE
            - time.time()
        ) / 3600.0

        queue_size = c.execute(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE status='pending'
            """
        ).fetchone()[0]

        log(
            "BATCH",
            len(pending),
            "remaining_h=",
            f"{left:.2f}",
            "queue=",
            queue_size,
        )

        pool = ctx.Pool(
            WORKERS
        )

        completed_ids = set()

        try:
            for result in (
                pool.imap_unordered(
                    execute_task,
                    pending,
                    chunksize=1,
                )
            ):
                completed_ids.add(
                    result[0]
                )

                store_result(
                    c,
                    result,
                )

                c.commit()

                if (
                    time.time()
                    >= DEADLINE
                ):
                    break

        finally:
            pool.terminate()
            pool.join()

        # Tasks killed only because
        # deadline/batch termination
        # return to pending for resume.
        remaining_ids = [
            x
            for x in ids
            if x not in completed_ids
        ]

        if remaining_ids:
            c.executemany(
                """
                UPDATE tasks
                SET status='pending',
                    started=NULL
                WHERE id=?
                """,
                [
                    (x,)
                    for x
                    in remaining_ids
                ],
            )

            c.commit()

        write_report(c)

        done = c.execute(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE status='done'
            """
        ).fetchone()[0]

        strong = c.execute(
            """
            SELECT COUNT(*)
            FROM findings
            WHERE score>=2
            """
        ).fetchone()[0]

        rejected = c.execute(
            """
            SELECT COUNT(*)
            FROM rejected
            """
        ).fetchone()[0]

        log(
            "CHECKPOINT",
            "done=",
            done,
            "strong=",
            strong,
            "rejected=",
            rejected,
        )

    write_report(c)

    log(
        "DEADLINE REACHED",
        "MASTER:",
        MASTER,
    )

    c.close()


if __name__ == "__main__":
    main()
