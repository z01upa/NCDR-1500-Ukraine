"""Bounded read-only integrity experiment for NCDx block-container indexes.

This checks the existing container reader against real manifest-pinned files,
then exercises malformed offset-table references on small in-memory controls.
It does not infer record semantics or navigation geometry.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path, PurePosixPath
import struct
from typing import Any
import zlib

from src.readers.ncdx_container import (
    HEADER_BYTES, MAX_FILE_BYTES, NcdxContainerError, iter_decoded_blocks, read_index,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _corrupt_index_controls() -> list[dict[str, Any]]:
    """Require the production reader to reject three malformed absolute references."""
    block = b"N" * 64
    compressed = zlib.compress(block)
    table_end = HEADER_BYTES + 8
    physical = table_end + len(compressed)
    valid = bytearray(struct.pack("<4sIII", b"zip\x01", 64, 64, 0xA5A5A5A5))
    valid.extend(struct.pack("<II", table_end, physical))
    valid.extend(compressed)
    read_index(io.BytesIO(valid))

    cases = [
        ("first_offset_before_table_end", 16, table_end - 1),
        ("zero_length_block_reference", 20, table_end),
        ("last_offset_before_eof", 20, physical - 1),
    ]
    results: list[dict[str, Any]] = []
    for name, byte_offset, value in cases:
        candidate = bytearray(valid)
        struct.pack_into("<I", candidate, byte_offset, value)
        try:
            read_index(io.BytesIO(candidate))
        except NcdxContainerError as exc:
            results.append({"case": name, "rejected": True, "reason": str(exc)[:160]})
        else:
            raise RuntimeError(f"container reader accepted malformed index control: {name}")
    return results


def analyze_index_integrity(source_root: Path,
                            sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Check production-reader index/decompression behavior on bounded real inputs."""
    root = Path(source_root).resolve(strict=True)
    if len(sources) < 2:
        raise ValueError("at least two independent NCDx source files are required")
    observations: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for item in sources:
        relative = str(item.get("relative_path", "")).replace("\\", "/")
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or ".." in parsed.parts or not relative:
            raise ValueError("manifest-bound NCDx source path is unsafe")
        if relative.casefold() in seen_paths:
            raise ValueError("duplicate NCDx source path in integrity experiment")
        seen_paths.add(relative.casefold())
        path = (root / Path(*parsed.parts)).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("NCDx source escaped the read-only source root")
        before = path.stat()
        if before.st_size != int(item.get("size_bytes", -1)) or before.st_size > MAX_FILE_BYTES:
            raise ValueError("source size differs from its accepted manifest or reader bound")
        digest = _sha256_file(path)
        if digest != str(item.get("sha256", "")):
            raise ValueError("source SHA-256 differs from its accepted manifest")

        with path.open("rb") as handle:
            index = read_index(handle)
            decoded_sha = hashlib.sha256()
            decoded_size = 0
            block_lengths: list[int] = []
            for _logical_offset, decoded in iter_decoded_blocks(handle, index):
                decoded_sha.update(decoded)
                decoded_size += len(decoded)
                block_lengths.append(len(decoded))
        after = path.stat()
        if (before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns
                or digest != _sha256_file(path)):
            raise RuntimeError("manifest-bound source changed while being read")
        if decoded_size != index.logical_size_bytes or not block_lengths:
            raise RuntimeError("decoded block lengths do not match the declared logical size")
        offset_bytes = struct.pack(f"<{len(index.offsets)}I", *index.offsets)
        observations.append({
            "region": str(item.get("region", "")),
            "suffix": str(item.get("suffix", "")),
            "relative_path": relative,
            "source_sha256": digest,
            "source_size_bytes": before.st_size,
            "source_mtime_ns": before.st_mtime_ns,
            "reader": "src.readers.ncdx_container.read_index+iter_decoded_blocks",
            "marker_hex": "7a697001",
            "block_size_bytes": index.block_size_bytes,
            "logical_size_bytes": index.logical_size_bytes,
            "opaque_header_u32_le": index.opaque_header_u32_le,
            "physical_size_bytes": index.physical_size_bytes,
            "block_count": index.block_count,
            "offset_count": len(index.offsets),
            "offsets_sha256": hashlib.sha256(offset_bytes).hexdigest(),
            "offsets_head": list(index.offsets[:4]),
            "offsets_tail": list(index.offsets[-4:]),
            "decoded_size_bytes": decoded_size,
            "decoded_sha256": decoded_sha.hexdigest(),
            "first_decoded_block_bytes": block_lengths[0],
            "last_decoded_block_bytes": block_lengths[-1],
            "absolute_offsets_validated": True,
            "unexplained_trailing_bytes": 0,
            "record_semantics": "UNKNOWN",
        })
    controls = _corrupt_index_controls()
    if len(controls) != 3 or any(row.get("rejected") is not True for row in controls):
        raise RuntimeError("production reader did not reject every malformed offset control")
    return {
        "experiment": "ncdx_index_integrity_v1",
        "source_count": len(observations),
        "independent_suffix_count": len({row["suffix"] for row in observations}),
        "observations": observations,
        "valid_source_absolute_offset_error_count": 0,
        "invalid_reference_negative_controls": controls,
        "invalid_reference_negative_control_rejection_count": len(controls),
        "interpretation": {
            "endianness": "little-endian container header/offset table as used by the existing reader",
            "reference_scope": "absolute compressed-block offsets only; semantic record references remain UNKNOWN",
            "record_lengths": "logical block lengths verified; application-level record lengths remain UNKNOWN",
            "unexpected_segments": "no bytes remain beyond the terminal absolute offset in these inputs",
            "road_geometry_proven": False,
            "routing_proven": False,
            "original_media_write_count": 0,
        },
    }
