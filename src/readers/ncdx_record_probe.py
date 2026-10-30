"""Bounded structural probe for decoded NCDx map containers.

The probe reports literal text runs and integer pairs that fall inside a
regional geographic window at fixed experimental scales. These are candidate
anchors only: record boundaries, labels, coordinates and payload semantics are
not asserted by this module.
"""

from __future__ import annotations

import hashlib
from collections import Counter
import json
import math
import mmap
import random
import re
import statistics
from pathlib import Path
import struct
from typing import Any
import zlib

from src.readers.ncdx_container import MAX_FILE_BYTES, decode_bytes, iter_decoded_blocks, read_index


REGION_BOUNDS = {
    "SW": (35.0, -10.0, 72.0, 40.0),
    "Italy": (35.0, 6.0, 48.5, 19.5),
    "Scandinavia": (54.0, 3.0, 72.0, 33.0),
}
COORDINATE_SCALES = (100_000, 1_000_000, 10_000_000)
SAMPLE_DISTRIBUTION_BINS = 16
TEXT_SAMPLES_PER_BIN = 32
COORDINATE_SAMPLES_PER_BIN = 2
MAX_TEXT_SAMPLES = SAMPLE_DISTRIBUTION_BINS * TEXT_SAMPLES_PER_BIN
_PRINTABLE_RUN = re.compile(rb"[\x20-\x7e]{4,96}")
MAX_STANDALONE_ZLIB_FILE_BYTES = 128 * 1024 * 1024
MAX_STANDALONE_ZLIB_COMPRESSED_BYTES = 1024 * 1024
MAX_STANDALONE_ZLIB_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_STANDALONE_ZLIB_HEADER_CANDIDATES = 4096
ZLIB_COORDINATE_SAMPLE_STRIDE = 8
ZLIB_COORDINATE_SAMPLE_LIMIT = 512
ZLIB_COORDINATE_SAMPLE_PREFIX_BYTES = 4096
ZLIB_COORDINATE_MAX_JUMP_KM = 5.0
ZLIB_COORDINATE_PROFILE_PARAMETERS = {
    "sample_stride": ZLIB_COORDINATE_SAMPLE_STRIDE,
    "sample_limit": ZLIB_COORDINATE_SAMPLE_LIMIT,
    "sample_prefix_bytes": ZLIB_COORDINATE_SAMPLE_PREFIX_BYTES,
    "max_jump_km": ZLIB_COORDINATE_MAX_JUMP_KM,
    "coordinate_scales": list(COORDINATE_SCALES),
}
ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS = {
    "sample_stride": 4,
    "sample_limit": 1024,
    "sample_prefix_bytes": 1024,
    "max_jump_km": ZLIB_COORDINATE_MAX_JUMP_KM,
    "coordinate_scales": list(COORDINATE_SCALES),
}
ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS = {
    "sample_stride": 1,
    "sample_limit": MAX_STANDALONE_ZLIB_HEADER_CANDIDATES,
    "sample_prefix_bytes": 1024,
    "max_jump_km": ZLIB_COORDINATE_MAX_JUMP_KM,
    "coordinate_scales": list(COORDINATE_SCALES),
    "include_hit_stream_summaries": True,
}
ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS = {
    "sample_stride": 1,
    "sample_limit": MAX_STANDALONE_ZLIB_HEADER_CANDIDATES,
    "sample_prefix_bytes": ZLIB_COORDINATE_SAMPLE_PREFIX_BYTES,
    "max_jump_km": ZLIB_COORDINATE_MAX_JUMP_KM,
    "coordinate_scales": list(COORDINATE_SCALES),
    "include_hit_stream_summaries": True,
}
ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS = {
    "tier": "selected_full_payload_audit",
    "max_streams_per_region": 2,
    "sample_prefix_bytes": MAX_STANDALONE_ZLIB_OUTPUT_BYTES,
    "max_jump_km": ZLIB_COORDINATE_MAX_JUMP_KM,
    "coordinate_scales": list(COORDINATE_SCALES),
}
ZLIB_COORDINATE_PROFILE_PARAMETER_OPTIONS = (
    ZLIB_COORDINATE_PROFILE_PARAMETERS,
    ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS,
    ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS,
    ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS,
)


def is_zlib_coordinate_selected_payload_parameters(parameters: Any) -> bool:
    """Accept only the bounded full-payload tier with manifest-derived stream selections."""
    if not isinstance(parameters, dict):
        return False
    batch_index = parameters.get("batch_index", 0)
    if isinstance(batch_index, bool) or not isinstance(batch_index, int) or batch_index < 0:
        return False
    selection_class = parameters.get("selection_class", "repeated_pairs")
    if selection_class not in {"repeated_pairs", "single_pair"}:
        return False
    selected_by_region = parameters.get("selected_streams_by_region")
    fixed = {key: value for key, value in parameters.items()
             if key not in {"selected_streams_by_region", "batch_index", "selection_class"}}
    if fixed != ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS:
        return False
    if not isinstance(selected_by_region, dict) or set(selected_by_region) != set(REGION_BOUNDS):
        return False
    required = {"stream_index", "source_offset", "compressed_bytes", "decompressed_bytes",
                "decompressed_sha256", "sample_prefix_sha256"}
    for rows in selected_by_region.values():
        if not isinstance(rows, list) or len(rows) > int(fixed["max_streams_per_region"]):
            return False
        seen: set[int] = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != required:
                return False
            try:
                stream_index = int(row["stream_index"])
                offset = int(row["source_offset"])
                compressed = int(row["compressed_bytes"])
                decompressed = int(row["decompressed_bytes"])
            except (TypeError, ValueError):
                return False
            if (stream_index < 0 or offset < 0 or compressed < 1
                    or not 16 <= decompressed <= MAX_STANDALONE_ZLIB_OUTPUT_BYTES
                    or stream_index in seen):
                return False
            seen.add(stream_index)
            for name in ("decompressed_sha256", "sample_prefix_sha256"):
                digest = row.get(name)
                if (not isinstance(digest, str) or len(digest) != 64
                        or any(char not in "0123456789abcdef" for char in digest)):
                    return False
    return any(selected_by_region.values())
