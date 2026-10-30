from pathlib import Path
from collections import Counter, defaultdict
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

    used = len(data[start:]) - len(d.unused_data)
    raw += d.flush()

    return raw, start + used


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
        physical[pos] = raw
        pos = end

    pages = []

    for i in range(n):

        stream_off = struct.unpack_from(
            "<I",
            data,
            meta_off + 8*i
        )[0]

        pages.append(physical[stream_off])

    return pages


report = OUT / "mg_s5_type_ref_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        pages = load_pages(path)

        # Per exact slot0 code.
        stats = defaultdict(Counter)

        low_byte = Counter()
        high_byte = Counter()
        signed_high_byte = Counter()

        invalid_slot1_values = Counter()
        invalid_slot2_values = Counter()

        total_records = 0
        total_domain = 0
        total_referenced_domain = 0

        pages_full_coverage = 0
        pages_95_coverage = 0
        pages_90_coverage = 0

        ref_fanin = Counter()

        invalid_examples = []

        for page_i, raw in enumerate(pages):

            h = struct.unpack_from("<23H", raw, 0)

            s5_start = h[8]
            n5 = h[9]

            nref = h[11]

            referenced = set()
            page_fanin = Counter()

            total_domain += nref

            for i in range(n5):

                rec = raw[
                    s5_start + 10*i:
                    s5_start + 10*(i+1)
                ]

                code, a, b, c, d = struct.unpack(
                    "<5H", rec
                )

                total_records += 1

                lo = code & 0xFF
                hi = (code >> 8) & 0xFF
                shi = hi if hi < 128 else hi - 256

                low_byte[lo] += 1
                high_byte[hi] += 1
                signed_high_byte[shi] += 1

                s = stats[code]

                s["total"] += 1

                va = a < nref
                vb = b < nref

                s["slot1_valid"] += va
                s["slot2_valid"] += vb
                s["both_valid"] += va and vb
                s["both_invalid"] += (not va) and (not vb)

                if va:
                    referenced.add(a)
                    page_fanin[a] += 1
                else:
                    invalid_slot1_values[a] += 1

                if vb:
                    referenced.add(b)
                    page_fanin[b] += 1
                else:
                    invalid_slot2_values[b] += 1

                if va and vb:

                    s["equal"] += (a == b)

                    s["plus1"] += (
                        b == a + 1
                    )

                    s["minus1"] += (
                        a == b + 1
                    )

                    s["adjacent"] += (
                        abs(a - b) == 1
                    )

                if (
                    (not va or not vb)
                    and len(invalid_examples) < 100
                ):
                    invalid_examples.append(
                        (
                            page_i,
                            i,
                            f"0x{code:04X}",
                            a,
                            b,
                            nref,
                            rec.hex(),
                        )
                    )

            total_referenced_domain += len(referenced)

            if nref:
                cov = len(referenced) / nref
            else:
                cov = 1.0

            pages_full_coverage += (cov == 1.0)
            pages_95_coverage += (cov >= 0.95)
            pages_90_coverage += (cov >= 0.90)

            for count in page_fanin.values():
                ref_fanin[count] += 1

        print("=" * 100, file=out)
        print("FILE:", name, file=out)

        print(
            "TOTAL S5 RECORDS:",
            total_records,
            file=out,
        )

        print(
            "TOTAL h11 DOMAIN ENTRIES:",
            total_domain,
            file=out,
        )

        print(
            "REFERENCED DOMAIN ENTRIES:",
            total_referenced_domain,
            "/",
            total_domain,
            (
                f"({100*total_referenced_domain/total_domain:.4f}%)"
                if total_domain else ""
            ),
            file=out,
        )

        print(
            "PAGES 100% DOMAIN COVERAGE:",
            pages_full_coverage,
            "/",
            len(pages),
            file=out,
        )

        print(
            "PAGES >=95% DOMAIN COVERAGE:",
            pages_95_coverage,
            "/",
            len(pages),
            file=out,
        )

        print(
            "PAGES >=90% DOMAIN COVERAGE:",
            pages_90_coverage,
            "/",
            len(pages),
            file=out,
        )

        print()
        print(
            "REFERENCE FAN-IN DISTRIBUTION:",
            ref_fanin.most_common(50),
            file=out,
        )

        print()
        print(
            "SLOT0 LOW BYTE TOP:",
            low_byte.most_common(50),
            file=out,
        )

        print(
            "SLOT0 HIGH BYTE TOP:",
            high_byte.most_common(50),
            file=out,
        )

        print(
            "SLOT0 SIGNED HIGH BYTE TOP:",
            signed_high_byte.most_common(50),
            file=out,
        )

        print()
        print("SLOT0 TYPE TABLE:", file=out)

        ordered = sorted(
            stats.items(),
            key=lambda x: x[1]["total"],
            reverse=True,
        )

        for code, s in ordered[:150]:

            n = s["total"]

            lo = code & 0xFF
            hi = (code >> 8) & 0xFF
            shi = hi if hi < 128 else hi - 256

            print(
                f"code=0x{code:04X} "
                f"bytes={lo:02X},{hi:02X} "
                f"hi_signed={shi:+d} "
                f"n={n} "
                f"v1={s['slot1_valid']}/{n} "
                f"v2={s['slot2_valid']}/{n} "
                f"both={s['both_valid']}/{n} "
                f"+1={s['plus1']} "
                f"-1={s['minus1']} "
                f"adj={s['adjacent']}",
                file=out,
            )

        print()
        print(
            "TOP INVALID SLOT1 VALUES:",
            invalid_slot1_values.most_common(50),
            file=out,
        )

        print(
            "TOP INVALID SLOT2 VALUES:",
            invalid_slot2_values.most_common(50),
            file=out,
        )

        print()
        print("INVALID EXAMPLES:", file=out)

        for x in invalid_examples:
            print(x, file=out)

print("Created:", report)
