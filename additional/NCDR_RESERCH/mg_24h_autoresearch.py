from pathlib import Path
from collections import Counter, defaultdict, deque
from concurrent.futures import ProcessPoolExecutor, as_completed
import sqlite3
import struct
import zlib
import math
import json
import os
import time
import traceback
import hashlib
import re
import gzip
import csv

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"
OUT.mkdir(parents=True, exist_ok=True)

ROOT = OUT / "deep24"
ROOT.mkdir(parents=True, exist_ok=True)

STATE = ROOT / "state"
STATE.mkdir(exist_ok=True)

PARTS = ROOT / "parts"
PARTS.mkdir(exist_ok=True)

REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)

ROWS = ROOT / "rows"
ROWS.mkdir(exist_ok=True)

REBUILT = ROOT / "rebuilt"
REBUILT.mkdir(exist_ok=True)

LOG = OUT / "mg_24h.log"
MASTER = OUT / "mg_24h_master_report.txt"
SQLITE = OUT / "mg_overnight.sqlite"

HDR = 0x72

CPU = os.cpu_count() or 4
WORKERS = int(
    os.environ.get(
        "NCDR_WORKERS",
        max(2, CPU - 1)
    )
)

# На Вашому 8C/16T i9 це буде 15.
CHUNK_PAGES = 32

FILES = {
    "7185_MG1": Path("/Volumes/CD_7185/DB/IZ.MG1"),
    "7185_MG2": Path("/Volumes/CD_7185/DB/IZ.MG2"),
    "7185_MG3": Path("/Volumes/CD_7185/DB/IZ.MG3"),

    "7186_MG1": Path("/Volumes/CD_7186/DB/SCZ.MG1"),
    "7186_MG2": Path("/Volumes/CD_7186/DB/SCZ.MG2"),
    "7186_MG3": Path("/Volumes/CD_7186/DB/SCZ.MG3"),
}

LOD_PAIRS = [
    ("7185_MG1", "7185_MG2", {3, 4}),
    ("7185_MG2", "7185_MG3", {4}),
    ("7186_MG1", "7186_MG2", {3, 4}),
    ("7186_MG2", "7186_MG3", {4}),
]


def log(*args):
    line = (
        time.strftime("%Y-%m-%d %H:%M:%S")
        + " "
        + " ".join(str(x) for x in args)
    )

    print(line, flush=True)

    with LOG.open(
        "a",
        encoding="utf-8"
    ) as f:
        f.write(line + "\n")


def save_json(path, obj):
    path = Path(path)

    tmp = path.with_suffix(
        path.suffix + ".tmp"
    )

    with tmp.open(
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            obj,
            f,
            indent=2,
            sort_keys=True,
        )

    tmp.replace(path)