REGION_CONTROL_BOUNDS = {
    # Similar-size boxes displaced away from the target region provide a fixed
    # geographic null for the same signed-integer and scale search.
    "SW": (35.0, 35.0, 72.0, 85.0),
    "Italy": (35.0, 36.0, 48.5, 49.5),
    "Scandinavia": (24.0, 3.0, 42.0, 33.0),
}
LAYOUT_SAMPLE_LIMIT_PER_BIN = 8
REPEATED_TEXT_SAMPLE_MODULUS = 64
REPEATED_TEXT_TOP_LIMIT = 32
REPEATED_TEXT_CANDIDATE_LIMIT = 50_000


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def probe_file(path: str | Path, *, region: str, expected_sha256: str,
               max_file_bytes: int = MAX_FILE_BYTES) -> dict[str, Any]:
    """Stream-decode one manifest-bound file and collect bounded candidates."""
    source = Path(path).resolve(strict=True)
    if region not in REGION_BOUNDS:
        raise ValueError(f"unregistered regional coordinate window: {region}")
    before = source.stat()
    if before.st_size > max_file_bytes:
        raise ValueError("NCDx source exceeds the configured physical read bound")
    source_hash = _sha256_file(source)
    if source_hash.lower() != expected_sha256.lower():
        raise ValueError("NCDx source SHA-256 differs from the manifest-bound expectation")

    min_lat, min_lon, max_lat, max_lon = REGION_BOUNDS[region]
    counts = {f"scale_{scale}_{order}": 0 for scale in COORDINATE_SCALES
              for order in ("lat_lon", "lon_lat")}
    coordinate_samples: dict[str, list[dict[str, Any]]] = {key: [] for key in counts}
    coordinate_bin_counts: dict[str, dict[int, int]] = {key: {} for key in counts}
    text_sample_reservoirs: dict[int, list[tuple[bytes, dict[str, Any]]]] = {
        index: [] for index in range(SAMPLE_DISTRIBUTION_BINS)}
    text_seen_by_bin: dict[int, set[str]] = {
        index: set() for index in range(SAMPLE_DISTRIBUTION_BINS)}
    text_runs_seen = 0
    decoded_digest = hashlib.sha256()

    with source.open("rb") as stream:
        index = read_index(stream, max_file_bytes=max_file_bytes)
        for logical_offset, block in iter_decoded_blocks(stream, index):
            decoded_digest.update(block)
            for match in _PRINTABLE_RUN.finditer(block):
                text_runs_seen += 1
                text = match.group(0).decode("ascii", errors="strict")
                text_offset = logical_offset + match.start()
                text_bin = min(SAMPLE_DISTRIBUTION_BINS - 1,
                    text_offset * SAMPLE_DISTRIBUTION_BINS // index.logical_size_bytes)
                if text not in text_seen_by_bin[text_bin]:
                    text_seen_by_bin[text_bin].add(text)
                    rank = hashlib.sha256(f"{text_offset}:{text}".encode("ascii")).digest()
                    reservoir = text_sample_reservoirs[text_bin]
                    sample = {"logical_offset": text_offset,
                        "distribution_bin": text_bin, "text": text}
                    if len(reservoir) < TEXT_SAMPLES_PER_BIN:
                        reservoir.append((rank, sample))
                    else:
                        worst_index = max(range(len(reservoir)), key=lambda index: reservoir[index][0])
                        if rank < reservoir[worst_index][0]:
                            reservoir[worst_index] = (rank, sample)
            aligned_length = len(block) - (len(block) % 4)
            aligned = block[:aligned_length]
            for local_offset in range(0, max(0, len(aligned) - 7), 4):
                first, second = struct.unpack_from("<ii", aligned, local_offset)
                logical_position = logical_offset + local_offset
                for scale in COORDINATE_SCALES:
                    lat_lon_key = f"scale_{scale}_lat_lon"
                    latitude, longitude = first / scale, second / scale
                    if min_lat <= latitude <= max_lat and min_lon <= longitude <= max_lon:
                        counts[lat_lon_key] += 1
                        lat_lon_bin = min(SAMPLE_DISTRIBUTION_BINS - 1,
                            logical_position * SAMPLE_DISTRIBUTION_BINS // index.logical_size_bytes)
                        if coordinate_bin_counts[lat_lon_key].get(lat_lon_bin, 0) < COORDINATE_SAMPLES_PER_BIN:
                            coordinate_samples[lat_lon_key].append({"logical_offset": logical_position,
                                "distribution_bin": lat_lon_bin,
                                "latitude_candidate": round(latitude, 7),
                                "longitude_candidate": round(longitude, 7)})
                            coordinate_bin_counts[lat_lon_key][lat_lon_bin] = coordinate_bin_counts[lat_lon_key].get(lat_lon_bin, 0) + 1
                    lon_lat_key = f"scale_{scale}_lon_lat"
                    longitude, latitude = first / scale, second / scale
                    if min_lat <= latitude <= max_lat and min_lon <= longitude <= max_lon:
                        counts[lon_lat_key] += 1
                        lon_lat_bin = min(SAMPLE_DISTRIBUTION_BINS - 1,
                            logical_position * SAMPLE_DISTRIBUTION_BINS // index.logical_size_bytes)
                        if coordinate_bin_counts[lon_lat_key].get(lon_lat_bin, 0) < COORDINATE_SAMPLES_PER_BIN:
                            coordinate_samples[lon_lat_key].append({"logical_offset": logical_position,
                                "distribution_bin": lon_lat_bin,
                                "latitude_candidate": round(latitude, 7),
                                "longitude_candidate": round(longitude, 7)})
                            coordinate_bin_counts[lon_lat_key][lon_lat_bin] = coordinate_bin_counts[lon_lat_key].get(lon_lat_bin, 0) + 1
    after = source.stat()
    final_hash = _sha256_file(source)
    if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or final_hash != source_hash):
        raise RuntimeError("read-only NCDx structural probe detected a changed source")
    if before.st_size != index.physical_size_bytes:
        raise RuntimeError("NCDx source size changed between its initial stat and container read")
    return {"region": region, "file_name": source.name,
        "source_bytes": before.st_size, "source_sha256": source_hash,
        "logical_bytes": index.logical_size_bytes,
        "logical_sha256": decoded_digest.hexdigest(),
        "block_size_bytes": index.block_size_bytes, "block_count": index.block_count,
        "opaque_header_u32_le": index.opaque_header_u32_le,
        "ascii_run_count_by_block": text_runs_seen,
        "bounded_ascii_samples": [sample for bin_index in range(SAMPLE_DISTRIBUTION_BINS)
                                   for _, sample in sorted(text_sample_reservoirs[bin_index],
                                                           key=lambda item: item[1]["logical_offset"])],
        "sample_distribution_bins": SAMPLE_DISTRIBUTION_BINS,
        "coordinate_candidate_counts_by_scale_and_order": counts,
        "coordinate_candidate_samples": coordinate_samples,
        "source_stat_unchanged": True,
        "raw_payload_bytes_retained": False,
        "claim_scope": "literal decoded text and bounded integer-pair candidates only; semantics UNKNOWN"}


def probe_regional_set(sources: list[dict[str, Any]], *,
                       source_root: str | Path) -> dict[str, Any]:
    """Probe exactly the three inventory-bound regional source rows."""
    if len(sources) != 3 or {str(row.get("region")) for row in sources} != set(REGION_BOUNDS):
        raise ValueError("regional structure probe requires one source per registered region")
    root = Path(source_root).resolve(strict=True)
    observations = []
    for row in sources:
        relative = Path(str(row["relative_path"]).replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("structural probe source must be a safe relative path")
        source = (root / relative).resolve(strict=True)
        if not source.is_relative_to(root):
            raise ValueError("structural probe source escaped the configured media root")
        observation = probe_file(source, region=str(row["region"]),
                                 expected_sha256=str(row["sha256"]))
        if observation["source_bytes"] != int(row["size_bytes"]):
            raise ValueError("structural probe source size differs from the inventory")
        observations.append(observation)
    if not all(row["source_stat_unchanged"] for row in observations):
        raise RuntimeError("one or more regional source files changed during the structural probe")
    return {"status": "PASS", "observations": observations,
        "source_count": len(observations), "source_write_count": 0,
        "all_sources_bound_to_inventory": True,
        "raw_payload_bytes_retained": False,
        "claim_scope": "read-only decoded NCDx structure candidates; no field or record semantics inferred"}


def audit_string_coordinate_proximity(path: str | Path, *, region: str,
                                      expected_sha256: str,
                                      text_samples: list[dict[str, Any]],
                                      radius_bytes: int = 128,
                                      max_file_bytes: int = MAX_FILE_BYTES) -> dict[str, Any]:
    """Compare bounded sampled string windows with fixed-position controls.

    This tests whether regional signed-int32 candidates at fixed scales are
    more frequent near decoded printable strings than at evenly spaced control
    offsets. It does not prove that a candidate pair is a coordinate or that
    any string and pair belong to one record.
    """
    source = Path(path).resolve(strict=True)
    if region not in REGION_BOUNDS:
        raise ValueError(f"unregistered regional coordinate window: {region}")
    if not 0 < radius_bytes <= 1024:
        raise ValueError("proximity radius is outside the fixed safety bound")
    if not isinstance(text_samples, list) or len(text_samples) > MAX_TEXT_SAMPLES:
        raise ValueError("proximity audit received too many text anchors")
    before = source.stat()
    if before.st_size > max_file_bytes:
        raise ValueError("NCDx source exceeds the configured physical read bound")
    encoded = source.read_bytes()
    source_hash = hashlib.sha256(encoded).hexdigest()
    if source_hash.lower() != expected_sha256.lower():
        raise ValueError("NCDx source SHA-256 differs from the manifest-bound expectation")
    index, logical_data = decode_bytes(encoded, max_file_bytes=max_file_bytes)
    if len(logical_data) != index.logical_size_bytes:
        raise RuntimeError("decoded payload size differs from the container header")

    valid_anchors: list[dict[str, Any]] = []
    for row in text_samples:
        if not isinstance(row, dict):
            continue
        offset, label = int(row.get("logical_offset", -1)), str(row.get("text", ""))
        if offset < 1024 or offset + len(label) > len(logical_data):
            continue
        if logical_data[offset:offset + len(label)] != label.encode("ascii", errors="strict"):
            raise ValueError("saved text anchor does not match the independently decoded source")
        valid_anchors.append({"logical_offset": offset, "text": label})
    if not valid_anchors:
        raise ValueError("no non-header text anchors are available for the proximity audit")

    control_count = min(256, max(64, len(valid_anchors) // 2))
    controls = sorted({min(len(logical_data) - 8,
        (((2 * index + 1) * len(logical_data)) // (2 * control_count)) // 4 * 4)
        for index in range(control_count)})
    min_lat, min_lon, max_lat, max_lon = REGION_BOUNDS[region]
    keys = [f"scale_{scale}_{order}" for scale in COORDINATE_SCALES
            for order in ("lat_lon", "lon_lat")]

    def score(centers: list[int], *, labels: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        hit_windows = {key: 0 for key in keys}
        candidate_pairs = {key: 0 for key in keys}
        examples: dict[str, list[dict[str, Any]]] = {key: [] for key in keys}
        total_hits = 0
        for window_index, center in enumerate(centers):
            start = max(0, center - radius_bytes)
            start = (start + 3) // 4 * 4
            end = min(len(logical_data) - 8, center + radius_bytes)
            local_hit = {key: False for key in keys}
            nearest: dict[str, tuple[int, int, float, float]] = {}
            for position in range(start, end + 1, 4):
                first, second = struct.unpack_from("<ii", logical_data, position)
                for scale in COORDINATE_SCALES:
                    for order, latitude, longitude in (
                        ("lat_lon", first / scale, second / scale),
                        ("lon_lat", second / scale, first / scale)):
                        if min_lat <= latitude <= max_lat and min_lon <= longitude <= max_lon:
                            key = f"scale_{scale}_{order}"
                            local_hit[key] = True
                            candidate_pairs[key] += 1
                            distance = abs(position - center)
                            previous = nearest.get(key)
                            if previous is None or distance < previous[0]:
                                nearest[key] = (distance, position, round(latitude, 7), round(longitude, 7))
            for key, present in local_hit.items():
                if present:
                    hit_windows[key] += 1
                    total_hits += 1
                    if len(examples[key]) < 8:
                        detail: dict[str, Any] = {"anchor_offset": center,
                            "window_index": window_index, "distance_bytes": nearest[key][0],
                            "candidate_offset": nearest[key][1],
                            "latitude_candidate": nearest[key][2],
                            "longitude_candidate": nearest[key][3]}
                        if labels is not None:
                            detail["text_anchor"] = labels[window_index]["text"]
                        examples[key].append(detail)
        return {"window_count": len(centers), "candidate_hit_windows_by_scale_and_order": hit_windows,
            "candidate_pairs_by_scale_and_order": candidate_pairs,
            "bounded_examples_by_scale_and_order": examples, "total_hit_windows": total_hits}

    label_offsets = [row["logical_offset"] for row in valid_anchors]
    label_result = score(label_offsets, labels=valid_anchors)
    control_result = score(controls)
    after = source.stat()
    final_hash = _sha256_file(source)
    if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or final_hash != source_hash):
        raise RuntimeError("read-only NCDx proximity audit detected a changed source")
    return {"region": region, "file_name": source.name,
        "source_bytes": before.st_size, "source_sha256": source_hash,
        "logical_bytes": len(logical_data), "logical_sha256": hashlib.sha256(logical_data).hexdigest(),
        "block_size_bytes": index.block_size_bytes, "block_count": index.block_count,
        "label_windows": label_result, "fixed_control_windows": control_result,
        "window_radius_bytes": radius_bytes, "coordinate_scales": list(COORDINATE_SCALES),
        "regional_bounds": {"min_lat": min_lat, "min_lon": min_lon,
                            "max_lat": max_lat, "max_lon": max_lon},
        "source_stat_unchanged": True, "raw_payload_bytes_retained": False,
        "claim_scope": "hypothesis test for proximity enrichment only; record and coordinate semantics UNKNOWN"}


def profile_printable_run_layout(path: str | Path, *, region: str,
                                 expected_sha256: str,
                                 max_file_bytes: int = MAX_FILE_BYTES) -> dict[str, Any]:
    """Summarize printable-run layout without retaining decoded source text."""
    source = Path(path).resolve(strict=True)
    if region not in REGION_BOUNDS:
        raise ValueError(f"unregistered regional layout profile: {region}")
    before = source.stat()
    if before.st_size > max_file_bytes:
        raise ValueError("NCDx source exceeds the configured physical read bound")
    encoded = source.read_bytes()
    source_hash = hashlib.sha256(encoded).hexdigest()
    if source_hash.lower() != expected_sha256.lower():
        raise ValueError("NCDx source SHA-256 differs from the manifest-bound expectation")
    index, logical_data = decode_bytes(encoded, max_file_bytes=max_file_bytes)
    if len(logical_data) != index.logical_size_bytes:
        raise RuntimeError("decoded payload size differs from the container header")

    length_labels = ("4_7", "8_15", "16_31", "32_63", "64_96")
    gap_labels = ("0", "1_3", "4_7", "8_15", "16_63", "64_plus")
    length_counts = Counter({label: 0 for label in length_labels})
    gap_counts = Counter({label: 0 for label in gap_labels})
    bins = [{"run_count": 0, "printable_bytes": 0} for _ in range(SAMPLE_DISTRIBUTION_BINS)]
    samples: dict[int, list[tuple[bytes, dict[str, Any]]]] = {
        bin_index: [] for bin_index in range(SAMPLE_DISTRIBUTION_BINS)}
    run_count = printable_bytes = max_run_length = 0
    previous_end: int | None = None
    for match in _PRINTABLE_RUN.finditer(logical_data):
        offset, run = match.start(), match.group(0)
        length = len(run)
        bin_index = min(SAMPLE_DISTRIBUTION_BINS - 1,
            offset * SAMPLE_DISTRIBUTION_BINS // max(1, len(logical_data)))
        label = ("4_7" if length <= 7 else "8_15" if length <= 15 else
                 "16_31" if length <= 31 else "32_63" if length <= 63 else "64_96")
        length_counts[label] += 1
        bins[bin_index]["run_count"] += 1
        bins[bin_index]["printable_bytes"] += length
        run_count += 1
        printable_bytes += length
        max_run_length = max(max_run_length, length)
        if previous_end is not None:
            gap = max(0, offset - previous_end)
            gap_label = ("0" if gap == 0 else "1_3" if gap <= 3 else
                "4_7" if gap <= 7 else "8_15" if gap <= 15 else
                "16_63" if gap <= 63 else "64_plus")
            gap_counts[gap_label] += 1
        previous_end = offset + length
        digest = hashlib.sha256(run).hexdigest()
        rank = hashlib.sha256(f"{offset}:{digest}".encode("ascii")).digest()
        sample = {"logical_offset": offset, "length_bytes": length, "sha256": digest}
        reservoir = samples[bin_index]
        if len(reservoir) < LAYOUT_SAMPLE_LIMIT_PER_BIN:
            reservoir.append((rank, sample))
        else:
            worst_index = max(range(len(reservoir)), key=lambda item: reservoir[item][0])
            if rank < reservoir[worst_index][0]:
                reservoir[worst_index] = (rank, sample)

    after = source.stat()
    final_hash = _sha256_file(source)
    if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or final_hash != source_hash or before.st_size != index.physical_size_bytes):
        raise RuntimeError("read-only NCDx layout profile detected a changed source")
    return {"region": region, "file_name": source.name,
        "source_bytes": before.st_size, "source_sha256": source_hash,
        "logical_bytes": len(logical_data), "logical_sha256": hashlib.sha256(logical_data).hexdigest(),
        "block_size_bytes": index.block_size_bytes, "block_count": index.block_count,
        "opaque_header_u32_le": index.opaque_header_u32_le,
        "printable_run_count": run_count, "printable_bytes": printable_bytes,
        "maximum_run_bytes": max_run_length,
        "run_length_counts": dict(length_counts), "inter_run_gap_counts": dict(gap_counts),
        "distribution_bins": bins,
        "bounded_hash_samples_by_bin": [sample for bin_index in range(SAMPLE_DISTRIBUTION_BINS)
            for _, sample in sorted(samples[bin_index], key=lambda item: item[1]["logical_offset"])],
        "source_stat_unchanged": True, "raw_payload_bytes_retained": False,
        "claim_scope": "printable-run length, spacing and distribution statistics only; record semantics UNKNOWN"}


def profile_repeated_text_candidates(path: str | Path, *, region: str,
                                     expected_sha256: str,
                                     sampling_modulus: int = REPEATED_TEXT_SAMPLE_MODULUS,
                                     top_n: int = REPEATED_TEXT_TOP_LIMIT,
                                     max_candidates: int = REPEATED_TEXT_CANDIDATE_LIMIT,
                                     max_file_bytes: int = MAX_FILE_BYTES) -> dict[str, Any]:
    """Count a deterministic hash sample of unique printable values exactly.

    Inclusion depends only on the string bytes, so the same literal is sampled
    in every region. At most ``max_candidates`` distinct values are retained.
    """
    if (sampling_modulus < 1 or sampling_modulus > 4096
            or sampling_modulus & (sampling_modulus - 1)):
        raise ValueError("sampling modulus must be a power of two from 1 through 4096")
    if not 1 <= top_n <= 64 or not 1 <= max_candidates <= 100_000:
        raise ValueError("repeated-text output and candidate bounds are invalid")
    source = Path(path).resolve(strict=True)
    if region not in REGION_BOUNDS:
        raise ValueError(f"unregistered regional repeated-text profile: {region}")
    before = source.stat()
    if before.st_size > max_file_bytes:
        raise ValueError("NCDx source exceeds the configured physical read bound")
    encoded = source.read_bytes()
    source_hash = hashlib.sha256(encoded).hexdigest()
    if source_hash.lower() != expected_sha256.lower():
        raise ValueError("NCDx source SHA-256 differs from the manifest-bound expectation")
    index, logical_data = decode_bytes(encoded, max_file_bytes=max_file_bytes)
    if len(logical_data) != index.logical_size_bytes:
        raise RuntimeError("decoded payload size differs from the container header")

    exact_counts: Counter[bytes] = Counter()
    offsets: dict[bytes, list[int]] = {}
    total_runs = sampled_occurrences = 0
    for match in _PRINTABLE_RUN.finditer(logical_data):
        token = match.group(0)
        total_runs += 1
        digest = hashlib.sha256(token).digest()
        if int.from_bytes(digest[:4], "big") % sampling_modulus != 0:
            continue
        if token not in exact_counts and len(exact_counts) >= max_candidates:
            raise ValueError("deterministic repeated-text sample exceeds its fixed candidate cap")
        exact_counts[token] += 1
        sampled_occurrences += 1
        samples = offsets.setdefault(token, [])
        if len(samples) < 4:
            samples.append(match.start())

    top = sorted(exact_counts.items(), key=lambda item: (-item[1], len(item[0]), item[0]))[:top_n]
    inventory = sorted(exact_counts.items(), key=lambda item: hashlib.sha256(item[0]).hexdigest())
    after = source.stat()
    final_hash = _sha256_file(source)
    if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or final_hash != source_hash or before.st_size != index.physical_size_bytes):
        raise RuntimeError("read-only repeated-text profile detected a changed source")
    return {"region": region, "file_name": source.name,
        "source_bytes": before.st_size, "source_sha256": source_hash,
        "logical_bytes": len(logical_data), "logical_sha256": hashlib.sha256(logical_data).hexdigest(),
        "block_count": index.block_count, "total_printable_runs": total_runs,
        "sampling_modulus": sampling_modulus, "candidate_value_count": len(exact_counts),
        "sampled_occurrence_count": sampled_occurrences,
        "sampled_value_inventory": [{"text": token.decode("ascii"),
            "length_bytes": len(token), "sha256": hashlib.sha256(token).hexdigest(),
            "exact_sampled_count": count} for token, count in inventory],
        "top_repeated_values": [{"text": token.decode("ascii"),
            "length_bytes": len(token), "sha256": hashlib.sha256(token).hexdigest(),
            "exact_sampled_count": count, "sampled_offsets": offsets[token]}
            for token, count in top],
        "source_stat_unchanged": True, "raw_payload_bytes_retained": False,
        "claim_scope": "exact counts for deterministically sampled printable values only; record semantics UNKNOWN"}


def audit_repeated_text_coordinate_proximity(path: str | Path, *, region: str,
                                             expected_sha256: str,
                                             anchor_texts: list[str],
                                             occurrences_per_value: int = 4) -> dict[str, Any]:
    """Test coordinate-candidate proximity to repeated values from a verified index."""
    if not isinstance(anchor_texts, list) or not 1 <= len(anchor_texts) <= 32:
        raise ValueError("repeated-text proximity requires 1-32 verified anchor values")
    if not 1 <= occurrences_per_value <= 16:
        raise ValueError("repeated-text occurrence sample is outside its fixed bound")
    values = []
    for value in anchor_texts:
        if not isinstance(value, str):
            raise ValueError("repeated-text anchors must be strings from the verified dictionary")
        encoded_value = value.encode("ascii", errors="strict")
        if not 4 <= len(encoded_value) <= 96:
            raise ValueError("repeated-text anchor length is outside the decoded-run allowlist")
        values.append(encoded_value)
    if len(set(values)) != len(values):
        raise ValueError("repeated-text anchors must be unique")
    source = Path(path).resolve(strict=True)
    if region not in REGION_BOUNDS:
        raise ValueError(f"unregistered regional repeated-text audit: {region}")
    before = source.stat()
    if before.st_size > MAX_FILE_BYTES:
        raise ValueError("NCDx source exceeds the configured physical read bound")
    encoded = source.read_bytes()
    source_hash = hashlib.sha256(encoded).hexdigest()
    if source_hash.lower() != expected_sha256.lower():
        raise ValueError("NCDx source SHA-256 differs from the manifest-bound expectation")
    index, logical_data = decode_bytes(encoded)
    value_set = set(values)
    counts = Counter({value: 0 for value in values})
    reservoirs: dict[bytes, list[tuple[bytes, int]]] = {value: [] for value in values}
    for match in _PRINTABLE_RUN.finditer(logical_data):
        token = match.group(0)
        if token not in value_set:
            continue
        counts[token] += 1
        offset = match.start()
        rank = hashlib.sha256(f"{offset}:".encode("ascii") + token).digest()
        reservoir = reservoirs[token]
        if len(reservoir) < occurrences_per_value:
            reservoir.append((rank, offset))
        else:
            worst_index = max(range(len(reservoir)), key=lambda item: reservoir[item][0])
            if rank < reservoir[worst_index][0]:
                reservoir[worst_index] = (rank, offset)
    missing = [value.decode("ascii") for value in values if counts[value] == 0]
    if missing:
        raise ValueError("verified repeated-text anchors are absent from the fresh decoded source")
    samples = [{"logical_offset": offset, "text": value.decode("ascii")}
        for value in values for _, offset in sorted(reservoirs[value], key=lambda item: item[1])]
    proximity = audit_string_coordinate_proximity(source, region=region,
        expected_sha256=expected_sha256, text_samples=samples)
    after = source.stat()
    if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or before.st_size != index.physical_size_bytes):
        raise RuntimeError("read-only repeated-text proximity audit detected a changed source")
    return {"region": region, "source_bytes": before.st_size,
        "source_sha256": source_hash, "logical_sha256": hashlib.sha256(logical_data).hexdigest(),
        "anchor_value_count": len(values),
        "anchor_occurrence_counts_by_sha256": {hashlib.sha256(value).hexdigest(): counts[value]
            for value in values},
        "selected_anchor_offsets_by_sha256": {hashlib.sha256(value).hexdigest():
            [offset for _, offset in sorted(reservoirs[value], key=lambda item: item[1])]
            for value in values},
        "proximity": proximity, "source_stat_unchanged": True,
        "raw_payload_bytes_retained": False,
        "claim_scope": "proximity hypothesis for repeatedly observed literal values only; coordinate and record semantics UNKNOWN"}


def profile_text_block_boundaries(path: str | Path, *, region: str,
                                  expected_sha256: str,
                                  position_bins: int = 16) -> dict[str, Any]:
    """Measure decoded printable-run starts and crossings at NCDx block boundaries."""
    if not 4 <= position_bins <= 64:
        raise ValueError("block position histogram must contain 4-64 bins")
    source = Path(path).resolve(strict=True)
    if region not in REGION_BOUNDS:
        raise ValueError(f"unregistered regional block-boundary profile: {region}")
    before = source.stat()
    if before.st_size > MAX_FILE_BYTES:
        raise ValueError("NCDx source exceeds the configured physical read bound")
    encoded = source.read_bytes()
    source_hash = hashlib.sha256(encoded).hexdigest()
    if source_hash.lower() != expected_sha256.lower():
        raise ValueError("NCDx source SHA-256 differs from the manifest-bound expectation")
    index, logical_data = decode_bytes(encoded)
    if len(logical_data) != index.logical_size_bytes:
        raise RuntimeError("decoded payload size differs from the container header")
    starts_per_block = [0] * index.block_count
    boundary_buckets = Counter({"0_3": 0, "4_15": 0, "16_63": 0, "64_plus": 0})
    position_counts = [0] * position_bins
    run_count = crossing_count = 0
    expected_crossings = crossing_variance = 0.0
    boundary_positions = Counter()
    block_size = index.block_size_bytes
    for within_block in range(block_size):
        distance = min(within_block, block_size - within_block)
        bucket = ("0_3" if distance <= 3 else "4_15" if distance <= 15
                  else "16_63" if distance <= 63 else "64_plus")
        boundary_positions[bucket] += 1
    for match in _PRINTABLE_RUN.finditer(logical_data):
        start, end = match.start(), match.end()
        start_block = start // block_size
        end_block = (end - 1) // block_size
        run_count += 1
        probability_crossing = min(1.0, max(0, len(match.group(0)) - 1) / block_size)
        expected_crossings += probability_crossing
        crossing_variance += probability_crossing * (1.0 - probability_crossing)
        starts_per_block[start_block] += 1
        within_block = start % block_size
        position_counts[min(position_bins - 1, within_block * position_bins // block_size)] += 1
        boundary_distance = min(within_block, block_size - within_block)
        bucket = ("0_3" if boundary_distance <= 3 else "4_15" if boundary_distance <= 15
                  else "16_63" if boundary_distance <= 63 else "64_plus")
        boundary_buckets[bucket] += 1
        if end_block != start_block:
            crossing_count += 1
    after = source.stat()
    final_hash = _sha256_file(source)
    if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or final_hash != source_hash or before.st_size != index.physical_size_bytes):
        raise RuntimeError("read-only NCDx block-boundary profile detected a changed source")
    expected_by_boundary = {bucket: run_count * boundary_positions[bucket] / block_size
                            for bucket in boundary_buckets}
    variance_by_boundary = {bucket: expected_by_boundary[bucket] *
        (1.0 - boundary_positions[bucket] / block_size) for bucket in boundary_buckets}
    crossing_z = ((crossing_count - expected_crossings) / crossing_variance ** 0.5
                  if crossing_variance > 0 else 0.0)
    return {"region": region, "file_name": source.name,
        "source_bytes": before.st_size, "source_sha256": source_hash,
        "logical_bytes": len(logical_data), "logical_sha256": hashlib.sha256(logical_data).hexdigest(),
        "block_size_bytes": block_size, "block_count": index.block_count,
        "printable_run_count": run_count, "runs_crossing_block_boundary": crossing_count,
        "crossing_run_rate": round(crossing_count / run_count, 8) if run_count else 0.0,
        "run_start_distance_to_nearest_boundary": dict(boundary_buckets),
        "run_start_position_histogram": position_counts,
        "random_phase_null": {"assumption": "each printable run start has a uniform independent phase within a block",
            "expected_crossing_count": round(expected_crossings, 3),
            "expected_crossing_rate": round(expected_crossings / run_count, 8) if run_count else 0.0,
            "crossing_z_score": round(crossing_z, 4),
            "crossings_consistent_with_null_at_abs_z_le_2": abs(crossing_z) <= 2.0,
            "observed_vs_expected_start_distance_counts": {bucket: {
                "observed": boundary_buckets[bucket],
                "expected": round(expected_by_boundary[bucket], 3),
                "z_score": round((boundary_buckets[bucket] - expected_by_boundary[bucket]) /
                    variance_by_boundary[bucket] ** 0.5, 4)
                    if variance_by_boundary[bucket] > 0 else 0.0}
                for bucket in boundary_buckets}},
        "runs_per_block_summary": {"minimum": min(starts_per_block, default=0),
            "median": statistics.median(starts_per_block) if starts_per_block else 0,
            "maximum": max(starts_per_block, default=0),
            "empty_blocks": sum(count == 0 for count in starts_per_block)},
        "source_stat_unchanged": True, "raw_payload_bytes_retained": False,
        "claim_scope": "decoded printable-run placement relative to independent block boundaries only; record semantics UNKNOWN"}


def audit_text_coordinate_association(path: str | Path, *, region: str,
                                      expected_sha256: str,
                                      anchor_strategy: str = "all_printable",
                                      max_anchors: int = 4096,
                                      controls_per_anchor: int = 1,
                                      radius_bytes: int = 64,
                                      max_file_bytes: int = MAX_FILE_BYTES) -> dict[str, Any]:
    """Census text-run proximity to regional integer-pair candidates.

    Anchor windows are stratified over the entire decoded file. Each anchor is
    paired with a deterministic, same-bin control window that contains no
    printable run. This improves on sparse evenly-spaced controls while still
    making no claim that an integer pair is a coordinate or belongs to a text
    record.
    """
    source = Path(path).resolve(strict=True)
    if region not in REGION_BOUNDS:
        raise ValueError(f"unregistered regional coordinate window: {region}")
    if anchor_strategy not in {"all_printable", "repeated_literals"}:
        raise ValueError("unsupported text-anchor strategy")
    if not 1 <= max_anchors <= 8192:
        raise ValueError("anchor sample limit is outside the fixed safety bound")
    if not 1 <= controls_per_anchor <= 2:
        raise ValueError("control windows per anchor are outside the fixed safety bound")
    if not 0 < radius_bytes <= 128:
        raise ValueError("association radius is outside the fixed safety bound")

    before = source.stat()
    if before.st_size > max_file_bytes:
        raise ValueError("NCDx source exceeds the configured physical read bound")
    encoded = source.read_bytes()
    source_hash = hashlib.sha256(encoded).hexdigest()
    if source_hash.lower() != expected_sha256.lower():
        raise ValueError("NCDx source SHA-256 differs from the manifest-bound expectation")
    index, logical_data = decode_bytes(encoded, max_file_bytes=max_file_bytes)
    if len(logical_data) != index.logical_size_bytes:
        raise RuntimeError("decoded payload size differs from the container header")

    source_seed = hashlib.sha256(
        f"{source_hash}:{anchor_strategy}:{max_anchors}:{controls_per_anchor}:{radius_bytes}".encode("ascii")
    ).digest()
    anchor_rng = random.Random(int.from_bytes(source_seed[:8], "little"))
    control_rng = random.Random(int.from_bytes(source_seed[8:16], "little"))
    repeated_counts: Counter[bytes] | None = None
    if anchor_strategy == "repeated_literals":
        repeated_counts = Counter(match.group(0) for match in _PRINTABLE_RUN.finditer(logical_data))
        if len(repeated_counts) > 500_000:
            raise ValueError("repeated-literal inventory exceeds the fixed unique-value limit")

    bins = SAMPLE_DISTRIBUTION_BINS
    per_bin_limit = max(1, math.ceil(max_anchors / bins))
    reservoirs: list[list[int]] = [[] for _ in range(bins)]
    eligible_by_bin = [0] * bins
    printable_run_count = 0
    eligible_anchor_count = 0
    for match in _PRINTABLE_RUN.finditer(logical_data):
        printable_run_count += 1
        literal = match.group(0)
        if repeated_counts is not None and repeated_counts[literal] < 2:
            continue
        eligible_anchor_count += 1
        offset = match.start()
        bin_index = min(bins - 1, offset * bins // len(logical_data))
        eligible_by_bin[bin_index] += 1
        reservoir = reservoirs[bin_index]
        if len(reservoir) < per_bin_limit:
            reservoir.append(offset)
        else:
            replacement = anchor_rng.randrange(eligible_by_bin[bin_index])
            if replacement < per_bin_limit:
                reservoir[replacement] = offset

    anchors = sorted(offset for reservoir in reservoirs for offset in reservoir)
    if len(anchors) > max_anchors:
        anchors = [anchors[(index * len(anchors)) // max_anchors] for index in range(max_anchors)]
    if not anchors:
        raise ValueError("no eligible printable text anchors are present in the decoded source")

    min_lat, min_lon, max_lat, max_lon = REGION_BOUNDS[region]
    keys = [f"scale_{scale}_{order}" for scale in COORDINATE_SCALES
            for order in ("lat_lon", "lon_lat")]
    hit_counts = {group: {key: 0 for key in keys} for group in ("anchors", "controls")}
    pair_counts = {group: {key: 0 for key in keys} for group in ("anchors", "controls")}
    examples: dict[str, dict[str, list[dict[str, int | float]]]] = {
        group: {key: [] for key in keys} for group in ("anchors", "controls")}
    matched_anchors: list[int] = []
    controls: list[int] = []
    used_controls: set[int] = set()

    def find_controls(anchor: int, bin_index: int) -> list[int]:
        start = bin_index * len(logical_data) // bins
        end = max(start, (bin_index + 1) * len(logical_data) // bins - 8)
        first_aligned = (start + 3) // 4 * 4
        last_aligned = end // 4 * 4
        slot_count = (last_aligned - first_aligned) // 4 + 1
        if slot_count <= 0:
            return []
        found: list[int] = []
        for _ in range(256):
            if len(found) >= controls_per_anchor:
                break
            center = first_aligned + control_rng.randrange(slot_count) * 4
            window_start = max(0, center - radius_bytes)
            window_end = min(len(logical_data), center + radius_bytes + 8)
            if _PRINTABLE_RUN.search(logical_data[window_start:window_end]):
                continue
            if abs(center - anchor) <= radius_bytes * 2:
                continue
            if any(center + delta in used_controls or any(center + delta == prior
                    for prior in found) for delta in range(-radius_bytes * 2,
                                                           radius_bytes * 2 + 1, 4)):
                continue
            found.append(center)
        return found

    def score_window(center: int, group: str) -> None:
        start = max(0, center - radius_bytes)
        start = (start + 3) // 4 * 4
        end = min(len(logical_data) - 8, center + radius_bytes)
        local_hits = {key: False for key in keys}
        for position in range(start, end + 1, 4):
            first, second = struct.unpack_from("<ii", logical_data, position)
            for scale in COORDINATE_SCALES:
                a, b = first / scale, second / scale
                for order, lat, lon in (("lat_lon", a, b), ("lon_lat", b, a)):
                    if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
                        key = f"scale_{scale}_{order}"
                        pair_counts[group][key] += 1
                        local_hits[key] = True
                        if len(examples[group][key]) < 12:
                            examples[group][key].append({"window_center": center,
                                "candidate_offset": position, "latitude_candidate": lat,
                                "longitude_candidate": lon})
        for key, hit in local_hits.items():
            if hit:
                hit_counts[group][key] += 1

    for anchor in anchors:
        bin_index = min(bins - 1, anchor * bins // len(logical_data))
        matched_controls = find_controls(anchor, bin_index)
        if len(matched_controls) != controls_per_anchor:
            continue
        matched_anchors.append(anchor)
        controls.extend(matched_controls)
        used_controls.update(matched_controls)
        score_window(anchor, "anchors")
        for control in matched_controls:
            score_window(control, "controls")

    if not matched_anchors:
        raise ValueError("could not draw any text-free control windows matched to an anchor bin")

    anchor_n, control_n = len(matched_anchors), len(controls)
    association: dict[str, dict[str, Any]] = {}
    for key in keys:
        anchor_hits = hit_counts["anchors"][key]
        control_hits = hit_counts["controls"][key]
        anchor_rate = anchor_hits / anchor_n
        control_rate = control_hits / control_n
        association[key] = {
            "anchor_hit_windows": anchor_hits,
            "anchor_window_count": anchor_n,
            "anchor_hit_rate": round(anchor_rate, 8),
            "control_hit_windows": control_hits,
            "control_window_count": control_n,
            "control_hit_rate": round(control_rate, 8),
            "rate_difference": round(anchor_rate - control_rate, 8),
            "rate_ratio": round(anchor_rate / control_rate, 6) if control_rate else None,
            "candidate_pairs_near_anchors": pair_counts["anchors"][key],
            "candidate_pairs_near_controls": pair_counts["controls"][key],
            "bounded_anchor_examples": examples["anchors"][key],
            "bounded_control_examples": examples["controls"][key],
        }

    after = source.stat()
    if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or _sha256_file(source) != source_hash):
        raise RuntimeError("read-only coordinate association census detected a changed source")
    return {"region": region, "file_name": source.name,
        "source_bytes": before.st_size, "source_sha256": source_hash,
        "logical_bytes": len(logical_data), "logical_sha256": hashlib.sha256(logical_data).hexdigest(),
        "anchor_strategy": anchor_strategy,
        "printable_run_count": printable_run_count,
        "eligible_anchor_count": eligible_anchor_count,
        "eligible_anchor_counts_by_bin": eligible_by_bin,
        "sampled_anchor_count": anchor_n,
        "unmatched_anchor_count": len(anchors) - anchor_n,
        "control_windows_per_anchor": controls_per_anchor,
        "matched_control_count": control_n, "radius_bytes": radius_bytes,
        "association_by_scale_and_order": association,
        "source_stat_unchanged": True, "raw_payload_bytes_retained": False,
        "claim_scope": "text-window association of regional integer-pair candidates only; coordinate and record semantics UNKNOWN"}


def scan_standalone_zlib_streams(path: str | Path, *, expected_sha256: str,
                                 max_file_bytes: int = MAX_STANDALONE_ZLIB_FILE_BYTES,
                                 max_compressed_bytes: int = MAX_STANDALONE_ZLIB_COMPRESSED_BYTES,
                                 max_output_bytes: int = MAX_STANDALONE_ZLIB_OUTPUT_BYTES,
                                 max_header_candidates: int = MAX_STANDALONE_ZLIB_HEADER_CANDIDATES,
                                 _payload_sample_stride: int = ZLIB_COORDINATE_SAMPLE_STRIDE,
                                 _payload_sample_limit: int = ZLIB_COORDINATE_SAMPLE_LIMIT,
                                 _payload_sample_prefix_bytes: int = ZLIB_COORDINATE_SAMPLE_PREFIX_BYTES,
                                 _payload_sample_indices: set[int] | None = None,
                                 _all_streams: list[dict[str, Any]] | None = None,
                                 _payload_samples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Find bounded self-contained zlib streams without retaining payloads.

    This scans raw NCDx family files only. The already-confirmed ``zip\x01``
    block container is reported and skipped so its inner per-block zlib streams
    are not misrepresented as a new file format.
    """
    source = Path(path).resolve(strict=True)
    if not 0 < max_file_bytes <= MAX_STANDALONE_ZLIB_FILE_BYTES:
        raise ValueError("standalone zlib source limit exceeds the fixed safety bound")
    if not 1024 <= max_compressed_bytes <= MAX_STANDALONE_ZLIB_COMPRESSED_BYTES:
        raise ValueError("standalone zlib compressed-byte limit is outside the fixed safety bound")
    if not 1024 <= max_output_bytes <= MAX_STANDALONE_ZLIB_OUTPUT_BYTES:
        raise ValueError("standalone zlib output-byte limit is outside the fixed safety bound")
    if not 1 <= max_header_candidates <= MAX_STANDALONE_ZLIB_HEADER_CANDIDATES:
        raise ValueError("standalone zlib header-candidate limit is outside the fixed safety bound")
    if not 1 <= _payload_sample_stride <= 8:
        raise ValueError("standalone zlib payload sample stride is outside the fixed safety bound")
    if not 1 <= _payload_sample_limit <= MAX_STANDALONE_ZLIB_HEADER_CANDIDATES:
        raise ValueError("standalone zlib payload sample count is outside the fixed safety bound")
    if not 1 <= _payload_sample_prefix_bytes <= MAX_STANDALONE_ZLIB_OUTPUT_BYTES:
        raise ValueError("standalone zlib payload sample prefix is outside the fixed safety bound")
    if (_payload_sample_indices is not None
            and (len(_payload_sample_indices) > 2
                 or any(not isinstance(index, int) or index < 0
                        or index >= max_header_candidates for index in _payload_sample_indices))):
        raise ValueError("selected zlib stream sample indices exceed the fixed audit bound")
    before = source.stat()
    if not 0 < before.st_size <= max_file_bytes:
        raise ValueError(f"standalone zlib source size is outside the accepted range: {before.st_size}")
    source_hash = _sha256_file(source)
    if source_hash.lower() != expected_sha256.lower():
        raise ValueError("standalone zlib source SHA-256 differs from the manifest-bound expectation")

    streams: list[dict[str, Any]] = []
    header_candidates = 0
    attempted_candidates = 0
    rejected_output_limit = 0
    candidate_limit_reached = False
    recognized_container = False
    with source.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        recognized_container = data[:4] == b"zip\x01"
        if not recognized_container:
            offset = 0
            while True:
                offset = data.find(b"\x78", offset)
                if offset < 0 or offset + 2 > len(data):
                    break
                cmf, flg = data[offset], data[offset + 1]
                offset += 1
                if (cmf & 0x0F) != 8 or (cmf >> 4) > 7 or ((cmf << 8) | flg) % 31:
                    continue
                header_candidates += 1
                if attempted_candidates >= max_header_candidates:
                    candidate_limit_reached = True
                    break
                attempted_candidates += 1
                compressed_end = min(len(data), offset - 1 + max_compressed_bytes)
                try:
                    decoder = zlib.decompressobj()
                    payload = decoder.decompress(data[offset - 1:compressed_end], max_output_bytes + 1)
                except zlib.error:
                    continue
                if len(payload) > max_output_bytes or decoder.unconsumed_tail:
                    rejected_output_limit += 1
                    continue
                if not decoder.eof:
                    continue
                consumed = compressed_end - (offset - 1) - len(decoder.unused_data)
                if consumed <= 0 or len(payload) < 16:
                    continue
                stream_index = len(streams)
                decompressed_hash = hashlib.sha256(payload).hexdigest()
                selected_for_audit = (_payload_sample_indices is not None
                    and stream_index in _payload_sample_indices)
                selected_by_stride = (_payload_sample_indices is None
                    and stream_index % _payload_sample_stride == 0
                    and _payload_samples is not None
                    and len(_payload_samples) < _payload_sample_limit)
                if (_payload_samples is not None and (selected_for_audit or selected_by_stride)):
                    sample_prefix = payload[:_payload_sample_prefix_bytes]
                    _payload_samples.append({"stream_index": stream_index,
                        "offset": offset - 1, "decompressed_bytes": len(payload),
                        "compressed_bytes": consumed,
                        "decompressed_sha256": decompressed_hash,
                        "sample_prefix_bytes": len(sample_prefix),
                        "sample_prefix_sha256": hashlib.sha256(sample_prefix).hexdigest(),
                        "payload_prefix": sample_prefix})
                streams.append({"offset": offset - 1, "compressed_bytes": consumed,
                    "decompressed_bytes": len(payload),
                    "decompressed_sha256": decompressed_hash,
                    "zlib_checksum_verified": True})
                offset = offset - 1 + consumed

    after = source.stat()
    if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or _sha256_file(source) != source_hash):
        raise RuntimeError("standalone zlib scan detected a changed read-only source")
    inventory_digest = hashlib.sha256()
    for item in streams:
        inventory_digest.update(struct.pack("<QQQ", item["offset"], item["compressed_bytes"],
                                            item["decompressed_bytes"]))
        inventory_digest.update(bytes.fromhex(item["decompressed_sha256"]))
    if _all_streams is not None:
        _all_streams.extend(streams)
    return {"file_name": source.name, "source_bytes": before.st_size,
        "source_sha256": source_hash, "recognized_zip01_container": recognized_container,
        "header_candidates": header_candidates, "attempted_candidates": attempted_candidates,
        "candidate_limit_reached": candidate_limit_reached,
        "streams": streams[:64], "stream_count": len(streams),
        "stream_inventory_sha256": inventory_digest.hexdigest(),
        "rejected_output_limit_count": rejected_output_limit,
        "source_stat_unchanged": True, "raw_payload_bytes_retained": False,
        "claim_scope": "bounded self-contained zlib streams with valid checksums only; enclosing record semantics UNKNOWN"}


def profile_standalone_zlib_coordinate_candidates(
        path: str | Path, *, expected_sha256: str, expected_stream_count: int,
        expected_stream_inventory_sha256: str, region: str,
        profile_parameters: dict[str, Any] | None = None,
        max_file_bytes: int = MAX_STANDALONE_ZLIB_FILE_BYTES,
        max_compressed_bytes: int = MAX_STANDALONE_ZLIB_COMPRESSED_BYTES,
        max_output_bytes: int = MAX_STANDALONE_ZLIB_OUTPUT_BYTES,
        max_header_candidates: int = MAX_STANDALONE_ZLIB_HEADER_CANDIDATES) -> dict[str, Any]:
    """Measure bounded coordinate-pair and short-run candidates in valid zlib payloads.

    A fixed, evenly spaced sample retains only short prefixes transiently. The
    result contains aggregate counts and hashes; payload bytes and coordinate
    examples are never persisted. Region-box hits are compared with a fixed,
    similarly sized displaced control box. All observations remain structural
    candidates and do not establish road or navigation semantics.
    """
    if region not in REGION_BOUNDS or region not in REGION_CONTROL_BOUNDS:
        raise ValueError(f"unregistered region for zlib coordinate profile: {region}")
    parameters = dict(profile_parameters or ZLIB_COORDINATE_PROFILE_PARAMETERS)
    selected_payload_tier = is_zlib_coordinate_selected_payload_parameters(parameters)
    if parameters not in ZLIB_COORDINATE_PROFILE_PARAMETER_OPTIONS and not selected_payload_tier:
        raise ValueError("zlib coordinate profile parameters differ from the fixed sampling allowlist")
    if not 1 <= expected_stream_count <= max_header_candidates:
        raise ValueError("expected zlib stream count is outside the bounded scanner range")
    if (len(expected_stream_inventory_sha256) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in expected_stream_inventory_sha256)):
        raise ValueError("expected zlib stream inventory digest must be a SHA-256 hex value")

    source = Path(path).resolve(strict=True)
    all_streams: list[dict[str, Any]] = []
    payload_samples: list[dict[str, Any]] = []
    selected_streams = (parameters["selected_streams_by_region"][region]
                        if selected_payload_tier else None)
    selected_indices = ({int(row["stream_index"]) for row in selected_streams}
                        if selected_streams is not None else None)
    sample_prefix_bytes = (int(parameters["sample_prefix_bytes"])
                           if selected_payload_tier else int(parameters["sample_prefix_bytes"]))
    census = scan_standalone_zlib_streams(source, expected_sha256=expected_sha256,
        max_file_bytes=max_file_bytes, max_compressed_bytes=max_compressed_bytes,
        max_output_bytes=max_output_bytes, max_header_candidates=max_header_candidates,
        _payload_sample_stride=(1 if selected_payload_tier else int(parameters["sample_stride"])),
        _payload_sample_limit=(max(1, len(selected_streams)) if selected_payload_tier
                               else int(parameters["sample_limit"])),
        _payload_sample_prefix_bytes=sample_prefix_bytes,
        _payload_sample_indices=selected_indices,
        _all_streams=all_streams, _payload_samples=payload_samples)
    if (census["stream_count"] != expected_stream_count
            or census["stream_inventory_sha256"] != expected_stream_inventory_sha256
            or len(all_streams) != expected_stream_count):
        raise RuntimeError("fresh zlib stream inventory differs from the independently verified census")
    if selected_payload_tier:
        selected_by_index = {int(row["stream_index"]): row for row in selected_streams}
        samples_by_index = {int(row["stream_index"]): row for row in payload_samples}
        if set(samples_by_index) != set(selected_by_index):
            raise RuntimeError("selected full-payload audit could not reproduce every evidence-bound stream")
        for index, expected in selected_by_index.items():
            sample = samples_by_index[index]
            full_stream = all_streams[index]
            if any(int(sample[field]) != int(expected[source_field]) for field, source_field in (
                    ("offset", "source_offset"), ("compressed_bytes", "compressed_bytes"),
                    ("decompressed_bytes", "decompressed_bytes"))) or (
                    str(sample["decompressed_sha256"]) != str(expected["decompressed_sha256"])
                    or hashlib.sha256(sample["payload_prefix"][:ZLIB_COORDINATE_SAMPLE_PREFIX_BYTES]).hexdigest()
                        != str(expected["sample_prefix_sha256"])
                    or full_stream["decompressed_sha256"] != expected["decompressed_sha256"]):
                raise RuntimeError("selected stream metadata or deep-prefix hash differs from verified evidence")

    min_lat, min_lon, max_lat, max_lon = REGION_BOUNDS[region]
    cmin_lat, cmin_lon, cmax_lat, cmax_lon = REGION_CONTROL_BOUNDS[region]
    measurements: dict[str, dict[str, Any]] = {}
    keys: list[tuple[int, int, str, str]] = []
    coordinate_scales = tuple(int(scale) for scale in parameters["coordinate_scales"])
    max_jump_km = float(parameters["max_jump_km"])
    for alignment in range(8):
        for scale in coordinate_scales:
            for order in ("lat_lon", "lon_lat"):
                key = f"alignment_{alignment}/scale_{scale}_{order}"
                keys.append((alignment, scale, order, key))
                measurements[key] = {"region_candidate_pairs": 0,
                    "control_candidate_pairs": 0, "adjacent_pairs_within_5km": 0,
                    "streams_with_region_candidates": 0,
                    "streams_with_adjacent_pairs_within_5km": 0,
                    "maximum_continuous_candidate_points": 0}

    sample_trace = hashlib.sha256()
    candidate_stream_summaries: list[dict[str, Any]] = []
    sampled_payload_bytes = 0
    include_stream_summaries = (parameters.get("include_hit_stream_summaries") is True
                                or selected_payload_tier)
    for sample in payload_samples:
        payload = sample["payload_prefix"]
        sampled_payload_bytes += len(payload)
        sample_trace.update(struct.pack("<QQQ", int(sample["stream_index"]),
            int(sample["offset"]), int(sample["decompressed_bytes"])))
        sample_trace.update(bytes.fromhex(str(sample["sample_prefix_sha256"])))
        sample_region_hits: set[str] = set()
        sample_continuity_hits: set[str] = set()
        per_stream_candidate_counts: dict[str, int] = {}
        per_stream_adjacent_counts: dict[str, int] = {}
        for alignment, scale, order, key in keys:
            previous: tuple[int, float, float, int] | None = None
            current_run = 0
            candidate_pairs = 0
            adjacent_pairs = 0
            for pair_index, offset in enumerate(range(alignment, len(payload) - 7, 8)):
                first, second = struct.unpack_from("<ii", payload, offset)
                if order == "lat_lon":
                    latitude, longitude = first / scale, second / scale
                else:
                    longitude, latitude = first / scale, second / scale
                if min_lat <= latitude <= max_lat and min_lon <= longitude <= max_lon:
                    metric = measurements[key]
                    metric["region_candidate_pairs"] += 1
                    candidate_pairs += 1
                    sample_region_hits.add(key)
                    if previous is not None and previous[0] == pair_index - 1:
                        _, prior_lat, prior_lon, _ = previous
                        mean_lat = math.radians((latitude + prior_lat) / 2.0)
                        dx = (longitude - prior_lon) * math.cos(mean_lat) * 111.32
                        dy = (latitude - prior_lat) * 111.32
                        distance_km = math.hypot(dx, dy)
                        if 0.0 < distance_km <= max_jump_km:
                            metric["adjacent_pairs_within_5km"] += 1
                            adjacent_pairs += 1
                            sample_continuity_hits.add(key)
                            current_run = current_run + 1 if current_run else 2
                            metric["maximum_continuous_candidate_points"] = max(
                                metric["maximum_continuous_candidate_points"], current_run)
                        else:
                            current_run = 1
                    else:
                        current_run = 1
                    previous = (pair_index, latitude, longitude, offset)
                else:
                    current_run = 0
                    previous = None
                if cmin_lat <= latitude <= cmax_lat and cmin_lon <= longitude <= cmax_lon:
                    measurements[key]["control_candidate_pairs"] += 1
            if candidate_pairs:
                per_stream_candidate_counts[key] = candidate_pairs
            if adjacent_pairs:
                per_stream_adjacent_counts[key] = adjacent_pairs
        for key in sample_region_hits:
            measurements[key]["streams_with_region_candidates"] += 1
        for key in sample_continuity_hits:
            measurements[key]["streams_with_adjacent_pairs_within_5km"] += 1
        if include_stream_summaries and per_stream_adjacent_counts:
            top_keys = sorted(per_stream_adjacent_counts,
                key=lambda key: (-per_stream_adjacent_counts[key],
                    -per_stream_candidate_counts.get(key, 0), key))[:8]
            summary = {
                "stream_index": int(sample["stream_index"]),
                "source_offset": int(sample["offset"]),
                "compressed_bytes": int(sample["compressed_bytes"]),
                "decompressed_bytes": int(sample["decompressed_bytes"]),
                "decompressed_sha256": str(sample["decompressed_sha256"]),
                "sample_prefix_sha256": str(sample["sample_prefix_sha256"]),
                "candidate_measurements": [{
                    "measurement": key,
                    "region_candidate_pairs": per_stream_candidate_counts.get(key, 0),
                    "adjacent_pairs_within_5km": per_stream_adjacent_counts[key],
                } for key in top_keys],
            }
            if selected_payload_tier:
                summary["prior_deep_prefix_sha256"] = str(
                    selected_by_index[int(sample["stream_index"])]["sample_prefix_sha256"])
            candidate_stream_summaries.append(summary)

    after = source.stat()
    if (after.st_size != census["source_bytes"] or not census["source_stat_unchanged"]):
        raise RuntimeError("zlib coordinate profile detected a changed read-only source")
    # The census checks the source stat and SHA-256 both before and after decode.
    for sample in payload_samples:
        sample.pop("payload_prefix", None)
    result = {"region": region, "file_name": source.name,
        "source_bytes": census["source_bytes"], "source_sha256": census["source_sha256"],
        "stream_count": census["stream_count"],
        "stream_inventory_sha256": census["stream_inventory_sha256"],
        "sample_stride": 1 if selected_payload_tier else int(parameters["sample_stride"]),
        "sampled_stream_count": len(payload_samples),
        "sampled_payload_bytes": sampled_payload_bytes,
        "sampled_payload_trace_sha256": sample_trace.hexdigest(),
        "profile_parameters": parameters,
        "measurements": measurements, "source_stat_unchanged": True,
        "raw_sample_bytes_retained": False, "raw_payload_bytes_retained": False,
        "claim_scope": "bounded signed-int32 geographic-window and short-step candidates inside valid zlib payload prefixes; road and record semantics UNKNOWN"}
    if include_stream_summaries:
        result["candidate_stream_summaries"] = candidate_stream_summaries
        result["candidate_stream_index_sha256"] = hashlib.sha256(json.dumps(
            candidate_stream_summaries, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        result["claim_scope"] = ("bounded candidate stream indices and hashes with repeated short-step geographic pairs; "
            "no coordinate examples, road or record semantics inferred")
    if selected_payload_tier:
        result["selected_full_payload_audit"] = {
            "selected_stream_count": len(selected_streams),
            "selected_streams": [{
                "stream_index": int(sample["stream_index"]),
                "source_offset": int(sample["offset"]),
                "compressed_bytes": int(sample["compressed_bytes"]),
                "decompressed_bytes": int(sample["decompressed_bytes"]),
                "deep_prefix_sha256": str(selected_by_index[int(sample["stream_index"])]["sample_prefix_sha256"]),
                "full_payload_sha256": str(sample["decompressed_sha256"]),
            } for sample in payload_samples],
            "sampled_payload_bytes": sampled_payload_bytes,
            "source_payload_limit_bytes": 2 * MAX_STANDALONE_ZLIB_OUTPUT_BYTES,
            "raw_payload_bytes_retained": False,
        }
        result["claim_scope"] = (
            "full bounded zlib payloads for evidence-selected streams were rescanned for geographic-pair and short-step candidates; "
            "road, record and navigation semantics remain UNKNOWN")
    return result


def profile_standalone_zlib_boundary_contexts(
        path: str | Path, *, expected_sha256: str, expected_stream_count: int,
        expected_stream_inventory_sha256: str, context_bytes: int = 16,
        max_file_bytes: int = MAX_STANDALONE_ZLIB_FILE_BYTES,
        max_compressed_bytes: int = MAX_STANDALONE_ZLIB_COMPRESSED_BYTES,
        max_output_bytes: int = MAX_STANDALONE_ZLIB_OUTPUT_BYTES,
        max_header_candidates: int = MAX_STANDALONE_ZLIB_HEADER_CANDIDATES) -> dict[str, Any]:
    """Profile bounded hashes around verified stream boundaries, without saving context bytes."""
    if not 1 <= context_bytes <= 64:
        raise ValueError("zlib boundary context must be between 1 and 64 bytes")
    if expected_stream_count < 1 or expected_stream_count > max_header_candidates:
        raise ValueError("expected zlib stream count is outside the bounded scanner range")
    if (len(expected_stream_inventory_sha256) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in expected_stream_inventory_sha256)):
        raise ValueError("expected zlib stream inventory digest must be a SHA-256 hex value")

    source = Path(path).resolve(strict=True)
    all_streams: list[dict[str, Any]] = []
    census = scan_standalone_zlib_streams(source, expected_sha256=expected_sha256,
        max_file_bytes=max_file_bytes, max_compressed_bytes=max_compressed_bytes,
        max_output_bytes=max_output_bytes, max_header_candidates=max_header_candidates,
        _all_streams=all_streams)
    if (census["stream_count"] != expected_stream_count
            or census["stream_inventory_sha256"] != expected_stream_inventory_sha256):
        raise RuntimeError("fresh zlib stream inventory differs from the independently verified census")

    before = source.stat()
    prefix_counts: Counter[str] = Counter()
    suffix_counts: Counter[str] = Counter()
    prefix_offsets: dict[str, list[int]] = {}
    suffix_offsets: dict[str, list[int]] = {}
    prefix_trace = hashlib.sha256()
    suffix_trace = hashlib.sha256()
    offset_counts: dict[str, Counter[int]] = {str(modulus): Counter()
                                               for modulus in (16, 64, 256, 3072)}
    gap_buckets: Counter[str] = Counter()

    def add_context(counter: Counter[str], offsets: dict[str, list[int]],
                    trace: Any, raw: bytes, offset: int) -> None:
        context_hash = hashlib.sha256(struct.pack("<H", len(raw)) + raw).hexdigest()
        counter[context_hash] += 1
        samples = offsets.setdefault(context_hash, [])
        if len(samples) < 8:
            samples.append(offset)
        trace.update(struct.pack("<QH", offset, len(raw)))
        trace.update(bytes.fromhex(context_hash))

    def gap_bucket(value: int) -> str:
        if value == 0:
            return "0"
        if value <= 15:
            return "1-15"
        if value <= 63:
            return "16-63"
        if value <= 255:
            return "64-255"
        if value <= 1023:
            return "256-1023"
        return "1024+"

    with source.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        for item in all_streams:
            start = int(item["offset"])
            end = start + int(item["compressed_bytes"])
            prefix = data[max(0, start - context_bytes):start]
            suffix = data[end:min(len(data), end + context_bytes)]
            add_context(prefix_counts, prefix_offsets, prefix_trace, prefix, start)
            add_context(suffix_counts, suffix_offsets, suffix_trace, suffix, end)
            for modulus, counts in offset_counts.items():
                counts[start % int(modulus)] += 1
        for left, right in zip(all_streams, all_streams[1:]):
            gap = int(right["offset"]) - (int(left["offset"]) + int(left["compressed_bytes"]))
            if gap < 0:
                raise RuntimeError("verified zlib stream boundaries overlap")
            gap_buckets[gap_bucket(gap)] += 1

    after = source.stat()
    if ((before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or _sha256_file(source) != expected_sha256.lower()):
        raise RuntimeError("zlib boundary context scan detected a changed read-only source")

    def top_contexts(counts: Counter[str], offsets: dict[str, list[int]]) -> list[dict[str, Any]]:
        return [{"context_sha256": key, "count": count, "first_offsets": offsets[key]}
                for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:32]]

    return {"file_name": source.name, "source_bytes": before.st_size,
        "source_sha256": expected_sha256.lower(), "context_bytes": context_bytes,
        "stream_count": census["stream_count"],
        "stream_inventory_sha256": census["stream_inventory_sha256"],
        "prefix_context_unique_count": len(prefix_counts),
        "prefix_context_trace_sha256": prefix_trace.hexdigest(),
        "prefix_context_top": top_contexts(prefix_counts, prefix_offsets),
        "suffix_context_unique_count": len(suffix_counts),
        "suffix_context_trace_sha256": suffix_trace.hexdigest(),
        "suffix_context_top": top_contexts(suffix_counts, suffix_offsets),
        "stream_start_modulo_top": {modulus: [{"remainder": value, "count": count}
            for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:16]]
            for modulus, counts in offset_counts.items()},
        "inter_stream_gap_buckets": {key: gap_buckets.get(key, 0)
            for key in ("0", "1-15", "16-63", "64-255", "256-1023", "1024+")},
        "source_stat_unchanged": True, "raw_context_bytes_retained": False,
        "raw_payload_bytes_retained": False,
        "claim_scope": "hash-only byte context around bounded checksum-verified zlib boundaries; enclosing record semantics UNKNOWN"}
