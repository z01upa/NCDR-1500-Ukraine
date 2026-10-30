from pathlib import Path
from collections import defaultdict, Counter
import mmap
import struct

SCALE = 5_555_555.0
OUT = Path.home() / "Desktop" / "NCDR_RESERCH"

SETS = {
    "7185": (
        Path("/Volumes/CD_7185/DB"),
        ["IZ.MG1", "IZ.MG2", "IZ.MG3"],
        (6.0, 19.0, 35.0, 48.0),
    ),
    "7186": (
        Path("/Volumes/CD_7186/DB"),
        ["SCZ.MG1", "SCZ.MG2", "SCZ.MG3"],
        (4.0, 33.0, 53.0, 73.0),
    ),
}

MAX_HITS_PER_KEY = 8
MAX_EXTEND = 2048


def limits(box):
    lon0, lon1, lat0, lat1 = box
    return (
        int((lon0 + 30) * SCALE),
        int((lon1 + 30) * SCALE),
        int(lat0 * SCALE),
        int(lat1 * SCALE),
    )


def collect(mm, box):
    xmin, xmax, ymin, ymax = limits(box)
    d = defaultdict(list)

    for phase in range(4):
        for off in range(phase, len(mm)-7, 4):
            x, y = struct.unpack_from(">II", mm, off)

            if xmin <= x <= xmax and ymin <= y <= ymax:
                key = bytes(mm[off:off+8])
                if len(d[key]) < MAX_HITS_PER_KEY:
                    d[key].append(off)

    return d


def exact_extent(a, ao, b, bo):
    left = 0
    lim = min(ao, bo, MAX_EXTEND)

    while left < lim:
        if a[ao-left-1] != b[bo-left-1]:
            break
        left += 1

    right = 8
    lim = min(
        len(a)-ao,
        len(b)-bo,
        MAX_EXTEND
    )

    while right < lim:
        if a[ao+right] != b[bo+right]:
            break
        right += 1

    return left, right, left + right


report = OUT / "mg_exact_blocks.txt"

with report.open("w", encoding="utf-8") as out:

    for ds, (root, names, box) in SETS.items():

        print("=" * 80, file=out)
        print("DATASET:", ds, file=out)

        handles = {}
        mmaps = {}
        tables = {}

        try:
            for name in names:
                fh = (root / name).open("rb")
                mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)

                handles[name] = fh
                mmaps[name] = mm
                tables[name] = collect(mm, box)

                print(
                    name,
                    "candidate keys:",
                    len(tables[name]),
                    file=out,
                )

            for ia in range(len(names)):
                for ib in range(ia+1, len(names)):

                    A = names[ia]
                    B = names[ib]

                    common = set(tables[A]) & set(tables[B])

                    results = []

                    for key in common:
                        for ao in tables[A][key]:
                            for bo in tables[B][key]:

                                left, right, total = exact_extent(
                                    mmaps[A], ao,
                                    mmaps[B], bo
                                )

                                results.append(
                                    (total, left, right, key, ao, bo)
                                )

                    results.sort(reverse=True)

                    print(file=out)
                    print("-" * 80, file=out)
                    print(f"{A} <-> {B}", file=out)
                    print("COMMON RAW8:", len(common), file=out)
                    print("COMPARISONS:", len(results), file=out)

                    bins = Counter()

                    for total, *_ in results:
                        if total >= 1024:
                            bins[">=1024"] += 1
                        elif total >= 512:
                            bins["512-1023"] += 1
                        elif total >= 256:
                            bins["256-511"] += 1
                        elif total >= 128:
                            bins["128-255"] += 1
                        elif total >= 64:
                            bins["64-127"] += 1
                        elif total >= 32:
                            bins["32-63"] += 1
                        elif total >= 16:
                            bins["16-31"] += 1
                        else:
                            bins["8-15"] += 1

                    print("LENGTH HISTOGRAM:", dict(bins), file=out)

                    starts_mod = Counter()
                    ends_mod = Counter()

                    for total, left, right, key, ao, bo in results:
                        if total < 32:
                            continue

                        sa = ao-left
                        sb = bo-left
                        ea = ao+right
                        eb = bo+right

                        for mod in (2, 4, 8, 16, 32, 64, 128):
                            starts_mod[(mod, sa % mod, sb % mod)] += 1
                            ends_mod[(mod, ea % mod, eb % mod)] += 1

                    print("TOP EXACT MATCHES:", file=out)

                    for total, left, right, key, ao, bo in results[:50]:

                        sa = ao-left
                        sb = bo-left

                        print(
                            f"len={total:4d} "
                            f"left={left:4d} right={right:4d} "
                            f"raw8={key.hex()} "
                            f"{A}=0x{ao:X} {B}=0x{bo:X} "
                            f"startA=0x{sa:X} startB=0x{sb:X}",
                            file=out,
                        )

                        before = 32
                        after = min(total + 32, 256)

                        aa = max(0, sa-before)
                        ab = min(len(mmaps[A]), sa+after)

                        ba = max(0, sb-before)
                        bb = min(len(mmaps[B]), sb+after)

                        print(
                            " A:",
                            bytes(mmaps[A][aa:ab]).hex(),
                            file=out,
                        )

                        print(
                            " B:",
                            bytes(mmaps[B][ba:bb]).hex(),
                            file=out,
                        )

                    print("START MOD ALIGNMENT TOP:", file=out)

                    for k, n in starts_mod.most_common(30):
                        print(k, n, file=out)

                    print("END MOD ALIGNMENT TOP:", file=out)

                    for k, n in ends_mod.most_common(30):
                        print(k, n, file=out)

        finally:
            for mm in mmaps.values():
                mm.close()

            for fh in handles.values():
                fh.close()

print("Created:", report)
