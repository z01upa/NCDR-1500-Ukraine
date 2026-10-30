from pathlib import Path
from collections import defaultdict, Counter
from multiprocessing import get_context
import sqlite3
import heapq
import math
import json
import os
import time
import gc

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"
ROOT = OUT / "cpu_lod_v2"
ROOT.mkdir(parents=True, exist_ok=True)

DB = OUT / "mg_overnight.sqlite"

PAIRS = [
    ("7185_MG1", "7185_MG2"),
    ("7185_MG2", "7185_MG3"),
    ("7186_MG1", "7186_MG2"),
    ("7186_MG2", "7186_MG3"),
]

WORKERS = int(
    os.environ.get(
        "NCDR_CPU_WORKERS",
        "10"
    )
)

WORKERS = max(1, min(WORKERS, 14))

CELL = 64

ADJ = None
GRID = None
EDGE_ATTR = None


def norm_edge(a, b):
    if a <= b:
        return (a, b)
    return (b, a)


def dist(a, b):
    return math.hypot(
        a[0] - b[0],
        a[1] - b[1],
    )


def point_segment_distance(p, a, b):
    vx = b[0] - a[0]
    vy = b[1] - a[1]

    wx = p[0] - a[0]
    wy = p[1] - a[1]

    vv = vx * vx + vy * vy

    if vv == 0:
        return dist(p, a)

    t = (
        wx * vx + wy * vy
    ) / vv

    if t < 0:
        t = 0.0
    elif t > 1:
        t = 1.0

    qx = a[0] + t * vx
    qy = a[1] + t * vy

    return math.hypot(
        p[0] - qx,
        p[1] - qy,
    )


def build_graph(conn, dataset):
    print(
        time.strftime("%H:%M:%S"),
        "LOAD GRAPH",
        dataset,
        flush=True,
    )

    adj = defaultdict(list)
    attrs = {}

    rows = conn.execute(
        """
        SELECT
            ax,ay,bx,by,
            s60,s61,s62,
            s65,s66
        FROM edges
        WHERE dataset=?
        """,
        (dataset,),
    )

    input_rows = 0

    for (
        ax, ay, bx, by,
        s60, s61, s62,
        s65, s66
    ) in rows:

        input_rows += 1

        a = (int(ax), int(ay))
        b = (int(bx), int(by))

        if a == b:
            continue

        key = norm_edge(a, b)

        if key in attrs:
            continue

        attrs[key] = (
            int(s60),
            int(s61),
            int(s62),
            int(s65),
            int(s66),
        )

        adj[a].append(b)
        adj[b].append(a)

    grid = defaultdict(list)

    for p in adj:
        cell = (
            p[0] // CELL,
            p[1] // CELL,
        )
        grid[cell].append(p)

    print(
        "  rows:",
        input_rows,
        "unique_edges:",
        len(attrs),
        "vertices:",
        len(adj),
        "grid_cells:",
        len(grid),
        flush=True,
    )

    return dict(adj), dict(grid), attrs


def nearest_points(p, radius, limit):
    if radius == 0:
        if p in ADJ:
            return [(0.0, p)]
        return []

    cx = p[0] // CELL
    cy = p[1] // CELL

    cells = (
        radius // CELL
        + 2
    )

    r2 = radius * radius

    found = []

    for gx in range(
        cx - cells,
        cx + cells + 1
    ):
        for gy in range(
            cy - cells,
            cy + cells + 1
        ):
            for q in GRID.get(
                (gx, gy),
                ()
            ):
                dx = q[0] - p[0]
                dy = q[1] - p[1]

                d2 = dx * dx + dy * dy

                if d2 <= r2:
                    found.append(
                        (d2, q)
                    )

    found.sort(
        key=lambda x: x[0]
    )

    out = []

    for d2, q in found[:limit]:
        out.append(
            (
                math.sqrt(d2),
                q,
            )
        )

    return out


