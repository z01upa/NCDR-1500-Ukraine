"""Conservative full-file MP0 shape editor; never writes its source file.

Only an existing, ordinary shape-bearing edge can be edited. The writer
recompresses that block, preserves all other compressed streams and opaque
bytes, and rebuilds absolute stream pointers in physical stream order.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import zlib
from typing import Any

GEOMETRY_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = GEOMETRY_ROOT.parents[1]
WRITER_ROOT = Path(__file__).resolve().parent
if str(GEOMETRY_ROOT) not in sys.path:
    sys.path.insert(0, str(GEOMETRY_ROOT))
if str(WRITER_ROOT) not in sys.path:
    sys.path.insert(0, str(WRITER_ROOT))

from decoder import decode_mp0_polylines  # noqa: E402
from encoder import encode_shapes  # noqa: E402
from independent_verify import independent_blocks  # noqa: E402

DEFAULT_SOURCE = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3])) / 'SW' / 'DB' / 'EUZ.MP0'
DEFAULT_OUTPUT = WRITER_ROOT / "EUZ_MP0_block886_edge1_geometry_experiment.MP0"
HEADER_SIZE = 114
MP0_ENTRY_SIZE = 24
FEET_TO_METRES = 0.3048
FEET_ROUNDING_TOLERANCE_M = FEET_TO_METRES / 2.0 + 1e-9


class MP0FormatError(ValueError):
    """The input does not satisfy the format invariants already established."""


@dataclass(frozen=True)
class BlockEntry:
    index: int
    bbox: tuple[int, int, int, int]
    offset: int
    raw_size: int
    packed_size: int
    descriptor_offset: int
    packed: bytes
    raw: bytes


@dataclass(frozen=True)
class MP0Image:
    path: Path
    data: bytes
    sha256: str
    block_count: int
    index_end: int
    payload_start: int
    opaque_region: bytes
    entries: tuple[BlockEntry, ...]
    physical_order: tuple[BlockEntry, ...]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decompress_exact(packed: bytes, raw_size: int, block: int) -> bytes:
    decoder = zlib.decompressobj()
    raw = decoder.decompress(packed, raw_size + 1)
    if len(raw) > raw_size or decoder.unconsumed_tail:
        raise MP0FormatError(f"block {block}: decompressed data exceeds indexed size")
    raw += decoder.flush()
    if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
            or len(raw) != raw_size):
        raise MP0FormatError(f"block {block}: invalid zlib extent or decoded size")
    return raw


def read_mp0(path: Path) -> MP0Image:
    """Read and validate the established MP0 header, index and all 2956 streams."""
    path = path.expanduser().resolve(strict=True)
    data = path.read_bytes()
    if len(data) < HEADER_SIZE:
        raise MP0FormatError("MP0 is shorter than its verified 114-byte header")
    block_count = struct.unpack_from("<I", data, 86)[0]
    repeated_count = struct.unpack_from("<H", data, 112)[0]
    if not block_count or block_count != repeated_count:
        raise MP0FormatError(f"inconsistent MP0 block counts: {block_count}/{repeated_count}")
    index_end = HEADER_SIZE + MP0_ENTRY_SIZE * block_count
    payload_start = HEADER_SIZE + 28 * block_count
    if payload_start > len(data):
        raise MP0FormatError("MP0 index and opaque pre-payload region exceed file bounds")

    entries: list[BlockEntry] = []
    for index in range(block_count):
        descriptor_offset = HEADER_SIZE + MP0_ENTRY_SIZE * index
        bbox = struct.unpack_from("<4i", data, descriptor_offset)
        offset, raw_size, packed_size = struct.unpack_from("<IHH", data, descriptor_offset + 16)
        if not raw_size or not packed_size or offset < payload_start or offset + packed_size > len(data):
            raise MP0FormatError(f"block {index}: invalid absolute stream pointer or size")
        packed = data[offset:offset + packed_size]
        raw = _decompress_exact(packed, raw_size, index)
        # Reuse the current signed-secondary decoder as the established shape
        # table/edge invariant checker. It is not used for final readback.
        decode_mp0_polylines(raw)
        entries.append(BlockEntry(index, bbox, offset, raw_size, packed_size,
                                  descriptor_offset, packed, raw))

    physical_order = tuple(sorted(entries, key=lambda entry: entry.offset))
    cursor = payload_start
    for entry in physical_order:
        if entry.offset != cursor:
            raise MP0FormatError(
                f"non-contiguous physical stream order at block {entry.index}: "
                f"expected {cursor}, found {entry.offset}")
        cursor += entry.packed_size
    if cursor != len(data):
        raise MP0FormatError(f"unindexed bytes after final stream: end={cursor}, file={len(data)}")
    return MP0Image(path, data, _sha256(data), block_count, index_end, payload_start,
                    data[index_end:payload_start], tuple(entries), physical_order)


def _canonical_line(points: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    forward = tuple(points)
    reverse = tuple(reversed(points))
    return min(forward, reverse)


def cross_block_copies(image: MP0Image, block_index: int,
                       edge_index: int) -> list[dict[str, int]]:
    """Find exact geometry copies in other blocks using the independent reader."""
    if not 0 <= block_index < image.block_count:
        raise IndexError(f"block index out of range: {block_index}")
    lines = decode_mp0_polylines(image.entries[block_index].raw)
    if not 0 <= edge_index < len(lines):
        raise IndexError(f"edge index out of range in block {block_index}: {edge_index}")
    signature = _canonical_line(lines[edge_index]["coordinates_integer"])
    matches: list[dict[str, int]] = []
    # This parse is deliberately separate from writer decoding. The reader in
    # independent_verify.py does not import either decoder.py or encoder.py.
    for other_block, _nodes, _secondary, other_lines in independent_blocks(image.path):
        if other_block == block_index:
            continue
        for row in other_lines:
            if _canonical_line(row["points"]) == signature:
                matches.append({"block": other_block, "edge": int(row["edge"])})
    return matches


def _haversine_m(points: list[tuple[int, int]]) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        lat1, lat2 = math.radians(y1 / 100000.0), math.radians(y2 / 100000.0)
        dlat = lat2 - lat1
        dlon = math.radians((x2 - x1) / 100000.0)
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        total += 12742017.6 * math.asin(min(1.0, math.sqrt(a)))
    return total


def _rounded_feet(distance_m: float) -> int:
    return int(math.floor(distance_m / FEET_TO_METRES + 0.5))


def edit_one_shape_point(image: MP0Image, *, block_index: int = 886, edge_index: int = 1,
                         point_index: int = 1, dx: int = 5, dy: int = 0
                         ) -> tuple[bytes, dict[str, Any]]:
    """Edit exactly one existing interior vertex on a verified ordinary edge."""
    if not 0 <= block_index < image.block_count:
        raise IndexError(f"block index out of range: {block_index}")
    entry = image.entries[block_index]
    lines = decode_mp0_polylines(entry.raw)
    if not 0 <= edge_index < len(lines):
        raise IndexError(f"edge index out of range in block {block_index}: {edge_index}")
    if isinstance(dx, bool) or isinstance(dy, bool) or not isinstance(dx, int) or not isinstance(dy, int):
        raise TypeError("shape movement dx/dy must be integer coordinate units")
    if dx == 0 and dy == 0:
        raise ValueError("a nonzero point edit is required; use the no-op path for an unchanged image")

    target = lines[edge_index]
    old_points = list(target["coordinates_integer"])
    if not target["flags"] & 0x8000:
        raise ValueError("target edge has no existing shape-tail span")
    if not 0 < point_index < len(old_points) - 1:
        raise ValueError("point_index must select an existing interior shape point")

    copies = cross_block_copies(image, block_index, edge_index)
    if copies:
        raise MP0FormatError(
            f"refusing partial edit: edge has exact inter-block copies {copies}; "
            "v1 does not mutate reciprocal records")

    old_distance = _haversine_m(old_points)
    old_feet = int(target["length_field"])
    if (_rounded_feet(old_distance) != old_feet
            or abs(old_distance - old_feet * FEET_TO_METRES) > FEET_ROUNDING_TOLERANCE_M):
        raise MP0FormatError(
            f"target is not an ordinary rounded-feet edge; refusing to rewrite length: "
            f"geometry={old_distance:.6f}m, stored={old_feet}ft")

    x, y = old_points[point_index]
    new_point = (x + dx, y + dy)
    min_x, max_x = min(p[0] for p in old_points), max(p[0] for p in old_points)
    min_y, max_y = min(p[1] for p in old_points), max(p[1] for p in old_points)
    if not (min_x <= new_point[0] <= max_x and min_y <= new_point[1] <= max_y):
        raise ValueError("edited point must stay inside the edge's original geometry bounds")
    bx0, by0, bx1, by1 = entry.bbox
    if not (bx0 <= new_point[0] <= bx1 and by0 <= new_point[1] <= by1):
        raise ValueError("edited point would leave the indexed block bounding box")

    updated_lines = [dict(row, coordinates_integer=list(row["coordinates_integer"])) for row in lines]
    updated_lines[edge_index]["coordinates_integer"][point_index] = new_point
    edited_raw = bytearray(encode_shapes(entry.raw, updated_lines))
    new_distance = _haversine_m(updated_lines[edge_index]["coordinates_integer"])
    new_feet = _rounded_feet(new_distance)
    if not 0 <= new_feet <= 0xFFFFFFFF:
        raise ValueError("recomputed length does not fit the established u32 length field")
    record_offset = int(target["record_offset"])
    struct.pack_into("<I", edited_raw, record_offset + 10, new_feet)
    edited_raw = bytes(edited_raw)

    # Shape counts and block length must remain stable for this one-point edit.
    if len(edited_raw) != len(entry.raw):
        raise MP0FormatError("one-point shape edit unexpectedly changed decoded block size")
    allowed = set(range(record_offset + 10, record_offset + 14))
    pairs = list(struct.iter_unpack("<HH", entry.raw[:44]))
    shape_no = sum(1 for row in lines[:edge_index] if row["flags"] & 0x8000)
    shape_start, shape_count = pairs[10]
    offsets = struct.unpack_from("<" + "H" * (shape_count + 1), entry.raw, shape_start)
    if not 0 <= shape_no < shape_count:
        raise MP0FormatError("target edge does not map to a valid shape-tail span")
    span_start = shape_start + offsets[shape_no]
    for pair_no in (point_index - 1, point_index):
        pair_start = span_start + 4 * pair_no
        allowed.update(range(pair_start, pair_start + 4))
    raw_differences = [i for i, (old, new) in enumerate(zip(entry.raw, edited_raw)) if old != new]
    unexpected = sorted(set(raw_differences) - allowed)
    if unexpected:
        raise MP0FormatError(f"encoder changed unexpected decoded-block bytes at {unexpected[:12]}")

    reread = decode_mp0_polylines(edited_raw)[edge_index]
    if reread["coordinates_integer"] != updated_lines[edge_index]["coordinates_integer"]:
        raise MP0FormatError("current decoder did not recover the requested edited shape")
    if reread["length_field"] != new_feet:
        raise MP0FormatError("current decoder did not recover the recomputed length field")

    detail: dict[str, Any] = {
        "block": block_index,
        "edge": edge_index,
        "point_index": point_index,
        "before_point": list(old_points[point_index]),
        "after_point": list(new_point),
        "dx": dx,
        "dy": dy,
        "flags": int(target["flags"]),
        "length_raw_before_feet": old_feet,
        "length_raw_after_feet": new_feet,
        "geometry_length_before_m": old_distance,
        "geometry_length_after_m": new_distance,
        "stored_length_after_m": new_feet * FEET_TO_METRES,
        "stored_length_error_after_m": abs(new_distance - new_feet * FEET_TO_METRES),
        "record_offset_in_block": record_offset,
        "raw_changed_offsets": raw_differences,
        "raw_changed_byte_count": len(raw_differences),
        "cross_block_exact_copies": copies,
    }
    return edited_raw, detail


def rebuild_mp0(image: MP0Image, replacements: dict[int, bytes] | None = None) -> bytes:
    """Rebuild the complete MP0 while keeping physical payload order and opaque bytes."""
    replacements = replacements or {}
    if not replacements or all(replacements.get(i, entry.raw) == entry.raw
                               for i, entry in enumerate(image.entries)):
        return image.data
    if any(not 0 <= index < image.block_count for index in replacements):
        raise IndexError("replacement block index outside MP0 table")
    result = bytearray(image.data[:image.payload_start])
    for entry in image.physical_order:
        raw = replacements.get(entry.index, entry.raw)
        if len(raw) > 0xFFFF:
            raise ValueError(f"block {entry.index}: decoded size does not fit u16")
        decode_mp0_polylines(raw)
        packed = entry.packed if entry.index not in replacements else zlib.compress(raw, level=9)
        if len(packed) > 0xFFFF:
            raise ValueError(f"block {entry.index}: compressed size does not fit u16")
        if len(result) > 0xFFFFFFFF:
            raise ValueError("absolute block pointer does not fit u32")
        struct.pack_into("<IHH", result, entry.descriptor_offset + 16,
                         len(result), len(raw), len(packed))
        result.extend(packed)
    return bytes(result)


def _assert_output_in_writer_root(output: Path) -> Path:
    output = output.expanduser().resolve()
    root = WRITER_ROOT.resolve()
    if output == root or root not in output.parents:
        raise ValueError(f"experimental output must be inside {root}")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite an existing experiment: {output}")
    return output


def prepare_experiment(source: Path = DEFAULT_SOURCE, *, block: int = 886, edge: int = 1,
                       point_index: int = 1, dx: int = 5, dy: int = 0
                       ) -> tuple[MP0Image, bytes, dict[str, Any]]:
    image = read_mp0(source)
    edited_raw, edit = edit_one_shape_point(image, block_index=block, edge_index=edge,
                                            point_index=point_index, dx=dx, dy=dy)
    output = rebuild_mp0(image, {block: edited_raw})
    if output == image.data:
        raise MP0FormatError("requested edit produced a byte-identical full-file no-op")
    edit.update({
        "source_path": str(image.path),
        "source_sha256": image.sha256,
        "source_bytes": len(image.data),
        "output_bytes": len(output),
        "output_size_delta": len(output) - len(image.data),
        "block_count": image.block_count,
        "payload_start": image.payload_start,
        "opaque_region_bytes": len(image.opaque_region),
        "changed_compressed_blocks": [block],
    })
    return image, output, edit


def _pointer_change_report(image: MP0Image, rebuilt: bytes, target_block: int) -> dict[str, Any]:
    moved: list[dict[str, int]] = []
    target_sizes: dict[str, int] = {}
    for entry in image.entries:
        out_offset, out_raw_size, out_packed_size = struct.unpack_from(
            "<IHH", rebuilt, entry.descriptor_offset + 16)
        if out_offset != entry.offset:
            moved.append({"block": entry.index, "from": entry.offset, "to": out_offset})
        if entry.index == target_block:
            target_sizes = {"raw_size_before": entry.raw_size, "raw_size_after": out_raw_size,
                            "packed_size_before": entry.packed_size,
                            "packed_size_after": out_packed_size}
    return {"moved_absolute_pointer_entries": moved,
            "moved_absolute_pointer_entry_count": len(moved),
            "target_block_sizes": target_sizes,
            "header_0_113_preserved": rebuilt[:HEADER_SIZE] == image.data[:HEADER_SIZE],
            "opaque_pre_payload_region_preserved": (
                rebuilt[image.index_end:image.payload_start] == image.opaque_region)}


def _write_exclusive(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def run_experiment(source: Path = DEFAULT_SOURCE, output: Path = DEFAULT_OUTPUT, *,
                   block: int = 886, edge: int = 1, point_index: int = 1,
                   dx: int = 5, dy: int = 0, dry_run: bool = False
                   ) -> dict[str, Any]:
    """Write only a new file after independent readback passes; never overwrite."""
    source = Path(source).expanduser().resolve(strict=True)
    output = Path(output)
    if source == output.resolve():
        raise ValueError("output path resolves to the read-only source MP0")
    image, candidate, edit = prepare_experiment(
        source, block=block, edge=edge, point_index=point_index, dx=dx, dy=dy)
    output = _assert_output_in_writer_root(output)

    from verify_mp0 import verify_mp0  # independent Reader; does not import this module

    fd, temporary_name = tempfile.mkstemp(prefix=".mp0-writer-v1-", suffix=".candidate",
                                           dir=WRITER_ROOT)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(candidate)
        verification = verify_mp0(source, temporary, block=block, edge=edge,
                                  point_index=point_index, dx=dx, dy=dy)
        source_hash_after = _sha256(source.read_bytes())
        if source_hash_after != image.sha256:
            raise RuntimeError("source EUZ.MP0 hash changed during read-only experiment")
        if verification["status"] != "PASS":
            raise RuntimeError("independent full-file reader rejected candidate")
        if dry_run:
            return {"status": "DRY_RUN_PASS", "output_written": False, "edit": edit,
                    "verification": verification,
                    "container_changes": _pointer_change_report(image, candidate, block)}
        if output.exists():
            raise FileExistsError(f"refusing to overwrite an existing experiment: {output}")
        os.rename(temporary, output)
        return {"status": "PASS", "output_written": True, "output_path": str(output),
                "output_sha256": _sha256(output.read_bytes()), "edit": edit,
                "verification": verification,
                "container_changes": _pointer_change_report(image, candidate, block),
                "source_sha256_after": source_hash_after}
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--block", type=int, default=886, help="zero-based MP0 block index")
    parser.add_argument("--edge", type=int, default=1, help="zero-based edge index within its block")
    parser.add_argument("--point-index", type=int, default=1, help="zero-based interior point index")
    parser.add_argument("--dx", type=int, default=5, help="longitude-grid movement in 1e-5 degree units")
    parser.add_argument("--dy", type=int, default=0, help="latitude-grid movement in 1e-5 degree units")
    parser.add_argument("--dry-run", action="store_true", help="perform full independent validation without keeping an MP0")
    args = parser.parse_args()
    try:
        result = run_experiment(args.source, args.output, block=args.block, edge=args.edge,
                                point_index=args.point_index, dx=args.dx, dy=args.dy,
                                dry_run=args.dry_run)
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
