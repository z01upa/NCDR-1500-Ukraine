from pathlib import Path
from collections import defaultdict, Counter
import mmap
import struct
import hashlib
import math
import zlib

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


class NavZip:
    def __init__(self, path):
        self.path = path
        self.fh = path.open("rb")
        self.mm = mmap.mmap(
            self.fh.fileno(),
            0,
            access=mmap.ACCESS_READ
        )

        if self.mm[:4] != b"zip\x01":
            raise RuntimeError(
                f"{path} is not zip\\x01"
            )

        (
            self.block_size,
            self.total_size,
            self.max_packed,
        ) = struct.unpack_from("<III", self.mm, 4)

        self.nblocks = math.ceil(
            self.total_size / self.block_size
        )

        self.offsets = struct.unpack_from(
            "<" + "I" * (self.nblocks + 1),
            self.mm,
            16
        )

    def unpack_block(self, i):
        a = self.offsets[i]
        b = self.offsets[i + 1]

        packed = self.mm[a:b]
        raw = zlib.decompress(packed)

        expected = min(
            self.block_size,
            self.total_size - i * self.block_size
        )

        if len(raw) != expected:
            raise RuntimeError(
                f"{self.path.name} block {i}: "
                f"{len(raw)} != {expected}"
            )

        return raw

    def close(self):
        self.mm.close()
        self.fh.close()


def block_hash(raw):
    return hashlib.blake2b(
        raw,
        digest_size=16
    ).digest()


def make_index(nz):
    by_hash = defaultdict(list)
    first_bytes = {}

    for i in range(nz.nblocks):
        raw = nz.unpack_block(i)
        h = block_hash(raw)

        by_hash[h].append(i)

        if h not in first_bytes:
            first_bytes[h] = raw[:32]

    return by_hash, first_bytes


def unique_pairs(aidx, bidx):
    """
    Clean mapping: hashes which occur exactly once
    in A and exactly once in B.
    """
    pairs = []

    common = set(aidx) & set(bidx)

    for h in common:
        if len(aidx[h]) == 1 and len(bidx[h]) == 1:
            pairs.append(
                (aidx[h][0], bidx[h][0], h)
            )

    pairs.sort()

    return common, pairs


def consecutive_runs(pairs):
    """
    Group exact equal decompressed blocks where:
      A block increments by 1
      B block increments by 1
    """
    if not pairs:
        return []

    runs = []

    start_a, start_b, _ = pairs[0]
    prev_a = start_a
    prev_b = start_b
    count = 1

    for a, b, h in pairs[1:]:

        if a == prev_a + 1 and b == prev_b + 1:
            count += 1

        else:
            runs.append(
                (start_a, start_b, count)
            )

            start_a = a
            start_b = b
            count = 1

        prev_a = a
        prev_b = b

    runs.append(
        (start_a, start_b, count)
    )

    return runs


report = OUT / "mg_unpacked_blockmap.txt"

with report.open("w", encoding="utf-8") as out:

    for dataset, (root, names) in SETS.items():

        print("=" * 80, file=out)
        print("DATASET:", dataset, file=out)

        zips = {}
        indexes = {}
        previews = {}

        try:
            for name in names:

                nz = NavZip(root / name)
                zips[name] = nz

                print(file=out)
                print("FILE:", name, file=out)
                print(
                    "disk_size:",
                    (root / name).stat().st_size,
                    file=out,
                )
                print(
                    "block_size:",
                    nz.block_size,
                    file=out,
                )
                print(
                    "unpacked_size:",
                    nz.total_size,
                    file=out,
                )
                print(
                    "blocks:",
                    nz.nblocks,
                    file=out,
                )
                print(
                    "max_packed:",
                    nz.max_packed,
                    file=out,
                )

                idx, prv = make_index(nz)

                indexes[name] = idx
                previews[name] = prv

                duplicate_hashes = sum(
                    1 for v in idx.values()
                    if len(v) > 1
                )

                print(
                    "unique block hashes:",
                    len(idx),
                    file=out,
                )
                print(
                    "hashes repeated inside file:",
                    duplicate_hashes,
                    file=out,
                )

            for ia in range(len(names)):
                for ib in range(ia + 1, len(names)):

                    A = names[ia]
                    B = names[ib]

                    common, pairs = unique_pairs(
                        indexes[A],
                        indexes[B]
                    )

                    print(file=out)
                    print("-" * 80, file=out)
                    print(f"{A} <-> {B}", file=out)

                    print(
                        "COMMON RAW BLOCK HASHES:",
                        len(common),
                        file=out,
                    )

                    print(
                        "UNIQUE<->UNIQUE BLOCKS:",
                        len(pairs),
                        file=out,
                    )

                    deltas = Counter(
                        b - a
                        for a, b, _ in pairs
                    )

                    print("TOP BLOCK DELTAS:", file=out)

                    for d, n in deltas.most_common(30):
                        print(
                            f"  delta_blocks={d:+d} "
                            f"delta_bytes={d * 3072:+d} "
                            f"count={n}",
                            file=out,
                        )

                    runs = consecutive_runs(pairs)

                    runs.sort(
                        key=lambda x: (-x[2], x[0], x[1])
                    )

                    print(
                        "CONSECUTIVE BLOCK RUNS:",
                        len(runs),
                        file=out,
                    )

                    print(
                        "LONGEST RUNS:",
                        file=out,
                    )

                    for a, b, count in runs[:50]:

                        size = count * 3072

                        print(
                            f"  blocks={count:5d} "
                            f"bytes~={size:10d} "
                            f"A_block={a:6d} "
                            f"B_block={b:6d} "
                            f"delta={b-a:+d}",
                            file=out,
                        )

                        if count:
                            h = None

                            for aa, bb, hh in pairs:
                                if aa == a and bb == b:
                                    h = hh
                                    break

                            if h:
                                print(
                                    "    first32=",
                                    previews[A][h].hex(),
                                    file=out,
                                )

        finally:
            for nz in zips.values():
                nz.close()

print("Created:", report)