def load_json(path):
    with Path(path).open(
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


def open_db():
    return sqlite3.connect(
        f"file:{SQLITE}?mode=ro",
        uri=True,
        timeout=120,
    )


def read_directory(path):
    with path.open("rb") as f:
        header = f.read(HDR)

        n = struct.unpack_from(
            "<I",
            header,
            0x56,
        )[0]

        table_a = f.read(n * 16)
        table_b = f.read(n * 8)
        table_c = f.read(n * 4)

    pages = []

    for i in range(n):
        bbox = struct.unpack_from(
            "<4i",
            table_a,
            i * 16,
        )

        off, rawlen, packed = (
            struct.unpack_from(
                "<IHH",
                table_b,
                i * 8,
            )
        )

        pages.append(
            (
                i,
                bbox,
                off,
                rawlen,
                packed,
            )
        )

    return (
        header,
        table_a,
        table_b,
        table_c,
        pages,
    )


def get_raw_page(path, rec):
    (
        page,
        bbox,
        off,
        rawlen,
        packed,
    ) = rec

    with path.open("rb") as f:
        f.seek(off)
        comp = f.read(packed)

    raw = zlib.decompress(comp)

    if len(raw) != rawlen:
        raise RuntimeError(
            f"{path.name} page {page}: "
            f"{len(raw)} != {rawlen}"
        )

    return raw


def decode_chains(raw, start, end):
    pos = start
    points = []
    chains = []

    while pos < end:
        q = struct.unpack_from(
            "<H",
            raw,
            pos,
        )[0]

        x, y = struct.unpack_from(
            "<ii",
            raw,
            pos + 2,
        )

        pos += 10

        chain = [len(points)]
        points.append((x, y))

        for _ in range(q):
            dx, dy = struct.unpack_from(
                "<hh",
                raw,
                pos,
            )

            pos += 4

            x += dx
            y += dy

            chain.append(
                len(points)
            )

            points.append(
                (x, y)
            )

        chains.append(chain)

    if pos != end:
        raise RuntimeError(
            f"bad chain consume "
            f"{pos} != {end}"
        )

    return points, chains


def encode_chains(points, chains):
    out = bytearray()

    for chain in chains:
        q = len(chain) - 1

        x, y = points[
            chain[0]
        ]

        out += struct.pack(
            "<Hii",
            q,
            x,
            y,
        )

        px, py = x, y

        for idx in chain[1:]:
            x, y = points[idx]

            dx = x - px
            dy = y - py

            if not (
                -32768 <= dx <= 32767
                and
                -32768 <= dy <= 32767
            ):
                raise RuntimeError(
                    "delta outside s16"
                )

            out += struct.pack(
                "<hh",
                dx,
                dy,
            )

            px, py = x, y

    return bytes(out)


def angle_diff(a, b):
    d = abs(
        (a - b) % 360.0
    )

    return min(
        d,
        360.0 - d,
    )


def bearing(a, b):
    return (
        math.degrees(
            math.atan2(
                b[1] - a[1],
                b[0] - a[0],
            )
        )
        % 360.0
    )


def angle_models(
    current_bearing,
    neighbour_bearing,
):
    ccw = (
        neighbour_bearing
        - current_bearing
    ) % 360.0

    cw = (
        current_bearing
        - neighbour_bearing
    ) % 360.0

    small = min(ccw, cw)

    return {
        "turn_ccw": ccw,
        "turn_cw": cw,
        "turn_small": small,
        "turn_180minus":
            (180.0 - small) % 360.0,

        "neighbor_E_CCW":
            neighbour_bearing,

        "neighbor_E_CW":
            (-neighbour_bearing)
            % 360.0,

        "neighbor_N_CW":
            (90.0 - neighbour_bearing)
            % 360.0,

        "neighbor_N_CCW":
            (neighbour_bearing - 90.0)
            % 360.0,

        "current_E_CCW":
            current_bearing,

        "current_E_CW":
            (-current_bearing)
            % 360.0,
    }


def merge_counter(dst, src):
    for k, v in src.items():
        dst[k] += v


# ============================================================
# PHASE 1
# Exhaustive S11 ↔ incident-edge / turn search
# ============================================================

def phase1_worker(task):
    dataset, start, end = task

    path = FILES[dataset]

    _, _, _, _, pages = (
        read_directory(path)
    )

    stats = Counter()
    samples = []

    csv_path = (
        ROWS
        / f"s11_{dataset}_{start:05d}_{end:05d}.csv.gz"
    )

    with gzip.open(
        csv_path,
        "wt",
        encoding="utf-8",
        newline="",
    ) as gz:

        wr = csv.writer(gz)

        wr.writerow([
            "dataset",
            "page",
            "eid",
            "orientation",
            "endpoint",
            "degree",
            "w_value",
            "angle_value",
            "current_s65",
            "neighbor_eid",
            "neighbor_s65",
            "angle_model",
            "angle_error",
        ])

        for rec in pages[start:end]:
            page = rec[0]

            raw = get_raw_page(
                path,
                rec,
            )

            h = struct.unpack_from(
                "<23H",
                raw,
                0,
            )

            points, _ = decode_chains(
                raw,
                h[0],
                h[2],
            )

            edges = []
            incident = defaultdict(list)

            for eid in range(h[11]):
                r6 = struct.unpack_from(
                    "<7H",
                    raw,
                    h[10] + 14 * eid,
                )

                r11 = struct.unpack_from(
                    "<4H",
                    raw,
                    h[20] + 8 * eid,
                )

                a = r6[3]
                b = r6[4]

                edges.append(
                    (a, b, r6, r11)
                )

                if (
                    a < len(points)
                    and
                    b < len(points)
                    and
                    a != b
                ):
                    incident[a].append(eid)
                    incident[b].append(eid)

            for eid, (
                a,
                b,
                r6,
                r11,
            ) in enumerate(edges):

                if not (
                    a < len(points)
                    and
                    b < len(points)
                    and
                    a != b
                ):
                    continue

                stats["edges"] += 1

                current_s65 = r6[5]

                # Перевіряємо обидві можливі
                # прив'язки S11 до endpoints.
                for orientation in (
                    "01",
                    "10",
                ):
                    if orientation == "01":
                        desc_a = (
                            r11[0],
                            r11[1],
                        )
                        desc_b = (
                            r11[2],
                            r11[3],
                        )
                    else:
                        desc_a = (
                            r11[2],
                            r11[3],
                        )
                        desc_b = (
                            r11[0],
                            r11[1],
                        )

                    for (
                        endpoint_name,
                        vertex,
                        other_vertex,
                        desc,
                    ) in (
                        (
                            "A",
                            a,
                            b,
                            desc_a,
                        ),
                        (
                            "B",
                            b,
                            a,
                            desc_b,
                        ),
                    ):
                        w_value = desc[0]
                        angle_value = desc[1]

                        prefix = (
                            orientation
                            + "."
                            + endpoint_name
                        )

                        degree = len(
                            incident[vertex]
                        )

                        stats[
                            prefix + ".records"
                        ] += 1

                        stats[
                            prefix
                            + ".degree"
                            + str(
                                min(
                                    degree,
                                    9,
                                )
                            )
                        ] += 1

                        if (
                            w_value
                            == current_s65
                        ):
                            stats[
                                prefix
                                + ".w_eq_current_s65"
                            ] += 1

                        neighbours = []

                        for ne in incident[
                            vertex
                        ]:
                            if ne == eid:
                                continue

                            (
                                na,
                                nb,
                                n6,
                                n11,
                            ) = edges[ne]

                            if na == vertex:
                                nv = nb
                            else:
                                nv = na

                            if not (
                                nv < len(points)
                            ):
                                continue

                            neighbours.append(
                                (
                                    ne,
                                    nv,
                                    n6,
                                )
                            )

                        # Чи w0/w2 — field
                        # сусіднього edge?
                        for field_name, pos in (
                            ("s60", 0),
                            ("s61", 1),
                            ("s62", 2),
                            ("s65", 5),
                            ("s66", 6),
                        ):
                            matches = [
                                x
                                for x
                                in neighbours
                                if x[2][pos]
                                == w_value
                            ]

                            if matches:
                                stats[
                                    prefix
                                    + ".w_eq_neighbor_"
                                    + field_name
                                ] += 1

                            if len(matches) == 1:
                                stats[
                                    prefix
                                    + ".unique_neighbor_"
                                    + field_name
                                ] += 1

                        if not (
                            0 <= angle_value <= 359
                        ):
                            continue

                        stats[
                            prefix
                            + ".angle_domain"
                        ] += 1

                        current_b = bearing(
                            points[vertex],
                            points[
                                other_vertex
                            ],
                        )

                        best_any = 999.0
                        best_s65 = 999.0
                        best_info = None

                        for (
                            ne,
                            nv,
                            n6,
                        ) in neighbours:

                            nb = bearing(
                                points[vertex],
                                points[nv],
                            )

                            for (
                                model_name,
                                model_value,
                            ) in angle_models(
                                current_b,
                                nb,
                            ).items():

                                err = angle_diff(
                                    angle_value,
                                    model_value,
                                )

                                if err < best_any:
                                    best_any = err

                                if (
                                    w_value
                                    == n6[5]
                                    and
                                    err < best_s65
                                ):
                                    best_s65 = err

                                    best_info = (
                                        ne,
                                        n6[5],
                                        model_name,
                                        err,
                                    )

                        for tol in (
                            0.5,
                            1.0,
                            2.0,
                            5.0,
                        ):
                            if best_any <= tol:
                                stats[
                                    prefix
                                    + ".angle_any_le"
                                    + str(tol)
                                ] += 1

                            if best_s65 <= tol:
                                stats[
                                    prefix
                                    + ".angle_s65match_le"
                                    + str(tol)
                                ] += 1

                        if best_info is not None:
                            (
                                ne,
                                neighbor_s65,
                                model_name,
                                err,
                            ) = best_info

                            wr.writerow([
                                dataset,
                                page,
                                eid,
                                orientation,
                                endpoint_name,
                                degree,
                                w_value,
                                angle_value,
                                current_s65,
                                ne,
                                neighbor_s65,
                                model_name,
                                f"{err:.6f}",
                            ])

                            if len(samples) < 100:
                                samples.append([
                                    page,
                                    eid,
                                    orientation,
                                    endpoint_name,
                                    degree,
                                    w_value,
                                    angle_value,
                                    current_s65,
                                    ne,
                                    neighbor_s65,
                                    model_name,
                                    err,
                                ])

    return {
        "dataset": dataset,
        "start": start,
        "end": end,
        "stats": dict(stats),
        "samples": samples,
        "rows": str(csv_path),
    }


def phase1():
    name = "01_s11_incident_turn"

    pdir = PARTS / name
    pdir.mkdir(exist_ok=True)

    jobs = []

    for dataset, path in FILES.items():
        _, _, _, _, pages = (
            read_directory(path)
        )

        for start in range(
            0,
            len(pages),
            CHUNK_PAGES,
        ):
            end = min(
                len(pages),
                start + CHUNK_PAGES,
            )

            result_file = (
                pdir
                / f"{dataset}_{start:05d}_{end:05d}.json"
            )

            if not result_file.exists():
                jobs.append(
                    (
                        dataset,
                        start,
                        end,
                    )
                )

    log(
        name,
        "jobs",
        len(jobs),
        "workers",
        WORKERS,
    )

    if jobs:
        with ProcessPoolExecutor(
            max_workers=WORKERS
        ) as pool:

            futures = {
                pool.submit(
                    phase1_worker,
                    job,
                ): job
                for job in jobs
            }

            completed = 0

            for future in as_completed(
                futures
            ):
                result = future.result()

                path = (
                    pdir
                    / (
                        f"{result['dataset']}_"
                        f"{result['start']:05d}_"
                        f"{result['end']:05d}.json"
                    )
                )

                save_json(
                    path,
                    result,
                )

                completed += 1

                if (
                    completed % 10 == 0
                    or
                    completed == len(jobs)
                ):
                    log(
                        name,
                        completed,
                        "/",
                        len(jobs),
                    )

    total = Counter()
    samples = []

    for path in pdir.glob(
        "*.json"
    ):
        result = load_json(path)

        merge_counter(
            total,
            result["stats"],
        )

        samples.extend(
            result.get(
                "samples",
                [],
            )[:3]
        )

    save_json(
        REPORTS / (name + ".json"),
        {
            "stats": dict(total),
            "samples": samples[:500],
        },
    )

    with (
        REPORTS / (name + ".txt")
    ).open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "S11 INCIDENT EDGE / TURN MINER\n\n"
        )

        for key, value in sorted(
            total.items()
        ):
            f.write(
                f"{key}\t{value}\n"
            )

        f.write(
            "\nSAMPLES\n"
        )

        for row in samples[:200]:
            f.write(
                repr(row) + "\n"
            )


