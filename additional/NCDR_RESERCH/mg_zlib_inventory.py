from pathlib import Path
from collections import Counter, defaultdict
import mmap
import zlib
import hashlib

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"

SETS = {
    "7185": (
        Path("/Volumes/CD_7185/DB"),
        ["IZ.MG1", "IZ.MG2", "IZ.MG3"],
    ),
    "7186": (
        Path("/Volumes/CD_7186/DB"),
        ["SCZ.MG1", "SCZ.MG2", "SCZ.MG3"],
    ),
}

CHUNK = 65536
MAX_RAW = 64 * 1024 * 1024


def valid_header(mm, off):
    if off + 2 > len(mm):
        return False

    cmf = mm[off]
    flg = mm[off + 1]

    if (cmf & 0x0f) != 8:
        return False

    if (cmf >> 4) > 7:
        return False

    return ((cmf << 8) | flg) % 31 == 0


def parse_stream(mm, start):
    d = zlib.decompressobj()
    pos = start

    raw_len = 0
    h = hashlib.blake2b(digest_size=16)

    first = bytearray()
    last = bytearray()

    try:
        while pos < len(mm):
            stop = min(pos + CHUNK, len(mm))
            src = bytes(mm[pos:stop])

            raw = d.decompress(src)

            if raw:
                raw_len += len(raw)

                if raw_len > MAX_RAW:
                    return None

                h.update(raw)

                if len(first) < 64:
                    need = 64 - len(first)
                    first.extend(raw[:need])

                last.extend(raw)
                if len(last) > 64:
                    del last[:-64]

            pos = stop

            if d.eof:
                end = pos - len(d.unused_data)

                if end <= start:
                    return None

                return {
                    "start": start,
                    "end": end,
                    "packed_len": end - start,
                    "raw_len": raw_len,
                    "header": bytes(mm[start:start+2]).hex(),
                    "trailer": bytes(mm[end-4:end]).hex(),
                    "hash": h.hexdigest(),
                    "first64": bytes(first).hex(),
                    "last64": bytes(last).hex(),
                }

    except zlib.error:
        return None

    return None


def scan_file(path):
    fh = path.open("rb")
    mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)

    streams = []
    gaps = []

    cursor = 0
    previous_end = 0

    while cursor < len(mm) - 1:

        candidate = mm.find(b"\x78", cursor)

        if candidate < 0:
            break

        if not valid_header(mm, candidate):
            cursor = candidate + 1
            continue

        s = parse_stream(mm, candidate)

        if s is None:
            cursor = candidate + 1
            continue

        if candidate > previous_end:
            gaps.append((previous_end, candidate))

        streams.append(s)

        previous_end = s["end"]
        cursor = s["end"]

    if previous_end < len(mm):
        gaps.append((previous_end, len(mm)))

    size = len(mm)

    mm.close()
    fh.close()

    return size, streams, gaps


report = OUT / "mg_zlib_inventory.txt"

with report.open("w", encoding="utf-8") as out:

    all_streams = {}

    for dataset, (root, names) in SETS.items():

        print("=" * 80, file=out)
        print("DATASET:", dataset, file=out)

        for name in names:
            size, streams, gaps = scan_file(root / name)

            all_streams[(dataset, name)] = streams

            covered = sum(
                s["packed_len"] for s in streams
            )

            gap_bytes = sum(
                e - s for s, e in gaps
            )

            print(file=out)
            print("FILE:", name, file=out)
            print("FILE SIZE:", size, file=out)
            print("ZLIB STREAMS:", len(streams), file=out)
            print("ZLIB COVERED:", covered, file=out)
            print(
                "COVERAGE:",
                f"{covered / size * 100:.4f}%",
                file=out,
            )
            print("GAPS:", len(gaps), file=out)
            print("GAP BYTES:", gap_bytes, file=out)

            if gaps:
                lengths = [e-s for s,e in gaps]

                print(
                    "MAX GAP:",
                    max(lengths),
                    file=out,
                )

                print(
                    "TOP GAP LENGTHS:",
                    Counter(lengths).most_common(20),
                    file=out,
                )

            print(
                "HEADERS:",
                Counter(
                    s["header"] for s in streams
                ),
                file=out,
            )

            print(
                "TOP RAW LENGTHS:",
                Counter(
                    s["raw_len"] for s in streams
                ).most_common(20),
                file=out,
            )

            print(
                "TOP PACKED LENGTHS:",
                Counter(
                    s["packed_len"] for s in streams
                ).most_common(20),
                file=out,
            )

            print("FIRST STREAMS:", file=out)

            for i, s in enumerate(streams[:30]):

                print(
                    f"  #{i:04d} "
                    f"0x{s['start']:X}..0x{s['end']:X} "
                    f"packed={s['packed_len']} "
                    f"raw={s['raw_len']} "
                    f"hdr={s['header']} "
                    f"adler={s['trailer']}",
                    file=out,
                )

                print(
                    "     first64=",
                    s["first64"],
                    file=out,
                )

        # Compare the three levels using decompressed hashes.
        print(file=out)
        print("CROSS-LEVEL RAW HASH COMPARISON:", file=out)

        for ia in range(len(names)):
            for ib in range(ia + 1, len(names)):

                A = names[ia]
                B = names[ib]

                sa = all_streams[(dataset, A)]
                sb = all_streams[(dataset, B)]

                ha = Counter(x["hash"] for x in sa)
                hb = Counter(x["hash"] for x in sb)

                common_hashes = set(ha) & set(hb)

                exact_streams = sum(
                    min(ha[h], hb[h])
                    for h in common_hashes
                )

                print(file=out)
                print(f"{A} <-> {B}", file=out)
                print(
                    "COMMON RAW HASHES:",
                    len(common_hashes),
                    file=out,
                )
                print(
                    "EXACT RAW STREAM MATCHES:",
                    exact_streams,
                    file=out,
                )

                # Same size + same beginning/end is a useful
                # candidate for near-identical chunks.
                ka = Counter(
                    (
                        x["raw_len"],
                        x["first64"][:32],
                        x["last64"][-32:],
                    )
                    for x in sa
                )

                kb = Counter(
                    (
                        x["raw_len"],
                        x["first64"][:32],
                        x["last64"][-32:],
                    )
                    for x in sb
                )

                near_keys = set(ka) & set(kb)

                near_count = sum(
                    min(ka[k], kb[k])
                    for k in near_keys
                )

                print(
                    "SAME LEN/FIRST16/LAST16:",
                    near_count,
                    file=out,
                )

print("Created:", report)
