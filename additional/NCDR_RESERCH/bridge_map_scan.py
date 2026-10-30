from pathlib import Path
from collections import Counter
import struct
import zlib
import math

SCALE = 5_555_555.0
OUT = Path.home() / "Desktop" / "NCDR_RESERCH"

DATASETS = [
    (
        "7185",
        Path("/Volumes/CD_7185/DB"),
        ["IZ.MP0", "IZ.FEA", "IZ.MG1", "IZ.MG2", "IZ.MG3"],
        (6.0, 19.0, 35.0, 48.0),
    ),
    (
        "7186",
        Path("/Volumes/CD_7186/DB"),
        ["SCZ.MP0", "SCZ.FEA", "SCZ.MG1", "SCZ.MG2", "SCZ.MG3"],
        (4.0, 33.0, 53.0, 73.0),
    ),
]


def navzip_unpack(data):
    if not data.startswith(b"zip\x01"):
        return data, None

    block_size, total_size, max_packed = struct.unpack_from("<III", data, 4)
    nblocks = math.ceil(total_size / block_size)
    offsets = struct.unpack_from("<" + "I" * (nblocks + 1), data, 16)

    out = bytearray()

    for a, b in zip(offsets, offsets[1:]):
        out.extend(zlib.decompress(data[a:b]))

    if len(out) != total_size:
        raise RuntimeError(
            f"size mismatch {len(out)} != {total_size}"
        )

    return bytes(out), {
        "block_size": block_size,
        "total_size": total_size,
        "blocks": nblocks,
        "max_packed": max_packed,
    }


def ranges(box):
    lon0, lon1, lat0, lat1 = box

    return (
        int((lon0 + 30) * SCALE),
        int((lon1 + 30) * SCALE),
        int(lat0 * SCALE),
        int(lat1 * SCALE),
    )


def scan(payload, box):
    xmin, xmax, ymin, ymax = ranges(box)

    hits = []

    # Try all four 32-bit alignment phases.
    for phase in range(4):
        for off in range(phase, len(payload) - 7, 4):
            x, y = struct.unpack_from(">II", payload, off)

            if xmin <= x <= xmax and ymin <= y <= ymax:
                lon = x / SCALE - 30
                lat = y / SCALE
                hits.append((off, lon, lat))

    hits.sort()
    hs = {x[0] for x in hits}

    stride_stats = []

    # Do not assume 24-byte records.
    for stride in range(4, 129, 4):
        pairs = sum(1 for off in hs if off + stride in hs)
        triples = sum(
            1 for off in hs
            if off + stride in hs and off + stride * 2 in hs
        )

        if pairs or triples:
            stride_stats.append((stride, pairs, triples))

    stride_stats.sort(key=lambda x: (-x[2], -x[1], x[0]))

    return hits, stride_stats


report = OUT / "bridge_map_scan.txt"

with report.open("w", encoding="utf-8") as out:

    for ds, root, files, box in DATASETS:

        for name in files:
            p = root / name
            data = p.read_bytes()

            print("=" * 78, file=out)
            print("DATASET:", ds, file=out)
            print("FILE:", name, file=out)
            print("DISK SIZE:", len(data), file=out)

            raw, zi = navzip_unpack(data)

            if zi:
                print("FORMAT: NAVTEQ ZIP", file=out)
                print("UNPACKED SIZE:", zi["total_size"], file=out)
                print("BLOCKS:", zi["blocks"], file=out)
            else:
                print("FORMAT: RAW", file=out)

            hits, strides = scan(raw, box)

            print("BE MULCOORD HITS:", len(hits), file=out)

            residues = Counter(off % 64 for off, _, _ in hits)
            print("MOD64 TOP:", residues.most_common(16), file=out)

            print("TOP STRIDES (stride, pairs, triples):", file=out)
            for row in strides[:20]:
                print(" ", row, file=out)

            print("FIRST HITS:", file=out)

            for off, lon, lat in hits[:30]:
                a = max(0, off - 8)
                b = min(len(raw), off + 32)

                print(
                    f"  0x{off:08X} "
                    f"{lon:.7f},{lat:.7f} "
                    f"context={raw[a:b].hex()}",
                    file=out,
                )

            print(file=out)

print("Created:", report)
