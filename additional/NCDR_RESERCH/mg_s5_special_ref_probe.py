from pathlib import Path
from collections import defaultdict, Counter
import struct
import zlib
import math

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

# Existing strongly confirmed simple forms.
CLEAN = {
    2: (0, 1),
    3: (0, 1, 2),
    4: (0, 1, 2, 3),
}

SPECIAL = {0, 1, 5, 6, 7}


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
        bbox = struct.unpack_from(
            "<4i", data, bbox_off + 16*i
        )

        stream_off = struct.unpack_from(
            "<I", data, meta_off + 8*i
        )[0]

        pages.append((bbox, physical[stream_off]))

    return pages


def decode_s1(raw, h):
    pos = h[0]
    end = h[2]

    pts = []

    while pos < end:
        q = struct.unpack_from("<H", raw, pos)[0]
        x, y = struct.unpack_from("<ii", raw, pos + 2)
        pos += 10

        pts.append((x, y))

        for _ in range(q):
            dx, dy = struct.unpack_from("<hh", raw, pos)
            pos += 4

            x += dx
            y += dy
            pts.append((x, y))

    return pts


report = OUT / "mg_s5_special_ref_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        tag_slot = {
            t: [Counter() for _ in range(4)]
            for t in SPECIAL
        }

        tag_masks = {
            t: Counter()
            for t in SPECIAL
        }

        exact_code_masks = defaultdict(Counter)

        examples = []

        total_special = Counter()

        for page_i, (bbox, raw) in enumerate(load_pages(path)):

            h = struct.unpack_from("<23H", raw, 0)

            pts = decode_s1(raw, h)

            nref = h[11]
            s5_start = h[8]

            diag = math.hypot(
                max(1, bbox[2] - bbox[0]),
                max(1, bbox[3] - bbox[1]),
            )

            # ------------------------------------------------
            # First pass:
            # build edge -> known endpoint points using only
            # clean tag2/3/4 records.
            # ------------------------------------------------

            known = defaultdict(list)
            records = []

            for i in range(h[9]):

                rec = raw[
                    s5_start + 10*i:
                    s5_start + 10*(i+1)
                ]

                b0 = rec[0]
                b1 = rec[1]
                tag = b0 & 7

                vals = struct.unpack_from("<4H", rec, 2)

                records.append((b0, b1, tag, vals, rec))

                if tag not in CLEAN:
                    continue

                fields = CLEAN[tag]

                if not all(vals[j] < nref for j in fields):
                    continue

                for j in fields:
                    known[vals[j]].append(i)

            # ------------------------------------------------
            # Second pass:
            # score every possible special slot.
            #
            # A candidate ref is geometrically supported when
            # it points to an edge ID already observed at a
            # different clean point nearby.
            # ------------------------------------------------

            for i, (b0, b1, tag, vals, rec) in enumerate(records):

                if tag not in SPECIAL:
                    continue

                total_special[tag] += 1

                px, py = pts[i]

                supported_mask_005 = 0
                supported_mask_002 = 0
                supported_mask_001 = 0

                for j, ref in enumerate(vals):

                    s = tag_slot[tag][j]

                    s["total"] += 1

                    if ref >= nref:
                        s["out_of_range"] += 1
                        continue

                    s["in_range"] += 1

                    others = known.get(ref)

                    if not others:
                        s["no_known_other"] += 1
                        continue

                    best = None

                    for k in others:
                        if k == i:
                            continue

                        qx, qy = pts[k]

                        d = math.hypot(
                            qx - px,
                            qy - py,
                        ) / diag

                        if best is None or d < best:
                            best = d

                    if best is None:
                        s["self_only"] += 1
                        continue

                    s["has_other"] += 1

                    if best <= 0.100:
                        s["d100"] += 1

                    if best <= 0.050:
                        s["d050"] += 1
                        supported_mask_005 |= 1 << j

                    if best <= 0.020:
                        s["d020"] += 1
                        supported_mask_002 |= 1 << j

                    if best <= 0.010:
                        s["d010"] += 1
                        supported_mask_001 |= 1 << j

                tag_masks[tag][
                    (
                        supported_mask_005,
                        supported_mask_002,
                        supported_mask_001,
                    )
                ] += 1

                code = b0 | (b1 << 8)

                exact_code_masks[code][
                    (
                        supported_mask_005,
                        supported_mask_002,
                        supported_mask_001,
                    )
                ] += 1

                if (
                    len(examples) < 120
                    and tag in SPECIAL
                ):
                    examples.append(
                        (
                            page_i,
                            i,
                            f"tag={tag}",
                            f"code=0x{code:04X}",
                            vals,
                            (
                                f"m05={supported_mask_005:04b}",
                                f"m02={supported_mask_002:04b}",
                                f"m01={supported_mask_001:04b}",
                            ),
                            rec.hex(),
                        )
                    )

        print("=" * 100, file=out)
        print("FILE:", name, file=out)

        print(file=out)
        print("SPECIAL TAG COUNTS:", file=out)

        for tag in sorted(SPECIAL):
            print(
                f"tag={tag}:",
                total_special[tag],
                file=out,
            )

        print(file=out)
        print("PER TAG / SLOT:", file=out)

        for tag in sorted(SPECIAL):

            print(f"TAG {tag}", file=out)

            for j in range(4):

                s = tag_slot[tag][j]
                n = s["total"]

                if not n:
                    continue

                ir = s["in_range"]
                ho = s["has_other"]

                print(
                    f" slot{j}: "
                    f"in_range={ir}/{n} "
                    f"has_known_other={ho}/{n} "
                    f"d<=.05={s['d050']}/{n} "
                    f"d<=.02={s['d020']}/{n} "
                    f"d<=.01={s['d010']}/{n}",
                    file=out,
                )

            print(
                " masks (m05,m02,m01):",
                tag_masks[tag].most_common(30),
                file=out,
            )

        print(file=out)
        print("EXACT CODE TOPOLOGY MASKS:", file=out)

        ordered = sorted(
            exact_code_masks.items(),
            key=lambda x: sum(x[1].values()),
            reverse=True,
        )

        for code, masks in ordered[:200]:

            n = sum(masks.values())

            print(
                f"code=0x{code:04X} "
                f"n={n} "
                f"masks={masks.most_common(12)}",
                file=out,
            )

        print(file=out)
        print("EXAMPLES:", file=out)

        for e in examples:
            print(e, file=out)

print("Created:", report)
