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
        raise RuntimeError(f"bad zlib @ 0x{start:X}")

    consumed = len(data[start:]) - len(d.unused_data)
    end = start + consumed

    raw += d.flush()

    return raw, end


def load_pages(path):
    data = path.read_bytes()

    n = struct.unpack_from("<I", data, 0x56)[0]

    bbox_off = HDR
    meta_off = bbox_off + n * 16
    zero_off = meta_off + n * 8
    payload_off = zero_off + n * 4

    physical = {}

    pos = payload_off

    while pos < len(data):
        raw, end = unpack_one(data, pos)

        physical[pos] = {
            "raw": raw,
            "packed_len": end - pos,
        }

        pos = end

    pages = []

    for i in range(n):

        stream_off, meta1 = struct.unpack_from(
            "<2I",
            data,
            meta_off + i * 8,
        )

        s = physical[stream_off]

        pages.append({
            "raw": s["raw"],
            "packed_len": s["packed_len"],
            "raw_len": len(s["raw"]),
            "meta1": meta1,
        })

    return pages


report = OUT / "mg_page_header_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        pages = load_pages(path)

        total = len(pages)

        low_raw = 0

        high_packed = 0
        high_packed_minus6 = 0
        high_packed_plus6 = 0

        hdr_2e = 0
        prefix_count = 0

        f_h2 = 0
        f_h4 = 0
        f_h8 = 0
        f_h9 = 0
        f_h10 = 0
        f_h12 = 0
        f_repeated = 0
        f_h21 = 0
        f_final = 0

        middle_residual = Counter()

        bad = []

        for i, p in enumerate(pages):

            raw = p["raw"]
            meta1 = p["meta1"]

            lo = meta1 & 0xFFFF
            hi = meta1 >> 16

            low_raw += (
                lo == p["raw_len"]
            )

            high_packed += (
                hi == p["packed_len"]
            )

            high_packed_minus6 += (
                hi == p["packed_len"] - 6
            )

            high_packed_plus6 += (
                hi == p["packed_len"] + 6
            )

            if len(raw) < 0x34:
                continue

            h = struct.unpack_from("<23H", raw, 0)

            hdr_2e += (
                h[0] == 0x2E
            )

            p0 = struct.unpack_from(
                "<H", raw, 0x2E
            )[0]

            prefix_count += (
                p0 == ((h[1] - 1) & 0xFFFF)
            )

            f_h2 += (
                h[2] == 0x34 + 4*h[1]
            )

            f_h4 += (
                h[4] == h[2] + 3*h[3]
            )

            residual = (
                h[6]
                - h[4]
                - 4*h[5]
            )

            middle_residual[residual] += 1

            f_h8 += (
                h[8] == h[6] + 3*h[7]
            )

            f_h9 += (
                h[9] == h[1]
            )

            f_h10 += (
                h[10] == h[8] + 10*h[9]
            )

            f_h12 += (
                h[12] == h[10] + 14*h[11]
            )

            f_repeated += (
                h[14] == h[12]
                and h[16] == h[12]
                and h[18] == h[12]
                and h[20] == h[12]
                and h[13] == 0
                and h[15] == 0
                and h[17] == 0
                and h[19] == 0
            )

            f_h21 += (
                h[21] == h[11]
            )

            f_final += (
                h[12] + h[22]
                == len(raw)
            )

            tests = (
                h[0] == 0x2E,
                p0 == ((h[1] - 1) & 0xFFFF),
                h[2] == 0x34 + 4*h[1],
                h[4] == h[2] + 3*h[3],
                h[8] == h[6] + 3*h[7],
                h[9] == h[1],
                h[10] == h[8] + 10*h[9],
                h[12] == h[10] + 14*h[11],
                h[12] + h[22] == len(raw),
            )

            if (
                not all(tests)
                and len(bad) < 30
            ):
                bad.append(
                    (
                        i,
                        len(raw),
                        h,
                        residual,
                    )
                )

        print("=" * 90, file=out)
        print("FILE:", name, file=out)
        print("PAGES:", total, file=out)

        print(file=out)
        print("META1:", file=out)

        print(
            "low16 == raw_len:",
            low_raw, "/", total,
            file=out,
        )

        print(
            "high16 == packed_len:",
            high_packed, "/", total,
            file=out,
        )

        print(
            "high16 == packed_len-6:",
            high_packed_minus6, "/", total,
            file=out,
        )

        print(
            "high16 == packed_len+6:",
            high_packed_plus6, "/", total,
            file=out,
        )

        print(file=out)
        print("RAW HEADER:", file=out)

        for label, value in (
            ("h0 == 0x2E", hdr_2e),
            ("body_u16@2E == h1-1", prefix_count),
            ("h2 == 0x34 + 4*h1", f_h2),
            ("h4 == h2 + 3*h3", f_h4),
            ("h8 == h6 + 3*h7", f_h8),
            ("h9 == h1", f_h9),
            ("h10 == h8 + 10*h9", f_h10),
            ("h12 == h10 + 14*h11", f_h12),
            ("empty-section offsets", f_repeated),
            ("h21 == h11", f_h21),
            ("h12 + h22 == raw_len", f_final),
        ):
            print(
                f"{label}: {value}/{total}",
                file=out,
            )

        print(
            "h6-h4-4*h5 residuals:",
            middle_residual.most_common(30),
            file=out,
        )

        print(file=out)
        print("FIRST FAILURES:", file=out)

        for x in bad:
            print(x, file=out)

print("Created:", report)
