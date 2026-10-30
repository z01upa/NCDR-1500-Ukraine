from pathlib import Path
from collections import Counter
import struct
import zlib

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"

FILES = {
    "7185_MG1": Path("/Volumes/CD_7185/DB/IZ.MG1"),
    "7185_MG2": Path("/Volumes/CD_7185/DB/IZ.MG2"),
    "7185_MG3": Path("/Volumes/CD_7185/DB/IZ.MG3"),
    "7186_MG1": Path("/Volumes/CD_7186/DB/SCZ.MG1"),
    "7186_MG2": Path("/Volumes/CD_7186/DB/SCZ.MG2"),
    "7186_MG3": Path("/Volumes/CD_7186/DB/SCZ.MG3"),
}

HDR = 0x72


def unpack_one(data, start):
    d = zlib.decompressobj()
    raw = d.decompress(data[start:])

    if not d.eof:
        raise RuntimeError(
            f"bad zlib at 0x{start:X}"
        )

    consumed = len(data[start:]) - len(d.unused_data)
    end = start + consumed

    raw += d.flush()

    return raw, end


def load_pages(path):
    data = path.read_bytes()

    n = struct.unpack_from("<I", data, 0x56)[0]

    meta_off = HDR + n * 16
    zero_off = meta_off + n * 8
    payload_off = zero_off + n * 4

    physical = {}

    pos = payload_off

    while pos < len(data):
        raw, end = unpack_one(data, pos)
        physical[pos] = raw
        pos = end

    pages = []

    for i in range(n):
        stream_off = struct.unpack_from(
            "<I",
            data,
            meta_off + i * 8
        )[0]

        pages.append(physical[stream_off])

    return pages


report = OUT / "mg_page_layout_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        pages = load_pages(path)

        a_good = 0
        c_good = 0
        tail8 = 0

        a_extra_counts = Counter()
        c_extra_counts = Counter()

        all_bounds_good = 0

        bad = []

        for i, raw in enumerate(pages):

            h = struct.unpack_from("<23H", raw, 0)

            # ---------------------------------------------
            # SECTION A
            #
            # header ends at 0x2E.
            # hypothesized:
            #
            #   6 bytes
            #   h1 * 4
            #   K1 * 6
            # ---------------------------------------------

            a_extra_bytes = (
                h[2]
                - 0x34
                - 4 * h[1]
            )

            a_ok = (
                a_extra_bytes >= 0
                and a_extra_bytes % 6 == 0
            )

            if a_ok:
                a_good += 1
                a_extra_counts[
                    a_extra_bytes // 6
                ] += 1

            # ---------------------------------------------
            # SECTION C
            #
            # hypothesized:
            #
            #   6 bytes
            #   h5 * 4
            #   K2 * 6
            # ---------------------------------------------

            c_extra_bytes = (
                h[6]
                - h[4]
                - 6
                - 4 * h[5]
            )

            c_ok = (
                c_extra_bytes >= 0
                and c_extra_bytes % 6 == 0
            )

            if c_ok:
                c_good += 1
                c_extra_counts[
                    c_extra_bytes // 6
                ] += 1

            # ---------------------------------------------
            # Final section
            # ---------------------------------------------

            tail_ok = (
                h[22] == 8 * h[21]
            )

            tail8 += int(tail_ok)

            # ---------------------------------------------
            # All fixed sections together
            # ---------------------------------------------

            bounds_ok = (
                h[4] == h[2] + 3*h[3]
                and h[8] == h[6] + 3*h[7]
                and h[9] == h[1]
                and h[10] == h[8] + 10*h[9]
                and h[12] == h[10] + 14*h[11]
                and h[14] == h[12]
                and h[16] == h[12]
                and h[18] == h[12]
                and h[20] == h[12]
                and h[13] == 0
                and h[15] == 0
                and h[17] == 0
                and h[19] == 0
                and h[21] == h[11]
                and h[22] == 8*h[21]
                and h[12] + h[22] == len(raw)
            )

            all_bounds_good += int(bounds_ok)

            if (
                (not a_ok or not c_ok or not tail_ok)
                and len(bad) < 30
            ):
                bad.append({
                    "page": i,
                    "raw": len(raw),
                    "h": h,
                    "A_extra_bytes": a_extra_bytes,
                    "C_extra_bytes": c_extra_bytes,
                })

        print("=" * 90, file=out)
        print("FILE:", name, file=out)
        print("PAGES:", len(pages), file=out)

        print(
            "SECTION A = 6 + 4*h1 + 6*K:",
            a_good,
            "/",
            len(pages),
            file=out,
        )

        print(
            "SECTION C = 6 + 4*h5 + 6*K:",
            c_good,
            "/",
            len(pages),
            file=out,
        )

        print(
            "FINAL SECTION = 8*h21:",
            tail8,
            "/",
            len(pages),
            file=out,
        )

        print(
            "ALL FIXED BOUNDS CONSISTENT:",
            all_bounds_good,
            "/",
            len(pages),
            file=out,
        )

        print(file=out)

        print(
            "SECTION A extra-record counts:",
            a_extra_counts.most_common(40),
            file=out,
        )

        print(
            "SECTION C extra-record counts:",
            c_extra_counts.most_common(40),
            file=out,
        )

        print(file=out)
        print("FIRST FAILURES:", file=out)

        for x in bad:
            print(x, file=out)

print("Created:", report)
