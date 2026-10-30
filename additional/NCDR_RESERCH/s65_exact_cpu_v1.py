from pathlib import Path
from collections import defaultdict, Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from fractions import Fraction
import sqlite3
import pickle
import random
import zlib
import hashlib
import json
import math
import os
import re
import time

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"

DB = OUT / "mg_overnight.sqlite"

ROOT = OUT / "s65_exact_v1"
SAMPLES = ROOT / "samples"
MODELS = ROOT / "models"

ROOT.mkdir(parents=True, exist_ok=True)
SAMPLES.mkdir(parents=True, exist_ok=True)
MODELS.mkdir(parents=True, exist_ok=True)

DATASETS = [
    "7185_MG1",
    "7185_MG2",
    "7185_MG3",
    "7186_MG1",
    "7186_MG2",
    "7186_MG3",
]

WORKERS = int(
    os.environ.get(
        "NCDR_CPU_WORKERS",
        "12",
    )
)

WORKERS = max(
    1,
    min(WORKERS, 14)
)

SAMPLE_N = 12000
TOP_PER_DATASET = 12
MAX_MULTI_KEYS = 48
MIN_MULTI_TOTAL = 25000
MIN_DATASET_COUNT = 800

P_VALUES = [
    1.0,
    1.5,
    2.0,
    3.0,
    4.0,
    8.0,
]


def ckey(
    s60,
    s61,
    s62,
    s66,
):
    return (
        s60 & 255,
        (s61 >> 8) & 255,
        s62 & 255,
        (s62 >> 8) & 255,
        s66,
    )


def keystr(k):
    return "_".join(
        str(x) for x in k
    )


def sample_path(dataset, key):
    return (
        SAMPLES
        / (
            dataset
            + "__"
            + keystr(key)
            + ".pkl"
        )
    )


def model_path(dataset, key):
    return (
        MODELS
        / (
            dataset
            + "__"
            + keystr(key)
            + ".json"
        )
    )


def metric_value(
    dx,
    dy,
    p,
    lam,
):
    x = abs(float(dx))
    y = abs(float(dy))

    if p == 2.0:
        return math.sqrt(
            x*x
            + lam*y*y
        )

    if p == 1.0:
        return (
            x
            + lam*y
        )

    return (
        x**p
        + lam*(y**p)
    ) ** (1.0/p)


def fit_linear(
    rows,
    p,
    lam,
):
    n = 0

    sx = 0.0
    sy = 0.0

    sxx = 0.0
    syy = 0.0
    sxy = 0.0

    for row in rows:
        dx,dy,y = (
            row[0],
            row[1],
            row[2],
        )

        x = metric_value(
            dx,
            dy,
            p,
            lam,
        )

        y = float(y)

        n += 1
        sx += x
        sy += y
        sxx += x*x
        syy += y*y
        sxy += x*y

    if n < 3:
        return None

    fn = float(n)

    vx = (
        sxx
        - sx*sx/fn
    )

    vy = (
        syy
        - sy*sy/fn
    )

    cov = (
        sxy
        - sx*sy/fn
    )

    if (
        vx <= 0.0
        or vy <= 0.0
    ):
        return None

    a = cov / vx

    b = (
        sy
        - a*sx
    ) / fn

    r = (
        cov
        / math.sqrt(vx*vy)
    )

    return {
        "n": n,
        "a": a,
        "b": b,
        "r": r,
    }


