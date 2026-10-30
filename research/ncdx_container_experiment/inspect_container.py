"""Copy and inspect only the regional PTI/PDX/PTP candidate files.

The experiment tests a bounded container hypothesis: ``zip\x01``, a declared
block size and logical size, an opaque header word, a table of absolute block
offsets, and one zlib stream per block. It deliberately makes no claim about
the meaning of decompressed records.
"""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import os
import shutil
import struct
import zlib
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_ROOT = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[2]))
MANIFEST_PATH = PROJECT_ROOT / "inventory" / "discs_manifest.json"
WORK_ROOT = PROJECT_ROOT / "work" / "ncdx_container_experiment" / "inputs"
REPORT_PATH = PROJECT_ROOT / "reports" / "ncdx_container_experiment.json"

MAGIC = b"zip\x01"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_LOGICAL_BYTES = 64 * 1024 * 1024
MAX_BLOCK_BYTES = 64 * 1024
MAX_CHUNKS = 32_768
MAX_COMPRESSED_CHUNK_BYTES = 1024 * 1024

DISC_SPECS = (
    ("Italy", "OPEL NCDx Italia 2010-2011", "IZ"),
    ("Scandinavia", "OPEL NCDx Scandinavia 2010-2011", "SCZ"),
    ("EU", "SW", "EUZ"),
)
EXTENSIONS = ("PTI", "PDX", "PTP")


