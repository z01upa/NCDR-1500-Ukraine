from pathlib import Path
from collections import Counter
import struct
import zlib

ROOT = Path("/Volumes/CD_7185/DB")
OUT = Path.home() / "Desktop" / "NCDR_RESERCH"

A = (ROOT / "IZ.MG1").read_bytes()
B = (ROOT / "IZ.MG2").read_bytes()

TESTS = {
    "PAIR_21412": {
        "A": (0x1FFE6D0, 0x20019A8),
        "B": (0x131FF8C, 0x1323264),
    },
    "PAIR_18804": {
        "A": (0x9B02D1, 0x9B2F2C),
        "B": (0x57879F, 0x57B3FA),
    },
}


def unpack(data, start, end):
    raw = zlib.decompress(data[start:end])
    return raw


def diff_runs(a, b):
    assert len(a) == len(b)

    runs = []
    i = 0

    while i < len(a):
        if a[i] == b[i]:
            i += 1
            continue

        start = i

        while i < len(a) and a[i] != b[i]:
            i += 1

        runs.append((start, i))

    return runs


def merge_nearby(runs, gap=16):
    if not runs:
        return []

    out = [list(runs[0])]

    for s, e in runs[1:]:
        if s - out[-1][1] <= gap:
            out[-1][1] = e
        else:
            out.append([s, e])

    return [tuple(x) for x in out]


def le16_words(data, start, end):
    start &= ~1
    end = min(len(data), (end + 1) & ~1)

    result = []

    for off in range(start, end - 1, 2):
        v = struct.unpack_from("<H", data, off)[0]
        result.append((off, v))

    return result


report = OUT / "mg_zlib_raw_diff.txt"

with report.open("w", encoding="utf-8") as out:

    for name, t in TESTS.items():

        print("=" * 80, file=out)
        print("TEST:", name, file=out)

        ra = unpack(A, *t["A"])
        rb = unpack(B, *t["B"])

        print("RAW A:", len(ra), file=out)
        print("RAW B:", len(rb), file=out)
        print("SAME LENGTH:", len(ra) == len(rb), file=out)

        if len(ra) != len(rb):
            continue

        different = [
            i for i, (x, y) in enumerate(zip(ra, rb))
            if x != y
        ]

        runs = diff_runs(ra, rb)
        windows = merge_nearby(runs, gap=16)

        print("DIFFERENT BYTES:", len(different), file=out)
        print("EXACT DIFF RUNS:", len(runs), file=out)
        print("MERGED WINDOWS <=16 gap:", len(windows), file=out)

        print(
            "DIFF START MOD2:",
            Counter(s % 2 for s, e in runs),
            file=out,
        )

        print(
            "DIFF START MOD4:",
            Counter(s % 4 for s, e in runs),
            file=out,
        )

        print(
            "DIFF START MOD8:",
            Counter(s % 8 for s, e in runs),
            file=out,
        )

        print(
            "DIFF START MOD16:",
            Counter(s % 16 for s, e in runs),
            file=out,
        )

        print(file=out)
        print("EXACT DIFF RUNS:", file=out)

        for n, (s, e) in enumerate(runs[:300], 1):

            print(
                f"#{n:03d} "
                f"0x{s:04X}..0x{e:04X} "
                f"len={e-s}",
                file=out,
            )

            print(
                " A:",
                ra[s:e].hex(),
                file=out,
            )

            print(
                " B:",
                rb[s:e].hex(),
                file=out,
            )

        print(file=out)
        print("MERGED DIFF WINDOWS:", file=out)

        for n, (s, e) in enumerate(windows[:100], 1):

            lo = max(0, s - 24)
            hi = min(len(ra), e + 24)

            print("-" * 72, file=out)

            print(
                f"WINDOW #{n} "
                f"diff=0x{s:X}..0x{e:X} "
                f"context=0x{lo:X}..0x{hi:X}",
                file=out,
            )

            print(
                "A HEX:",
                ra[lo:hi].hex(),
                file=out,
            )

            print(
                "B HEX:",
                rb[lo:hi].hex(),
                file=out,
            )

            print("LE16:", file=out)

            wa = dict(le16_words(ra, lo, hi))
            wb = dict(le16_words(rb, lo, hi))

            for off in sorted(set(wa) | set(wb)):
                va = wa.get(off)
                vb = wb.get(off)

                mark = "*" if va != vb else " "

                print(
                    f"{mark} 0x{off:04X}: "
                    f"A={va:5d} 0x{va:04X} "
                    f"B={vb:5d} 0x{vb:04X}",
                    file=out,
                )

print("Created:", report)