def optimize_p(
    rows,
    p,
    seed_lambda=None,
    fine=True,
):
    cache = {}

    def evaluate_exp(e):
        e = max(
            0.0,
            min(
                4.0,
                float(e),
            )
        )

        key = round(
            e,
            10,
        )

        if key in cache:
            return cache[key]

        lam = 2.0**e

        fit = fit_linear(
            rows,
            p,
            lam,
        )

        if fit is None:
            score = -1.0
        else:
            score = abs(
                fit["r"]
            )

        cache[key] = (
            score,
            lam,
            fit,
            e,
        )

        return cache[key]

    candidates = []

    # Full coarse search:
    # lambda 1 .. 16
    for i in range(33):
        e = i / 8.0
        candidates.append(
            evaluate_exp(e)
        )

    if seed_lambda:
        try:
            seed_e = math.log(
                float(seed_lambda),
                2.0,
            )

            for d in (
                -0.50,
                -0.25,
                -0.125,
                0.0,
                0.125,
                0.25,
                0.50,
            ):
                candidates.append(
                    evaluate_exp(
                        seed_e + d
                    )
                )
        except Exception:
            pass

    best = max(
        candidates,
        key=lambda x: x[0],
    )

    if fine:
        best_e = best[3]

        step = 0.125

        for _ in range(4):
            step /= 4.0

            local = []

            for k in range(
                -4,
                5,
            ):
                local.append(
                    evaluate_exp(
                        best_e
                        + k*step
                    )
                )

            candidate = max(
                local,
                key=lambda x: x[0],
            )

            if candidate[0] >= best[0]:
                best = candidate
                best_e = candidate[3]

    return best


def round_value(
    value,
    mode,
):
    if mode == "half_up":
        return int(
            math.floor(
                value + 0.5
            )
        )

    if mode == "floor":
        return int(
            math.floor(value)
        )

    if mode == "ceil":
        return int(
            math.ceil(value)
        )

    if mode == "trunc":
        return int(value)

    raise ValueError(mode)


def integer_metrics(
    rows,
    p,
    lam,
    a,
    b,
    mode,
):
    exact = 0
    within1 = 0
    within2 = 0
    within4 = 0

    abs_sum = 0.0
    sq_sum = 0.0

    continuous_abs = 0.0

    n = 0

    for row in rows:
        dx,dy,y = (
            row[0],
            row[1],
            int(row[2]),
        )

        m = metric_value(
            dx,
            dy,
            p,
            lam,
        )

        raw_pred = (
            a*m + b
        )

        pred = round_value(
            raw_pred,
            mode,
        )

        err = pred - y
        ae = abs(err)

        if ae == 0:
            exact += 1

        if ae <= 1:
            within1 += 1

        if ae <= 2:
            within2 += 1

        if ae <= 4:
            within4 += 1

        abs_sum += ae
        sq_sum += err*err

        continuous_abs += abs(
            raw_pred - y
        )

        n += 1

    if n == 0:
        return {}

    return {
        "n": n,
        "exact": exact,
        "exact_pct":
            100.0*exact/n,
        "within1_pct":
            100.0*within1/n,
        "within2_pct":
            100.0*within2/n,
        "within4_pct":
            100.0*within4/n,
        "mae":
            abs_sum/n,
        "rmse":
            math.sqrt(
                sq_sum/n
            ),
        "continuous_mae":
            continuous_abs/n,
    }


def residual_groups(
    rows,
    model,
    mode,
):
    groups = defaultdict(
        lambda: [
            0,
            0,
            0.0,
            0.0,
        ]
    )

    p = model["p"]
    lam = model["lambda"]
    a = model["a"]
    b = model["b"]

    for row in rows:
        (
            dx,
            dy,
            y,
            s60,
            s61,
            s62,
            s66,
        ) = row

        m = metric_value(
            dx,
            dy,
            p,
            lam,
        )

        pred = round_value(
            a*m+b,
            mode,
        )

        err = int(y) - pred

        # GPU class already contains:
        # s60 low byte,
        # s61 high byte,
        # full s62,
        # s66.
        #
        # Therefore inspect the remaining
        # bytes as possible hidden selector.
        g = (
            (int(s60) >> 8) & 255,
            int(s61) & 255,
        )

        x = groups[g]

        x[0] += 1

        if err == 0:
            x[1] += 1

        x[2] += abs(err)
        x[3] += err

    out = []

    for g, x in groups.items():
        n, exact, sae, se = x

        if n < 50:
            continue

        out.append({
            "s60_hi": g[0],
            "s61_lo": g[1],
            "n": n,
            "exact_pct":
                100.0*exact/n,
            "mae":
                sae/n,
            "mean_signed_error":
                se/n,
        })

    out.sort(
        key=lambda x:
            (-x["n"], x["mae"])
    )

    return out[:30]


