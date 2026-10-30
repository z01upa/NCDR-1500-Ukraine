from pathlib import Path
from collections import Counter, defaultdict
import struct
import zlib

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"
OUT.mkdir(parents=True, exist_ok=True)

FILES = {
    "7185_MG1": Path("/Volumes/CD_7185/DB/IZ.MG1"),
    "7185_MG2": Path("/Volumes/CD_7185/DB/IZ.MG2"),
    "7185_MG3": Path("/Volumes/CD_7185/DB/IZ.MG3"),
    "7186_MG1": Path("/Volumes/CD_7186/DB/SCZ.MG1"),
    "7186_MG2": Path("/Volumes/CD_7186/DB/SCZ.MG2"),
    "7186_MG3": Path("/Volumes/CD_7186/DB/SCZ.MG3"),
}

HDR = 0x72

# Strong hypotheses only.
EXPECTED = {
    2: (0, 1),
    3: (0, 1, 2),
    4: (0, 1, 2, 3),

    # escape/special family hypothesis
    5: (1, 2, 3),
}


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
    meta_off = bbox_off + 16*n
    zero_off = meta_off + 8*n
    payload_off = zero_off + 4*n

    physical = {}
    pos = payload_off

    while pos < len(data):
        raw, end = unpack_one(data, pos)
        physical[pos] = raw
        pos = end

    pages = []

    for i in range(n):
        stream_off = struct.unpack_from(
            "<I", data, meta_off + 8*i
        )[0]

        pages.append(physical[stream_off])

    return pages


report = OUT / "mg_s5_arity_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        pages = load_pages(path)

        tag_total = Counter()
        tag_good = Counter()

        tag_masks = {
            t: Counter()
            for t in range(8)
        }

        tag_nonref_accidental = {
            t: Counter()
            for t in range(8)
        }

        failure_codes = Counter()
        failure_b0b1 = Counter()

        unknown_codes = Counter()

        domain_total = 0
        domain_hit = 0

        fanin_global = Counter()

        examples = []

        for page_i, raw in enumerate(pages):

            h = struct.unpack_from("<23H", raw, 0)

            s5_start = h[8]
            n5 = h[9]
            nref = h[11]

            domain_total += nref

            refs = Counter()

            for i in range(n5):

                rec = raw[
                    s5_start + 10*i:
                    s5_start + 10*(i+1)
                ]

                b0 = rec[0]
                b1 = rec[1]

                tag = b0 & 7

                vals = struct.unpack_from(
                    "<4H", rec, 2
                )

                mask = 0

                for j, v in enumerate(vals):
                    if v < nref:
                        mask |= 1 << j

                tag_total[tag] += 1
                tag_masks[tag][mask] += 1

                code = b0 | (b1 << 8)

                if tag not in EXPECTED:
                    unknown_codes[
                        (tag, code, mask)
                    ] += 1
                    continue

                expected = EXPECTED[tag]

                good = all(
                    vals[j] < nref
                    for j in expected
                )

                if good:
                    tag_good[tag] += 1

                    for j in expected:
                        refs[vals[j]] += 1

                else:
                    failure_codes[
                        (tag, code)
                    ] += 1

                    failure_b0b1[
                        (b0, b1)
                    ] += 1

                    if len(examples) < 150:
                        examples.append(
                            (
                                page_i,
                                i,
                                f"tag={tag}",
                                f"b0=0x{b0:02X}",
                                f"b1=0x{b1:02X}",
                                f"code=0x{code:04X}",
                                f"mask={mask:04b}",
                                vals,
                                nref,
                                rec.hex(),
                            )
                        )

                # Are "non-ref" positions accidentally
                # inside h11?
                non_expected = (
                    set(range(4))
                    - set(expected)
                )

                for j in non_expected:
                    if vals[j] < nref:
                        tag_nonref_accidental[tag][j] += 1

            domain_hit += len(refs)

            for n in refs.values():
                fanin_global[n] += 1

        print("=" * 100, file=out)
        print("FILE:", name, file=out)

        print(
            "DOMAIN COVERAGE FROM TAG RULE:",
            domain_hit,
            "/",
            domain_total,
            (
                f"({100*domain_hit/domain_total:.6f}%)"
                if domain_total else ""
            ),
            file=out,
        )

        print(
            "FAN-IN:",
            fanin_global.most_common(30),
            file=out,
        )

        print(file=out)
        print("TAG RULE:", file=out)

        for tag in range(8):

            n = tag_total[tag]

            if not n:
                continue

            if tag in EXPECTED:
                g = tag_good[tag]

                print(
                    f"tag={tag} "
                    f"expected={EXPECTED[tag]} "
                    f"good={g}/{n} "
                    f"({100*g/n:.6f}%) "
                    f"masks={tag_masks[tag].most_common(12)} "
                    f"nonref_accidental="
                    f"{tag_nonref_accidental[tag]}",
                    file=out,
                )
            else:
                print(
                    f"tag={tag} UNKNOWN "
                    f"n={n} "
                    f"masks={tag_masks[tag].most_common(12)}",
                    file=out,
                )

        print(file=out)
        print("TOP RULE-FAILURE EXACT CODES:", file=out)

        for x in failure_codes.most_common(100):
            print(x, file=out)

        print(file=out)
        print("TOP RULE-FAILURE B0/B1:", file=out)

        for x in failure_b0b1.most_common(100):
            print(x, file=out)

        print(file=out)
        print("UNKNOWN TAG EXACT CODE/MASK:", file=out)

        for x in unknown_codes.most_common(150):
            print(x, file=out)

        print(file=out)
        print("FAILURE EXAMPLES:", file=out)

        for x in examples:
            print(x, file=out)

print("Created:", report)
