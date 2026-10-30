"""Conservative writer for the observed NCDx ``zip\x01`` block container.

This writer preserves the opaque header word and zlib level 9 used by the
validated regional samples.  It writes only a caller-selected output path;
the autonomous research handler restricts that path to the project's work
directory and never targets original media.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import struct
from typing import Any
import zlib

from src.readers.ncdx_container import (
    MAX_BLOCKS,
    MAX_BLOCK_BYTES,
    MAX_FILE_BYTES,
    MAX_LOGICAL_BYTES,
    NcdxContainerError,
    decode_bytes,
)


ZLIB_LEVEL = 9


def encode_container(logical_data: bytes, *, block_size_bytes: int = 3072,
                     opaque_header_u32_le: int = 0) -> bytes:
    """Encode one logical byte string using the observed 3072-byte/zlib layout."""
    if not logical_data or len(logical_data) > MAX_LOGICAL_BYTES:
        raise NcdxContainerError("logical payload size is outside the accepted range")
    if not 0 < block_size_bytes <= MAX_BLOCK_BYTES:
        raise NcdxContainerError("block size is outside the accepted range")
    if not 0 <= opaque_header_u32_le <= 0xFFFFFFFF:
        raise NcdxContainerError("opaque header word must fit an unsigned 32-bit field")
    block_count = (len(logical_data) + block_size_bytes - 1) // block_size_bytes
    if block_count > MAX_BLOCKS:
        raise NcdxContainerError("logical payload needs too many blocks")
    table_end = 16 + 4 * (block_count + 1)
    compressed_blocks = [
        zlib.compress(logical_data[offset:offset + block_size_bytes], level=ZLIB_LEVEL)
        for offset in range(0, len(logical_data), block_size_bytes)
    ]
    offsets = [table_end]
    for block in compressed_blocks:
        if not block or len(block) > 1024 * 1024:
            raise NcdxContainerError("encoded block is outside the accepted compressed size")
        offsets.append(offsets[-1] + len(block))
    physical_size = offsets[-1]
    if physical_size > MAX_FILE_BYTES or physical_size > 0xFFFFFFFF:
        raise NcdxContainerError("encoded container exceeds the accepted physical size")
    header = b"zip\x01" + struct.pack("<III", block_size_bytes, len(logical_data), opaque_header_u32_le)
    table = struct.pack(f"<{len(offsets)}I", *offsets)
    return header + table + b"".join(compressed_blocks)


def rewrite_container(encoded: bytes, logical_data: bytes) -> bytes:
    """Re-encode a validated container payload while preserving its framing fields."""
    index, _prior_payload = decode_bytes(encoded)
    return encode_container(logical_data, block_size_bytes=index.block_size_bytes,
                            opaque_header_u32_le=index.opaque_header_u32_le)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_lossless_roundtrip(source_path: str | Path, destination_path: str | Path, *,
                             expected_sha256: str, work_root: str | Path) -> dict[str, Any]:
    """Create a byte-exact no-op re-encoding under ``work_root`` only.

    The input is opened read-only, and an existing destination is never
    overwritten.  The actual source is hashed and stat-checked around the
    operation.  This proves the encoder's lossless no-op behavior only; it
    does not validate decoded record semantics or vehicle compatibility.
    """
    source = Path(source_path).resolve(strict=True)
    allowed_root = Path(work_root).resolve(strict=True)
    destination = Path(destination_path).resolve(strict=False)
    if not destination.is_relative_to(allowed_root):
        raise ValueError("round-trip output must remain inside the configured work directory")
    if destination == source:
        raise ValueError("round-trip output cannot replace its input")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite prior round-trip evidence: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    before = source.stat()
    encoded = source.read_bytes()
    source_digest = _sha256(encoded)
    if source_digest.lower() != expected_sha256.lower():
        raise NcdxContainerError("source SHA-256 differs from the supplied inventory entry")
    index, logical_data = decode_bytes(encoded)
    roundtrip = encode_container(logical_data, block_size_bytes=index.block_size_bytes,
                                 opaque_header_u32_le=index.opaque_header_u32_le)
    if len(roundtrip) != len(encoded):
        raise NcdxContainerError("no-op re-encoding changed physical file length")
    if roundtrip != encoded:
        raise NcdxContainerError("zlib level 9 did not reproduce the source byte-for-byte")

    created_output = False
    try:
        with destination.open("xb") as output:
            created_output = True
            output.write(roundtrip)
            output.flush()
            os.fsync(output.fileno())
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise NcdxContainerError("source size or modification time changed during round-trip")
        if _sha256(source.read_bytes()) != source_digest:
            raise NcdxContainerError("source hash changed during round-trip")
    except BaseException:
        if created_output:
            destination.unlink(missing_ok=True)
        raise

    return {
        "status": "PASS_COPY_ONLY",
        "source_sha256": source_digest,
        "output_sha256": _sha256(roundtrip),
        "source_bytes": len(encoded),
        "output_bytes": len(roundtrip),
        "logical_bytes": len(logical_data),
        "logical_sha256": _sha256(logical_data),
        "block_size_bytes": index.block_size_bytes,
        "block_count": index.block_count,
        "opaque_header_u32_le_preserved": index.opaque_header_u32_le,
        "zlib_level": ZLIB_LEVEL,
        "byte_identical": True,
        "source_stat_unchanged": True,
        "original_media_write_count": 0,
        "claim_scope": "byte-exact container no-op round-trip only; payload semantics UNKNOWN",
    }
