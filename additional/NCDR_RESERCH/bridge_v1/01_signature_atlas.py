from pathlib import Path
from collections import defaultdict
from multiprocessing import get_context
import sqlite3
import struct
import mmap
import zlib
import json
import math
import os
import sys
import time

ROOT = Path.home() / "Desktop" / "NCDR_RESERCH"
OUT = ROOT / "bridge_v1"
CACHE = OUT / "cache"

OUT.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)

DB = ROOT / "mg_overnight.sqlite"
BUNDLE = ROOT / "DEEPSEEK_BRIDGE_INPUT"

WORKERS = min(
    int(os.environ.get("NCDR_CPU_WORKERS", "10")),
    12
)

TOP_TUPLES = 8192
SAMPLE_HITS = 24

FIELDS = [
    "s60",
    "s61",
    "s62",
    "s65",
    "s66",
]

PAIRS = []

for i in range(len(FIELDS)):
    for j in range(i + 1, len(FIELDS)):
        PAIRS.append(
            (FIELDS[i], FIELDS[j], i, j)
        )

SIGMASK = {}
LABELS = []


def find_source(key):
    explicit = {
        "7185_RD": [
            BUNDLE / "CD_7185_I.RD",
            Path("/Volumes/CD_7185/DB/I.RD"),
            ROOT / "I.RD",
        ],
        "7185_RT": [
            BUNDLE / "CD_7185_IZ.RT",
            Path("/Volumes/CD_7185/DB/IZ.RT"),
            ROOT / "IZ.RT",
        ],
        "7185_RL": [
            BUNDLE / "CD_7185_IZ.RL",
            Path("/Volumes/CD_7185/DB/IZ.RL"),
            ROOT / "IZ.RL",
        ],
        "7186_RD": [
            BUNDLE / "CD_7186_SC.RD",
            Path("/Volumes/CD_7186/DB/SC.RD"),
            ROOT / "SC.RD",
        ],
        "7186_RT": [
            BUNDLE / "CD_7186_SCZ.RT",
            Path("/Volumes/CD_7186/DB/SCZ.RT"),
            ROOT / "SCZ.RT",
        ],
        "7186_RL": [
            BUNDLE / "CD_7186_SCZ.RL",
            Path("/Volumes/CD_7186/DB/SCZ.RL"),
            ROOT / "SCZ.RL",
        ],
    }

    for p in explicit[key]:
        if p.is_file():
            return p

    basename = {
        "7185_RD": "I.RD",
        "7185_RT": "IZ.RT",
        "7185_RL": "IZ.RL",
        "7186_RD": "SC.RD",
        "7186_RT": "SCZ.RT",
        "7186_RL": "SCZ.RL",
    }[key]

    for p in ROOT.rglob(basename):
        if "bridge_v1/cache" in str(p):
            continue

        if p.is_file():
            return p

    return None


def materialize_logical(key, src):
    with src.open("rb") as f:
        head = f.read(16)

    if head[:4] != b"zip\x01":
        print(
            key,
            "RAW logical file:",
            src,
            src.stat().st_size,
            flush=True,
        )
        return src

    block_size, total, max_comp = struct.unpack_from(
        "<III",
        head,
        4,
    )

    n = (
        total + block_size - 1
    ) // block_size

    dst = CACHE / (key + ".logical")

    if (
        dst.is_file()
        and dst.stat().st_size == total
    ):
        print(
            key,
            "logical cache:",
            dst,
            total,
            flush=True,
        )
        return dst

    print(
        key,
        "DECOMPRESS",
        src,
        "blocks",
        n,
        "logical",
        total,
        flush=True,
    )

    with src.open("rb") as f:
        f.seek(16)

        table = f.read(
            4 * (n + 1)
        )

        offsets = struct.unpack(
            "<" + "I" * (n + 1),
            table,
        )

        tmp = dst.with_suffix(
            ".logical.tmp"
        )

        with tmp.open("wb") as out:
            produced = 0

            for i in range(n):
                a = offsets[i]
                b = offsets[i + 1]

                f.seek(a)
                packed = f.read(b - a)

                raw = zlib.decompress(
                    packed
                )

                expected = min(
                    block_size,
                    total - produced,
                )

                if len(raw) != expected:
                    raise RuntimeError(
                        f"{key} block {i}: "
                        f"{len(raw)} != {expected}"
                    )

                out.write(raw)
                produced += len(raw)

                if i and i % 10000 == 0:
                    print(
                        key,
                        i,
                        "/",
                        n,
                        flush=True,
                    )

        if produced != total:
            raise RuntimeError(
                f"{key}: logical size "
                f"{produced} != {total}"
            )

        tmp.replace(dst)

    print(
        key,
        "logical cache READY:",
        dst,
        flush=True,
    )

    return dst