def astar(
    start,
    goal,
    src_a,
    src_b,
    max_hops,
    max_expansions,
    stretch_cap,
):
    if start == goal:
        return {
            "path": [start],
            "length": 0.0,
            "expansions": 0,
        }

    chord = max(
        dist(src_a, src_b),
        1.0
    )

    max_length = (
        chord * stretch_cap
        + 512.0
    )

    margin = max(
        256.0,
        chord * 0.40
    )

    minx = min(
        src_a[0],
        src_b[0]
    ) - margin

    maxx = max(
        src_a[0],
        src_b[0]
    ) + margin

    miny = min(
        src_a[1],
        src_b[1]
    ) - margin

    maxy = max(
        src_a[1],
        src_b[1]
    ) + margin

    pq = []

    heapq.heappush(
        pq,
        (
            dist(start, goal),
            0.0,
            0,
            start,
        )
    )

    best = {
        start: 0.0
    }

    prev = {}

    expansions = 0

    while pq:
        f, g, hops, node = (
            heapq.heappop(pq)
        )

        if g != best.get(node):
            continue

        if node == goal:
            path = [node]

            while node in prev:
                node = prev[node]
                path.append(node)

            path.reverse()

            return {
                "path": path,
                "length": g,
                "expansions": expansions,
            }

        if hops >= max_hops:
            continue

        expansions += 1

        if expansions > max_expansions:
            return None

        for nxt in ADJ.get(
            node,
            ()
        ):
            x, y = nxt

            if (
                x < minx
                or x > maxx
                or y < miny
                or y > maxy
            ):
                continue

            step = dist(
                node,
                nxt
            )

            ng = g + step

            if ng > max_length:
                continue

            old = best.get(nxt)

            if (
                old is not None
                and old <= ng
            ):
                continue

            best[nxt] = ng
            prev[nxt] = node

            nf = (
                ng
                + dist(nxt, goal)
            )

            heapq.heappush(
                pq,
                (
                    nf,
                    ng,
                    hops + 1,
                    nxt,
                )
            )

    return None


ROUNDS = [
    # radius, nearest candidates, hops,
    # expansion cap, stretch cap
    (0,   1,  8,  4000,  2.0),
    (0,   1, 32, 20000, 3.0),
    (16,  4, 32, 25000, 3.0),
    (64,  6, 48, 45000, 4.0),
    (192, 8, 64, 70000, 6.0),
]


def path_metrics(
    path,
    src_a,
    src_b,
    length,
):
    chord = max(
        dist(src_a, src_b),
        1.0
    )

    max_dev = 0.0

    classes = Counter()

    for p in path:
        d = point_segment_distance(
            p,
            src_a,
            src_b,
        )

        if d > max_dev:
            max_dev = d

    for a, b in zip(
        path,
        path[1:]
    ):
        attr = EDGE_ATTR.get(
            norm_edge(a, b)
        )

        if attr:
            classes[
                attr[0] & 7
            ] += 1

    return {
        "hops": max(
            0,
            len(path) - 1
        ),
        "path_length": length,
        "source_chord": chord,
        "stretch": (
            length / chord
        ),
        "max_deviation": max_dev,
        "class_hist": dict(
            sorted(classes.items())
        ),
    }