def fraction_info(x, maxden):
    try:
        f = Fraction(
            float(x)
        ).limit_denominator(
            maxden
        )

        return {
            "numerator":
                f.numerator,
            "denominator":
                f.denominator,
            "value":
                float(f),
            "error":
                float(x)-float(f),
        }
    except Exception:
        return None


def load_gpu_seeds():
    seeds = {}
    gpu_dir = (
        OUT
        / "gpu24"
        / "parts"
    )

    if not gpu_dir.exists():
        return seeds

    rx = re.compile(
        r"^(718[56]_MG[123])_"
        r"(\d+)_(\d+)_(\d+)_"
        r"(\d+)_(\d+)\.txt$"
    )

    for path in gpu_dir.glob(
        "*.txt"
    ):
        m = rx.match(
            path.name
        )

        if not m:
            continue

        dataset = m.group(1)

        key = tuple(
            int(m.group(i))
            for i in range(2, 7)
        )

        vals = {}

        for line in path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines():

            if "\t" not in line:
                continue

            k, v = line.split(
                "\t",
                1,
            )

            vals[k.strip()] = (
                v.strip()
            )

        try:
            theta = float(
                vals["theta_deg"]
            )

            lam = float(
                vals["lambda"]
            )

            p = float(
                vals["p"]
            )

            r = float(
                vals["best_r"]
            )
        except Exception:
            continue

        # Convert 90-degree solution
        # into canonical axis form.
        if (
            75.0 <= theta <= 105.0
        ):
            lam = 1.0 / lam

        elif not (
            theta <= 15.0
            or theta >= 165.0
        ):
            # Non-axis solution:
            # keep p/r but do not use
            # lambda as optimization seed.
            lam = None

        if lam is not None:
            if lam < 1.0:
                lam = 1.0 / lam

        seeds[
            (dataset, key)
        ] = {
            "p": p,
            "lambda": lam,
            "r": r,
            "theta": theta,
        }

    return seeds


def select_classes(conn, gpu_seeds):
    print(
        time.strftime("%H:%M:%S"),
        "COUNT CLASSES",
        flush=True,
    )

    rows = conn.execute(
        """
        SELECT
            dataset,
            (s60 & 255) AS c0,
            ((s61 >> 8) & 255) AS c1,
            (s62 & 255) AS c2,
            ((s62 >> 8) & 255) AS c3,
            s66 AS c4,
            COUNT(*) AS n
        FROM edges
        GROUP BY
            dataset,
            c0,c1,c2,c3,c4
        """
    ).fetchall()

    counts = {}

    per_dataset = defaultdict(
        list
    )

    per_key = defaultdict(
        dict
    )

    for row in rows:
        dataset = row[0]
        key = tuple(
            int(x)
            for x in row[1:6]
        )
        n = int(row[6])

        counts[
            (dataset, key)
        ] = n

        per_dataset[
            dataset
        ].append(
            (n, key)
        )

        per_key[
            key
        ][dataset] = n

    selected = set()

    # Always include classes
    # already investigated by GPU.
    for (
        dataset,
        key
    ) in gpu_seeds:
        if counts.get(
            (dataset, key),
            0
        ) >= MIN_DATASET_COUNT:

            selected.add(key)

    # Top classes per dataset.
    for dataset in DATASETS:
        top = sorted(
            per_dataset[dataset],
            reverse=True,
        )[:TOP_PER_DATASET]

        for n, key in top:
            if n >= MIN_DATASET_COUNT:
                selected.add(key)

    # Strong classes seen in more
    # than one dataset.
    multi = []

    for key, ds in per_key.items():
        if len(ds) < 2:
            continue

        total = sum(
            ds.values()
        )

        max_n = max(
            ds.values()
        )

        if (
            total >= MIN_MULTI_TOTAL
            and max_n >= MIN_DATASET_COUNT
        ):
            multi.append(
                (
                    total,
                    key,
                )
            )

    multi.sort(
        reverse=True
    )

    for total, key in (
        multi[
            :MAX_MULTI_KEYS
        ]
    ):
        selected.add(key)

    selected = sorted(
        selected
    )

    print(
        "selected class keys:",
        len(selected),
        flush=True,
    )

    return (
        selected,
        counts,
    )


