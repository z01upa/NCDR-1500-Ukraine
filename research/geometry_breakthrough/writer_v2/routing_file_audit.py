"""Read-only audit of the known RT and RL companion containers.

Uses the existing bounded zip\x01/zlib reader. It proves container integrity
and logical headers only; it intentionally assigns no routing semantics.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import struct
import sys

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from src.readers.ncdx_container import iter_decoded_blocks, read_index  # noqa: E402

DB = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3])) / 'SW' / 'DB'
EXPECTED = {
    "RT": "eb2fc3e0c431d3eb69dd0cefe23463f0bc5c7d51c9eca86692062115a920c456",
    "RL": "fbe22e41a41a9cf58a629ebda7036ab8492c3ab52d093bbe199c9559509c53b4",
}
EVIDENCE = HERE / "evidence"


def _audit_one(suffix: str) -> dict:
    source = DB / f"EUZ.{suffix}"
    before_stat = source.stat()
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    source_hash = digest.hexdigest()
    if source_hash != EXPECTED[suffix]:
        raise ValueError(f"EUZ.{suffix} differs from the existing source manifest: {source_hash}")

    logical_digest = hashlib.sha256()
    prefix = bytearray()
    logical_bytes = 0
    block_hashes = []
    with source.open("rb") as stream:
        index = read_index(stream)
        for logical_offset, block in iter_decoded_blocks(stream, index):
            if logical_offset != logical_bytes:
                raise ValueError(f"EUZ.{suffix}: discontinuous logical offsets")
            logical_digest.update(block)
            if len(prefix) < 110:
                prefix.extend(block[:110 - len(prefix)])
            block_hashes.append(hashlib.sha256(block).hexdigest())
            logical_bytes += len(block)
    if logical_bytes != index.logical_size_bytes or len(prefix) < 94:
        raise ValueError(f"EUZ.{suffix}: incomplete logical payload/header")
    type_id = struct.unpack_from("<H", prefix, 84)[0]
    record_count = struct.unpack_from("<I", prefix, 86)[0]
    word90 = struct.unpack_from("<I", prefix, 90)[0]
    body_bytes = logical_bytes - 94
    derived_stride = body_bytes // record_count if record_count and body_bytes % record_count == 0 else None
    after_stat = source.stat()
    after_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if ((before_stat.st_size, before_stat.st_mtime_ns) != (after_stat.st_size, after_stat.st_mtime_ns)
            or after_hash != source_hash):
        raise RuntimeError(f"EUZ.{suffix} changed during read-only audit")
    return {
        "suffix": suffix, "source": str(source), "source_sha256_before": source_hash,
        "source_sha256_after": after_hash, "source_write_count": 0,
        "physical_size_bytes": index.physical_size_bytes,
        "container_magic": "zip\\x01", "block_size_bytes": index.block_size_bytes,
        "logical_size_bytes": index.logical_size_bytes, "opaque_container_u32": index.opaque_header_u32_le,
        "compressed_stream_count": index.block_count,
        "compressed_offsets_cover_file": index.offsets[0] < index.offsets[-1] == index.physical_size_bytes,
        "all_streams_decoded": len(block_hashes) == index.block_count,
        "logical_sha256": logical_digest.hexdigest(),
        "logical_type_id_u16_at_84": type_id, "logical_count_u32_at_86": record_count,
        "logical_u32_at_90_uninterpreted": word90, "candidate_fixed_stride_bytes": derived_stride,
        "logical_first_110_bytes_hex": bytes(prefix).hex(),
        "semantic_status": "UNKNOWN; container/header facts only",
    }


def audit_routing_files(*, write_evidence: bool = True) -> dict:
    result = {suffix: _audit_one(suffix) for suffix in ("RT", "RL")}
    report = {
        "status": "PASS_CONTAINERS_DECODED_SEMANTICS_UNKNOWN",
        "files": result,
        "finding": "A separate EUZ.RT zip\\x01 container exists (logical type 22, 0 generic records, 8,333,242 logical bytes). This is an external companion to MP0, but its relation to Section 4/5 edge routing is not established.",
        "routing_graph_inside_mp0_only": "UNPROVEN; EUZ.RT and Sections 6-9 remain potential dependencies",
        "method": "Existing bounded NCDx container reader; complete zlib stream decode and source hashes; no logical RT records retained or interpreted.",
    }
    if write_evidence:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / "routing_file_audit.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(audit_routing_files(), ensure_ascii=False, indent=2))