# ============================================================
# PHASE 2
# Resolve LOD exceptions with short paths
# ============================================================

def phase2_worker(task):
    src, dst, wanted_classes = task

    conn = open_db()

    dst_rows = list(
        conn.execute(
            """
            SELECT
                ax,ay,bx,by,
                s60,s61,s62,s65,s66
            FROM geom_unique
            WHERE dataset=?
            """,
            (dst,),
        )
    )

    adjacency = defaultdict(list)
    nodes = set()

    for row in dst_rows:
        (
            ax, ay,
            bx, by,
            s60, s61,
            s62, s65,
            s66,
        ) = row

        a = (ax, ay)
        b = (bx, by)

        nodes.add(a)
        nodes.add(b)

        attr = (
            s60,
            s61,
            s62,
            s65,
            s66,
        )

        adjacency[a].append(
            (b, attr)
        )

        adjacency[b].append(
            (a, attr)
        )

    placeholders = ",".join(
        "?"
        for _ in wanted_classes
    )

    query = f"""
        SELECT
            a.ax,a.ay,
            a.bx,a.by,
            a.s60,a.s61,
            a.s62,a.s65,
            a.s66
        FROM geom_unique a

        LEFT JOIN geom_unique b
          ON b.dataset=?
         AND b.ax=a.ax
         AND b.ay=a.ay
         AND b.bx=a.bx
         AND b.by=a.by

        WHERE
            a.dataset=?
            AND b.dataset IS NULL
            AND (a.s60 & 7)
                IN ({placeholders})
    """

    missing = list(
        conn.execute(
            query,
            (
                dst,
                src,
                *sorted(
                    wanted_classes
                ),
            ),
        )
    )

    conn.close()

    stats = Counter()
    examples = []

    csv_path = (
        ROWS
        / f"lod_{src}_to_{dst}.csv.gz"
    )

    with gzip.open(
        csv_path,
        "wt",
        encoding="utf-8",
        newline="",
    ) as gz:

        wr = csv.writer(gz)

        wr.writerow([
            "src",
            "dst",
            "ax",
            "ay",
            "bx",
            "by",
            "low3",
            "A_present",
            "B_present",
            "path_hops",
            "stretch",
            "max_deviation",
        ])

        for row in missing:
            (
                ax, ay,
                bx, by,
                s60, s61,
                s62, s65,
                s66,
            ) = row

            a = (ax, ay)
            b = (bx, by)

            low3 = s60 & 7

            stats["missing"] += 1
            stats[
                "class_" + str(low3)
            ] += 1

            a_present = a in nodes
            b_present = b in nodes

            stats[
                "endpoint_presence_"
                + str(int(a_present))
                + str(int(b_present))
            ] += 1

            found = None

            if (
                a_present
                and
                b_present
            ):
                chord = math.hypot(
                    bx - ax,
                    by - ay,
                )

                queue = deque([
                    (
                        a,
                        [a],
                        0.0,
                    )
                ])

                best_depth = {
                    a: 0
                }

                while (
                    queue
                    and
                    found is None
                ):
                    (
                        current,
                        path_vertices,
                        path_length,
                    ) = queue.popleft()

                    depth = (
                        len(path_vertices)
                        - 1
                    )

                    if depth >= 4:
                        continue

                    for (
                        nxt,
                        attr,
                    ) in adjacency.get(
                        current,
                        (),
                    ):
                        if (
                            len(path_vertices) > 1
                            and
                            nxt
                            == path_vertices[-2]
                        ):
                            continue

                        nd = depth + 1

                        segment_len = (
                            math.hypot(
                                nxt[0]
                                - current[0],
                                nxt[1]
                                - current[1],
                            )
                        )

                        new_length = (
                            path_length
                            + segment_len
                        )

                        if (
                            chord > 0
                            and
                            new_length
                            >
                            chord * 1.8
                            + 50
                        ):
                            continue

                        if (
                            nxt == b
                            and
                            nd >= 2
                        ):
                            found = (
                                path_vertices
                                + [nxt],
                                new_length,
                            )
                            break

                        if nd < 4:
                            old = best_depth.get(
                                nxt
                            )

                            if (
                                old is None
                                or
                                nd < old
                            ):
                                best_depth[
                                    nxt
                                ] = nd

                                queue.append(
                                    (
                                        nxt,
                                        path_vertices
                                        + [nxt],
                                        new_length,
                                    )
                                )

            hops = 0
            stretch = None
            max_deviation = None

            if found:
                vertices, plen = found

                hops = (
                    len(vertices) - 1
                )

                stats[
                    "path_" + str(hops)
                ] += 1

                chord = max(
                    1e-9,
                    math.hypot(
                        bx - ax,
                        by - ay,
                    ),
                )

                stretch = (
                    plen / chord
                )

                dx = bx - ax
                dy = by - ay

                den = (
                    dx * dx
                    + dy * dy
                )

                max_deviation = 0.0

                for x, y in vertices[
                    1:-1
                ]:
                    if den == 0:
                        d = math.hypot(
                            x - ax,
                            y - ay,
                        )
                    else:
                        t = (
                            (
                                (x - ax) * dx
                                +
                                (y - ay) * dy
                            )
                            / den
                        )

                        px = ax + t * dx
                        py = ay + t * dy

                        d = math.hypot(
                            x - px,
                            y - py,
                        )

                    max_deviation = max(
                        max_deviation,
                        d,
                    )

                for tol in (
                    0,
                    1,
                    2,
                    5,
                    10,
                    50,
                    100,
                ):
                    if (
                        max_deviation
                        <= tol
                    ):
                        stats[
                            "path_dev_le_"
                            + str(tol)
                        ] += 1

            wr.writerow([
                src,
                dst,
                ax,
                ay,
                bx,
                by,
                low3,
                int(a_present),
                int(b_present),
                hops,
                (
                    ""
                    if stretch is None
                    else
                    f"{stretch:.8f}"
                ),
                (
                    ""
                    if max_deviation
                    is None
                    else
                    f"{max_deviation:.3f}"
                ),
            ])

            if (
                len(examples) < 300
                and
                (
                    found
                    or
                    not (
                        a_present
                        and
                        b_present
                    )
                )
            ):
                examples.append([
                    a,
                    b,
                    low3,
                    a_present,
                    b_present,
                    hops,
                    stretch,
                    max_deviation,
                ])

    return {
        "src": src,
        "dst": dst,
        "stats": dict(stats),
        "examples": examples,
        "csv": str(csv_path),
    }


