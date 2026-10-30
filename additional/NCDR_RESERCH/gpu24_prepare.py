from pathlib import Path
from collections import defaultdict
from array import array
import sqlite3
import struct
import random
import zlib

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"
ROOT = OUT / "gpu24"
DATA = ROOT / "data"
DB = OUT / "mg_overnight.sqlite"

DATASETS = [
    "7185_MG1",
    "7185_MG2",
    "7185_MG3",
    "7186_MG1",
    "7186_MG2",
    "7186_MG3",
]

TOP_CLASSES = 6
SAMPLE = 32768

ROOT.mkdir(parents=True, exist_ok=True)
DATA.mkdir(parents=True, exist_ok=True)

if not DB.exists():
    raise SystemExit(f"ERROR: missing {DB}")

conn = sqlite3.connect(
    f"file:{DB}?mode=ro",
    uri=True,
    timeout=120,
)

manifest = []

for dataset in DATASETS:
    top = conn.execute(
        """
        SELECT
            (s60 & 255) AS c0,
            ((s61 >> 8) & 255) AS c1,
            (s62 & 255) AS c2,
            ((s62 >> 8) & 255) AS c3,
            s66 AS c4,
            COUNT(*) AS n
        FROM edges
        WHERE dataset=?
        GROUP BY c0,c1,c2,c3,c4
        ORDER BY n DESC
        LIMIT ?
        """,
        (dataset, TOP_CLASSES),
    ).fetchall()

    wanted = {
        tuple(row[:5]): int(row[5])
        for row in top
    }

    samples = {
        key: []
        for key in wanted
    }

    seen = defaultdict(int)

    rng = {}

    for key in wanted:
        seed_text = dataset + ":" + ",".join(map(str, key))
        seed = zlib.crc32(seed_text.encode("utf-8"))
        rng[key] = random.Random(seed)

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

    scanned = 0

    for (
        ax,ay,bx,by,
        s60,s61,s62,
        s65,s66
    ) in rows:

        scanned += 1

        key = (
            s60 & 255,
            (s61 >> 8) & 255,
            s62 & 255,
            (s62 >> 8) & 255,
            s66,
        )

        if key not in wanted:
            continue

        dx = float(bx - ax)
        dy = float(by - ay)

        if dx == 0.0 and dy == 0.0:
            continue

        seen[key] += 1

        item = (
            dx,
            dy,
            float(s65),
        )

        arr = samples[key]

        if len(arr) < SAMPLE:
            arr.append(item)
        else:
            j = rng[key].randrange(seen[key])

            if j < SAMPLE:
                arr[j] = item

    print()
    print(dataset, "scanned", scanned)

    for key, rows2 in samples.items():
        if len(rows2) < 1000:
            print(
                "SKIP",
                key,
                "sample",
                len(rows2),
            )
            continue

        maxcoord = max(
            max(abs(dx), abs(dy))
            for dx,dy,_ in rows2
        )

        if maxcoord == 0:
            maxcoord = 1.0

        mean_y = (
            sum(y for _,_,y in rows2)
            / len(rows2)
        )

        dxs = array("f")
        dys = array("f")
        ycs = array("f")

        sumyy = 0.0

        for dx,dy,y in rows2:
            yc = y - mean_y

            dxs.append(dx / maxcoord)
            dys.append(dy / maxcoord)
            ycs.append(yc)

            sumyy += yc * yc

        ident = (
            dataset
            + "_"
            + "_".join(
                str(x)
                for x in key
            )
        )

        binpath = DATA / (ident + ".bin")

        with binpath.open("wb") as f:
            f.write(
                struct.pack(
                    "<I",
                    len(rows2),
                )
            )

            dxs.tofile(f)
            dys.tofile(f)
            ycs.tofile(f)

        manifest.append(
            (
                ident,
                dataset,
                *key,
                len(rows2),
                wanted[key],
                sumyy,
                maxcoord,
                str(binpath),
            )
        )

        print(
            "  READY",
            key,
            "sample",
            len(rows2),
            "original",
            wanted[key],
        )

conn.close()

manifest_path = ROOT / "manifest.tsv"

with manifest_path.open(
    "w",
    encoding="utf-8",
) as f:

    for row in manifest:
        f.write(
            "\t".join(
                str(x)
                for x in row
            )
            + "\n"
        )

print()
print("GPU PREPARE READY")
print("classes:", len(manifest))
print("manifest:", manifest_path)
