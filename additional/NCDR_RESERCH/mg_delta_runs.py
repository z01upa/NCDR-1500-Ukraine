from pathlib import Path
from collections import defaultdict, Counter
import mmap
import struct

SCALE = 5_555_555.0
OUT = Path.home() / "Desktop" / "NCDR_RESERCH"

SETS = {
    "7185": (
        Path("/Volumes/CD_7185/DB"),
        "IZ.MG1",
        "IZ.MG2",
        (6.0, 19.0, 35.0, 48.0),
    ),
    "7186": (
        Path("/Volumes/CD_7186/DB"),
        "SCZ.MG1",
        "SCZ.MG2",
        (4.0, 33.0, 53.0, 73.0),
    ),
}

MAX_OFFSETS_PER_KEY = 12
TOP_DELTAS = 30
CHUNK = 65536


def coord_limits(box):
    lon0, lon1, lat0, lat1 = box

    return (
        int((lon0 + 30.0) * SCALE),
        int((lon1 + 30.0) * SCALE),
        int(lat0 * SCALE),
        int(lat1 * SCALE),
    )


def collect(mm, box):
    xmin, xmax, ymin, ymax = coord_limits(box)

    result = defaultdict(list)

    for phase in range(4):

        for off in range(phase, len(mm) - 7, 4):

            x, y = struct.unpack_from(">II", mm, off)

            if xmin <= x <= xmax and ymin <= y <= ymax:

                key = bytes(mm[off:off+8])

                if len(result[key]) < MAX_OFFSETS_PER_KEY:
                    result[key].append(off)

    return result


def equal(a, ao, b, bo, n):
    return a[ao:ao+n] == b[bo:bo+n]


def extend_right(a, ao, b, bo):
    maximum = min(len(a) - ao, len(b) - bo)
    done = 0

    while done + CHUNK <= maximum:

        if not equal(a, ao + done, b, bo + done, CHUNK):
            break

        done += CHUNK

    remain = min(CHUNK, maximum - done)

    lo = 0
    hi = remain

    while lo < hi:
        mid = (lo + hi + 1) // 2

        if equal(a, ao + done, b, bo + done, mid):
            lo = mid
        else:
            hi = mid - 1

    return done + lo


def extend_left(a, ao, b, bo):
    maximum = min(ao, bo)
    done = 0

    while done + CHUNK <= maximum:

        aa = ao - done - CHUNK
        bb = bo - done - CHUNK

        if not equal(a, aa, b, bb, CHUNK):
            break

        done += CHUNK

    remain = min(CHUNK, maximum - done)

    lo = 0
    hi = remain

    while lo < hi:
        mid = (lo + hi + 1) // 2

        aa = ao - done - mid
        bb = bo - done - mid

        if equal(a, aa, b, bb, mid):
            lo = mid
        else:
            hi = mid - 1

    return done + lo


report = OUT / "mg_delta_runs.txt"

with report.open("w", encoding="utf-8") as out:

    for dataset, (root, name_a, name_b, box) in SETS.items():

        print("=" * 80, file=out)
        print("DATASET:", dataset, file=out)
        print("A:", name_a, file=out)
        print("B:", name_b, file=out)

        fa = (root / name_a).open("rb")
        fb = (root / name_b).open("rb")

        a = mmap.mmap(fa.fileno(), 0, access=mmap.ACCESS_READ)
        b = mmap.mmap(fb.fileno(), 0, access=mmap.ACCESS_READ)

        try:
            ta = collect(a, box)
            tb = collect(b, box)

            common = set(ta) & set(tb)

            print("COMMON RAW8:", len(common), file=out)

            delta_count = Counter()
            delta_anchors = defaultdict(list)

            for key in common:

                for ao in ta[key]:
                    for bo in tb[key]:

                        delta = bo - ao

                        delta_count[delta] += 1

                        if len(delta_anchors[delta]) < 5000:
                            delta_anchors[delta].append(
                                (ao, bo, key)
                            )

            print(file=out)
            print("TOP DELTAS:", file=out)

            top = delta_count.most_common(TOP_DELTAS)

            for delta, count in top:

                print(
                    f"delta={delta:+d} "
                    f"hex={delta:+#x} "
                    f"anchors={count}",
                    file=out,
                )

            print(file=out)
            print("DEDUPLICATED EXACT RUNS:", file=out)

            all_runs = []

            for delta, anchor_count in top:

                anchors = sorted(
                    delta_anchors[delta],
                    key=lambda x: x[0]
                )

                runs = []

                for ao, bo, key in anchors:

                    inside = False

                    for sa, ea, sb, eb in runs:
                        if sa <= ao < ea:
                            inside = True
                            break

                    if inside:
                        continue

                    left = extend_left(a, ao, b, bo)
                    right = extend_right(a, ao, b, bo)

                    sa = ao - left
                    sb = bo - left

                    ea = ao + right
                    eb = bo + right

                    length = ea - sa

                    if length >= 32:

                        runs.append(
                            (sa, ea, sb, eb)
                        )

                runs.sort()

                # Merge accidental duplicate/overlapping discoveries.
                merged = []

                for run in runs:

                    sa, ea, sb, eb = run

                    if (
                        merged
                        and sa <= merged[-1][1]
                        and sb <= merged[-1][3]
                    ):
                        old = merged[-1]

                        merged[-1] = (
                            min(old[0], sa),
                            max(old[1], ea),
                            min(old[2], sb),
                            max(old[3], eb),
                        )

                    else:
                        merged.append(run)

                if not merged:
                    continue

                print(file=out)
                print(
                    f"DELTA {delta:+d} "
                    f"({delta:+#x}) "
                    f"anchors={anchor_count} "
                    f"runs={len(merged)}",
                    file=out,
                )

                for sa, ea, sb, eb in sorted(
                    merged,
                    key=lambda r: -(r[1] - r[0])
                )[:20]:

                    length = ea - sa

                    print(
                        f"  len={length:,} "
                        f"A=0x{sa:X}..0x{ea:X} "
                        f"B=0x{sb:X}..0x{eb:X}",
                        file=out,
                    )

                    all_runs.append(
                        (length, delta, sa, ea, sb, eb)
                    )

            print(file=out)
            print("LONGEST UNIQUE RUNS:", file=out)

            seen = set()

            for length, delta, sa, ea, sb, eb in sorted(
                all_runs,
                reverse=True
            ):

                sig = (sa, ea, sb, eb)

                if sig in seen:
                    continue

                seen.add(sig)

                print(
                    f"len={length:,} "
                    f"delta={delta:+#x} "
                    f"A=0x{sa:X}..0x{ea:X} "
                    f"B=0x{sb:X}..0x{eb:X}",
                    file=out,
                )

                if len(seen) >= 100:
                    break

        finally:
            a.close()
            b.close()
            fa.close()
            fb.close()

print("Created:", report)