def phase2():
    name = "02_lod_exception_resolver"

    jobs = []
    results = []

    for (
        src,
        dst,
        classes,
    ) in LOD_PAIRS:

        cache = (
            PARTS
            / f"lod_{src}_to_{dst}.json"
        )

        if cache.exists():
            results.append(
                load_json(cache)
            )
        else:
            jobs.append(
                (
                    src,
                    dst,
                    classes,
                )
            )

    log(
        name,
        "pairs",
        len(jobs),
    )

    if jobs:
        with ProcessPoolExecutor(
            max_workers=min(
                4,
                len(jobs),
            )
        ) as pool:

            futures = [
                pool.submit(
                    phase2_worker,
                    job,
                )
                for job in jobs
            ]

            for future in as_completed(
                futures
            ):
                result = future.result()

                save_json(
                    PARTS
                    / (
                        "lod_"
                        + result["src"]
                        + "_to_"
                        + result["dst"]
                        + ".json"
                    ),
                    result,
                )

                results.append(
                    result
                )

                log(
                    name,
                    result["src"],
                    "->",
                    result["dst"],
                    "done",
                )

    save_json(
        REPORTS / (name + ".json"),
        results,
    )

    with (
        REPORTS / (name + ".txt")
    ).open(
        "w",
        encoding="utf-8",
    ) as f:

        for result in results:
            f.write(
                "\n"
                + result["src"]
                + " -> "
                + result["dst"]
                + "\n"
            )

            for k, v in sorted(
                result["stats"].items()
            ):
                f.write(
                    f"{k}\t{v}\n"
                )

            f.write(
                "\nEXAMPLES\n"
            )

            for x in result[
                "examples"
            ][:100]:
                f.write(
                    repr(x)
                    + "\n"
                )


