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


def parse_refs(rec, nref):
    tag = rec[0] & 7
    vals = struct.unpack_from("<4H", rec, 2)

    if tag == 2:
        ids = vals[:2]
    elif tag == 3:
        ids = vals[:3]
    elif tag == 4:
        ids = vals[:4]
    else:
        return None

    if not all(v < nref for v in ids):
        return None

    return tuple(ids)


def percentile(values, p):
    if not values:
        return None

    a = sorted(values)

    pos = (len(a) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(a) - 1)
    f = pos - lo

    return a[lo] * (1 - f) + a[hi] * f


def summarize(name, values, out):
    print(name, "N=", len(values), file=out)

    for p in (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99):
        v = percentile(values, p)

        print(
            f"  p{int(p*100):02d}:",
            f"{v:.8f}" if v is not None else "-",
            file=out,
        )


report = OUT / "mg_s5_edge_geometry_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        edge_dist = []
        control_dist = []

        singleton_border = []
        allpoint_border = []

        fanin = Counter()

        edge_examples = []

        for page_i, (bbox, raw) in enumerate(load_pages(path)):

            h = struct.unpack_from("<23H", raw, 0)

            pts = decode_s1(raw, h)

            nref = h[11]
            s5_start = h[8]

            refs_to_points = defaultdict(list)

            clean_ids = []

            for i in range(h[9]):

                rec = raw[
                    s5_start + 10*i:
                    s5_start + 10*(i+1)
                ]

                refs = parse_refs(rec, nref)

                if refs is None:
                    continue

                clean_ids.append(i)

                for r in set(refs):
                    refs_to_points[r].append(i)

            x0, y0, x1, y1 = bbox

            w = max(1, x1 - x0)
            hh = max(1, y1 - y0)

            diag = math.hypot(w, hh)

            # -----------------------------------
            # Baseline border distance for points
            # -----------------------------------

            for i in clean_ids:

                x, y = pts[i]

                d = min(
                    x - x0,
                    x1 - x,
                    y - y0,
                    y1 - y,
                )

                allpoint_border.append(
                    d / diag
                )

            # -----------------------------------
            # ref fan-in
            # -----------------------------------

            for ref, ids in refs_to_points.items():

                fanin[len(ids)] += 1

                if len(ids) == 2:

                    a, b = ids
                    xa, ya = pts[a]
                    xb, yb = pts[b]

                    d = math.hypot(
                        xb - xa,
                        yb - ya,
                    ) / diag

                    edge_dist.append(d)

                    if len(edge_examples) < 30:
                        edge_examples.append(
                            (
                                page_i,
                                ref,
                                a,
                                b,
                                pts[a],
                                pts[b],
                                d,
                            )
                        )

                elif len(ids) == 1:

                    i = ids[0]
                    x, y = pts[i]

                    d = min(
                        x - x0,
                        x1 - x,
                        y - y0,
                        y1 - y,
                    )

                    singleton_border.append(
                        d / diag
                    )

            # -----------------------------------
            # Deterministic control pairs.
            #
            # Pair points far apart in the local
            # array to avoid using randomness.
            # -----------------------------------

            m = len(clean_ids)

            if m >= 4:

                shift = m // 2

                for k in range(m):

                    a = clean_ids[k]
                    b = clean_ids[(k + shift) % m]

                    if a == b:
                        continue

                    xa, ya = pts[a]
                    xb, yb = pts[b]

                    d = math.hypot(
                        xb - xa,
                        yb - ya,
                    ) / diag

                    control_dist.append(d)

        print("=" * 100, file=out)
        print("FILE:", name, file=out)

        print(
            "REF FAN-IN:",
            fanin.most_common(20),
            file=out,
        )

        print(file=out)

        summarize(
            "EDGE FANIN2 NORMALIZED DISTANCE",
            edge_dist,
            out,
        )

        print(file=out)

        summarize(
            "CONTROL NORMALIZED DISTANCE",
            control_dist,
            out,
        )

        print(file=out)

        print("EDGE VS CONTROL THRESHOLDS:", file=out)

        for t in (
            0.001,
            0.002,
            0.005,
            0.01,
            0.02,
            0.05,
            0.10,
            0.25,
        ):

            e = sum(x <= t for x in edge_dist)
            c = sum(x <= t for x in control_dist)

            print(
                f" <= {t:.3f}: "
                f"edge={e}/{len(edge_dist)} "
                f"({100*e/len(edge_dist):.4f}%) "
                f"control={c}/{len(control_dist)} "
                f"({100*c/len(control_dist):.4f}%)",
                file=out,
            )

        print(file=out)

        summarize(
            "FANIN1 BORDER DISTANCE",
            singleton_border,
            out,
        )

        print(file=out)

        summarize(
            "ALL CLEAN POINT BORDER DISTANCE",
            allpoint_border,
            out,
        )

        print(file=out)

        print("BORDER THRESHOLDS:", file=out)

        for t in (
            0.0001,
            0.0005,
            0.001,
            0.002,
            0.005,
            0.01,
            0.02,
            0.05,
        ):

            a = sum(x <= t for x in singleton_border)
            b = sum(x <= t for x in allpoint_border)

            print(
                f" <= {t:.4f}: "
                f"fanin1={a}/{len(singleton_border)} "
                f"({100*a/len(singleton_border):.4f}%) "
                f"all={b}/{len(allpoint_border)} "
                f"({100*b/len(allpoint_border):.4f}%)",
                file=out,
            )

        print(file=out)
        print("EDGE EXAMPLES:", file=out)

        for e in edge_examples:
            print(e, file=out)

print("Created:", report)
