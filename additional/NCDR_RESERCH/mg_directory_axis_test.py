from pathlib import Path
import struct

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"

SETS = {
    "7185": (
        Path("/Volumes/CD_7185/DB"),
        ["IZ.MG1", "IZ.MG2", "IZ.MG3"],
    ),
    "7186": (
        Path("/Volumes/CD_7186/DB"),
        ["SCZ.MG1", "SCZ.MG2", "SCZ.MG3"],
    ),
}

HDR = 0x72
REC = 0x1C


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def in_range(v, lo, hi):
    return lo <= v <= hi


report = OUT / "mg_directory_axis_test.txt"

with report.open("w", encoding="utf-8") as out:

    for dataset, (root, names) in SETS.items():

        print("=" * 90, file=out)
        print("DATASET:", dataset, file=out)

        for name in names:

            data = (root / name).read_bytes()

            arity = struct.unpack_from("<H", data, 0x54)[0]
            count = struct.unpack_from("<I", data, 0x56)[0]
            data_size = struct.unpack_from("<I", data, 0x5A)[0]

            xmin, ymin, xmax, ymax = struct.unpack_from(
                "<4i", data, 0x5E
            )

            level = struct.unpack_from("<H", data, 0x6E)[0]
            count2 = struct.unpack_from("<H", data, 0x70)[0]

            directory_end = HDR + count * REC

            print()
            print("-" * 90, file=out)
            print("FILE:", name, file=out)

            print("arity:", arity, file=out)
            print("count:", count, file=out)
            print("count2:", count2, file=out)
            print("level:", level, file=out)
            print("compressed_data_size:", data_size, file=out)

            print(
                "actual compressed area:",
                len(data) - directory_end,
                file=out,
            )

            print(
                "compressed size match:",
                data_size == len(data) - directory_end,
                file=out,
            )

            print(
                "bounds:",
                xmin, ymin, xmax, ymax,
                file=out,
            )

            # ---------------------------------------------------------
            # Parse 28-byte rows.
            # ---------------------------------------------------------

            rows = []

            for i in range(count):
                off = HDR + i * REC
                vals = struct.unpack_from("<7i", data, off)
                rows.append(vals)

            zero_rows = [
                i for i, row in enumerate(rows)
                if all(v == 0 for v in row)
            ]

            nonzero_rows = [
                i for i, row in enumerate(rows)
                if any(v != 0 for v in row)
            ]

            print("zero rows:", len(zero_rows), file=out)
            print("nonzero rows:", len(nonzero_rows), file=out)

            if zero_rows:
                print(
                    "first zero row:",
                    zero_rows[0],
                    file=out,
                )
                print(
                    "last zero row:",
                    zero_rows[-1],
                    file=out,
                )

                tail_start = zero_rows[0]

                tail_is_all_zero = all(
                    all(v == 0 for v in rows[i])
                    for i in range(tail_start, count)
                )

                print(
                    "all rows after first zero are zero:",
                    tail_is_all_zero,
                    file=out,
                )

            # ---------------------------------------------------------
            # Hypothesis 1:
            #
            # Flattened s32 stream alternates X,Y,X,Y...
            #
            # Since each row has seven values, row parity flips.
            # ---------------------------------------------------------

            good_xy = 0
            good_yx = 0
            tested = 0

            bad_xy_examples = []

            for row_index, row in enumerate(rows):

                if all(v == 0 for v in row):
                    continue

                for slot, v in enumerate(row):

                    global_index = row_index * 7 + slot

                    expect_x = (global_index % 2 == 0)

                    if expect_x:
                        ok_xy = in_range(v, xmin, xmax)
                        ok_yx = in_range(v, ymin, ymax)
                    else:
                        ok_xy = in_range(v, ymin, ymax)
                        ok_yx = in_range(v, xmin, xmax)

                    tested += 1
                    good_xy += int(ok_xy)
                    good_yx += int(ok_yx)

                    if (
                        not ok_xy
                        and len(bad_xy_examples) < 30
                    ):
                        bad_xy_examples.append(
                            (
                                row_index,
                                slot,
                                global_index,
                                v,
                                "X" if expect_x else "Y",
                            )
                        )

            print()
            print("GLOBAL ALTERNATING AXIS TEST:", file=out)

            print(
                "XYXY... hits:",
                good_xy,
                "/",
                tested,
                f"({pct(good_xy, tested):.4f}%)",
                file=out,
            )

            print(
                "YXYX... hits:",
                good_yx,
                "/",
                tested,
                f"({pct(good_yx, tested):.4f}%)",
                file=out,
            )

            print("first XY failures:", file=out)

            for x in bad_xy_examples:
                print(" ", x, file=out)

            # ---------------------------------------------------------
            # Per-row interpretation.
            #
            # Even row:
            #   X Y X Y X Y X
            #
            # Odd row:
            #   Y X Y X Y X Y
            # ---------------------------------------------------------

            perfect_rows = 0
            partially_good = 0

            first_bad_rows = []

            for i, row in enumerate(rows):

                if all(v == 0 for v in row):
                    continue

                good = 0

                for slot, v in enumerate(row):
                    gi = i * 7 + slot

                    if gi % 2 == 0:
                        good += in_range(v, xmin, xmax)
                    else:
                        good += in_range(v, ymin, ymax)

                if good == 7:
                    perfect_rows += 1

                if good >= 6:
                    partially_good += 1

                if good != 7 and len(first_bad_rows) < 30:
                    first_bad_rows.append(
                        (i, good, row)
                    )

            print()
            print(
                "perfect nonzero rows 7/7:",
                perfect_rows,
                "/",
                len(nonzero_rows),
                f"({pct(perfect_rows, len(nonzero_rows)):.4f}%)",
                file=out,
            )

            print(
                "rows >=6/7:",
                partially_good,
                "/",
                len(nonzero_rows),
                f"({pct(partially_good, len(nonzero_rows)):.4f}%)",
                file=out,
            )

            print("first imperfect rows:", file=out)

            for x in first_bad_rows:
                print(" ", x, file=out)

            # ---------------------------------------------------------
            # Find longest initial region for which every nonzero
            # scalar follows the XYXY bounds.
            # ---------------------------------------------------------

            first_bad_scalar = None

            for i, row in enumerate(rows):

                if all(v == 0 for v in row):
                    continue

                for slot, v in enumerate(row):
                    gi = i * 7 + slot

                    lo, hi = (
                        (xmin, xmax)
                        if gi % 2 == 0
                        else (ymin, ymax)
                    )

                    if not in_range(v, lo, hi):
                        first_bad_scalar = (
                            i, slot, gi, v, lo, hi
                        )
                        break

                if first_bad_scalar:
                    break

            print()
            print(
                "FIRST GLOBAL-XY FAILURE:",
                first_bad_scalar,
                file=out,
            )

            # ---------------------------------------------------------
            # Is every value a sign-extended 24-bit integer?
            # ---------------------------------------------------------

            s24_good = 0
            s24_total = 0

            for i in nonzero_rows:
                for v in rows[i]:
                    s24_total += 1

                    if -0x800000 <= v <= 0x7FFFFF:
                        s24_good += 1

            print(
                "signed-24-compatible:",
                s24_good,
                "/",
                s24_total,
                f"({pct(s24_good, s24_total):.4f}%)",
                file=out,
            )

print("Created:", report)
