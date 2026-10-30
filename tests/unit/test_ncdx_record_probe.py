from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
from typing import Any

from src.readers.ncdx_record_probe import (audit_string_coordinate_proximity,
    audit_repeated_text_coordinate_proximity, audit_text_coordinate_association,
    probe_file, profile_printable_run_layout,
    profile_repeated_text_candidates, profile_text_block_boundaries,
    ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS,
    profile_standalone_zlib_boundary_contexts,
    profile_standalone_zlib_coordinate_candidates, scan_standalone_zlib_streams)
from src.writers.ncdx_container_writer import encode_container


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class NcdxRecordProbeTests(unittest.TestCase):
    def test_reports_bounded_text_and_fixed_scale_coordinate_candidates(self) -> None:
        logical = bytearray(12_288)
        logical[32:50] = b"AUTOBUSOVE NADRAZI"
        struct.pack_into("<ii", logical, 128, 45 * 10_000_000, 10 * 10_000_000)
        encoded = encode_container(bytes(logical), opaque_header_u32_le=324)
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PTI"
            source.write_bytes(encoded)
            source_hash = hashlib.sha256(encoded).hexdigest()
            result = probe_file(source, region="Italy", expected_sha256=source_hash)
            self.assertEqual(result["logical_bytes"], len(logical))
            self.assertEqual(result["source_sha256"], source_hash)
            self.assertTrue(any(row["text"] == "AUTOBUSOVE NADRAZI"
                                for row in result["bounded_ascii_samples"]))
            key = "scale_10000000_lat_lon"
            self.assertEqual(result["coordinate_candidate_counts_by_scale_and_order"][key], 1)
            self.assertEqual(result["coordinate_candidate_samples"][key][0]["logical_offset"], 128)
            self.assertFalse(result["raw_payload_bytes_retained"])
            self.assertTrue(result["source_stat_unchanged"])

    def test_rejects_wrong_inventory_hash_and_unknown_region(self) -> None:
        encoded = encode_container(b"a short fixture with labels")
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PDX"
            source.write_bytes(encoded)
            with self.assertRaises(ValueError):
                probe_file(source, region="Italy", expected_sha256="0" * 64)
            with self.assertRaises(ValueError):
                probe_file(source, region="Unknown", expected_sha256=hashlib.sha256(encoded).hexdigest())

    def test_text_samples_are_distributed_across_decoded_file(self) -> None:
        logical = bytearray(32_768)
        for offset, text in ((64, b"HEADER_TOKEN"), (8192, b"MIDDLE_TOKEN"),
                             (16_384, b"LATE_TOKEN"), (30_000, b"TAIL_TOKEN")):
            logical[offset:offset + len(text)] = text
        encoded = encode_container(bytes(logical))
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PDX"
            source.write_bytes(encoded)
            result = probe_file(source, region="Italy", expected_sha256=hashlib.sha256(encoded).hexdigest())
            samples = result["bounded_ascii_samples"]
            self.assertEqual(result["sample_distribution_bins"], 16)
            self.assertTrue({"HEADER_TOKEN", "MIDDLE_TOKEN", "LATE_TOKEN", "TAIL_TOKEN"}
                            <= {row["text"] for row in samples})
            self.assertGreaterEqual(len({row["distribution_bin"] for row in samples}), 4)

    def test_string_reservoir_is_deterministic_and_bounded_per_bin(self) -> None:
        logical = bytearray(32_768)
        for index in range(64):
            offset = 1024 + index * 12
            token = f"TOKEN{index:03d}".encode("ascii")
            logical[offset:offset + len(token)] = token
        encoded = encode_container(bytes(logical))
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PDX"
            source.write_bytes(encoded)
            digest = hashlib.sha256(encoded).hexdigest()
            first = probe_file(source, region="Italy", expected_sha256=digest)["bounded_ascii_samples"]
            second = probe_file(source, region="Italy", expected_sha256=digest)["bounded_ascii_samples"]
            bin_zero = [row for row in first if row["distribution_bin"] == 0]
            self.assertEqual(len(bin_zero), 32)
            self.assertEqual(first, second)
            self.assertEqual(len({row["text"] for row in bin_zero}), 32)

    def test_proximity_audit_distinguishes_anchor_windows_from_fixed_controls(self) -> None:
        logical = bytearray(1_048_576)
        anchor = b"POI ANCHOR"
        anchor_offset = 132_072
        candidate_offset = anchor_offset - 96
        logical[anchor_offset:anchor_offset + len(anchor)] = anchor
        struct.pack_into("<ii", logical, candidate_offset, 45 * 10_000_000, 10 * 10_000_000)
        encoded = encode_container(bytes(logical))
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PDX"
            source.write_bytes(encoded)
            result = audit_string_coordinate_proximity(source, region="Italy",
                expected_sha256=hashlib.sha256(encoded).hexdigest(),
                text_samples=[{"logical_offset": anchor_offset, "text": anchor.decode("ascii")}])
            key = "scale_10000000_lat_lon"
            self.assertEqual(result["label_windows"]["candidate_hit_windows_by_scale_and_order"][key], 1)
            self.assertEqual(result["fixed_control_windows"]["candidate_hit_windows_by_scale_and_order"][key], 0)
            self.assertEqual(result["label_windows"]["bounded_examples_by_scale_and_order"][key][0]["candidate_offset"], candidate_offset)
            self.assertFalse(result["raw_payload_bytes_retained"])
            self.assertTrue(result["source_stat_unchanged"])

    def test_proximity_audit_rejects_a_stale_or_missing_anchor(self) -> None:
        logical = bytearray(4096)
        logical[2048:2057] = b"POI LABEL"
        encoded = encode_container(bytes(logical))
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PDX"
            source.write_bytes(encoded)
            digest = hashlib.sha256(encoded).hexdigest()
            with self.assertRaises(ValueError):
                audit_string_coordinate_proximity(source, region="Italy", expected_sha256=digest,
                    text_samples=[{"logical_offset": 2048, "text": "NOT THE LABEL"}])
            with self.assertRaises(ValueError):
                audit_string_coordinate_proximity(source, region="Italy", expected_sha256=digest,
                    text_samples=[{"logical_offset": 64, "text": "HEADER"}])

    def test_text_coordinate_association_uses_stratified_anchors_and_matched_controls(self) -> None:
        logical = bytearray(32_768)
        for anchor_offset, label in ((1400, b"CITY CENTER"), (12_000, b"ROAD TERMINAL")):
            logical[anchor_offset:anchor_offset + len(label)] = label
            struct.pack_into("<ii", logical, anchor_offset - 32,
                int(45.12345 * 100_000), int(9.12345 * 100_000))
        encoded = encode_container(bytes(logical))
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PDX"
            source.write_bytes(encoded)
            result = audit_text_coordinate_association(source, region="Italy",
                expected_sha256=hashlib.sha256(encoded).hexdigest(), max_anchors=16,
                radius_bytes=48)
            key = "scale_100000_lat_lon"
            self.assertEqual(result["printable_run_count"], 2)
            self.assertEqual(result["sampled_anchor_count"], 2)
            self.assertEqual(result["matched_control_count"], 2)
            self.assertEqual(result["association_by_scale_and_order"][key]["anchor_hit_rate"], 1.0)
            self.assertEqual(result["association_by_scale_and_order"][key]["control_hit_rate"], 0.0)
            self.assertEqual(result["association_by_scale_and_order"][key]["rate_difference"], 1.0)
            self.assertFalse(result["raw_payload_bytes_retained"])
            self.assertTrue(result["source_stat_unchanged"])

    def test_repeated_literal_association_requires_exact_repeated_runs(self) -> None:
        logical = bytearray(16_384)
        for anchor_offset in (1024, 5120, 9216):
            logical[anchor_offset:anchor_offset + 8] = b"DOWNTOWN"
            struct.pack_into("<ii", logical, anchor_offset - 24,
                int(45.12345 * 100_000), int(9.12345 * 100_000))
        logical[2048:2055] = b"UNIQUE1"
        encoded = encode_container(bytes(logical))
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PDX"
            source.write_bytes(encoded)
            result = audit_text_coordinate_association(source, region="Italy",
                expected_sha256=hashlib.sha256(encoded).hexdigest(),
                anchor_strategy="repeated_literals", max_anchors=16, radius_bytes=40)
            self.assertEqual(result["printable_run_count"], 4)
            self.assertEqual(result["eligible_anchor_count"], 3)
            self.assertEqual(result["sampled_anchor_count"], 3)
            self.assertEqual(result["anchor_strategy"], "repeated_literals")

    def test_text_coordinate_association_rejects_unbounded_or_stale_requests(self) -> None:
        encoded = encode_container(b"A REAL PLACE NAME followed by a bounded fixture payload")
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PDX"
            source.write_bytes(encoded)
            digest = hashlib.sha256(encoded).hexdigest()
            with self.assertRaises(ValueError):
                audit_text_coordinate_association(source, region="Italy", expected_sha256="0" * 64)
            with self.assertRaises(ValueError):
                audit_text_coordinate_association(source, region="Italy", expected_sha256=digest,
                    max_anchors=8193)
            with self.assertRaises(ValueError):
                audit_text_coordinate_association(source, region="Italy", expected_sha256=digest,
                    anchor_strategy="model_invented_method")

    def test_standalone_zlib_scan_finds_only_checksum_valid_bounded_streams(self) -> None:
        payload = (b"NCDX map payload with repeated record-like structure. " * 80)
        encoded_stream = zlib.compress(payload)
        raw = b"header-prefix".ljust(64, b"_") + encoded_stream + b"opaque-tail"
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.RL"
            source.write_bytes(raw)
            result = scan_standalone_zlib_streams(source,
                expected_sha256=hashlib.sha256(raw).hexdigest())
            self.assertEqual(result["stream_count"], 1)
            self.assertEqual(result["streams"][0]["offset"], 64)
            self.assertEqual(result["streams"][0]["compressed_bytes"], len(encoded_stream))
            self.assertEqual(result["streams"][0]["decompressed_bytes"], len(payload))
            self.assertEqual(result["streams"][0]["decompressed_sha256"], hashlib.sha256(payload).hexdigest())
            self.assertTrue(result["streams"][0]["zlib_checksum_verified"])
            self.assertEqual(result["stream_count"], 1)
            self.assertEqual(len(result["stream_inventory_sha256"]), 64)
            self.assertFalse(result["raw_payload_bytes_retained"])
            bounded = scan_standalone_zlib_streams(source,
                expected_sha256=hashlib.sha256(raw).hexdigest(), max_output_bytes=1024)
            self.assertEqual(bounded["stream_count"], 0)
            self.assertGreaterEqual(bounded["rejected_output_limit_count"], 1)

    def test_standalone_zlib_scan_bounds_serialized_preview_but_exposes_full_inventory_internally(self) -> None:
        payloads = [f"NCDX payload {index:03d} with bounded record evidence".encode("ascii")
                    for index in range(80)]
        raw = b"prefix" + b"".join(zlib.compress(payload) for payload in payloads)
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.ASC"
            source.write_bytes(raw)
            full_inventory: list[dict[str, Any]] = []
            result = scan_standalone_zlib_streams(source,
                expected_sha256=hashlib.sha256(raw).hexdigest(), _all_streams=full_inventory)
            self.assertEqual(result["stream_count"], len(payloads))
            self.assertEqual(len(result["streams"]), 64)
            self.assertEqual(len(full_inventory), len(payloads))
            self.assertNotIn("_all_streams", result)
            self.assertEqual(len(result["stream_inventory_sha256"]), 64)

    def test_zlib_boundary_context_profile_is_hash_only_and_bound_to_prior_inventory(self) -> None:
        payloads = [f"NCDX payload {index:03d} with boundary evidence".encode("ascii")
                    for index in range(12)]
        raw = b"prefix" + b"".join(zlib.compress(payload) for payload in payloads) + b"tail"
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.MG1"
            source.write_bytes(raw)
            census = scan_standalone_zlib_streams(source,
                expected_sha256=hashlib.sha256(raw).hexdigest())
            profile = profile_standalone_zlib_boundary_contexts(source,
                expected_sha256=hashlib.sha256(raw).hexdigest(),
                expected_stream_count=census["stream_count"],
                expected_stream_inventory_sha256=census["stream_inventory_sha256"])
            self.assertEqual(profile["stream_count"], len(payloads))
            self.assertEqual(profile["stream_inventory_sha256"], census["stream_inventory_sha256"])
            self.assertEqual(sum(profile["inter_stream_gap_buckets"].values()), len(payloads) - 1)
            self.assertEqual(sum(row["count"] for row in profile["stream_start_modulo_top"]["16"]), len(payloads))
            self.assertEqual(len(profile["prefix_context_trace_sha256"]), 64)
            self.assertFalse(profile["raw_context_bytes_retained"])
            self.assertFalse(profile["raw_payload_bytes_retained"])
            with self.assertRaises(RuntimeError):
                profile_standalone_zlib_boundary_contexts(source,
                    expected_sha256=hashlib.sha256(raw).hexdigest(),
                    expected_stream_count=census["stream_count"] + 1,
                    expected_stream_inventory_sha256=census["stream_inventory_sha256"])

    def test_zlib_coordinate_profile_finds_regional_runs_without_retaining_payloads(self) -> None:
        decoded = bytearray(128)
        for index in range(12):
            struct.pack_into("<ii", decoded, index * 8,
                (45_460_000 + index * 900) * 1,
                (9_190_000 + index * 900) * 1)
        raw = b"".join(zlib.compress(bytes(decoded)) for _ in range(12)) + bytes(4096)
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.MG1"
            source.write_bytes(raw)
            digest = hashlib.sha256(raw).hexdigest()
            census = scan_standalone_zlib_streams(source, expected_sha256=digest)
            profile = profile_standalone_zlib_coordinate_candidates(source,
                expected_sha256=digest, expected_stream_count=census["stream_count"],
                expected_stream_inventory_sha256=census["stream_inventory_sha256"],
                region="Italy")
            metric = profile["measurements"]["alignment_0/scale_1000000_lat_lon"]
            self.assertEqual(profile["stream_count"], 12)
            self.assertEqual(profile["sampled_stream_count"], 2)
            self.assertGreater(metric["region_candidate_pairs"], 0)
            self.assertEqual(metric["control_candidate_pairs"], 0)
            self.assertGreater(metric["adjacent_pairs_within_5km"], 0)
            self.assertFalse(profile["raw_sample_bytes_retained"])
            self.assertFalse(profile["raw_payload_bytes_retained"])
            self.assertNotIn("payload_prefix", profile)
            expanded = profile_standalone_zlib_coordinate_candidates(source,
                expected_sha256=digest, expected_stream_count=census["stream_count"],
                expected_stream_inventory_sha256=census["stream_inventory_sha256"],
                region="Italy", profile_parameters=ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS)
            self.assertEqual(expanded["stream_count"], 12)
            self.assertEqual(expanded["sampled_stream_count"], 3)
            self.assertEqual(expanded["sample_stride"], 4)
            self.assertEqual(expanded["profile_parameters"], ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS)
            self.assertFalse(expanded["raw_payload_bytes_retained"])
            with self.assertRaises(RuntimeError):
                profile_standalone_zlib_coordinate_candidates(source,
                    expected_sha256=digest, expected_stream_count=census["stream_count"],
                    expected_stream_inventory_sha256="0" * 64, region="Italy")

    def test_standalone_zlib_scan_skips_known_block_container_and_rejects_stale_source(self) -> None:
        container = encode_container(b"A recognized zip marker must not be rescanned as a new container")
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PDX"
            source.write_bytes(container)
            digest = hashlib.sha256(container).hexdigest()
            result = scan_standalone_zlib_streams(source, expected_sha256=digest)
            self.assertTrue(result["recognized_zip01_container"])
            self.assertEqual(result["stream_count"], 0)
            with self.assertRaises(ValueError):
                scan_standalone_zlib_streams(source, expected_sha256="0" * 64)

    def test_printable_run_layout_reports_bounded_hash_only_structure(self) -> None:
        logical = bytearray(8192)
        logical[100:104] = b"CITY"
        logical[110:116] = b"STREET"
        logical[300:309] = b"POI-LABEL"
        logical[3070:3080] = b"CROSSBLOCK"
        encoded = encode_container(bytes(logical))
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PDX"
            source.write_bytes(encoded)
            result = profile_printable_run_layout(source, region="Italy",
                expected_sha256=hashlib.sha256(encoded).hexdigest())
            self.assertEqual(result["printable_run_count"], 4)
            self.assertEqual(result["run_length_counts"]["4_7"], 2)
            self.assertEqual(result["run_length_counts"]["8_15"], 2)
            self.assertGreaterEqual(result["inter_run_gap_counts"]["4_7"], 1)
            self.assertTrue(all("sha256" in row and "text" not in row
                                for row in result["bounded_hash_samples_by_bin"]))
            self.assertFalse(result["raw_payload_bytes_retained"])
            self.assertTrue(result["source_stat_unchanged"])

    def test_repeated_text_profile_counts_included_literals_exactly(self) -> None:
        logical = bytearray(4096)
        values = (b"BANK", b"ROAD", b"BANK", b"CITY", b"BANK")
        for index, value in enumerate(values):
            offset = 128 + index * 32
            logical[offset:offset + len(value)] = value
        encoded = encode_container(bytes(logical))
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PDX"
            source.write_bytes(encoded)
            digest = hashlib.sha256(encoded).hexdigest()
            result = profile_repeated_text_candidates(source, region="Italy",
                expected_sha256=digest, sampling_modulus=1, top_n=8, max_candidates=16)
            bank = next(row for row in result["top_repeated_values"] if row["text"] == "BANK")
            self.assertEqual(bank["exact_sampled_count"], 3)
            self.assertEqual(len(bank["sampled_offsets"]), 3)
            inventory_bank = next(row for row in result["sampled_value_inventory"]
                                  if row["text"] == "BANK")
            self.assertEqual(inventory_bank["exact_sampled_count"], 3)
            self.assertEqual(inventory_bank["sha256"], hashlib.sha256(b"BANK").hexdigest())
            self.assertFalse(result["raw_payload_bytes_retained"])
            with self.assertRaises(ValueError):
                profile_repeated_text_candidates(source, region="Italy", expected_sha256=digest,
                    sampling_modulus=1, top_n=8, max_candidates=1)

    def test_repeated_text_proximity_resamples_real_value_occurrences(self) -> None:
        logical = bytearray(65_536)
        anchor_offsets = (2000, 9000, 20_000, 40_000)
        for offset in anchor_offsets:
            logical[offset:offset + 4] = b"BANK"
        struct.pack_into("<ii", logical, anchor_offsets[0] - 48,
                         45 * 10_000_000, 10 * 10_000_000)
        encoded = encode_container(bytes(logical))
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PDX"
            source.write_bytes(encoded)
            result = audit_repeated_text_coordinate_proximity(source, region="Italy",
                expected_sha256=hashlib.sha256(encoded).hexdigest(), anchor_texts=["BANK"])
            anchor_hash = hashlib.sha256(b"BANK").hexdigest()
            self.assertEqual(result["anchor_occurrence_counts_by_sha256"][anchor_hash], 4)
            self.assertEqual(result["selected_anchor_offsets_by_sha256"][anchor_hash], list(anchor_offsets))
            self.assertEqual(result["proximity"]["label_windows"]["window_count"], 4)
            self.assertGreaterEqual(result["proximity"]["label_windows"][
                "candidate_hit_windows_by_scale_and_order"]["scale_10000000_lat_lon"], 1)

    def test_block_boundary_profile_counts_crossing_runs_and_positions(self) -> None:
        logical = bytearray(6144)
        logical[100:104] = b"CITY"
        logical[3068:3078] = b"CROSSBLOCK"
        encoded = encode_container(bytes(logical))
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            source = Path(temporary) / "fixture.PDX"
            source.write_bytes(encoded)
            result = profile_text_block_boundaries(source, region="Italy",
                expected_sha256=hashlib.sha256(encoded).hexdigest())
            self.assertEqual(result["block_size_bytes"], 3072)
            self.assertEqual(result["printable_run_count"], 2)
            self.assertEqual(result["runs_crossing_block_boundary"], 1)
            self.assertEqual(result["run_start_distance_to_nearest_boundary"]["4_15"], 1)
            self.assertEqual(result["runs_per_block_summary"]["empty_blocks"], 1)
            self.assertAlmostEqual(result["random_phase_null"]["expected_crossing_rate"],
                (3 + 9) / (3072 * 2), places=8)
            self.assertFalse(result["raw_payload_bytes_retained"])


if __name__ == "__main__":
    unittest.main()
