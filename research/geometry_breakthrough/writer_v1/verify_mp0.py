"""Independent whole-container MP0 validation; imports no Writer or decoder."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import os
import struct
import sys
import zlib
from typing import Any, Iterator

GEOMETRY_ROOT = Path(__file__).resolve().parents[1]
if str(GEOMETRY_ROOT) not in sys.path:
    sys.path.insert(0, str(GEOMETRY_ROOT))

from independent_verify import distance, independent_blocks  # noqa: E402

HEADER_SIZE = 114
ENTRY_SIZE = 24
FEET_TO_METRES = 0.3048
LENGTH_TOLERANCE_M = FEET_TO_METRES / 2 + 1e-9
EXPECTED_BLOCK_COUNT = 2956
EXPECTED_EDGE_COUNT = 1_090_323


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _inflate_exact(packed: bytes, size: int, block: int) -> bytes:
    inflater = zlib.decompressobj()
    raw = inflater.decompress(packed, size + 1)
    if len(raw) > size or inflater.unconsumed_tail:
        raise ValueError(f"block {block}: uncompressed data exceeds indexed size")
    raw += inflater.flush()
    if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail or len(raw) != size:
        raise ValueError(f"block {block}: bad zlib stream end or size")
    return raw


def _container(path: Path) -> dict[str, Any]:
    """Read all MP0 index rows and inflate each stream with strict bounds."""
    path = Path(path).resolve(strict=True)
    data = path.read_bytes()
    if len(data) < HEADER_SIZE:
        raise ValueError("file shorter than MP0 header")
    count = struct.unpack_from("<I", data, 86)[0]
    repeated = struct.unpack_from("<H", data, 112)[0]
    if count != EXPECTED_BLOCK_COUNT or repeated != count:
        raise ValueError(f"expected {EXPECTED_BLOCK_COUNT} matching header counts, got {count}/{repeated}")
    index_end = HEADER_SIZE + ENTRY_SIZE * count
    payload_start = HEADER_SIZE + 28 * count
    if payload_start > len(data):
        raise ValueError("header/index and opaque bytes exceed file length")
    entries: list[dict[str, Any]] = []
    for block in range(count):
        entry_at = HEADER_SIZE + ENTRY_SIZE * block
        bbox = struct.unpack_from("<4i", data, entry_at)
        offset, raw_size, packed_size = struct.unpack_from("<IHH", data, entry_at + 16)
        if offset < payload_start or raw_size == 0 or packed_size == 0 or offset + packed_size > len(data):
            raise ValueError(f"block {block}: pointer or size outside file bounds")
        packed = data[offset:offset + packed_size]
        raw = _inflate_exact(packed, raw_size, block)
        entries.append({"index": block, "bbox": bbox, "offset": offset,
                        "raw_size": raw_size, "packed_size": packed_size,
                        "entry_at": entry_at, "packed": packed, "raw": raw})
    physical = sorted(entries, key=lambda row: row["offset"])
    cursor = payload_start
    for row in physical:
        if row["offset"] != cursor:
            raise ValueError(f"physical payload gap/overlap at block {row['index']}: {cursor} != {row['offset']}")
        cursor += row["packed_size"]
    if cursor != len(data):
        raise ValueError(f"trailing/unindexed bytes after payload: {cursor} != {len(data)}")
    return {"path": path, "data": data, "sha256": hashlib.sha256(data).hexdigest(),
            "count": count, "index_end": index_end, "payload_start": payload_start,
            "opaque": data[index_end:payload_start], "entries": entries,
            "physical": physical}


def _word(data: bytes, offset: int, size: int = 2, signed: bool = False) -> int:
    return int.from_bytes(data[offset:offset + size], "little", signed=signed)


def _allowed_raw_differences(raw: bytes, edge: int, point_index: int) -> set[int]:
    """The one length field and the two adjacent shape-tail delta pairs only."""
    sections = [_word(raw, 4 * i) for i in range(11)]
    counts = [_word(raw, 4 * i + 2) for i in range(11)]
    edge_start, edge_count = sections[5], counts[5]
    if not 0 <= edge < edge_count:
        raise ValueError("target edge not in independently decoded edge table")
    edge_record = edge_start + 14 * edge
    flags = _word(raw, edge_record)
    if not flags & 0x8000:
        raise ValueError("target edge has no existing shape-tail entry")
    if not 0 < point_index:
        raise ValueError("target point must be a one-based interior index")
    shape_number = sum(bool(_word(raw, edge_start + 14 * i) & 0x8000) for i in range(edge))
    shape_count = counts[10]
    if shape_number >= shape_count:
        raise ValueError("target shape-tail number exceeds shape table")
    tail_at = sections[10]
    offsets = [_word(raw, tail_at + 2 * i) for i in range(shape_count + 1)]
    span_start = tail_at + offsets[shape_number]
    span_end = tail_at + offsets[shape_number + 1]
    pair_index = point_index - 1
    pair_count = (span_end - span_start) // 4
    if pair_index < 0 or pair_index + 1 >= pair_count:
        raise ValueError("target interior vertex does not have two adjacent shape deltas")
    allowed = set(range(edge_record + 10, edge_record + 14))
    for pair in (pair_index, pair_index + 1):
        start = span_start + pair * 4
        allowed.update(range(start, start + 4))
    return allowed


def _canon(points: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    forward, reverse = tuple(points), tuple(reversed(points))
    return min(forward, reverse)


def _rounded_feet(metres: float) -> int:
    return int(math.floor(metres / FEET_TO_METRES + 0.5))


def verify_mp0(source: Path, candidate: Path, *, block: int = 886, edge: int = 1,
               point_index: int = 1, dx: int = 5, dy: int = 0) -> dict[str, Any]:
    """Validate full-file extents, independent decode, exact changes and source hash."""
    source, candidate = Path(source).resolve(strict=True), Path(candidate).resolve(strict=True)
    if source == candidate:
        raise ValueError("candidate path must differ from the original source")
    source_sha_before = _hash(source)
    original, output = _container(source), _container(candidate)
    if original["count"] != output["count"]:
        raise ValueError("block count changed")
    if original["data"][:HEADER_SIZE] != output["data"][:HEADER_SIZE]:
        raise ValueError("header bytes changed")
    if original["opaque"] != output["opaque"]:
        raise ValueError("opaque pre-payload service bytes changed")

    if not 0 <= block < original["count"]:
        raise IndexError(f"block index out of range: {block}")
    changed_blocks: list[int] = []
    raw_changed_offsets: list[int] = []
    moved_pointers: list[int] = []
    for before, after in zip(original["entries"], output["entries"], strict=True):
        if before["index"] != after["index"] or before["bbox"] != after["bbox"]:
            raise ValueError(f"block {before['index']}: index or bbox changed")
        if before["raw"] != after["raw"]:
            changed_blocks.append(before["index"])
            if before["index"] != block:
                raise ValueError(f"unmodified block {before['index']} decoded bytes changed")
            if len(before["raw"]) != len(after["raw"]):
                raise ValueError("edited block decoded size changed")
            diff = [i for i, (a, b) in enumerate(zip(before["raw"], after["raw"])) if a != b]
            allowed = _allowed_raw_differences(before["raw"], edge, point_index)
            if set(diff) - allowed:
                raise ValueError(f"edited block has unrelated raw changes at {sorted(set(diff)-allowed)[:12]}")
            raw_changed_offsets = diff
        elif before["packed"] != after["packed"]:
            raise ValueError(f"block {before['index']} recompressed despite identical raw bytes")
        if before["offset"] != after["offset"]:
            moved_pointers.append(before["index"])
    if changed_blocks != [block]:
        raise ValueError(f"expected only block {block} to change, got {changed_blocks}")
    if original["entries"][block]["raw"] == output["entries"][block]["raw"]:
        raise ValueError("target block is unchanged")

    # Pointer values are checked against the output's physical payload order,
    # not the numeric block-index order.
    if [r["index"] for r in original["physical"]] != [r["index"] for r in output["physical"]]:
        raise ValueError("physical stream order changed")
    cursor = output["payload_start"]
    expected_pointers: dict[int, int] = {}
    for row in output["physical"]:
        expected_pointers[row["index"]] = cursor
        cursor += row["packed_size"]
    if cursor != len(output["data"]):
        raise ValueError("output file size does not equal final physical stream end")
    for row in output["entries"]:
        if row["offset"] != expected_pointers[row["index"]]:
            raise ValueError(f"block {row['index']} pointer not rebuilt for physical order")

    # Independent geometry/record parser. This module is based on raw file
    # fields and imports neither the writer nor the current decoder.
    target_source: dict[str, Any] | None = None
    for block_number, _main, _secondary, lines in independent_blocks(source):
        if block_number == block:
            if not 0 <= edge < len(lines):
                raise IndexError(f"edge {edge} missing in source block {block}")
            target_source = lines[edge]
            break
    if target_source is None:
        raise ValueError("independent Reader did not produce requested source block")
    expected_points = list(target_source["points"])
    if not 0 < point_index < len(expected_points) - 1:
        raise ValueError("requested point is not an existing intermediate point")
    x, y = expected_points[point_index]
    expected_points[point_index] = (x + dx, y + dy)
    expected_signature = _canon(expected_points)
    source_signature = _canon(target_source["points"])
    source_signature_occurrences = 0
    output_signature_occurrences = 0
    total_edges = 0
    target_seen = False
    new_length_raw: int | None = None
    new_distance: float | None = None

    src_iter, out_iter = independent_blocks(source), independent_blocks(candidate)
    for src_row, out_row in zip(src_iter, out_iter, strict=True):
        src_block, src_main, src_secondary, src_lines = src_row
        out_block, out_main, out_secondary, out_lines = out_row
        if src_block != out_block:
            raise ValueError("independent Reader block order mismatch")
        if src_main != out_main or src_secondary != out_secondary:
            raise ValueError(f"block {src_block}: independently decoded coordinate tables changed")
        if len(src_lines) != len(out_lines):
            raise ValueError(f"block {src_block}: edge count changed")
        for before, after in zip(src_lines, out_lines, strict=True):
            total_edges += 1
            if _canon(before["points"]) == source_signature:
                source_signature_occurrences += 1
            if _canon(after["points"]) == expected_signature:
                output_signature_occurrences += 1
            is_target = src_block == block and before["edge"] == edge
            if not is_target:
                for field in ("edge", "flags", "length_raw", "points", "record_hex"):
                    if before[field] != after[field]:
                        raise ValueError(f"block {src_block} edge {before['edge']}: {field} changed")
                continue
            if target_seen:
                raise ValueError("independent Reader returned target edge more than once")
            target_seen = True
            if before["points"] != target_source["points"]:
                raise ValueError("independent Reader source pass disagrees on target geometry")
            if after["points"] != expected_points:
                raise ValueError(f"new shape differs from requested point edit: {after['points']}")
            if after["flags"] != before["flags"]:
                raise ValueError("edge flags changed; v1 does not alter direction or endpoint tables")
            before_record = bytes.fromhex(before["record_hex"])
            after_record = bytes.fromhex(after["record_hex"])
            if before_record[:10] != after_record[:10]:
                raise ValueError("target edge topology/attributes changed")
            new_distance = distance(after["points"])
            new_length_raw = _rounded_feet(new_distance)
            if after["length_raw"] != new_length_raw:
                raise ValueError(f"target length mismatch: read {after['length_raw']}, expected {new_length_raw}")
            if abs(new_distance - new_length_raw * FEET_TO_METRES) > LENGTH_TOLERANCE_M:
                raise ValueError("new length is outside half-foot rounding tolerance")
            if before["length_raw"] != _rounded_feet(distance(before["points"])):
                raise ValueError("source edge is not a regular rounded-feet length case")
    if total_edges != EXPECTED_EDGE_COUNT:
        raise ValueError(f"expected {EXPECTED_EDGE_COUNT} independently read edges, got {total_edges}")
    if not target_seen or new_length_raw is None or new_distance is None:
        raise ValueError("independent Reader did not recover edited target edge")
    if source_signature_occurrences != 1:
        raise ValueError(f"source edge has {source_signature_occurrences} exact cross-block geometry copies")
    if output_signature_occurrences != 1:
        raise ValueError(f"edited edge has {output_signature_occurrences} exact cross-block geometry copies")
    source_sha_after = _hash(source)
    if source_sha_after != source_sha_before:
        raise ValueError("original source SHA-256 changed during verification")

    unchanged = EXPECTED_BLOCK_COUNT - 1
    return {
        "status": "PASS",
        "source_sha256_before": source_sha_before,
        "source_sha256_after": source_sha_after,
        "candidate_sha256": output["sha256"],
        "source_bytes": len(original["data"]),
        "candidate_bytes": len(output["data"]),
        "block_count": output["count"],
        "all_streams_decompressed": len(output["entries"]),
        "physical_stream_order_valid": True,
        "absolute_pointers_and_sizes_valid": True,
        "opaque_pre_payload_region_identical": True,
        "unchanged_blocks_byte_identical_after_independent_inflate": unchanged,
        "changed_decoded_blocks": changed_blocks,
        "unchanged_packed_streams_byte_identical": EXPECTED_BLOCK_COUNT - 1,
        "target_block_raw_changed_byte_offsets": raw_changed_offsets,
        "moved_pointer_entries": moved_pointers,
        "independently_read_edges": total_edges,
        "target": {"block": block, "edge": edge, "point_index": point_index,
                   "before_point": list(target_source["points"][point_index]),
                   "after_point": list(expected_points[point_index]),
                   "length_raw_feet": new_length_raw,
                   "geometry_length_m": new_distance,
                   "stored_length_m": new_length_raw * FEET_TO_METRES,
                   "length_error_m": abs(new_distance - new_length_raw * FEET_TO_METRES),
                   "exact_cross_block_copies_before": source_signature_occurrences - 1,
                   "exact_cross_block_copies_after": output_signature_occurrences - 1},
        "independent_reader": "research/geometry_breakthrough/independent_verify.py",
        "writer_imported_by_reader": False,
        "decoder_imported_by_reader": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3])) / 'SW' / 'DB' / 'EUZ.MP0')
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--block", type=int, default=886)
    parser.add_argument("--edge", type=int, default=1)
    parser.add_argument("--point-index", type=int, default=1)
    parser.add_argument("--dx", type=int, default=5)
    parser.add_argument("--dy", type=int, default=0)
    args = parser.parse_args()
    try:
        report = verify_mp0(args.source, args.candidate, block=args.block, edge=args.edge,
                            point_index=args.point_index, dx=args.dx, dy=args.dy)
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