def solve_edge(rec):
    (
        ax, ay,
        bx, by,
        s60, s61, s62,
        s65, s66,
        multiplicity,
    ) = rec

    src_a = (ax, ay)
    src_b = (bx, by)

    source_class = s60 & 7

    base = {
        "a": src_a,
        "b": src_b,
        "source_class": source_class,
        "s60": s60,
        "s61": s61,
        "s62": s62,
        "s65": s65,
        "s66": s66,
        "multiplicity": multiplicity,
        "a_exact_present":
            src_a in ADJ,
        "b_exact_present":
            src_b in ADJ,
    }

    for (
        radius,
        nearest_n,
        max_hops,
        max_expansions,
        stretch_cap,
    ) in ROUNDS:

        ca = nearest_points(
            src_a,
            radius,
            nearest_n,
        )

        cb = nearest_points(
            src_b,
            radius,
            nearest_n,
        )

        if not ca or not cb:
            continue

        pairs = []

        for da, pa in ca:
            for db, pb in cb:
                if pa == pb:
                    continue

                pairs.append(
                    (
                        da + db,
                        da,
                        db,
                        pa,
                        pb,
                    )
                )

        pairs.sort(
            key=lambda x: x[0]
        )

        # Avoid combinatorial explosion.
        pairs = pairs[:10]

        for (
            shift_sum,
            shift_a,
            shift_b,
            pa,
            pb,
        ) in pairs:

            edgekey = norm_edge(
                pa,
                pb
            )

            if edgekey in EDGE_ATTR:
                result = dict(base)

                result.update({
                    "status":
                        "direct_shifted_edge"
                        if radius
                        else "exact_direct",
                    "radius": radius,
                    "shift_a": shift_a,
                    "shift_b": shift_b,
                    "mapped_a": pa,
                    "mapped_b": pb,
                    "hops": 1,
                    "path_length":
                        dist(pa, pb),
                    "source_chord":
                        dist(src_a, src_b),
                    "stretch":
                        dist(pa, pb)
                        / max(
                            dist(
                                src_a,
                                src_b
                            ),
                            1.0
                        ),
                    "max_deviation":
                        max(
                            point_segment_distance(
                                pa,
                                src_a,
                                src_b,
                            ),
                            point_segment_distance(
                                pb,
                                src_a,
                                src_b,
                            ),
                        ),
                    "class_hist": {
                        EDGE_ATTR[
                            edgekey
                        ][0] & 7: 1
                    },
                })

                return result

            found = astar(
                pa,
                pb,
                src_a,
                src_b,
                max_hops,
                max_expansions,
                stretch_cap,
            )

            if found is None:
                continue

            result = dict(base)

            result.update({
                "status":
                    "fuzzy_path"
                    if radius
                    else "exact_endpoint_path",
                "radius": radius,
                "shift_a": shift_a,
                "shift_b": shift_b,
                "mapped_a": pa,
                "mapped_b": pb,
                "expansions":
                    found["expansions"],
            })

            result.update(
                path_metrics(
                    found["path"],
                    src_a,
                    src_b,
                    found["length"],
                )
            )

            return result

    result = dict(base)

    result.update({
        "status": "unresolved",
    })

    return result


def source_missing_edges(
    conn,
    source_dataset,
    dst_edges,
):
    unique = {}

    rows = conn.execute(
        """
        SELECT
            ax,ay,bx,by,
            s60,s61,s62,
            s65,s66
        FROM edges
        WHERE dataset=?
          AND (s60 & 7) IN (3,4)
        """,
        (source_dataset,),
    )

    source_rows = 0
    exact_survive = 0

    for row in rows:
        source_rows += 1

        (
            ax, ay,
            bx, by,
            s60, s61, s62,
            s65, s66
        ) = map(int, row)

        a = (ax, ay)
        b = (bx, by)

        key = norm_edge(a, b)

        if key in dst_edges:
            exact_survive += 1
            continue

        if key in unique:
            old = unique[key]
            old[-1] += 1
            continue

        unique[key] = [
            ax, ay,
            bx, by,
            s60, s61, s62,
            s65, s66,
            1,
        ]

    print(
        "  source class3/4 rows:",
        source_rows,
        "exact survive:",
        exact_survive,
        "missing unique:",
        len(unique),
        flush=True,
    )

    return list(
        unique.values()
    )


def load_completed(path):
    done = set()
    stats = Counter()

    if not path.exists():
        return done, stats

    with path.open(
        "r",
        encoding="utf-8"
    ) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue

            key = (
                tuple(r["a"]),
                tuple(r["b"]),
            )

            done.add(
                norm_edge(*key)
            )

            stats[
                r.get(
                    "status",
                    "unknown"
                )
            ] += 1

    return done, stats


