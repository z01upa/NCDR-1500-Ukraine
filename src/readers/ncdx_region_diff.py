"""Bounded cross-region NCDx byte and structure differencing.

The analyzer binds a fixed set of already inventoried regional files, hashes
each complete source while retaining only a bounded prefix, compares aligned
byte blocks, and reads only validated logical headers from block containers.
It does not assign road geometry or routing semantics.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import struct
from typing import Any, Iterable

from src.readers.ncdx_container import iter_decoded_blocks, read_index
from src.readers.ncdx_mp0_header import read_mp0_header


FORMAT_VERSION = 1
SAMPLE_BYTES = 1024 * 1024
BLOCK_BYTES = 4096
TABLE_START = 94
EXPECTED_TYPES = {"CTY": 3, "CNY": 12, "RL": 21, "IOF": 21, "IL": 20}
EXPECTED_STRIDES = {"CTY": 178, "CNY": 174, "RL": 61, "IOF": 6}
SUFFIXES = ("MP0", "MG1", "MG2", "MG3", "CTY", "CNY", "RL", "IOF", "IL")


def _hash_and_prefix(path: Path, sample_bytes: int) -> tuple[str, int, bytes, int, bool]:
    before = path.stat()
    digest = hashlib.sha256()
    prefix = bytearray()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            if len(prefix) < sample_bytes:
                prefix.extend(chunk[:sample_bytes - len(prefix)])
            size += len(chunk)
    after = path.stat()
    unchanged = (before.st_size == after.st_size == size
                 and before.st_mtime_ns == after.st_mtime_ns)
    if not unchanged:
        raise RuntimeError(f"regional source changed while being read: {path}")
    return digest.hexdigest(), size, bytes(prefix), before.st_mtime_ns, unchanged


def _inspect_header(path: Path, suffix: str) -> dict[str, Any]:
    with path.open("rb") as stream:
        first = stream.read(110)
    if first.startswith(b"zip\x01"):
        with path.open("rb") as stream:
            index = read_index(stream)
            blocks = iter_decoded_blocks(stream, index)
            first_offset, logical = next(blocks)
        if first_offset != 0 or len(logical) < TABLE_START:
            raise ValueError(f"missing bounded first logical block: {path.name}")
        type_id = struct.unpack_from("<H", logical, 84)[0]
        count = struct.unpack_from("<I", logical, 86)[0]
        body_bytes = index.logical_size_bytes - TABLE_START
        stride = None
        if count and body_bytes >= 0 and body_bytes % count == 0:
            stride = body_bytes // count
        if suffix in EXPECTED_TYPES and type_id != EXPECTED_TYPES[suffix]:
            raise ValueError(f"unexpected {suffix} type id {type_id} in {path.name}")
        if suffix in EXPECTED_STRIDES and stride != EXPECTED_STRIDES[suffix]:
            raise ValueError(f"unexpected {suffix} record stride {stride} in {path.name}")
        return {"encoding": "zip_01_block_container", "physical_magic": "zip\\x01",
            "physical_header_offsets": {"block_size_u32le": 4, "logical_size_u32le": 8,
                                        "offset_table_u32le": 16},
            "block_size_bytes": index.block_size_bytes,
            "logical_size_bytes": index.logical_size_bytes,
            "logical_header_bytes_examined": len(logical),
            "logical_type_id": type_id, "logical_type_id_offset": 84,
            "declared_record_count": count, "record_count_offset": 86,
            "logical_table_start_offset": TABLE_START,
            "derived_record_stride_bytes": stride,
            "fixed_stride_expected": EXPECTED_STRIDES.get(suffix),
            "header_read_status": "PASS"}
    if len(first) < 94:
        raise ValueError(f"truncated NCDx logical header: {path.name}")
    type_id = struct.unpack_from("<H", first, 84)[0]
    count = struct.unpack_from("<I", first, 86)[0]
    preceding = struct.unpack_from("<I", first, 90)[0]
    result: dict[str, Any] = {"encoding": "raw_siemens_map_header",
        "logical_type_id": type_id, "logical_type_id_offset": 84,
        "declared_record_count": count, "record_count_offset": 86,
        "preceding_u32_uninterpreted": preceding, "preceding_u32_offset": 90,
        "header_read_status": "PASS"}
    if suffix == "MP0":
        parsed = read_mp0_header(path)
        result["mp0_fixed_fields"] = {"magic": parsed.magic, "copyright": parsed.copyright,
            "internal_format_version": parsed.internal_format_version,
            "dataset_code": parsed.dataset_code,
            "offsets": {"magic": 0, "copyright": 16, "internal_format_version": 32,
                         "dataset_code": 48}}
    if suffix in {"MP0", "MG1", "MG2", "MG3"} and len(first) >= 110:
        result["candidate_bbox_int32"] = list(struct.unpack_from("<iiii", first, 94))
        result["candidate_bbox_offset"] = 94
        result["bbox_semantics"] = "candidate field only; spatial relation does not prove road geometry"
    return result


def _aligned_block_differences(samples: dict[str, bytes], block_bytes: int = BLOCK_BYTES) -> dict[str, Any]:
    regions = sorted(samples)
    common_offsets: list[int] = []
    pair_counts = {f"{left}:{right}": 0 for i, left in enumerate(regions)
                   for right in regions[i + 1:]}
    common_all_count = 0
    extent = min((len(samples[name]) for name in regions), default=0)
    for offset in range(0, extent - block_bytes + 1, block_bytes):
        hashes = {name: hashlib.sha256(samples[name][offset:offset + block_bytes]).digest()
                  for name in regions}
        if len(set(hashes.values())) == 1 and hashes:
            common_all_count += 1
            if len(common_offsets) < 64:
                common_offsets.append(offset)
        for i, left in enumerate(regions):
            for right in regions[i + 1:]:
                if hashes[left] == hashes[right]:
                    pair_counts[f"{left}:{right}"] += 1
    return {"block_bytes": block_bytes, "aligned_prefix_bytes": extent,
            "common_block_count_across_all_regions": common_all_count,
            "common_block_offsets_preview": common_offsets,
            "pairwise_equal_block_counts": pair_counts,
            "identical_full_files": False}


def analyze_ncdx_region_diff(*, source_root: Path,
                             regions: Iterable[tuple[str, Path, str]],
                             suffixes: Iterable[str] = SUFFIXES,
                             sample_bytes: int = SAMPLE_BYTES,
                             block_bytes: int = BLOCK_BYTES,
                             prior_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compare a fixed, parameterized set of regional NCDx files read-only."""
    root = Path(source_root).resolve(strict=True)
    if sample_bytes < block_bytes or sample_bytes > 4 * SAMPLE_BYTES:
        raise ValueError("regional diff sample bound must be 1..4 MiB and at least one block")
    if block_bytes < 256 or block_bytes > 64 * 1024 or block_bytes & (block_bytes - 1):
        raise ValueError("regional diff block size must be a bounded power of two")
    suffix_list = tuple(dict.fromkeys(str(value).upper() for value in suffixes))
    if not suffix_list or any(value not in SUFFIXES for value in suffix_list):
        raise ValueError("regional diff suffixes must belong to the fixed NCDx allowlist")
    region_list = list(regions)
    if len(region_list) != 3 or len({name for name, _folder, _prefix in region_list}) != 3:
        raise ValueError("regional diff requires exactly three distinct supplied CD trees")

    family_results: list[dict[str, Any]] = []
    for suffix in suffix_list:
        sources: dict[str, dict[str, Any]] = {}
        samples: dict[str, bytes] = {}
        for label, folder, prefix in region_list:
            path = (root / folder / f"{prefix}.{suffix}").resolve(strict=True)
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError(f"regional source escaped the read-only root: {path}")
            source_hash, size, sample, source_mtime_ns, unchanged = _hash_and_prefix(path, sample_bytes)
            header = _inspect_header(path, suffix)
            header_stat = path.stat()
            if header_stat.st_size != size or header_stat.st_mtime_ns != source_mtime_ns:
                raise RuntimeError(f"regional source changed between hashing and header read: {path}")
            samples[label] = sample
            sources[label] = {"relative_path": path.relative_to(root).as_posix(),
                "source_sha256": source_hash, "source_size_bytes": size,
                "source_mtime_ns_during_read": source_mtime_ns,
                "source_unchanged_during_read": unchanged, "header": header}
        full_hashes = {row["source_sha256"] for row in sources.values()}
        region_counts = {name: row["header"].get("declared_record_count")
                         for name, row in sources.items()}
        diff = _aligned_block_differences(samples, block_bytes)
        diff["aligned_prefix_bytes"] = min(len(sample) for sample in samples.values())
        diff["common_block_count_across_all_regions"] = diff["common_block_count_across_all_regions"]
        family_results.append({"suffix": suffix, "sources": sources,
            "all_full_file_hashes_distinct": len(full_hashes) == len(sources),
            "declared_counts_differ": len(set(region_counts.values())) > 1,
            "declared_record_counts": region_counts,
            "aligned_byte_diff": diff})

    return {"format_version": FORMAT_VERSION, "status": "PASS",
        "experiment": "ncdx_three_region_bounded_byte_and_header_diff",
        "hypothesis": "Regional NCDx files share container/header schemas while containing region-specific records; bounded aligned blocks will identify exact common segments or demonstrate their absence.",
        "hypothesis_result": "SUPPORTED" if all(row["all_full_file_hashes_distinct"] for row in family_results)
            else "MIXED",
        "regions": [label for label, _folder, _prefix in region_list],
        "suffixes": list(suffix_list), "sample_prefix_bytes": sample_bytes,
        "aligned_block_bytes": block_bytes, "families": family_results,
        "prior_evidence": prior_evidence or {},
        "claim_boundaries": {"full_file_hashes_are_identity_only": True,
            "common_blocks_are_exact_raw_byte_matches": True,
            "block_alignment_is_relative_to_file_start": True,
            "road_geometry_proven": False, "routing_proven": False,
            "physical_disc_compatibility_proven": False,
            "original_media_write_count": 0},
    }