class ContainerError(ValueError):
    """Raised when a candidate violates a tested container invariant."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_manifest_path(disc: str, prefix: str, extension: str) -> str:
    return f"{disc}\\DB\\{prefix}.{extension}"


def copy_verified_inputs(
    source_root: Path,
    manifest_path: Path = MANIFEST_PATH,
    work_root: Path = WORK_ROOT,
) -> list[dict[str, Any]]:
    """Copy nine manifest-listed inputs; refuse mismatches or altered copies."""
    manifest_rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest_rows, list):
        raise ValueError("Expected the existing inventory manifest to be a list")
    manifest = {row["relative_path"]: row for row in manifest_rows}
    results: list[dict[str, Any]] = []

    for region, disc, prefix in DISC_SPECS:
        for extension in EXTENSIONS:
            relative_path = _relative_manifest_path(disc, prefix, extension)
            row = manifest.get(relative_path)
            if row is None:
                raise FileNotFoundError(f"Candidate is absent from existing manifest: {relative_path}")
            source = source_root.joinpath(*PureWindowsPath(relative_path).parts)
            destination = work_root / region / f"{prefix}.{extension}"
            if not source.is_file():
                raise FileNotFoundError(f"Candidate source is missing: {source}")

            source_size = source.stat().st_size
            source_hash = sha256_file(source)
            expected_size = int(row["length_bytes"])
            expected_hash = str(row["sha256"]).lower()
            if source_size != expected_size or source_hash != expected_hash:
                raise ValueError(f"Source differs from existing manifest: {relative_path}")

            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.stat().st_size != expected_size or sha256_file(destination) != expected_hash:
                    raise FileExistsError(f"Refusing to overwrite a non-matching evidence copy: {destination}")
                disposition = "reused_identical_copy"
            else:
                shutil.copyfile(source, destination)
                disposition = "copied_from_verified_source"

            copy_hash = sha256_file(destination)
            if destination.stat().st_size != expected_size or copy_hash != expected_hash:
                raise IOError(f"Copied evidence did not verify: {destination}")
            results.append({
                "region": region,
                "relative_path": relative_path,
                "copy_path": str(destination.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                "size_bytes": expected_size,
                "manifest_sha256": expected_hash,
                "source_sha256": source_hash,
                "copy_sha256": copy_hash,
                "copy_status": disposition,
            })
    return results


def _block_preview(index: int, start: int, end: int, expected: int,
                   compressed: bytes, decoded: bytes) -> dict[str, Any]:
    return {
        "index": index,
        "offset_start": start,
        "offset_end": end,
        "compressed_bytes": end - start,
        "expected_output_bytes": expected,
        "observed_output_bytes": len(decoded),
        "zlib_header_hex": compressed[:2].hex(),
        "output_sha256": sha256_bytes(decoded),
    }


def inspect_container(data: bytes, *, max_file_bytes: int = MAX_FILE_BYTES,
                      max_logical_bytes: int = MAX_LOGICAL_BYTES,
                      max_chunks: int = MAX_CHUNKS) -> dict[str, Any]:
    """Validate the bounded block/offset/zlib hypothesis and hash decoded data."""
    if len(data) > max_file_bytes:
        raise ContainerError(f"candidate is larger than the {max_file_bytes}-byte input limit")
    if len(data) < 16:
        raise ContainerError("candidate is shorter than the 16-byte fixed header")
    if data[:4] != MAGIC:
        raise ContainerError("candidate does not start with zip\\x01")

    block_size, logical_size, opaque_word = struct.unpack_from("<III", data, 4)
    if block_size <= 0 or block_size > MAX_BLOCK_BYTES:
        raise ContainerError(f"declared block size is outside the safe bound: {block_size}")
    if logical_size <= 0 or logical_size > max_logical_bytes:
        raise ContainerError(f"declared logical size is outside the safe bound: {logical_size}")

    chunk_count = (logical_size + block_size - 1) // block_size
    if chunk_count > max_chunks:
        raise ContainerError(f"declared chunk count is outside the safe bound: {chunk_count}")
    table_end = 16 + 4 * (chunk_count + 1)
    if table_end > len(data):
        raise ContainerError("offset table does not fit inside the candidate")
    offsets = struct.unpack_from(f"<{chunk_count + 1}I", data, 16)
    if offsets[0] != table_end:
        raise ContainerError(f"first block offset {offsets[0]} does not equal table end {table_end}")
    if offsets[-1] != len(data):
        raise ContainerError(f"final block offset {offsets[-1]} does not equal file size {len(data)}")
    if any(right <= left for left, right in zip(offsets, offsets[1:])):
        raise ContainerError("block offsets are not strictly increasing")

    decoded_digest = hashlib.sha256()
    total_decoded = 0
    block_sizes: list[int] = []
    compressed_sizes: list[int] = []
    block_headers: dict[str, int] = {}
    previews: list[dict[str, Any]] = []

    for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
        compressed = data[start:end]
        if not compressed or len(compressed) > MAX_COMPRESSED_CHUNK_BYTES:
            raise ContainerError(f"compressed block {index} exceeds its safe bound")
        expected_output = min(block_size, logical_size - index * block_size)
        decompressor = zlib.decompressobj()
        try:
            decoded = decompressor.decompress(compressed, expected_output + 1)
        except zlib.error as exc:
            raise ContainerError(f"compressed block {index} is not a valid zlib stream: {exc}") from exc
        if not decompressor.eof:
            raise ContainerError(f"compressed block {index} did not reach a zlib stream end")
        if decompressor.unused_data or decompressor.unconsumed_tail:
            raise ContainerError(f"compressed block {index} has trailing or unconsumed bytes")
        if len(decoded) != expected_output:
            raise ContainerError(
                f"compressed block {index} produced {len(decoded)} bytes; expected {expected_output}"
            )

        decoded_digest.update(decoded)
        total_decoded += len(decoded)
        block_sizes.append(len(decoded))
        compressed_sizes.append(len(compressed))
        block_header = compressed[:2].hex()
        block_headers[block_header] = block_headers.get(block_header, 0) + 1
        if index < 3 or index >= chunk_count - 3:
            previews.append(_block_preview(index, start, end, expected_output, compressed, decoded))

    if total_decoded != logical_size:
        raise ContainerError(f"decoded {total_decoded} bytes; declared {logical_size}")
    return {
        "status": "PASS",
        "magic_hex": data[:4].hex(" "),
        "magic_ascii": data[:4].decode("ascii"),
        "block_size_bytes": block_size,
        "logical_size_bytes": logical_size,
        "opaque_header_u32_le": opaque_word,
        "physical_size_bytes": len(data),
        "chunk_count": chunk_count,
        "offset_table_start": 16,
        "offset_table_end": table_end,
        "first_payload_offset": offsets[0],
        "last_payload_offset": offsets[-1],
        "offset_table_covers_file": offsets[0] == table_end and offsets[-1] == len(data),
        "decoded_size_bytes": total_decoded,
        "decoded_sha256": decoded_digest.hexdigest(),
        "compressed_chunk_min_bytes": min(compressed_sizes),
        "compressed_chunk_max_bytes": max(compressed_sizes),
        "decoded_block_size_counts": {str(size): block_sizes.count(size) for size in sorted(set(block_sizes))},
        "zlib_header_counts": block_headers,
        "block_previews": previews,
    }


def write_immutable_report(report_path: Path, report: dict[str, Any]) -> None:
    """Create a report once and refuse to replace prior evidence."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    with report_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)