# ============================================================
# PHASE 3
# S6[5] exhaustive clean-edge model search
# ============================================================

def solve_normal(rows, feature_funcs):
    m = len(feature_funcs) + 1

    A = [
        [0.0] * m
        for _ in range(m)
    ]

    b = [0.0] * m

    for row in rows:
        xs = [
            fn(row)
            for fn in feature_funcs
        ] + [1.0]

        y = float(
            row[-1]
        )

        for i in range(m):
            b[i] += xs[i] * y

            for j in range(m):
                A[i][j] += (
                    xs[i] * xs[j]
                )

    M = [
        A[i] + [b[i]]
        for i in range(m)
    ]

    for col in range(m):
        pivot = max(
            range(col, m),
            key=lambda r:
                abs(M[r][col])
        )

        if abs(
            M[pivot][col]
        ) < 1e-12:
            return None

        M[col], M[pivot] = (
            M[pivot],
            M[col],
        )

        z = M[col][col]

        for j in range(
            col,
            m + 1,
        ):
            M[col][j] /= z

        for r in range(m):
            if r == col:
                continue

            z = M[r][col]

            for j in range(
                col,
                m + 1,
            ):
                M[r][j] -= (
                    z
                    * M[col][j]
                )

    return [
        M[i][m]
        for i in range(m)
    ]


def phase3_worker(dataset):
    conn = open_db()

    rows = []

    query = """
        SELECT
            ax,ay,bx,by,
            s60,s61,s62,
            s65,s66
        FROM edges
        WHERE dataset=?
    """

    for row in conn.execute(
        query,
        (dataset,),
    ):
        (
            ax, ay,
            bx, by,
            s60, s61,
            s62, s65,
            s66,
        ) = row

        dx = abs(
            bx - ax
        )

        dy = abs(
            by - ay
        )

        euclid = math.hypot(
            dx,
            dy,
        )

        manhattan = dx + dy

        angle_bin = int(
            (
                math.degrees(
                    math.atan2(
                        dy,
                        dx,
                    )
                )
                % 90.0
            )
            // 10.0
        )

        class_key = (
            s60 & 0xFF,
            (s61 >> 8) & 0xFF,
            s62 & 0xFF,
            (s62 >> 8) & 0xFF,
            s66,
        )

        rows.append(
            (
                dx,
                dy,
                euclid,
                manhattan,
                angle_bin,
                class_key,
                s65,
            )
        )

    conn.close()

    groups = defaultdict(list)

    for row in rows:
        (
            dx,
            dy,
            euclid,
            manhattan,
            angle_bin,
            class_key,
            s65,
        ) = row

        groups[
            (
                "class",
                *class_key,
            )
        ].append(row)

        groups[
            (
                "class_angle",
                *class_key,
                angle_bin,
            )
        ].append(row)

    models = {
        "euclid": [
            lambda r: r[2],
        ],

        "manhattan": [
            lambda r: r[3],
        ],

        "dx_dy": [
            lambda r: r[0],
            lambda r: r[1],
        ],

        "euclid_dx_dy": [
            lambda r: r[2],
            lambda r: r[0],
            lambda r: r[1],
        ],
    }

    results = []

    for key, group in groups.items():
        if len(group) < 500:
            continue

        for model_name, funcs in (
            models.items()
        ):
            coeff = solve_normal(
                group,
                funcs,
            )

            if coeff is None:
                continue

            abs_error = 0.0
            sq_error = 0.0
            rel_error = 0.0

            for row in group:
                predicted = (
                    sum(
                        coeff[i]
                        * funcs[i](row)
                        for i
                        in range(
                            len(funcs)
                        )
                    )
                    + coeff[-1]
                )

                actual = row[-1]

                err = (
                    predicted
                    - actual
                )

                abs_error += abs(err)
                sq_error += err * err
                rel_error += (
                    abs(err)
                    / max(
                        1.0,
                        abs(actual),
                    )
                )

            n = len(group)

            results.append({
                "group": list(key),
                "model": model_name,
                "n": n,
                "coeff": coeff,
                "mae":
                    abs_error / n,
                "rmse":
                    math.sqrt(
                        sq_error / n
                    ),
                "mre":
                    rel_error / n,
            })

    results.sort(
        key=lambda x: (
            x["mre"],
            x["rmse"],
        )
    )

    return {
        "dataset": dataset,
        "rows": len(rows),
        "best": results[:1000],
    }