def run_pair(
    source_dataset,
    dest_dataset,
):
    global ADJ, GRID, EDGE_ATTR

    pair_name = (
        source_dataset
        + "__TO__"
        + dest_dataset
    )

    print()
    print("=" * 78)
    print("PAIR", pair_name)
    print("=" * 78)

    conn = sqlite3.connect(
        f"file:{DB}?mode=ro",
        uri=True,
        timeout=120,
    )

    ADJ, GRID, EDGE_ATTR = (
        build_graph(
            conn,
            dest_dataset,
        )
    )

    tasks = source_missing_edges(
        conn,
        source_dataset,
        EDGE_ATTR,
    )

    conn.close()

    result_path = (
        ROOT
        / (
            pair_name
            + ".jsonl"
        )
    )

    completed, stats = (
        load_completed(
            result_path
        )
    )

    if completed:
        print(
            "  resume completed:",
            len(completed),
            flush=True,
        )

    pending = []

    for rec in tasks:
        key = norm_edge(
            (rec[0], rec[1]),
            (rec[2], rec[3]),
        )

        if key not in completed:
            pending.append(rec)

    print(
        "  pending:",
        len(pending),
        "workers:",
        WORKERS,
        flush=True,
    )

    started = time.time()

    if pending:
        ctx = get_context("fork")

        with ctx.Pool(
            WORKERS
        ) as pool:

            with result_path.open(
                "a",
                encoding="utf-8",
                buffering=1,
            ) as out:

                done_count = 0

                for result in (
                    pool.imap_unordered(
                        solve_edge,
                        pending,
                        chunksize=8,
                    )
                ):
                    out.write(
                        json.dumps(
                            result,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )

                    done_count += 1

                    stats[
                        result["status"]
                    ] += 1

                    if (
                        done_count % 100
                        == 0
                    ):
                        elapsed = (
                            time.time()
                            - started
                        )

                        rate = (
                            done_count
                            / max(
                                elapsed,
                                0.001
                            )
                        )

                        print(
                            time.strftime(
                                "%H:%M:%S"
                            ),
                            pair_name,
                            done_count,
                            "/",
                            len(pending),
                            "rate",
                            f"{rate:.2f}/s",
                            dict(stats),
                            flush=True,
                        )

    elapsed = (
        time.time()
        - started
    )

    print(
        "PAIR DONE",
        pair_name,
        f"{elapsed/60:.1f} min",
        dict(stats),
        flush=True,
    )

    summary = {
        "pair": pair_name,
        "workers": WORKERS,
        "task_count":
            len(tasks),
        "status_counts":
            dict(stats),
        "seconds": elapsed,
    }

    (
        ROOT
        / (
            pair_name
            + ".summary.json"
        )
    ).write_text(
        json.dumps(
            summary,
            indent=2,
        ),
        encoding="utf-8",
    )

    ADJ = None
    GRID = None
    EDGE_ATTR = None

    gc.collect()

    return summary


def main():
    if not DB.exists():
        raise SystemExit(
            f"Missing SQLite: {DB}"
        )

    conn = sqlite3.connect(
        f"file:{DB}?mode=ro",
        uri=True,
    )

    cols = [
        r[1]
        for r in conn.execute(
            "PRAGMA table_info(edges)"
        )
    ]

    conn.close()

    required = {
        "dataset",
        "ax", "ay",
        "bx", "by",
        "s60", "s61", "s62",
        "s65", "s66",
    }

    missing = (
        required - set(cols)
    )

    if missing:
        raise SystemExit(
            "Missing columns: "
            + repr(
                sorted(missing)
            )
        )

    print("NCDR LOD FUZZY CPU V2")
    print("workers:", WORKERS)
    print("db:", DB)

    all_summaries = []

    for pair in PAIRS:
        summary = run_pair(
            *pair
        )

        all_summaries.append(
            summary
        )

    report = (
        ROOT
        / "lod_fuzzy_v2_report.txt"
    )

    with report.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "NCDR LOD FUZZY V2\n\n"
        )

        for s in all_summaries:
            f.write(
                s["pair"]
                + "\n"
            )

            f.write(
                "  task_count: "
                + str(
                    s["task_count"]
                )
                + "\n"
            )

            for k, v in sorted(
                s["status_counts"].items()
            ):
                f.write(
                    f"  {k}: {v}\n"
                )

            f.write(
                "  minutes: "
                + f"{s['seconds']/60:.2f}"
                + "\n\n"
            )

    print()
    print("ALL PAIRS DONE")
    print("REPORT:", report)


if __name__ == "__main__":
    main()