def run_experiment(source_root: Path = DEFAULT_SOURCE_ROOT,
                   manifest_path: Path = MANIFEST_PATH,
                   work_root: Path = WORK_ROOT,
                   report_path: Path = REPORT_PATH) -> dict[str, Any]:
    if report_path.exists():
        raise FileExistsError(f"Refusing to overwrite immutable report: {report_path}")
    copied_inputs = copy_verified_inputs(source_root, manifest_path, work_root)
    by_relative_path = {row["relative_path"]: row for row in copied_inputs}
    inspected: list[dict[str, Any]] = []
    for region, disc, prefix in DISC_SPECS:
        for extension in EXTENSIONS:
            relative_path = _relative_manifest_path(disc, prefix, extension)
            copy_row = by_relative_path[relative_path]
            copy_path = PROJECT_ROOT / copy_row["copy_path"]
            result = inspect_container(copy_path.read_bytes())
            inspected.append({
                "region": region,
                "file": f"{prefix}.{extension}",
                "relative_path": relative_path,
                "copy_path": copy_row["copy_path"],
                "source_sha256": copy_row["source_sha256"],
                **result,
            })

    families: dict[str, list[dict[str, Any]]] = {}
    for row in inspected:
        families.setdefault(Path(row["file"]).suffix[1:], []).append(row)
    family_checks = {}
    for extension, rows in families.items():
        family_checks[extension] = {
            "regions": [row["region"] for row in rows],
            "all_pass": all(row["status"] == "PASS" for row in rows),
            "block_sizes": sorted({row["block_size_bytes"] for row in rows}),
            "magic_values": sorted({row["magic_hex"] for row in rows}),
            "each_offset_table_exactly_spans_payload": all(row["offset_table_covers_file"] for row in rows),
            "logical_sizes_bytes": {row["region"]: row["logical_size_bytes"] for row in rows},
            "chunk_counts": {row["region"]: row["chunk_count"] for row in rows},
            "opaque_header_words": {row["region"]: row["opaque_header_u32_le"] for row in rows},
            "decoded_hashes_differ_across_regions": len({row["decoded_sha256"] for row in rows}) == len(rows),
        }

    report = {
        "experiment": "bounded_ncdx_zip3kb_candidate_container",
        "status": "PASS" if len(inspected) == 9 and all(row["status"] == "PASS" for row in inspected) else "FAIL",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Nine manifest-verified PTI/PDX/PTP files only; all decoding used verified work copies.",
        "hypothesis": {
            "magic": "zip\\x01",
            "header_words": ["block_size_u32_le", "logical_size_u32_le", "opaque_u32_le"],
            "offset_table": "chunk_count+1 absolute u32 LE offsets beginning at byte 16",
            "chunk_count": "ceil(logical_size / block_size)",
            "payload": "one independent zlib stream per adjacent offset pair",
            "bounds": {
                "compressed_file_bytes": MAX_FILE_BYTES,
                "logical_bytes": MAX_LOGICAL_BYTES,
                "block_bytes": MAX_BLOCK_BYTES,
                "compressed_chunk_bytes": MAX_COMPRESSED_CHUNK_BYTES,
                "chunk_count": MAX_CHUNKS,
            },
        },
        "copy_verification": copied_inputs,
        "family_checks": family_checks,
        "files": inspected,
        "semantic_status": "UNCONFIRMED",
        "interpretation_limits": [
            "The experiment validates container framing, offsets, and bounded zlib decoding only.",
            "The opaque header word and record semantics are not assigned meaning.",
            "No POI, address, routing, coordinate, or NCDx compatibility claim is made.",
            "No existing database, inventory manifest, or original source file was modified.",
        ],
        "next_experiment": (
            "Map decoded PTI/PDX/PTP record references across regions and test candidate labels/coordinates "
            "against independently sourced records before assigning POI semantics."
        ),
    }
    write_immutable_report(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--work-root", type=Path, default=WORK_ROOT)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = run_experiment(args.source_root, args.manifest, args.work_root, args.report)
    print(json.dumps({"status": report["status"], "files": len(report["files"]),
                      "report": str(args.report)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
