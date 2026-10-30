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
        raise RuntimeError(
            f"bad zlib @ 0x{start:X}"
        )

    used = len(data[start:]) - len(d.unused_data)
    raw += d.flush()

    return raw, start + used


def load_pages(path):
    data = path.read_bytes()

    n = struct.unpack_from(
        "<I", data, 0x56
    )[0]

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
            "<I",
            data,
            meta_off + 8*i
        )[0]

        pages.append(
            physical[stream_off]
        )

    return pages


report = OUT / "mg_s5_layout_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        pages = load_pages(path)

        byte0 = Counter()
        byte1 = Counter()

        byte0_tag = Counter()
        byte1_tag = Counter()

        byte0_payload = Counter()
        byte1_payload = Counter()

        # Per first byte.
        by_b0 = defaultdict(
            lambda: {
                "n": 0,
                "masks": Counter(),
                "valid": [0, 0, 0, 0],
                "plus1": Counter(),
                "minus1": Counter(),
            }
        )

        # Per exact first u16.
        by_code = defaultdict(
            lambda: {
                "n": 0,
                "masks": Counter(),
                "valid": [0, 0, 0, 0],
            }
        )

        # Upper-bound coverage if every value < h11
        # is treated as a possible reference.
        all_valid_domain = 0
        total_domain = 0

        # Later: coverage using only fields that are
        # structurally stable for a byte0 family.
        page_records = []

        examples = defaultdict(list)

        for page_i, raw in enumerate(pages):

            h = struct.unpack_from(
                "<23H", raw, 0
            )

            s5_start = h[8]
            n5 = h[9]
            nref = h[11]

            total_domain += nref

            page_data = []
            all_refs = set()

            for i in range(n5):

                rec = raw[
                    s5_start + 10*i:
                    s5_start + 10*(i+1)
                ]

                b0 = rec[0]
                b1 = rec[1]

                code = struct.unpack_from(
                    "<H", rec, 0
                )[0]

                vals = struct.unpack_from(
                    "<4H", rec, 2
                )

                byte0[b0] += 1
                byte1[b1] += 1

                byte0_tag[b0 & 7] += 1
                byte1_tag[b1 & 7] += 1

                byte0_payload[b0 >> 3] += 1
                byte1_payload[b1 >> 3] += 1

                mask = 0

                for j, v in enumerate(vals):

                    if v < nref:
                        mask |= 1 << j
                        all_refs.add(v)

                s = by_b0[b0]
                s["n"] += 1
                s["masks"][mask] += 1

                c = by_code[code]
                c["n"] += 1
                c["masks"][mask] += 1

                for j, v in enumerate(vals):
                    if v < nref:
                        s["valid"][j] += 1
                        c["valid"][j] += 1

                # Pairwise +/-1 tests among the
                # four possible fields.
                for a in range(4):
                    for b in range(a+1, 4):

                        va = vals[a]
                        vb = vals[b]

                        if va < nref and vb < nref:

                            if vb == va + 1:
                                s["plus1"][(a, b)] += 1

                            if va == vb + 1:
                                s["minus1"][(a, b)] += 1

                if (
                    len(examples[b0]) < 10
                    and (
                        mask != 0b0011
                        or b0 in (
                            0x25, 0x45, 0x65,
                            0x26, 0x46, 0x66,
                            0x11, 0x01
                        )
                    )
                ):
                    examples[b0].append(
                        (
                            page_i,
                            i,
                            f"0x{code:04X}",
                            f"mask={mask:04b}",
                            vals,
                            rec.hex(),
                            nref,
                        )
                    )

                page_data.append(
                    (b0, vals, nref)
                )

            all_valid_domain += len(all_refs)
            page_records.append(
                (nref, page_data)
            )

        # ------------------------------------------------
        # Stable candidate reference positions by byte0.
        #
        # This is only a structural candidate:
        # >= 99.5% of records of this byte0 must have
        # the field within the h11 namespace.
        # ------------------------------------------------

        stable = {}

        for b0, s in by_b0.items():

            n = s["n"]
            fields = []

            if n >= 20:

                for j in range(4):

                    if (
                        s["valid"][j] / n
                        >= 0.995
                    ):
                        fields.append(j)

            stable[b0] = fields

        stable_coverage = 0
        stable_fanin = Counter()

        for nref, records in page_records:

            refs = Counter()

            for b0, vals, _ in records:

                for j in stable.get(b0, []):

                    v = vals[j]

                    if v < nref:
                        refs[v] += 1

            stable_coverage += len(refs)

            for cnt in refs.values():
                stable_fanin[cnt] += 1

        print("=" * 100, file=out)
        print("FILE:", name, file=out)

        print(
            "TOTAL DOMAIN:",
            total_domain,
            file=out,
        )

        print(
            "ALL <h11 VALUES COVERAGE:",
            all_valid_domain,
            "/",
            total_domain,
            (
                f"({100*all_valid_domain/total_domain:.4f}%)"
                if total_domain else ""
            ),
            file=out,
        )

        print(
            "STABLE-FIELD COVERAGE:",
            stable_coverage,
            "/",
            total_domain,
            (
                f"({100*stable_coverage/total_domain:.4f}%)"
                if total_domain else ""
            ),
            file=out,
        )

        print(
            "STABLE-FIELD FAN-IN:",
            stable_fanin.most_common(30),
            file=out,
        )

        print()
        print(
            "BYTE0 TAG (b0 & 7):",
            byte0_tag.most_common(),
            file=out,
        )

        print(
            "BYTE1 TAG (b1 & 7):",
            byte1_tag.most_common(),
            file=out,
        )

        print(
            "BYTE0 PAYLOAD (b0 >> 3):",
            byte0_payload.most_common(32),
            file=out,
        )

        print(
            "BYTE1 PAYLOAD (b1 >> 3):",
            byte1_payload.most_common(32),
            file=out,
        )

        print()
        print("BYTE0 LAYOUT TABLE:", file=out)

        ordered_b0 = sorted(
            by_b0.items(),
            key=lambda x: x[1]["n"],
            reverse=True,
        )

        for b0, s in ordered_b0[:100]:

            n = s["n"]

            rates = [
                100*s["valid"][j]/n
                for j in range(4)
            ]

            print(
                f"b0=0x{b0:02X} "
                f"tag={b0&7} "
                f"payload={b0>>3:02d} "
                f"n={n} "
                f"valid%="
                f"{rates[0]:.3f},"
                f"{rates[1]:.3f},"
                f"{rates[2]:.3f},"
                f"{rates[3]:.3f} "
                f"stable={stable[b0]} "
                f"masks={s['masks'].most_common(8)} "
                f"+1={s['plus1'].most_common(8)} "
                f"-1={s['minus1'].most_common(8)}",
                file=out,
            )

        print()
        print("SPECIAL EXACT CODES:", file=out)

        interesting = []

        for code, s in by_code.items():

            n = s["n"]

            if n < 2:
                continue

            r = [
                s["valid"][j] / n
                for j in range(4)
            ]

            # anything whose four fields do not all
            # behave alike
            if max(r) - min(r) > 0.25:
                interesting.append(
                    (n, code, s, r)
                )

        interesting.sort(reverse=True)

        for n, code, s, r in interesting[:150]:

            print(
                f"code=0x{code:04X} "
                f"n={n} "
                f"valid%="
                + ",".join(
                    f"{100*x:.2f}" for x in r
                )
                + " masks="
                + repr(
                    s["masks"].most_common(8)
                ),
                file=out,
            )

        print()
        print("SPECIAL EXAMPLES:", file=out)

        for b0 in sorted(examples):

            if not examples[b0]:
                continue

            print(
                f"b0=0x{b0:02X}",
                file=out,
            )

            for e in examples[b0]:
                print(" ", e, file=out)

print("Created:", report)