def top_s6_tuples(conn, country):
    datasets = [
        f"{country}_MG1",
        f"{country}_MG2",
        f"{country}_MG3",
    ]

    placeholders = ",".join(
        "?" for _ in datasets
    )

    sql = f"""
        SELECT
            s60,s61,s62,s65,s66,
            COUNT(*) AS n
        FROM edges
        WHERE dataset IN ({placeholders})
        GROUP BY
            s60,s61,s62,s65,s66
        ORDER BY n DESC
        LIMIT ?
    """

    rows = conn.execute(
        sql,
        datasets + [TOP_TUPLES],
    ).fetchall()

    out = []

    for row in rows:
        vals = tuple(
            int(x) & 0xFFFF
            for x in row[:5]
        )

        out.append(
            (
                vals,
                int(row[5]),
            )
        )

    return out


def native_int_for_bytes(b):
    return int.from_bytes(
        b,
        byteorder=sys.byteorder,
        signed=False,
    )


def pair_pattern(a, b, endian):
    if endian == "BE":
        raw = struct.pack(
            ">HH",
            a & 0xFFFF,
            b & 0xFFFF,
        )
    else:
        raw = struct.pack(
            "<HH",
            a & 0xFFFF,
            b & 0xFFFF,
        )

    return native_int_for_bytes(
        raw
    )


def build_atlas(country, tuples):
    global SIGMASK, LABELS

    local_labels = []

    values_only = [
        x[0]
        for x in tuples
    ]

    for (
        fa,
        fb,
        ia,
        ib,
    ) in PAIRS:

        for endian in (
            "BE",
            "LE",
        ):
            real = set()

            for vals in values_only:
                real.add(
                    pair_pattern(
                        vals[ia],
                        vals[ib],
                        endian,
                    )
                )

            # Matched controls:
            # same marginal values,
            # broken real pairing.
            ctrl = set()

            n = len(values_only)

            shifts = [
                997,
                2003,
                4001,
                6007,
                7919,
            ]

            for shift in shifts:
                if n == 0:
                    break

                shift %= n

                if shift == 0:
                    shift = 1

                for k in range(n):
                    a = values_only[k][ia]
                    b = values_only[
                        (k + shift) % n
                    ][ib]

                    v = pair_pattern(
                        a,
                        b,
                        endian,
                    )

                    if v not in real:
                        ctrl.add(v)

                    if len(ctrl) >= len(real):
                        break

                if len(ctrl) >= len(real):
                    break

            for kind, values in (
                ("real", real),
                ("control", ctrl),
            ):
                label_id = len(LABELS)

                meta = {
                    "id": label_id,
                    "country": country,
                    "field_a": fa,
                    "field_b": fb,
                    "pair": fa + "+" + fb,
                    "endian": endian,
                    "kind": kind,
                    "unique_signatures":
                        len(values),
                }

                LABELS.append(meta)
                local_labels.append(
                    label_id
                )

                bit = 1 << label_id

                for v in values:
                    SIGMASK[v] = (
                        SIGMASK.get(v, 0)
                        | bit
                    )

    return local_labels