def build_samples(
    conn,
    selected,
    counts,
):
    for dataset in DATASETS:
        wanted = {
            key
            for key in selected
            if counts.get(
                (dataset, key),
                0
            ) >= MIN_DATASET_COUNT
        }

        if not wanted:
            continue

        spec = {
            "dataset": dataset,
            "sample_n": SAMPLE_N,
            "keys": [
                list(k)
                for k in sorted(
                    wanted
                )
            ],
        }

        spec_hash = hashlib.sha256(
            json.dumps(
                spec,
                sort_keys=True,
            ).encode()
        ).hexdigest()

        marker = (
            SAMPLES
            / (
                dataset
                + ".ready.json"
            )
        )

        reuse = False

        if marker.exists():
            try:
                old = json.loads(
                    marker.read_text(
                        encoding="utf-8"
                    )
                )

                if (
                    old.get("spec_hash")
                    == spec_hash
                ):
                    reuse = all(
                        sample_path(
                            dataset,
                            key,
                        ).exists()
                        for key in wanted
                    )
            except Exception:
                pass

        if reuse:
            print(
                time.strftime("%H:%M:%S"),
                dataset,
                "SAMPLES CACHED",
                len(wanted),
                flush=True,
            )
            continue

        print(
            time.strftime("%H:%M:%S"),
            dataset,
            "BUILD SAMPLES",
            len(wanted),
            flush=True,
        )

        reservoirs = {
            key: []
            for key in wanted
        }

        seen = defaultdict(int)

        rng = {}

        for key in wanted:
            seed = zlib.crc32(
                (
                    dataset
                    + ":"
                    + keystr(key)
                ).encode()
            )

            rng[key] = (
                random.Random(seed)
            )

        scanned = 0

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

        for row in rows:
            (
                ax,ay,bx,by,
                s60,s61,s62,
                s65,s66
            ) = row

            scanned += 1

            key = ckey(
                int(s60),
                int(s61),
                int(s62),
                int(s66),
            )

            if key not in wanted:
                continue

            dx = int(bx) - int(ax)
            dy = int(by) - int(ay)

            if (
                dx == 0
                and dy == 0
            ):
                continue

            seen[key] += 1

            item = (
                dx,
                dy,
                int(s65),
                int(s60),
                int(s61),
                int(s62),
                int(s66),
            )

            arr = reservoirs[key]

            if len(arr) < SAMPLE_N:
                arr.append(item)

            else:
                j = rng[
                    key
                ].randrange(
                    seen[key]
                )

                if j < SAMPLE_N:
                    arr[j] = item

        for key, arr in (
            reservoirs.items()
        ):
            with sample_path(
                dataset,
                key,
            ).open("wb") as f:

                pickle.dump(
                    {
                        "dataset":
                            dataset,
                        "key":
                            key,
                        "original_n":
                            counts.get(
                                (
                                    dataset,
                                    key,
                                ),
                                0,
                            ),
                        "seen_valid":
                            seen[key],
                        "rows":
                            arr,
                    },
                    f,
                    protocol=
                        pickle.HIGHEST_PROTOCOL,
                )

        marker.write_text(
            json.dumps(
                {
                    "spec_hash":
                        spec_hash,
                    "scanned":
                        scanned,
                    "keys":
                        len(wanted),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        print(
            "  scanned:",
            scanned,
            "samples:",
            sum(
                len(x)
                for x in
                reservoirs.values()
            ),
            flush=True,
        )


def solve_model(job):
    dataset, key, seed = job

    outpath = model_path(
        dataset,
        key,
    )

    if outpath.exists():
        try:
            return json.loads(
                outpath.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            pass

    spath = sample_path(
        dataset,
        key,
    )

    with spath.open("rb") as f:
        sample = pickle.load(f)

    rows = sample["rows"]

    if len(rows) < 200:
        return None

    seed_lambda = None
    seed_p = None

    if seed:
        seed_lambda = (
            seed.get("lambda")
        )
        seed_p = (
            seed.get("p")
        )

    # First test p=2 because GPU
    # overwhelmingly selected it.
    best2 = optimize_p(
        rows,
        2.0,
        seed_lambda=(
            seed_lambda
            if seed_p == 2.0
            else None
        ),
        fine=True,
    )

    best = (
        best2,
        2.0,
    )

    # Expand to alternate Lp only
    # when p=2 is not already strong
    # or GPU explicitly preferred
    # another p.
    try_alt = (
        best2[0] < 0.985
        or (
            seed_p is not None
            and seed_p != 2.0
        )
    )

    if try_alt:
        for p in P_VALUES:
            if p == 2.0:
                continue

            candidate = optimize_p(
                rows,
                p,
                seed_lambda=(
                    seed_lambda
                    if seed_p == p
                    else None
                ),
                fine=False,
            )

            if (
                candidate[0]
                > best[0][0]
            ):
                best = (
                    candidate,
                    p,
                )

    info, p = best

    score, lam, fit, e = info

    a = fit["a"]
    b = fit["b"]
    r = fit["r"]

    modes = {}

    for mode in (
        "half_up",
        "floor",
        "ceil",
        "trunc",
    ):
        modes[mode] = (
            integer_metrics(
                rows,
                p,
                lam,
                a,
                b,
                mode,
            )
        )

    best_mode = max(
        modes,
        key=lambda mode: (
            modes[mode][
                "exact_pct"
            ],
            modes[mode][
                "within1_pct"
            ],
            -modes[mode][
                "mae"
            ],
        ),
    )

    result = {
        "dataset": dataset,
        "class_key":
            list(key),
        "sample_n":
            len(rows),
        "original_n":
            sample.get(
                "original_n"
            ),
        "p": p,
        "lambda": lam,
        "lambda_log2": e,
        "a": a,
        "b": b,
        "r": r,
        "rounding":
            best_mode,
        "metrics":
            modes[best_mode],
        "all_rounding":
            modes,
        "rational": {
            "lambda":
                fraction_info(
                    lam,
                    512,
                ),
            "sqrt_lambda":
                fraction_info(
                    math.sqrt(lam),
                    512,
                ),
            "a":
                fraction_info(
                    a,
                    2048,
                ),
            "b":
                fraction_info(
                    b,
                    2048,
                ),
        },
        "residual_groups":
            residual_groups(
                rows,
                {
                    "p": p,
                    "lambda": lam,
                    "a": a,
                    "b": b,
                },
                best_mode,
            ),
        "gpu_seed": seed,
    }

    tmp = outpath.with_suffix(
        ".json.tmp"
    )

    tmp.write_text(
        json.dumps(
            result,
            indent=2,
        ),
        encoding="utf-8",
    )

    tmp.replace(outpath)

    return result


def evaluate_external(
    model,
    target_dataset,
    key,
):
    spath = sample_path(
        target_dataset,
        key,
    )

    if not spath.exists():
        return None

    with spath.open("rb") as f:
        sample = pickle.load(f)

    rows = sample["rows"]

    if not rows:
        return None

    metrics = integer_metrics(
        rows,
        model["p"],
        model["lambda"],
        model["a"],
        model["b"],
        model["rounding"],
    )

    # Correlation with same metric,
    # but NO coefficient refit.
    fit_shape = fit_linear(
        rows,
        model["p"],
        model["lambda"],
    )

    return {
        "train_dataset":
            model["dataset"],
        "target_dataset":
            target_dataset,
        "class_key":
            list(key),
        "target_sample_n":
            len(rows),
        "target_original_n":
            sample.get(
                "original_n"
            ),
        "fixed_model_metrics":
            metrics,
        "shape_r":
            (
                fit_shape["r"]
                if fit_shape
                else None
            ),
    }


def lod_reaggregate():
    root = (
        OUT
        / "cpu_lod_v2"
    )

    outpath = (
        ROOT
        / "lod_reaggregate_by_class.txt"
    )

    if not root.exists():
        outpath.write_text(
            "cpu_lod_v2 not found\n",
            encoding="utf-8",
        )
        return

    lines = [
        "NCDR LOD V2 REAGGREGATED BY SOURCE CLASS",
        "",
    ]

    for path in sorted(
        root.glob(
            "*__TO__*.jsonl"
        )
    ):
        stats = defaultdict(
            Counter
        )

        radius = defaultdict(
            Counter
        )

        total = 0

        with path.open(
            "r",
            encoding="utf-8",
            errors="replace",
        ) as f:

            for line in f:
                try:
                    row = json.loads(
                        line
                    )
                except Exception:
                    continue

                sc = row.get(
                    "source_class"
                )

                status = row.get(
                    "status",
                    "unknown",
                )

                stats[sc][
                    status
                ] += 1

                if "radius" in row:
                    radius[sc][
                        row["radius"]
                    ] += 1

                total += 1

        lines.append(
            "="*72
        )

        lines.append(
            path.stem
        )

        lines.append(
            "total: "
            + str(total)
        )

        for sc in sorted(
            stats,
            key=lambda x:
                (
                    x is None,
                    x
                    if x is not None
                    else 999,
                )
        ):
            count = sum(
                stats[sc].values()
            )

            lines.append(
                f"source_class={sc} total={count}"
            )

            for status, n in sorted(
                stats[sc].items()
            ):
                pct = (
                    100.0*n/count
                    if count
                    else 0.0
                )

                lines.append(
                    f"  {status}: "
                    f"{n} "
                    f"({pct:.3f}%)"
                )

            if radius[sc]:
                lines.append(
                    "  radius: "
                    + repr(
                        dict(
                            sorted(
                                radius[
                                    sc
                                ].items()
                            )
                        )
                    )
                )

        lines.append("")

    outpath.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def write_report(
    models,
    cross,
):
    report = (
        ROOT
        / "s65_exact_report.txt"
    )

    with report.open(
        "w",
        encoding="utf-8",
    ) as f:

        print(
            "NCDR S65 EXACT FORMULA RESOLVER V1",
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
            "workers:",
            WORKERS,
            file=f,
        )

        print(
            "models:",
            len(models),
            file=f,
        )

        print(
            file=f
        )

        print(
            "="*100,
            file=f,
        )

        print(
            "PER-DATASET FITS",
            file=f,
        )

        ordered = sorted(
            models,
            key=lambda x: (
                -x["metrics"][
                    "exact_pct"
                ],
                -abs(x["r"]),
            )
        )

        for m in ordered:
            mm = m["metrics"]

            print(
                (
                    f"{m['dataset']} "
                    f"class={m['class_key']} "
                    f"n={m['sample_n']} "
                    f"p={m['p']} "
                    f"lambda={m['lambda']:.12g} "
                    f"a={m['a']:.12g} "
                    f"b={m['b']:.12g} "
                    f"r={m['r']:.9f} "
                    f"round={m['rounding']} "
                    f"exact={mm['exact_pct']:.4f}% "
                    f"±1={mm['within1_pct']:.4f}% "
                    f"±2={mm['within2_pct']:.4f}% "
                    f"MAE={mm['mae']:.6f}"
                ),
                file=f,
            )

            rat = m["rational"]

            print(
                "  rational:",
                json.dumps(
                    rat,
                    sort_keys=True,
                ),
                file=f,
            )

            if m[
                "residual_groups"
            ]:
                print(
                    "  top residual groups:",
                    file=f,
                )

                for g in m[
                    "residual_groups"
                ][:8]:
                    print(
                        "   ",
                        g,
                        file=f,
                    )

        print(
            "\n"
            + "="*100,
            file=f,
        )

        print(
            "CROSS-DATASET VALIDATION — NO REFIT",
            file=f,
        )

        for x in sorted(
            cross,
            key=lambda z: (
                z[
                    "train_dataset"
                ],
                z[
                    "target_dataset"
                ],
                z[
                    "class_key"
                ],
            )
        ):
            mm = x[
                "fixed_model_metrics"
            ]

            print(
                (
                    f"{x['train_dataset']} "
                    f"-> {x['target_dataset']} "
                    f"class={x['class_key']} "
                    f"n={x['target_sample_n']} "
                    f"exact={mm['exact_pct']:.4f}% "
                    f"±1={mm['within1_pct']:.4f}% "
                    f"±2={mm['within2_pct']:.4f}% "
                    f"MAE={mm['mae']:.6f} "
                    f"shape_r={x['shape_r']}"
                ),
                file=f,
            )

    return report


def main():
    print(
        "NCDR S65 EXACT CPU V1"
    )

    print(
        "workers:",
        WORKERS
    )

    print(
        "root:",
        ROOT
    )

    if not DB.exists():
        raise SystemExit(
            f"Missing DB: {DB}"
        )

    lod_reaggregate()

    gpu_seeds = (
        load_gpu_seeds()
    )

    print(
        "GPU seeds:",
        len(gpu_seeds),
        flush=True,
    )

    conn = sqlite3.connect(
        f"file:{DB}?mode=ro",
        uri=True,
        timeout=120,
    )

    selected, counts = (
        select_classes(
            conn,
            gpu_seeds,
        )
    )

    build_samples(
        conn,
        selected,
        counts,
    )

    conn.close()

    jobs = []

    for dataset in DATASETS:
        for key in selected:
            spath = sample_path(
                dataset,
                key,
            )

            if not spath.exists():
                continue

            jobs.append(
                (
                    dataset,
                    key,
                    gpu_seeds.get(
                        (
                            dataset,
                            key,
                        )
                    ),
                )
            )

    print(
        time.strftime("%H:%M:%S"),
        "MODEL JOBS:",
        len(jobs),
        flush=True,
    )

    models = []

    started = time.time()

    with ProcessPoolExecutor(
        max_workers=WORKERS
    ) as ex:

        futs = {
            ex.submit(
                solve_model,
                job,
            ): job
            for job in jobs
        }

        completed = 0

        for fut in as_completed(
            futs
        ):
            job = futs[fut]

            try:
                result = fut.result()
            except Exception as e:
                print(
                    "MODEL ERROR",
                    job,
                    repr(e),
                    flush=True,
                )
                continue

            if result:
                models.append(
                    result
                )

            completed += 1

            elapsed = (
                time.time()
                - started
            )

            rate = (
                completed
                / max(
                    elapsed,
                    0.001,
                )
            )

            if result:
                mm = result[
                    "metrics"
                ]

                print(
                    time.strftime(
                        "%H:%M:%S"
                    ),
                    completed,
                    "/",
                    len(jobs),
                    result["dataset"],
                    result["class_key"],
                    "p",
                    result["p"],
                    "lambda",
                    f"{result['lambda']:.6f}",
                    "R",
                    f"{result['r']:.6f}",
                    "exact",
                    f"{mm['exact_pct']:.2f}%",
                    "±1",
                    f"{mm['within1_pct']:.2f}%",
                    "rate",
                    f"{rate:.2f} jobs/s",
                    flush=True,
                )

    # Reload all checkpointed models
    # so resume runs produce a complete report.
    models = []

    for path in sorted(
        MODELS.glob(
            "*.json"
        )
    ):
        try:
            models.append(
                json.loads(
                    path.read_text(
                        encoding="utf-8"
                    )
                )
            )
        except Exception:
            pass

    cross = []

    for model in models:
        key = tuple(
            model["class_key"]
        )

        for target in DATASETS:
            if (
                target
                == model["dataset"]
            ):
                continue

            result = evaluate_external(
                model,
                target,
                key,
            )

            if result:
                cross.append(
                    result
                )

    (
        ROOT
        / "all_models.json"
    ).write_text(
        json.dumps(
            models,
            indent=2,
        ),
        encoding="utf-8",
    )

    (
        ROOT
        / "cross_validation.json"
    ).write_text(
        json.dumps(
            cross,
            indent=2,
        ),
        encoding="utf-8",
    )

    report = write_report(
        models,
        cross,
    )

    print()
    print(
        "ALL DONE"
    )

    print(
        "REPORT:",
        report
    )

    print(
        "LOD CLASS REPORT:",
        ROOT
        / "lod_reaggregate_by_class.txt"
    )


if __name__ == "__main__":
    main()