def phase3():
    name = "03_s65_clean_metric_models"

    results = []
    jobs = []

    for dataset in FILES:
        cache = (
            PARTS
            / f"metric_{dataset}.json"
        )

        if cache.exists():
            results.append(
                load_json(cache)
            )
        else:
            jobs.append(dataset)

    log(
        name,
        "datasets",
        len(jobs),
    )

    if jobs:
        with ProcessPoolExecutor(
            max_workers=min(
                WORKERS,
                len(jobs),
            )
        ) as pool:

            futures = {
                pool.submit(
                    phase3_worker,
                    dataset,
                ): dataset
                for dataset in jobs
            }

            for future in as_completed(
                futures
            ):
                result = future.result()

                save_json(
                    PARTS
                    / (
                        "metric_"
                        + result["dataset"]
                        + ".json"
                    ),
                    result,
                )

                results.append(
                    result
                )

                log(
                    name,
                    result["dataset"],
                    "done",
                )

    save_json(
        REPORTS / (name + ".json"),
        results,
    )

    with (
        REPORTS / (name + ".txt")
    ).open(
        "w",
        encoding="utf-8",
    ) as f:

        for result in sorted(
            results,
            key=lambda x:
                x["dataset"],
        ):
            f.write(
                "\nDATASET "
                + result["dataset"]
                + " rows="
                + str(
                    result["rows"]
                )
                + "\n"
            )

            for row in result[
                "best"
            ][:120]:
                f.write(
                    repr(row)
                    + "\n"
                )


# ============================================================
# PHASE 4
# True encoder round-trip
# ============================================================

def phase4_worker(dataset):
    path = FILES[dataset]

    (
        header,
        table_a,
        old_table_b,
        table_c,
        pages,
    ) = read_directory(path)

    compressed = []
    table_b = []

    first_stream = (
        HDR
        + len(pages) * 28
    )

    next_offset = first_stream

    s1_exact = 0
    s3_exact = 0
    raw_exact = 0

    failures = []

    for rec in pages:
        raw = get_raw_page(
            path,
            rec,
        )

        h = struct.unpack_from(
            "<23H",
            raw,
            0,
        )

        points1, chains1 = (
            decode_chains(
                raw,
                h[0],
                h[2],
            )
        )

        points3, chains3 = (
            decode_chains(
                raw,
                h[4],
                h[6],
            )
        )

        encoded1 = encode_chains(
            points1,
            chains1,
        )

        encoded3 = encode_chains(
            points3,
            chains3,
        )

        if (
            encoded1
            ==
            raw[h[0]:h[2]]
        ):
            s1_exact += 1
        else:
            failures.append(
                [rec[0], "S1"]
            )

        if (
            encoded3
            ==
            raw[h[4]:h[6]]
        ):
            s3_exact += 1
        else:
            failures.append(
                [rec[0], "S3"]
            )

        rebuilt_raw = bytearray(
            raw
        )

        rebuilt_raw[
            h[0]:h[2]
        ] = encoded1

        rebuilt_raw[
            h[4]:h[6]
        ] = encoded3

        rebuilt_raw = bytes(
            rebuilt_raw
        )

        if rebuilt_raw == raw:
            raw_exact += 1

        packed = zlib.compress(
            rebuilt_raw,
            9,
        )

        if (
            len(rebuilt_raw) > 65535
            or
            len(packed) > 65535
        ):
            raise RuntimeError(
                "MG page exceeds u16 size"
            )

        table_b.append(
            struct.pack(
                "<IHH",
                next_offset,
                len(rebuilt_raw),
                len(packed),
            )
        )

        compressed.append(
            packed
        )

        next_offset += len(
            packed
        )

    new_header = bytearray(
        header
    )

    struct.pack_into(
        "<I",
        new_header,
        0x5A,
        next_offset
        - first_stream,
    )

    output = (
        REBUILT
        / (
            dataset
            + ".rebuilt"
        )
    )

    tmp = output.with_suffix(
        ".tmp"
    )

    with tmp.open("wb") as f:
        f.write(new_header)
        f.write(table_a)
        f.write(
            b"".join(table_b)
        )
        f.write(table_c)

        for block in compressed:
            f.write(block)

    tmp.replace(output)

    # Verify the newly generated file.
    (
        _,
        _,
        _,
        _,
        generated_pages,
    ) = read_directory(output)

    verified = 0

    for old_rec, new_rec in zip(
        pages,
        generated_pages,
    ):
        old_raw = get_raw_page(
            path,
            old_rec,
        )

        new_raw = get_raw_page(
            output,
            new_rec,
        )

        if old_raw == new_raw:
            verified += 1

    sha = hashlib.sha256()

    with output.open("rb") as f:
        while True:
            b = f.read(
                4 * 1024 * 1024
            )

            if not b:
                break

            sha.update(b)

    return {
        "dataset": dataset,
        "pages": len(pages),
        "s1_exact": s1_exact,
        "s3_exact": s3_exact,
        "raw_exact": raw_exact,
        "verified": verified,
        "output": str(output),
        "size": output.stat().st_size,
        "sha256": sha.hexdigest(),
        "failures": failures[:100],
    }


def phase4():
    name = "04_encoder_roundtrip"

    results = []
    jobs = []

    for dataset in FILES:
        cache = (
            PARTS
            / f"rebuild_{dataset}.json"
        )

        if cache.exists():
            result = load_json(
                cache
            )

            if Path(
                result.get(
                    "output",
                    "",
                )
            ).exists():
                results.append(
                    result
                )
                continue

        jobs.append(dataset)

    log(
        name,
        "datasets",
        len(jobs),
    )

    if jobs:
        with ProcessPoolExecutor(
            max_workers=min(
                6,
                len(jobs),
            )
        ) as pool:

            futures = {
                pool.submit(
                    phase4_worker,
                    dataset,
                ): dataset
                for dataset in jobs
            }

            for future in as_completed(
                futures
            ):
                result = future.result()

                save_json(
                    PARTS
                    / (
                        "rebuild_"
                        + result["dataset"]
                        + ".json"
                    ),
                    result,
                )

                results.append(
                    result
                )

                log(
                    name,
                    result["dataset"],
                    result["verified"],
                    "/",
                    result["pages"],
                )

    save_json(
        REPORTS / (name + ".json"),
        results,
    )

    with (
        REPORTS / (name + ".txt")
    ).open(
        "w",
        encoding="utf-8",
    ) as f:

        for result in sorted(
            results,
            key=lambda x:
                x["dataset"],
        ):
            f.write(
                repr(result)
                + "\n"
            )


