from pathlib import Path
from collections import defaultdict
import hashlib
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
CHUNK = 65536


def parse_stream(data, start):
    d = zlib.decompressobj()
    pos = start
    h = hashlib.blake2b(digest_size=16)
    raw_len = 0

    while True:
        src = data[pos:min(pos + CHUNK, len(data))]

        if not src:
            raise RuntimeError(
                f"unterminated stream at 0x{start:X}"
            )

        raw = d.decompress(src)

        if raw:
            h.update(raw)
            raw_len += len(raw)

        if d.eof:
            consumed = len(src) - len(d.unused_data)
            end = pos + consumed
            break

        pos += len(src)

    return {
        "end": end,
        "raw_len": raw_len,
        "hash": h.digest(),
    }


def load_file(path):
    data = path.read_bytes()

    n = struct.unpack_from("<I", data, 0x56)[0]
    level = struct.unpack_from("<H", data, 0x6E)[0]

    bbox_off = HDR
    meta_off = bbox_off + n * 16
    zero_off = meta_off + n * 8
    payload_off = zero_off + n * 4

    boxes = [
        struct.unpack_from(
            "<4i",
            data,
            bbox_off + i * 16
        )
        for i in range(n)
    ]

    meta = [
        struct.unpack_from(
            "<2I",
            data,
            meta_off + i * 8
        )
        for i in range(n)
    ]

    offsets = [m[0] for m in meta]

    if len(set(offsets)) != n:
        raise RuntimeError(
            f"{path.name}: duplicate stream offsets"
        )

    physical = {}

    pos = payload_off

    while pos < len(data):
        s = parse_stream(data, pos)

        physical[pos] = s

        pos = s["end"]

    if len(physical) != n:
        raise RuntimeError(
            f"{path.name}: "
            f"{len(physical)} streams != {n}"
        )

    missing = [
        x for x in offsets
        if x not in physical
    ]

    if missing:
        raise RuntimeError(
            f"{path.name}: bad meta0 pointers "
            f"{missing[:10]}"
        )

    pages = []

    for i in range(n):
        bbox = boxes[i]
        stream_off, key = meta[i]
        stream = physical[stream_off]

        pages.append({
            "index": i,
            "bbox": bbox,
            "key": key,
            "stream_off": stream_off,
            "hash": stream["hash"],
            "raw_len": stream["raw_len"],
        })

    return {
        "level": level,
        "pages": pages,
    }


def make_map(pages, field):
    result = defaultdict(list)

    for p in pages:
        result[p[field]].append(p)

    return result


DB = {}

for name, path in FILES.items():
    DB[name] = load_file(path)


report = OUT / "mg_page_key_probe.txt"

with report.open("w", encoding="utf-8") as out:

    for name, db in DB.items():

        pages = db["pages"]

        keys = make_map(pages, "key")
        boxes = make_map(pages, "bbox")
        hashes = make_map(pages, "hash")

        print("=" * 90, file=out)
        print("FILE:", name, file=out)
        print("LEVEL:", db["level"], file=out)
        print("PAGES:", len(pages), file=out)

        print(
            "UNIQUE META1:",
            len(keys),
            "/",
            len(pages),
            file=out,
        )

        print(
            "UNIQUE BBOX:",
            len(boxes),
            "/",
            len(pages),
            file=out,
        )

        print(
            "UNIQUE RAW HASH:",
            len(hashes),
            "/",
            len(pages),
            file=out,
        )

        topbit = sum(
            1 for p in pages
            if p["key"] & 0x80000000
        )

        print(
            "META1 TOP BIT SET:",
            topbit,
            "/",
            len(pages),
            file=out,
        )

    names = list(DB)

    for ia in range(len(names)):
        for ib in range(ia + 1, len(names)):

            A = names[ia]
            B = names[ib]

            pa = DB[A]["pages"]
            pb = DB[B]["pages"]

            ba = make_map(pa, "bbox")
            bb = make_map(pb, "bbox")

            ka = make_map(pa, "key")
            kb = make_map(pb, "key")

            ha = make_map(pa, "hash")
            hb = make_map(pb, "hash")

            print(file=out)
            print("=" * 90, file=out)
            print(A, "<->", B, file=out)

            # --------------------------------------------
            # Same bbox
            # --------------------------------------------

            common_bbox = set(ba) & set(bb)

            bbox_unique = [
                x for x in common_bbox
                if len(ba[x]) == 1
                and len(bb[x]) == 1
            ]

            bbox_same_key = 0
            bbox_same_hash = 0

            for x in bbox_unique:
                a = ba[x][0]
                b = bb[x][0]

                bbox_same_key += (
                    a["key"] == b["key"]
                )

                bbox_same_hash += (
                    a["hash"] == b["hash"]
                )

            print(
                "COMMON BBOX:",
                len(common_bbox),
                file=out,
            )

            print(
                "UNIQUE COMMON BBOX:",
                len(bbox_unique),
                file=out,
            )

            print(
                "  same META1:",
                bbox_same_key,
                "/",
                len(bbox_unique),
                file=out,
            )

            print(
                "  same RAW HASH:",
                bbox_same_hash,
                "/",
                len(bbox_unique),
                file=out,
            )

            # --------------------------------------------
            # Same META1
            # --------------------------------------------

            common_key = set(ka) & set(kb)

            key_unique = [
                x for x in common_key
                if len(ka[x]) == 1
                and len(kb[x]) == 1
            ]

            key_same_bbox = 0
            key_same_hash = 0

            for x in key_unique:
                a = ka[x][0]
                b = kb[x][0]

                key_same_bbox += (
                    a["bbox"] == b["bbox"]
                )

                key_same_hash += (
                    a["hash"] == b["hash"]
                )

            print(
                "COMMON META1:",
                len(common_key),
                file=out,
            )

            print(
                "UNIQUE COMMON META1:",
                len(key_unique),
                file=out,
            )

            print(
                "  same BBOX:",
                key_same_bbox,
                "/",
                len(key_unique),
                file=out,
            )

            print(
                "  same RAW HASH:",
                key_same_hash,
                "/",
                len(key_unique),
                file=out,
            )

            # --------------------------------------------
            # Same raw payload
            # --------------------------------------------

            common_hash = set(ha) & set(hb)

            hash_unique = [
                x for x in common_hash
                if len(ha[x]) == 1
                and len(hb[x]) == 1
            ]

            hash_same_bbox = 0
            hash_same_key = 0

            for x in hash_unique:
                a = ha[x][0]
                b = hb[x][0]

                hash_same_bbox += (
                    a["bbox"] == b["bbox"]
                )

                hash_same_key += (
                    a["key"] == b["key"]
                )

            print(
                "COMMON RAW HASH:",
                len(common_hash),
                file=out,
            )

            print(
                "UNIQUE COMMON RAW HASH:",
                len(hash_unique),
                file=out,
            )

            print(
                "  same BBOX:",
                hash_same_bbox,
                "/",
                len(hash_unique),
                file=out,
            )

            print(
                "  same META1:",
                hash_same_key,
                "/",
                len(hash_unique),
                file=out,
            )

            # Useful concrete examples.
            shown = 0

            print("SAME-BBOX EXAMPLES:", file=out)

            for bbox in bbox_unique:

                a = ba[bbox][0]
                b = bb[bbox][0]

                print(
                    " ",
                    bbox,
                    f"Akey=0x{a['key']:08X}",
                    f"Bkey=0x{b['key']:08X}",
                    "same_raw=",
                    a["hash"] == b["hash"],
                    file=out,
                )

                shown += 1

                if shown >= 15:
                    break

print("Created:", report)
