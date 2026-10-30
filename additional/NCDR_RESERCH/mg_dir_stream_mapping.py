from pathlib import Path
from collections import defaultdict, Counter
import hashlib
import struct
import zlib

OUT = Path.home() / "Desktop" / "NCDR_RESERCH"
ROOT = Path("/Volumes/CD_7185/DB")

HEADER = 0x72
ENTRY = 0x1C

FILES = {
    "MG1": ROOT / "IZ.MG1",
    "MG2": ROOT / "IZ.MG2",
}


def count_from_header(data):
    first = data.find(b"\x78\xDA")
    n = (first - HEADER) // ENTRY
    return n, first


def streams(data, first):
    result = []
    pos = first

    while pos < len(data):
        d = zlib.decompressobj()
        raw = d.decompress(data[pos:])

        if not d.eof:
            raise RuntimeError(f"bad zlib at 0x{pos:X}")

        consumed = len(data[pos:]) - len(d.unused_data)
        end = pos + consumed
        raw += d.flush()

        h = hashlib.blake2b(raw, digest_size=16).digest()

        result.append({
            "start": pos,
            "end": end,
            "raw": raw,
            "hash": h,
        })

        pos = end

    return result


def dir_records(data, n):
    result = []

    for i in range(n):
        off = HEADER + i * ENTRY
        raw = data[off:off+ENTRY]

        vals = struct.unpack("<7i", raw)

        result.append({
            "raw": raw,
            "vals": vals,
        })

    return result


DATA = {}
STREAMS = {}
DIRS = {}

for name, path in FILES.items():
    data = path.read_bytes()
    n, first = count_from_header(data)
    ss = streams(data, first)
    dd = dir_records(data, n)

    assert len(ss) == n
    assert len(dd) == n

    DATA[name] = data
    STREAMS[name] = ss
    DIRS[name] = dd


def hash_index(ss):
    d = defaultdict(list)

    for i, s in enumerate(ss):
        d[s["hash"]].append(i)

    return d


H1 = hash_index(STREAMS["MG1"])
H2 = hash_index(STREAMS["MG2"])

unique_common = [
    h for h in set(H1) & set(H2)
    if len(H1[h]) == 1 and len(H2[h]) == 1
]

report = OUT / "mg_dir_stream_mapping.txt"

with report.open("w", encoding="utf-8") as out:

    print("MG1 streams:", len(STREAMS["MG1"]), file=out)
    print("MG2 streams:", len(STREAMS["MG2"]), file=out)
    print("UNIQUE COMMON RAW STREAMS:", len(unique_common), file=out)
    print(file=out)

    exact_dir = 0
    same_slot = Counter()
    delta_vectors = Counter()

    # Does a directory record associated with a common stream
    # appear anywhere in the other directory?
    dir2_lookup = defaultdict(list)

    for i, d in enumerate(DIRS["MG2"]):
        dir2_lookup[d["raw"]].append(i)

    record_found_anywhere = 0
    record_found_at_matching_stream = 0

    examples = []

    for h in unique_common:

        i1 = H1[h][0]
        i2 = H2[h][0]

        d1 = DIRS["MG1"][i1]
        d2 = DIRS["MG2"][i2]

        if d1["raw"] == d2["raw"]:
            exact_dir += 1

        for slot, (a, b) in enumerate(
            zip(d1["vals"], d2["vals"])
        ):
            if a == b:
                same_slot[slot] += 1

        delta = tuple(
            b - a
            for a, b in zip(d1["vals"], d2["vals"])
        )

        delta_vectors[delta] += 1

        locations = dir2_lookup.get(d1["raw"], [])

        if locations:
            record_found_anywhere += 1

            if i2 in locations:
                record_found_at_matching_stream += 1

        if len(examples) < 50:
            examples.append(
                (i1, i2, d1["vals"], d2["vals"], delta, locations)
            )

    print("EXACT DIR RECORD AT MATCHED STREAM:", exact_dir, file=out)
    print(
        "DIR RECORD FOUND ANYWHERE IN MG2:",
        record_found_anywhere,
        file=out,
    )
    print(
        "FOUND AT MATCHED STREAM INDEX:",
        record_found_at_matching_stream,
        file=out,
    )

    print(file=out)
    print("SAME S32 SLOT COUNTS:", file=out)

    for slot in range(7):
        print(
            f"slot{slot}: "
            f"{same_slot[slot]}/{len(unique_common)}",
            file=out,
        )

    print(file=out)
    print("TOP FULL 7-VALUE DELTA VECTORS:", file=out)

    for delta, n in delta_vectors.most_common(30):
        print(n, delta, file=out)

    print(file=out)
    print("EXAMPLES:", file=out)

    for i1, i2, a, b, delta, locations in examples:
        print("-" * 78, file=out)
        print(
            f"MG1 stream #{i1}  MG2 stream #{i2}",
            file=out,
        )
        print("MG1:", a, file=out)
        print("MG2:", b, file=out)
        print("DELTA:", delta, file=out)
        print(
            "MG1 dir record occurs in MG2 at:",
            locations[:20],
            file=out,
        )

    # ------------------------------------------------------------
    # Independent test:
    # identical directory records across files.
    # Do their associated stream hashes also match?
    # ------------------------------------------------------------

    map1 = defaultdict(list)
    map2 = defaultdict(list)

    for i, d in enumerate(DIRS["MG1"]):
        map1[d["raw"]].append(i)

    for i, d in enumerate(DIRS["MG2"]):
        map2[d["raw"]].append(i)

    common_dir = set(map1) & set(map2)

    total_pairs = 0
    hash_match_pairs = 0

    print(file=out)
    print("COMMON DIRECTORY RECORDS:", len(common_dir), file=out)

    for rec in common_dir:
        for i1 in map1[rec]:
            for i2 in map2[rec]:
                total_pairs += 1

                if (
                    STREAMS["MG1"][i1]["hash"]
                    == STREAMS["MG2"][i2]["hash"]
                ):
                    hash_match_pairs += 1

    print(
        "COMMON-DIR INDEX PAIRS:",
        total_pairs,
        file=out,
    )

    print(
        "OF THOSE, RAW STREAM HASH ALSO MATCHES:",
        hash_match_pairs,
        file=out,
    )

print("Created:", report)