# ============================================================
# PHASE 5
# Long transformed bridge scan of all non-MG DB files
# ============================================================

def logical_chunks(
    path,
    chunk_size=4*1024*1024,
):
    with path.open("rb") as f:
        signature = f.read(4)

        f.seek(0)

        if signature == b"zip\x01":
            header = f.read(16)

            (
                block_size,
                total_size,
                max_packed,
            ) = struct.unpack_from(
                "<III",
                header,
                4,
            )

            n = (
                total_size
                + block_size - 1
            ) // block_size

            offsets = struct.unpack(
                "<"
                + "I" * (n + 1),
                f.read(
                    4 * (n + 1)
                ),
            )

            buf = bytearray()

            for i in range(n):
                f.seek(
                    offsets[i]
                )

                comp = f.read(
                    offsets[i+1]
                    - offsets[i]
                )

                raw = zlib.decompress(
                    comp
                )

                buf += raw

                if len(buf) >= chunk_size:
                    yield bytes(buf)
                    buf.clear()

            if buf:
                yield bytes(buf)

        else:
            while True:
                chunk = f.read(
                    chunk_size
                )

                if not chunk:
                    break

                yield chunk


def build_patterns():
    conn = open_db()

    rows = list(
        conn.execute(
            """
            SELECT
                s60,s61,s62,
                s65,s66,
                COUNT(*) AS n
            FROM edges
            GROUP BY
                s60,s61,s62,
                s65,s66
            ORDER BY n DESC
            LIMIT 1024
            """
        )
    )

    conn.close()

    families = defaultdict(set)

    for (
        s60,
        s61,
        s62,
        s65,
        s66,
        n,
    ) in rows:

        families[
            "prefix6_LE"
        ].add(
            struct.pack(
                "<HHH",
                s60,
                s61,
                s62,
            )
        )

        families[
            "prefix6_BE"
        ].add(
            struct.pack(
                ">HHH",
                s60,
                s61,
                s62,
            )
        )

        families[
            "suffix4_LE"
        ].add(
            struct.pack(
                "<HH",
                s65,
                s66,
            )
        )

        families[
            "suffix4_BE"
        ].add(
            struct.pack(
                ">HH",
                s65,
                s66,
            )
        )

        families[
            "stable10_LE"
        ].add(
            struct.pack(
                "<HHHHH",
                s60,
                s61,
                s62,
                s65,
                s66,
            )
        )

        families[
            "stable10_BE"
        ].add(
            struct.pack(
                ">HHHHH",
                s60,
                s61,
                s62,
                s65,
                s66,
            )
        )

        families[
            "class4"
        ].add(
            bytes([
                s60 & 0xFF,
                (s61 >> 8)
                & 0xFF,
                s62 & 0xFF,
                (s62 >> 8)
                & 0xFF,
            ])
        )

    return {
        k: sorted(v)
        for k, v
        in families.items()
    }


def phase5_worker(task):
    label, filename, patterns = (
        task
    )

    path = Path(filename)

    compiled = {}

    max_len = 1

    for name, pats in (
        patterns.items()
    ):
        if not pats:
            continue

        real = re.compile(
            b"|".join(
                re.escape(x)
                for x in pats
            )
        )

        controls = []

        real_set = set(pats)

        for pat in pats:
            control = (
                bytes([
                    pat[0] ^ 0x5A
                ])
                + pat[1:]
            )

            if control not in real_set:
                controls.append(
                    control
                )

        ctrl = None

        if controls:
            ctrl = re.compile(
                b"|".join(
                    re.escape(x)
                    for x in controls
                )
            )

        compiled[name] = (
            real,
            ctrl,
        )

        max_len = max(
            max_len,
            max(
                len(x)
                for x in pats
            ),
        )

    counts = {
        name: [0, 0]
        for name in compiled
    }

    carry = b""
    logical_size = 0

    for chunk in logical_chunks(
        path
    ):
        logical_size += len(
            chunk
        )

        data = carry + chunk

        old_len = len(carry)

        for name, (
            real,
            control,
        ) in compiled.items():

            counts[name][0] += sum(
                1
                for m in real.finditer(
                    data
                )
                if m.end() > old_len
            )

            if control is not None:
                counts[name][1] += sum(
                    1
                    for m
                    in control.finditer(
                        data
                    )
                    if m.end() > old_len
                )

        if max_len > 1:
            carry = data[
                -(max_len - 1):
            ]
        else:
            carry = b""

    result = {
        "label": label,
        "file": str(path),
        "file_size":
            path.stat().st_size,
        "logical_size":
            logical_size,
        "families": {},
    }

    for name, (
        real_count,
        control_count,
    ) in counts.items():

        result[
            "families"
        ][name] = {
            "real": real_count,
            "control":
                control_count,
            "ratio":
                (
                    real_count + 1
                )
                /
                (
                    control_count
                    + 1
                ),
        }

    return result


