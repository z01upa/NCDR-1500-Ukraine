from pathlib import Path
from collections import defaultdict
import struct

SCALE = 5_555_555.0
OUT = Path.home() / "Desktop" / "NCDR_RESERCH"

SETS = {
    "7185": {
        "root": Path("/Volumes/CD_7185/DB"),
        "files": [
            "IZ.MP0",
            "IZ.FEA",
            "IZ.MG1",
            "IZ.MG2",
            "IZ.MG3",
        ],
        "box": (6.0, 19.0, 35.0, 48.0),
    },

    "7186": {
        "root": Path("/Volumes/CD_7186/DB"),
        "files": [
            "SCZ.MP0",
            "SCZ.FEA",
            "SCZ.MG1",
            "SCZ.MG2",
            "SCZ.MG3",
        ],
        "box": (4.0, 33.0, 53.0, 73.0),
    },
}


def raw_limits(box):
    lon0, lon1, lat0, lat1 = box

    return (
        int((lon0 + 30) * SCALE),
        int((lon1 + 30) * SCALE),
        int(lat0 * SCALE),
        int(lat1 * SCALE),
    )


def decode(raw8):
    x, y = struct.unpack(">II", raw8)

    return (
        x / SCALE - 30,
        y / SCALE,
    )


def collect(path, box):
    data = path.read_bytes()

    xmin, xmax, ymin, ymax = raw_limits(box)

    result = defaultdict(list)

    # Same four phases as our previous scanner.
    for phase in range(4):

        for off in range(phase, len(data) - 7, 4):
            x, y = struct.unpack_from(">II", data, off)

            if xmin <= x <= xmax and ymin <= y <= ymax:
                key = data[off:off+8]

                # We only need a few offsets per identical pair.
                if len(result[key]) < 8:
                    result[key].append(off)

    return data, result


report = OUT / "mg_crossmatch.txt"

with report.open("w", encoding="utf-8") as out:

    for dataset, cfg in SETS.items():

        print("=" * 80, file=out)
        print("DATASET:", dataset, file=out)

        binaries = {}
        tables = {}

        for name in cfg["files"]:
            p = cfg["root"] / name

            print("Loading:", name, file=out)

            data, table = collect(p, cfg["box"])

            binaries[name] = data
            tables[name] = table

            print(
                " ",
                name,
                "unique candidate pairs:",
                len(table),
                file=out,
            )

        print(file=out)
        print("PAIRWISE INTERSECTIONS", file=out)

        names = cfg["files"]

        for i in range(len(names)):
            for j in range(i + 1, len(names)):

                a = names[i]
                b = names[j]

                common = set(tables[a]) & set(tables[b])

                print(
                    f"{a} <-> {b}: {len(common)}",
                    file=out,
                )

        mg1 = names[2]
        mg2 = names[3]
        mg3 = names[4]

        common12 = set(tables[mg1]) & set(tables[mg2])
        common23 = set(tables[mg2]) & set(tables[mg3])
        common13 = set(tables[mg1]) & set(tables[mg3])

        common123 = (
            set(tables[mg1])
            & set(tables[mg2])
            & set(tables[mg3])
        )

        print(file=out)
        print("MG1/MG2:", len(common12), file=out)
        print("MG2/MG3:", len(common23), file=out)
        print("MG1/MG3:", len(common13), file=out)
        print("MG1/MG2/MG3:", len(common123), file=out)

        # Check coordinates also appearing in MP0.
        mp0 = names[0]
        fea = names[1]

        mg_union = (
            set(tables[mg1])
            | set(tables[mg2])
            | set(tables[mg3])
        )

        print(
            "MG union also in MP0:",
            len(mg_union & set(tables[mp0])),
            file=out,
        )

        print(
            "MG union also in FEA:",
            len(mg_union & set(tables[fea])),
            file=out,
        )

        print(file=out)
        print("COMMON MG1/MG2/MG3 EXAMPLES", file=out)

        shown = 0

        for raw8 in sorted(common123):

            lon, lat = decode(raw8)
            x, y = struct.unpack(">II", raw8)

            print("-" * 72, file=out)

            print(
                f"RAW={raw8.hex()} "
                f"X=0x{x:08X} Y=0x{y:08X} "
                f"lon={lon:.8f} lat={lat:.8f}",
                file=out,
            )

            print(
                "low8:",
                f"{x & 0xff:02x}",
                f"{y & 0xff:02x}",
                file=out,
            )

            for name in (mg1, mg2, mg3):

                offs = tables[name][raw8]

                print(
                    name,
                    "offsets:",
                    [f"0x{x:X}" for x in offs],
                    file=out,
                )

                if offs:
                    off = offs[0]
                    data = binaries[name]

                    a = max(0, off - 32)
                    b = min(len(data), off + 40)

                    print(
                        " context:",
                        data[a:b].hex(),
                        file=out,
                    )

            shown += 1

            if shown >= 100:
                break

        print(file=out)

print("Created:", report)
