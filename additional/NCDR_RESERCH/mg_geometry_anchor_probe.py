from pathlib import Path
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

        bbox = struct.unpack_from(
            "<4i",
            data,
            bbox_off + i * 16
        )

        stream_off = struct.unpack_from(
            "<I",
            data,
            meta_off + i * 8
        )[0]

        pages.append(
            (bbox, physical[stream_off])
        )

    return pages


def inside(x, y, bbox):
    x0, y0, x1, y1 = bbox

    return (
        x0 <= x <= x1
        and y0 <= y <= y1
    )


def probe_section(
    raw,
    bbox,
    start,
    end,
    count
):
    result = {
        "usable": False,
        "q_match": False,
        "anchor_inside": False,

        "cum_all": False,
        "anchor_rel_all": False,
        "swap_cum_all": False,

        "cum_hits": 0,
        "anchor_rel_hits": 0,
        "swap_cum_hits": 0,

        "points": 0,
        "first_bad": None,
    }

    if count <= 0:
        return result

    # Simple K=0 form only.
    expected_len = 6 + 4 * count

    if end - start != expected_len:
        return result

    q = struct.unpack_from(
        "<H", raw, start
    )[0]

    x0, y0 = struct.unpack_from(
        "<ii", raw, start + 2
    )

    result["usable"] = True
    result["q_match"] = (
        q == count - 1
    )

    result["anchor_inside"] = inside(
        x0, y0, bbox
    )

    if q != count - 1:
        return result

    rec_start = start + 10

    if rec_start + 4*q != end:
        raise RuntimeError(
            "section arithmetic mismatch"
        )

    # --------------------------------------------------
    # Interpretation A:
    # cumulative LE s16 dx,dy
    # --------------------------------------------------

    x = x0
    y = y0

    cum_ok = result["anchor_inside"]
    cum_hits = int(result["anchor_inside"])

    first_bad = None

    for j in range(q):

        dx, dy = struct.unpack_from(
            "<hh",
            raw,
            rec_start + 4*j
        )

        x += dx
        y += dy

        ok = inside(x, y, bbox)

        cum_hits += int(ok)

        if not ok:
            cum_ok = False

            if first_bad is None:
                first_bad = (
                    j,
                    dx,
                    dy,
                    x,
                    y,
                )

    result["cum_all"] = cum_ok
    result["cum_hits"] = cum_hits
    result["first_bad"] = first_bad

    # --------------------------------------------------
    # Interpretation B:
    # each pair relative to anchor
    # --------------------------------------------------

    rel_ok = result["anchor_inside"]
    rel_hits = int(result["anchor_inside"])

    for j in range(q):

        dx, dy = struct.unpack_from(
            "<hh",
            raw,
            rec_start + 4*j
        )

        x = x0 + dx
        y = y0 + dy

        ok = inside(x, y, bbox)

        rel_hits += int(ok)

        if not ok:
            rel_ok = False

    result["anchor_rel_all"] = rel_ok
    result["anchor_rel_hits"] = rel_hits

    # --------------------------------------------------
    # Interpretation C:
    # swapped cumulative dy,dx
    # --------------------------------------------------

    x = x0
    y = y0

    swap_ok = result["anchor_inside"]
    swap_hits = int(result["anchor_inside"])

    for j in range(q):

        a, b = struct.unpack_from(
            "<hh",
            raw,
            rec_start + 4*j
        )

        x += b
        y += a

        ok = inside(x, y, bbox)

        swap_hits += int(ok)

        if not ok:
            swap_ok = False

    result["swap_cum_all"] = swap_ok
    result["swap_cum_hits"] = swap_hits

    result["points"] = count

    return result


report = OUT / "mg_geometry_anchor_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, path in FILES.items():

        pages = load_pages(path)

        print("=" * 90, file=out)
        print("FILE:", name, file=out)
        print("PAGES:", len(pages), file=out)

        for section_name in (
            "S1",
            "S3",
        ):

            usable = 0
            q_match = 0
            anchor_inside = 0

            cum_all = 0
            rel_all = 0
            swap_all = 0

            total_points = 0
            cum_hits = 0
            rel_hits = 0
            swap_hits = 0

            examples = []

            for page_i, (bbox, raw) in enumerate(pages):

                h = struct.unpack_from(
                    "<23H",
                    raw,
                    0
                )

                if section_name == "S1":
                    start = h[0]
                    end = h[2]
                    count = h[1]

                else:
                    start = h[4]
                    end = h[6]
                    count = h[5]

                r = probe_section(
                    raw,
                    bbox,
                    start,
                    end,
                    count,
                )

                if not r["usable"]:
                    continue

                usable += 1
                q_match += int(r["q_match"])
                anchor_inside += int(
                    r["anchor_inside"]
                )

                if not r["q_match"]:
                    continue

                cum_all += int(r["cum_all"])
                rel_all += int(
                    r["anchor_rel_all"]
                )
                swap_all += int(
                    r["swap_cum_all"]
                )

                total_points += r["points"]

                cum_hits += r["cum_hits"]
                rel_hits += r["anchor_rel_hits"]
                swap_hits += r["swap_cum_hits"]

                if (
                    not r["cum_all"]
                    and len(examples) < 20
                ):
                    examples.append(
                        (
                            page_i,
                            bbox,
                            count,
                            r["first_bad"],
                        )
                    )

            print(file=out)
            print(section_name, file=out)

            print(
                "K=0 usable pages:",
                usable,
                file=out,
            )

            print(
                "q == count-1:",
                q_match,
                "/",
                usable,
                file=out,
            )

            print(
                "anchor X,Y inside bbox:",
                anchor_inside,
                "/",
                usable,
                file=out,
            )

            print(
                "cumulative s16 dx,dy ALL inside:",
                cum_all,
                "/",
                q_match,
                file=out,
            )

            print(
                "anchor-relative s16 dx,dy ALL inside:",
                rel_all,
                "/",
                q_match,
                file=out,
            )

            print(
                "swapped cumulative ALL inside:",
                swap_all,
                "/",
                q_match,
                file=out,
            )

            if total_points:
                print(
                    "cumulative point hits:",
                    cum_hits,
                    "/",
                    total_points,
                    f"({100*cum_hits/total_points:.4f}%)",
                    file=out,
                )

                print(
                    "anchor-relative point hits:",
                    rel_hits,
                    "/",
                    total_points,
                    f"({100*rel_hits/total_points:.4f}%)",
                    file=out,
                )

                print(
                    "swapped cumulative point hits:",
                    swap_hits,
                    "/",
                    total_points,
                    f"({100*swap_hits/total_points:.4f}%)",
                    file=out,
                )

            print(
                "FIRST CUMULATIVE FAILURES:",
                file=out,
            )

            for x in examples:
                print(" ", x, file=out)

print("Created:", report)