def scan_file(task):
    key, country, path = task

    labels_for_country = [
        x["id"]
        for x in LABELS
        if x["country"] == country
    ]

    allowed_mask = 0

    for i in labels_for_country:
        allowed_mask |= (
            1 << i
        )

    counts = [
        0
        for _ in LABELS
    ]

    mods = {
        2: [
            [0] * 2
            for _ in LABELS
        ],
        4: [
            [0] * 4
            for _ in LABELS
        ],
        8: [
            [0] * 8
            for _ in LABELS
        ],
        16: [
            [0] * 16
            for _ in LABELS
        ],
        32: [
            [0] * 32
            for _ in LABELS
        ],
    }

    samples = [
        []
        for _ in LABELS
    ]

    print(
        time.strftime("%H:%M:%S"),
        "SCAN",
        key,
        path,
        path.stat().st_size,
        flush=True,
    )

    with path.open("rb") as f:
        with mmap.mmap(
            f.fileno(),
            0,
            access=mmap.ACCESS_READ,
        ) as mm:

            size = len(mm)

            if size < 4:
                return {
                    "key": key,
                    "country": country,
                    "path": str(path),
                    "size": size,
                    "counts": counts,
                    "mods": mods,
                    "samples": samples,
                }

            mv = memoryview(mm)

            for residue in range(4):
                usable = (
                    (size - residue) // 4
                ) * 4

                if usable < 4:
                    continue

                rawview = mv[
                    residue:
                    residue + usable
                ]

                ints = rawview.cast(
                    "I"
                )

                for idx, value in enumerate(
                    ints
                ):
                    mask = (
                        SIGMASK.get(
                            int(value),
                            0
                        )
                        & allowed_mask
                    )

                    if not mask:
                        continue

                    off = (
                        residue
                        + idx * 4
                    )

                    m = mask

                    while m:
                        lsb = (
                            m & -m
                        )

                        label_id = (
                            lsb.bit_length()
                            - 1
                        )

                        counts[
                            label_id
                        ] += 1

                        for modn in mods:
                            mods[
                                modn
                            ][
                                label_id
                            ][
                                off % modn
                            ] += 1

                        if (
                            len(
                                samples[
                                    label_id
                                ]
                            )
                            < SAMPLE_HITS
                        ):
                            samples[
                                label_id
                            ].append(
                                (
                                    off,
                                    int(value),
                                )
                            )

                        m ^= lsb

                ints.release()
                rawview.release()

            mv.release()

            contexts = {}

            for label_id in labels_for_country:
                arr = []

                for off, value in samples[
                    label_id
                ]:
                    a = max(
                        0,
                        off - 32,
                    )

                    b = min(
                        size,
                        off + 36,
                    )

                    sigbytes = int(
                        value
                    ).to_bytes(
                        4,
                        byteorder=sys.byteorder,
                    )

                    arr.append({
                        "offset": off,
                        "offset_hex":
                            f"0x{off:X}",
                        "signature_hex":
                            sigbytes.hex(),
                        "context_start":
                            a,
                        "context_hex":
                            bytes(
                                mm[a:b]
                            ).hex(),
                    })

                contexts[
                    str(label_id)
                ] = arr

    print(
        time.strftime("%H:%M:%S"),
        "DONE",
        key,
        flush=True,
    )

    return {
        "key": key,
        "country": country,
        "path": str(path),
        "size": path.stat().st_size,
        "counts": counts,
        "mods": mods,
        "samples": contexts,
    }


def best_mod(hist):
    total = sum(hist)

    if total == 0:
        return None

    idx = max(
        range(len(hist)),
        key=lambda x:
            hist[x]
    )

    return {
        "residue": idx,
        "hits": hist[idx],
        "pct":
            100.0
            * hist[idx]
            / total,
    }