def phase5():
    name = "05_nonmg_bridge_scan"

    patterns = build_patterns()

    jobs = []
    results = []

    for disc in (
        "CD_7185",
        "CD_7186",
    ):
        db = (
            Path("/Volumes")
            / disc
            / "DB"
        )

        if not db.exists():
            continue

        for path in sorted(
            db.iterdir()
        ):
            if not path.is_file():
                continue

            if path.name.endswith(
                (
                    ".MG1",
                    ".MG2",
                    ".MG3",
                )
            ):
                continue

            label = (
                disc
                + "_"
                + path.name
            )

            safe = re.sub(
                r"[^A-Za-z0-9_.-]+",
                "_",
                label,
            )

            cache = (
                PARTS
                / (
                    "bridge_"
                    + safe
                    + ".json"
                )
            )

            if cache.exists():
                results.append(
                    load_json(cache)
                )
            else:
                jobs.append(
                    (
                        label,
                        str(path),
                        patterns,
                    )
                )

    # Не варто паралельно бити один ISO
    # 15 процесами — тут bottleneck буде I/O.
    bridge_workers = min(
        4,
        WORKERS,
    )

    log(
        name,
        "files",
        len(jobs),
        "workers",
        bridge_workers,
    )

    if jobs:
        with ProcessPoolExecutor(
            max_workers=
                bridge_workers
        ) as pool:

            futures = {
                pool.submit(
                    phase5_worker,
                    job,
                ): job
                for job in jobs
            }

            done = 0

            for future in as_completed(
                futures
            ):
                result = future.result()

                safe = re.sub(
                    r"[^A-Za-z0-9_.-]+",
                    "_",
                    result["label"],
                )

                save_json(
                    PARTS
                    / (
                        "bridge_"
                        + safe
                        + ".json"
                    ),
                    result,
                )

                results.append(
                    result
                )

                done += 1

                log(
                    name,
                    done,
                    "/",
                    len(jobs),
                    result["label"],
                )

    save_json(
        REPORTS / (name + ".json"),
        results,
    )

    with (
        REPORTS / (name + ".txt")
    ).open(
        "w",
        encoding="utf-8",
    ) as f:

        for result in sorted(
            results,
            key=lambda x:
                x["label"],
        ):
            f.write(
                "\n"
                + result["label"]
                + " logical="
                + str(
                    result[
                        "logical_size"
                    ]
                )
                + "\n"
            )

            families = sorted(
                result[
                    "families"
                ].items(),
                key=lambda x:
                    x[1]["ratio"],
                reverse=True,
            )

            for k, v in families:
                f.write(
                    f"{k}: {v}\n"
                )


PHASES = [
    (
        "01_s11_incident_turn",
        phase1,
    ),
    (
        "02_lod_exception_resolver",
        phase2,
    ),
    (
        "03_s65_clean_metric_models",
        phase3,
    ),
    (
        "04_encoder_roundtrip",
        phase4,
    ),
    (
        "05_nonmg_bridge_scan",
        phase5,
    ),
]


def write_master_report():
    with MASTER.open(
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "NCDR 24H AUTORESEARCH\n"
        )

        f.write(
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            + "\n\n"
        )

        f.write(
            f"CPU logical: {CPU}\n"
        )

        f.write(
            f"workers: {WORKERS}\n"
        )

        f.write(
            f"root: {ROOT}\n\n"
        )

        for name, fn in PHASES:
            done = (
                STATE
                / (name + ".done")
            ).exists()

            failed = (
                STATE
                / (name + ".failed")
            ).exists()

            if done:
                status = "DONE"
            elif failed:
                status = "FAILED"
            else:
                status = "PENDING"

            f.write(
                f"{name}: {status}\n"
            )

            report = (
                REPORTS
                / (name + ".txt")
            )

            if report.exists():
                f.write(
                    "  "
                    + str(report)
                    + "\n"
                )

        f.write(
            "\nREBUILT MG FILES\n"
        )

        for path in sorted(
            REBUILT.glob(
                "*.rebuilt"
            )
        ):
            f.write(
                f"{path} "
                f"{path.stat().st_size}\n"
            )


def preflight():
    if not SQLITE.exists():
        raise RuntimeError(
            f"Missing {SQLITE}"
        )

    for name, path in (
        FILES.items()
    ):
        if not path.exists():
            raise RuntimeError(
                "Missing mounted MG: "
                + name
                + " "
                + str(path)
            )

    st = os.statvfs(
        str(OUT)
    )

    free = (
        st.f_bavail
        * st.f_frsize
    )

    log(
        "PRECHECK",
        "logical CPU",
        CPU,
        "workers",
        WORKERS,
        "free GB",
        f"{free / 1e9:.2f}",
    )

    if free < 3_000_000_000:
        raise RuntimeError(
            "Less than 3 GB free"
        )


def main():
    preflight()

    log(
        "START 24H AUTORESEARCH"
    )

    for name, function in PHASES:
        done_file = (
            STATE
            / (name + ".done")
        )

        fail_file = (
            STATE
            / (name + ".failed")
        )

        if done_file.exists():
            log(
                "SKIP",
                name,
                "already done",
            )
            continue

        log(
            "PHASE START",
            name,
        )

        t0 = time.time()

        try:
            function()

            done_file.write_text(
                time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                encoding="utf-8",
            )

            if fail_file.exists():
                fail_file.unlink()

            log(
                "PHASE DONE",
                name,
                f"{(time.time()-t0)/60:.1f} min",
            )

        except Exception:
            error = traceback.format_exc()

            fail_file.write_text(
                error,
                encoding="utf-8",
            )

            log(
                "PHASE FAILED",
                name,
            )

            log(error)

            # ВАЖЛИВО:
            # не зупиняємо весь добовий цикл.
            continue

        finally:
            write_master_report()

    write_master_report()

    log(
        "ALL PHASES FINISHED"
    )

    log(
        "MASTER REPORT:",
        MASTER,
    )


if __name__ == "__main__":
    main()
