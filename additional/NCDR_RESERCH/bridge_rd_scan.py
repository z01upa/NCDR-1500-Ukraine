from pathlib import Path
from collections import Counter
import mmap
import struct
import csv

SCALE = 5_555_555.0

TESTS = [
    (
        "7185_ITALY",
        Path("/Volumes/CD_7185/DB/I.RD"),
        (6.0, 19.0, 35.0, 48.0),
    ),
    (
        "7186_SCANDINAVIA",
        Path("/Volumes/CD_7186/DB/SC.RD"),
        (4.0, 33.0, 53.0, 73.0),
    ),
]

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"
REPORT = OUT / "bridge_rd_scan.txt"
RUNCSV = OUT / "bridge_rd_24byte_runs.csv"


def limits(box):
    lon0, lon1, lat0, lat1 = box

    return (
        int((lon0 + 30.0) * SCALE),
        int((lon1 + 30.0) * SCALE),
        int(lat0 * SCALE),
        int(lat1 * SCALE),
    )


def decode(be1, be2):
    lon = be1 / SCALE - 30.0
    lat = be2 / SCALE
    return lon, lat


def find_hits(mm, endian, box):
    xmin, xmax, ymin, ymax = limits(box)

    fmt = ">II" if endian == "BE" else "<II"

    hits = set()
    residues24 = Counter()
    residues32 = Counter()

    end = len(mm) - 8

    for off in range(0, end + 1, 4):
        a, b = struct.unpack_from(fmt, mm, off)

        if xmin <= a <= xmax and ymin <= b <= ymax:
            hits.add(off)
            residues24[off % 24] += 1
            residues32[off % 32] += 1

    return hits, residues24, residues32


def find_24_runs(hits):
    runs = []

    for start in sorted(hits):
        if start - 24 in hits:
            continue

        if start + 24 not in hits or start + 48 not in hits:
            continue

        n = 1
        p = start

        while p + 24 in hits:
            p += 24
            n += 1

        runs.append((start, n))

    return runs


rows = []

with REPORT.open("w", encoding="utf-8") as report:

    for label, filename, box in TESTS:

        print("=" * 72, file=report)
        print(label, file=report)
        print("FILE:", filename, file=report)
        print("SIZE:", filename.stat().st_size, file=report)
        print("REGION:", box, file=report)
        print(file=report)

        with filename.open("rb") as fh:
            mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)

            for endian in ("BE", "LE"):

                hits, r24, r32 = find_hits(mm, endian, box)
                runs = find_24_runs(hits)

                print("ENDIAN:", endian, file=report)
                print("REGION COORD PAIRS:", len(hits), file=report)
                print("24-BYTE RUNS >= 3:", len(runs), file=report)

                print(
                    "MOD24:",
                    sorted(r24.items(),
                           key=lambda x: (-x[1], x[0])),
                    file=report,
                )

                print(
                    "MOD32:",
                    sorted(r32.items(),
                           key=lambda x: (-x[1], x[0])),
                    file=report,
                )

                print("TOP RUNS:", file=report)

                for start, count in sorted(
                    runs,
                    key=lambda x: (-x[1], x[0])
                )[:30]:

                    print(
                        f"  offset=0x{start:X} count={count}",
                        file=report,
                    )

                    fmt = ">II" if endian == "BE" else "<II"

                    for i in range(min(count, 5)):
                        off = start + i * 24
                        a, b = struct.unpack_from(fmt, mm, off)
                        lon, lat = decode(a, b)

                        raw = bytes(mm[off:off+24])

                        print(
                            f"    +{i:02d} "
                            f"0x{off:X} "
                            f"{lon:.6f},{lat:.6f} "
                            f"{raw.hex()}",
                            file=report,
                        )

                    for i in range(count):
                        off = start + i * 24
                        a, b = struct.unpack_from(fmt, mm, off)
                        lon, lat = decode(a, b)

                        rows.append({
                            "dataset": label,
                            "endian": endian,
                            "run_start": f"0x{start:X}",
                            "run_count": count,
                            "index": i,
                            "offset": f"0x{off:X}",
                            "longitude": f"{lon:.8f}",
                            "latitude": f"{lat:.8f}",
                            "raw24": bytes(mm[off:off+24]).hex(),
                        })

                print(file=report)

            mm.close()


with RUNCSV.open("w", newline="", encoding="utf-8") as f:
    fields = [
        "dataset",
        "endian",
        "run_start",
        "run_count",
        "index",
        "offset",
        "longitude",
        "latitude",
        "raw24",
    ]

    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)


print("Created:", REPORT)
print("Created:", RUNCSV)