def write_report(results):
    rows = []

    by_label = {
        (
            m["country"],
            m["pair"],
            m["endian"],
            m["kind"],
        ): m
        for m in LABELS
    }

    for result in results:
        country = result[
            "country"
        ]

        for fa, fb, ia, ib in PAIRS:
            pair = fa + "+" + fb

            for endian in (
                "BE",
                "LE",
            ):
                real_meta = by_label[
                    (
                        country,
                        pair,
                        endian,
                        "real",
                    )
                ]

                ctrl_meta = by_label[
                    (
                        country,
                        pair,
                        endian,
                        "control",
                    )
                ]

                rid = real_meta[
                    "id"
                ]

                cid = ctrl_meta[
                    "id"
                ]

                rh = result[
                    "counts"
                ][rid]

                ch = result[
                    "counts"
                ][cid]

                ru = max(
                    1,
                    real_meta[
                        "unique_signatures"
                    ]
                )

                cu = max(
                    1,
                    ctrl_meta[
                        "unique_signatures"
                    ]
                )

                rr = rh / ru
                cr = ch / cu

                ratio = (
                    (rr + 1e-12)
                    / (cr + 1e-12)
                )

                row = {
                    "file": result[
                        "key"
                    ],
                    "country": country,
                    "pair": pair,
                    "endian": endian,
                    "real_unique":
                        real_meta[
                            "unique_signatures"
                        ],
                    "control_unique":
                        ctrl_meta[
                            "unique_signatures"
                        ],
                    "real_hits": rh,
                    "control_hits": ch,
                    "real_hits_per_sig":
                        rr,
                    "control_hits_per_sig":
                        cr,
                    "enrichment":
                        ratio,
                    "mod2":
                        best_mod(
                            result[
                                "mods"
                            ][2][rid]
                        ),
                    "mod4":
                        best_mod(
                            result[
                                "mods"
                            ][4][rid]
                        ),
                    "mod8":
                        best_mod(
                            result[
                                "mods"
                            ][8][rid]
                        ),
                    "mod16":
                        best_mod(
                            result[
                                "mods"
                            ][16][rid]
                        ),
                    "mod32":
                        best_mod(
                            result[
                                "mods"
                            ][32][rid]
                        ),
                    "examples":
                        result[
                            "samples"
                        ].get(
                            str(rid),
                            [],
                        ),
                }

                rows.append(row)

    report = OUT / (
        "01_signature_atlas.txt"
    )

    with report.open(
        "w",
        encoding="utf-8",
    ) as f:

        print(
            "NCDR MG -> RD/RT/RL SIGNATURE ATLAS V1",
            file=f,
        )

        print(
            "generated:",
            time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            file=f,
        )

        print(
            "fields:",
            FIELDS,
            file=f,
        )

        print(
            "top stable S6 tuples per country:",
            TOP_TUPLES,
            file=f,
        )

        print(
            file=f
        )

        for filekey in sorted(
            {
                x["file"]
                for x in rows
            }
        ):
            print(
                "=" * 110,
                file=f,
            )

            print(
                filekey,
                file=f,
            )

            print(
                "=" * 110,
                file=f,
            )

            group = [
                x
                for x in rows
                if x["file"]
                == filekey
            ]

            group.sort(
                key=lambda x:
                    x["enrichment"],
                reverse=True,
            )

            for x in group:
                print(
                    (
                        f"{x['pair']:11s} "
                        f"{x['endian']} "
                        f"real={x['real_hits']:10d} "
                        f"ctrl={x['control_hits']:10d} "
                        f"real/sig={x['real_hits_per_sig']:.6f} "
                        f"ctrl/sig={x['control_hits_per_sig']:.6f} "
                        f"ENRICH={x['enrichment']:.3f}"
                    ),
                    file=f,
                )

                print(
                    "  alignment",
                    "mod2=", x["mod2"],
                    "mod4=", x["mod4"],
                    "mod8=", x["mod8"],
                    "mod16=", x["mod16"],
                    "mod32=", x["mod32"],
                    file=f,
                )

                if (
                    x["real_hits"]
                    and x["enrichment"]
                    >= 3.0
                ):
                    for ex in (
                        x["examples"][:5]
                    ):
                        print(
                            "   ",
                            ex,
                            file=f,
                        )

            print(
                file=f
            )

        print(
            "\n"
            + "=" * 110,
            file=f,
        )

        print(
            "GLOBAL TOP SIGNALS",
            file=f,
        )

        print(
            "=" * 110,
            file=f,
        )

        for x in sorted(
            rows,
            key=lambda x:
                x["enrichment"],
            reverse=True,
        )[:40]:

            print(
                (
                    f"{x['file']:8s} "
                    f"{x['pair']:11s} "
                    f"{x['endian']} "
                    f"real={x['real_hits']} "
                    f"ctrl={x['control_hits']} "
                    f"ENRICH={x['enrichment']:.3f}"
                ),
                file=f,
            )

    json_path = OUT / (
        "01_signature_atlas.json"
    )

    json_path.write_text(
        json.dumps(
            {
                "labels": LABELS,
                "rows": rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return report, json_path, rows


def write_sqlite(rows):
    dbpath = OUT / "bridge.sqlite"

    conn = sqlite3.connect(
        dbpath
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS signature_summary (
            file TEXT,
            country TEXT,
            pair TEXT,
            endian TEXT,
            real_unique INTEGER,
            control_unique INTEGER,
            real_hits INTEGER,
            control_hits INTEGER,
            real_hits_per_sig REAL,
            control_hits_per_sig REAL,
            enrichment REAL,
            mod2_json TEXT,
            mod4_json TEXT,
            mod8_json TEXT,
            mod16_json TEXT,
            mod32_json TEXT,
            PRIMARY KEY(
                file,
                country,
                pair,
                endian
            )
        )
    """)

    for x in rows:
        conn.execute("""
            INSERT OR REPLACE INTO
            signature_summary
            VALUES (
                ?,?,?,?,?,?,?,?,?,?,
                ?,?,?,?,?,?
            )
        """, (
            x["file"],
            x["country"],
            x["pair"],
            x["endian"],
            x["real_unique"],
            x["control_unique"],
            x["real_hits"],
            x["control_hits"],
            x["real_hits_per_sig"],
            x["control_hits_per_sig"],
            x["enrichment"],
            json.dumps(
                x["mod2"]
            ),
            json.dumps(
                x["mod4"]
            ),
            json.dumps(
                x["mod8"]
            ),
            json.dumps(
                x["mod16"]
            ),
            json.dumps(
                x["mod32"]
            ),
        ))

    conn.commit()
    conn.close()


def main():
    if not DB.is_file():
        raise SystemExit(
            f"Missing database: {DB}"
        )

    print(
        "NCDR SIGNATURE ATLAS V1"
    )

    print(
        "workers:",
        WORKERS
    )

    print(
        "database:",
        DB
    )

    sources = {}

    for key in (
        "7185_RD",
        "7185_RT",
        "7185_RL",
        "7186_RD",
        "7186_RT",
        "7186_RL",
    ):
        p = find_source(key)

        if p is None:
            raise SystemExit(
                f"Missing source file: {key}"
            )

        sources[key] = p

        print(
            key,
            "source:",
            p,
        )

    logical = {}

    for key, src in sources.items():
        logical[key] = (
            materialize_logical(
                key,
                src,
            )
        )

    conn = sqlite3.connect(
        f"file:{DB}?mode=ro",
        uri=True,
        timeout=120,
    )

    tuples_7185 = top_s6_tuples(
        conn,
        "7185",
    )

    tuples_7186 = top_s6_tuples(
        conn,
        "7186",
    )

    conn.close()

    print(
        "7185 top tuples:",
        len(tuples_7185)
    )

    print(
        "7186 top tuples:",
        len(tuples_7186)
    )

    build_atlas(
        "7185",
        tuples_7185,
    )

    build_atlas(
        "7186",
        tuples_7186,
    )

    print(
        "labels:",
        len(LABELS)
    )

    print(
        "unique 4-byte patterns:",
        len(SIGMASK)
    )

    tasks = []

    for key, path in logical.items():
        country = (
            "7185"
            if key.startswith("7185")
            else "7186"
        )

        tasks.append(
            (
                key,
                country,
                path,
            )
        )

    results = []

    ctx = get_context(
        "fork"
    )

    with ctx.Pool(
        min(
            WORKERS,
            len(tasks),
        )
    ) as pool:

        for result in (
            pool.imap_unordered(
                scan_file,
                tasks,
                chunksize=1,
            )
        ):
            results.append(
                result
            )

    report, js, rows = (
        write_report(
            results
        )
    )

    write_sqlite(
        rows
    )

    print()
    print(
        "SIGNATURE ATLAS COMPLETE"
    )

    print(
        "REPORT:",
        report
    )

    print(
        "JSON:",
        js
    )

    print(
        "SQLITE:",
        OUT / "bridge.sqlite"
    )

    print()
    print(
        "TOP 20:"
    )

    for x in sorted(
        rows,
        key=lambda x:
            x["enrichment"],
        reverse=True,
    )[:20]:

        print(
            x["file"],
            x["pair"],
            x["endian"],
            "real",
            x["real_hits"],
            "ctrl",
            x["control_hits"],
            "enrich",
            f"{x['enrichment']:.2f}",
        )


if __name__ == "__main__":
    main()
