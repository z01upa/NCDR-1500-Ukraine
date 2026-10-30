from __future__ import annotations

import json
import gzip
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest
import zlib
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import project_director, state_store
from src.agent.autonomous_gui import verified_progress
from src.writers.ncdx_container_writer import encode_container


class ProjectDirectorTests(unittest.TestCase):
    def test_secondary_city_crosscheck_selects_only_unused_full_payload_streams(self) -> None:
        observations = []
        for region, first, second, path in (
                ("SW", 969, 1183, "SW/DB/EUZ.MG1"),
                ("Scandinavia", 1176, 1752, "OPEL NCDx Scandinavia 2010-2011/DB/SCZ.MG1")):
            streams = []
            audited = []
            for index, adjacent in ((first, 10), (second, 6)):
                payload_hash = f"{index:064x}"
                streams.append({"stream_index": index, "source_offset": index * 100,
                    "compressed_bytes": 100 + index, "decompressed_bytes": 200 + index,
                    "decompressed_sha256": payload_hash,
                    "candidate_measurements": [
                        {"measurement": "alignment_0/scale_1000000_lat_lon",
                         "region_candidate_pairs": 30, "adjacent_pairs_within_5km": adjacent}]})
                audited.append({"stream_index": index, "full_payload_sha256": payload_hash})
            observations.append({"region": region, "relative_path": path,
                "source_sha256": f"{len(region):064x}", "stream_count": 2000,
                "stream_inventory_sha256": f"{(len(region) + 1):064x}",
                "candidate_stream_summaries": streams,
                "selected_full_payload_audit": {"selected_streams": audited}})
        report = {"observations": observations}
        selected = project_director._select_unconsumed_city_coordinate_candidates(
            report, prior_task_id="accepted-census", prior_artifact_path="evidence.json",
            prior_artifact_sha256="a" * 64,
            used_streams={("SW", "accepted-census", 969),
                          ("Scandinavia", "accepted-census", 1176)})
        self.assertEqual([(row["region"], row["stream_index"]) for row in selected],
                         [("SW", 1183), ("Scandinavia", 1752)])
        self.assertTrue(all(row["prior_adjacent_pairs"] >= 3 for row in selected))
        exhausted = project_director._select_unconsumed_city_coordinate_candidates(
            report, prior_task_id="accepted-census", prior_artifact_path="evidence.json",
            prior_artifact_sha256="a" * 64,
            used_streams={(region, "accepted-census", index)
                for region, first, second, _path in (
                    ("SW", 969, 1183, "SW/DB/EUZ.MG1"),
                    ("Scandinavia", 1176, 1752, "OPEL NCDx Scandinavia 2010-2011/DB/SCZ.MG1"))
                for index in (first, second)})
        self.assertEqual(exhausted, [])

    def test_roadlink_portability_goal_is_manifest_bound_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            region_rows = []
            regions = (("SW", Path("SW") / "DB", "EUZ"),
                       ("Italy", Path("OPEL NCDx Italia 2010-2011") / "DB", "IZ"),
                       ("Scandinavia", Path("OPEL NCDx Scandinavia 2010-2011") / "DB", "SCZ"))
            for region, folder, prefix in regions:
                for suffix in ("RL", "IOF", "IL"):
                    relative = folder / f"{prefix}.{suffix}"
                    source = root / relative
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_bytes(f"{region}:{suffix}".encode("ascii"))
                    region_rows.append({"region": region, "relative_path": relative.as_posix(),
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "size_bytes": source.stat().st_size})

            def rows_for(suffix: str) -> list[dict[str, object]]:
                return [row for row in region_rows
                        if Path(str(row["relative_path"])).suffix == f".{suffix}"]

            with mock.patch.object(project_director.coordinator_runtime, "SOURCE_ROOT", root), \
                 mock.patch.object(project_director, "_data_profile_sources", side_effect=rows_for), \
                 mock.patch.object(project_director, "_task_status", side_effect=[None, "PENDING"]), \
                 mock.patch.object(project_director.state_store, "add_task", return_value=True) as add_task, \
                 mock.patch.object(project_director.manager, "_event"):
                first = project_director.seed_next_roadlink_portability_task()
                second = project_director.seed_next_roadlink_portability_task()
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(add_task.call_count, 1)
        spec = add_task.call_args.args[0]
        self.assertEqual(spec["agent"], "ncdx-roadlink-portability")
        self.assertEqual(len(spec["budget"]["sources"]), 9)
        self.assertFalse(spec["budget"]["source_write"])

    def test_persistent_data_director_prioritizes_real_container_roundtrips(self) -> None:
        source_rows = [{"region": region, "relative_path": f"{region}/DB/X.PTI",
                        "sha256": f"{index:064x}", "size_bytes": 100 + index}
                       for index, region in enumerate(("SW", "Italy", "Scandinavia"), 1)]
        with mock.patch.object(project_director.coordinator_runtime,
                               "available_target_suffixes", return_value=("RD", "PTI")), \
             mock.patch.object(project_director, "_data_profile_sources", return_value=source_rows), \
             mock.patch.object(project_director, "_task_status", return_value=None):
            candidates = project_director._data_profile_candidates()
            self.assertEqual((candidates[0]["suffix"], candidates[0]["mode"]),
                             ("PTI", "CONTAINER_ROUNDTRIP"))
            self.assertIn(("PTI", "EXACT_BLOCK_ANCHOR_SCAN"),
                          [(row["suffix"], row["mode"]) for row in candidates])
            legacy = project_director._data_profile_candidates(include_legacy_modes=True)
            self.assertGreater(len(legacy), len(candidates))
        with mock.patch.object(project_director.coordinator_runtime,
                               "available_target_suffixes", return_value=("PTI", "PDX")), \
             mock.patch.object(project_director, "_data_profile_sources", return_value=source_rows), \
             mock.patch.object(project_director, "_task_status", return_value=None):
            prioritized = project_director._data_profile_candidates()
            self.assertEqual([(row["suffix"], row["mode"]) for row in prioritized],
                             [("PDX", "DECODED_STRUCTURE_SCAN"),
                              ("PTI", "CONTAINER_ROUNDTRIP"),
                              ("PDX", "CONTAINER_ROUNDTRIP"),
                              ("PDX", "PRINTABLE_RUN_LAYOUT_PROFILE"),
                              ("PDX", "REPEATED_TEXT_DICTIONARY_PROFILE"),
                              ("PDX", "BLOCK_BOUNDARY_PROFILE"),
                              ("PTI", "EXACT_BLOCK_ANCHOR_SCAN"),
                              ("PDX", "EXACT_BLOCK_ANCHOR_SCAN")])

    def test_proximity_audit_requires_independently_verified_pdx_scan(self) -> None:
        source_rows = [{"region": region, "relative_path": f"{region}/DB/X.PDX",
                        "sha256": f"{index:064x}", "size_bytes": 100 + index}
                       for index, region in enumerate(("SW", "Italy", "Scandinavia"), 1)]
        prerequisites = []

        def status(task_id: str) -> str | None:
            return "DONE" if task_id in prerequisites else None

        with mock.patch.object(project_director.coordinator_runtime,
                               "available_target_suffixes", return_value=("PDX",)), \
             mock.patch.object(project_director, "_data_profile_sources", return_value=source_rows), \
             mock.patch.object(project_director, "_task_status", side_effect=status):
            self.assertFalse(any(row["mode"] == "STRING_COORDINATE_PROXIMITY_AUDIT"
                                 for row in project_director._data_profile_candidates()))
            prior = project_director._data_profile_task_id("PDX", "DECODED_STRUCTURE_SCAN", source_rows)
            prerequisites.extend((prior, "AUTO_SUPERVISOR_" + prior))
            candidates = project_director._data_profile_candidates()
        audit = next(row for row in candidates if row["mode"] == "STRING_COORDINATE_PROXIMITY_AUDIT")
        self.assertEqual(audit["suffix"], "PDX")
        self.assertEqual(audit["prior_task_id"], prior)

    def test_repeated_text_coordinate_audit_waits_for_profile_and_supervisor(self) -> None:
        source_rows = [{"region": region, "relative_path": f"{region}/DB/X.PDX",
                        "sha256": f"{index:064x}", "size_bytes": 100 + index}
                       for index, region in enumerate(("SW", "Italy", "Scandinavia"), 1)]
        prerequisites = []

        def status(task_id: str) -> str | None:
            return "DONE" if task_id in prerequisites else None

        with mock.patch.object(project_director.coordinator_runtime,
                               "available_target_suffixes", return_value=("PDX",)), \
             mock.patch.object(project_director, "_data_profile_sources", return_value=source_rows), \
             mock.patch.object(project_director, "_task_status", side_effect=status):
            self.assertFalse(any(row["mode"] == "REPEATED_TEXT_COORDINATE_AUDIT"
                                 for row in project_director._data_profile_candidates()))
            prior = project_director._data_profile_task_id("PDX", "REPEATED_TEXT_DICTIONARY_PROFILE", source_rows)
            prerequisites.extend((prior, "AUTO_SUPERVISOR_" + prior))
            candidates = project_director._data_profile_candidates()
        audit = next(row for row in candidates if row["mode"] == "REPEATED_TEXT_COORDINATE_AUDIT")
        self.assertEqual(audit["prior_task_id"], prior)
        expected_id = project_director._data_profile_task_id(
            "PDX", "REPEATED_TEXT_COORDINATE_AUDIT", source_rows, upstream_task_id=prior)
        self.assertEqual(audit["goal_id"], expected_id)
        self.assertNotEqual(expected_id, project_director._data_profile_task_id(
            "PDX", "REPEATED_TEXT_COORDINATE_AUDIT", source_rows))
        self.assertNotEqual(expected_id, project_director._data_profile_task_id(
            "PDX", "REPEATED_TEXT_COORDINATE_AUDIT", source_rows,
            upstream_task_id=prior + "_NEXT"))

    def test_adaptive_association_census_requires_prior_independent_results(self) -> None:
        source_rows = [{"region": region, "relative_path": f"{region}/DB/X.PDX",
                        "sha256": f"{index:064x}", "size_bytes": 100 + index}
                       for index, region in enumerate(("SW", "Italy", "Scandinavia"), 1)]
        dictionary = project_director._data_profile_task_id(
            "PDX", "REPEATED_TEXT_DICTIONARY_PROFILE", source_rows)
        repeated_audit = project_director._data_profile_task_id(
            "PDX", "REPEATED_TEXT_COORDINATE_AUDIT", source_rows, upstream_task_id=dictionary)
        string_audit = project_director._data_profile_task_id(
            "PDX", "STRING_COORDINATE_PROXIMITY_AUDIT", source_rows)
        prerequisites = [string_audit, "AUTO_SUPERVISOR_" + string_audit]

        def status(task_id: str) -> str | None:
            return "DONE" if task_id in prerequisites else None

        with mock.patch.object(project_director.coordinator_runtime,
                               "available_target_suffixes", return_value=("PDX",)), \
             mock.patch.object(project_director, "_data_profile_sources", return_value=source_rows), \
             mock.patch.object(project_director, "_task_status", side_effect=status):
            candidates = project_director._data_profile_candidates()
        first = next(row for row in candidates if row["mode"] == "TEXT_COORDINATE_ASSOCIATION_CENSUS")
        self.assertEqual(first["prior_task_id"], string_audit)
        self.assertFalse(any(row["mode"] == "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS"
                             for row in candidates))

        prerequisites.extend((dictionary, "AUTO_SUPERVISOR_" + dictionary,
                              repeated_audit, "AUTO_SUPERVISOR_" + repeated_audit))
        with mock.patch.object(project_director.coordinator_runtime,
                               "available_target_suffixes", return_value=("PDX",)), \
             mock.patch.object(project_director, "_data_profile_sources", return_value=source_rows), \
             mock.patch.object(project_director, "_task_status", side_effect=status):
            candidates = project_director._data_profile_candidates()
        repeated = next(row for row in candidates
                        if row["mode"] == "REPEATED_TEXT_COORDINATE_ASSOCIATION_CENSUS")
        self.assertEqual(repeated["prior_task_id"], repeated_audit)
        self.assertNotEqual(first["goal_id"], repeated["goal_id"])

    def test_text_coordinate_census_worker_and_supervisor_reproduce_real_files(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            rows = []
            for index, (region, prefix, latitude, longitude) in enumerate((
                    ("SW", "EUZ", 52.5, 13.4),
                    ("Italy", "IZ", 45.1, 9.1),
                    ("Scandinavia", "SCZ", 59.3, 18.1)), 1):
                logical = bytearray(8192)
                label = f"CITY LANDMARK {region}".encode("ascii")
                anchor = 1200 + index * 128
                logical[anchor:anchor + len(label)] = label
                struct.pack_into("<ii", logical, anchor - 24,
                    int(latitude * 100_000), int(longitude * 100_000))
                source = root / region / "DB" / f"{prefix}.PDX"
                source.parent.mkdir(parents=True)
                encoded = encode_container(bytes(logical))
                source.write_bytes(encoded)
                rows.append({"region": region, "relative_path": source.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(encoded).hexdigest(), "size_bytes": len(encoded)})
            prior_id = project_director._data_profile_task_id(
                "PDX", "STRING_COORDINATE_PROXIMITY_AUDIT", rows)
            task_id = project_director._data_profile_task_id(
                "PDX", "TEXT_COORDINATE_ASSOCIATION_CENSUS", rows)
            task = {"id": task_id, "budget": {"data_family_profile": True, "suffix": "PDX",
                "profile_mode": "TEXT_COORDINATE_ASSOCIATION_CENSUS", "sources": rows,
                "prior_task_id": prior_id, "profile_parameters": {
                    "anchor_strategy": "all_printable", "max_anchors": 4096,
                    "controls_per_anchor": 1, "radius_bytes": 64}}}
            prior_result = {"status": "PASS", "profile_mode": "STRING_COORDINATE_PROXIMITY_AUDIT"}
            artifact = lambda _task_id, path, _description, acceptance: {
                "path": str(path.relative_to(root)), "acceptance": acceptance}
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director.coordinator_runtime, "SOURCE_ROOT", root), \
                 mock.patch.object(project_director.coordinator_runtime,
                                   "available_target_suffixes", return_value=("PDX",)), \
                 mock.patch.object(project_director, "_data_profile_sources", return_value=rows), \
                 mock.patch.object(project_director, "_ledger_hash",
                     side_effect=lambda relative: next(row["sha256"] for row in rows
                         if row["relative_path"] == relative)), \
                 mock.patch.object(project_director, "_task_result", return_value=prior_result), \
                 mock.patch.object(project_director, "_task_status", return_value="DONE"), \
                 mock.patch.object(project_director.manager, "_artifact", side_effect=artifact), \
                 mock.patch.object(project_director, "_register_supervisor"):
                result = project_director.execute_data_family_profile(task)
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["profile_mode"], "TEXT_COORDINATE_ASSOCIATION_CENSUS")
                self.assertTrue(all(row["sampled_anchor_count"] == 1 for row in result["observations"]))
                fresh = project_director._verify_text_coordinate_association_target(
                    task_id, task, result)
            self.assertTrue(fresh["fresh_manifest_bound_census"])
            self.assertEqual(fresh["independent_region_count"], 3)
            self.assertEqual(fresh["original_media_write_count"], 0)

    def test_standalone_zlib_census_offers_only_bounded_raw_manifest_families(self) -> None:
        from src.readers.ncdx_record_probe import MAX_STANDALONE_ZLIB_FILE_BYTES
        regions = ("SW", "Italy", "Scandinavia")
        sizes = {"PDX": [12_000, 14_000, 16_000], "FEA": [8_000, 16_000, 24_000],
                 "RL": [8_000, 300, 8_000], "MP0": [12_000, 16_000, MAX_STANDALONE_ZLIB_FILE_BYTES + 1]}

        def sources(suffix: str):
            return [{"region": region, "relative_path": f"{region}/DB/{region}.{suffix}",
                     "sha256": f"{index:064x}", "size_bytes": sizes[suffix][index]}
                    for index, region in enumerate(regions)]

        with mock.patch.object(project_director.coordinator_runtime,
                               "available_target_suffixes", return_value=("PDX", "FEA", "RL", "MP0")), \
             mock.patch.object(project_director, "_data_profile_sources", side_effect=sources), \
             mock.patch.object(project_director, "_task_status", return_value=None):
            candidates = project_director._data_profile_candidates()
        raw = [row for row in candidates if row["mode"] == "STANDALONE_ZLIB_STREAM_CENSUS"]
        self.assertEqual([(row["suffix"], row["mode"]) for row in raw],
                         [("FEA", "STANDALONE_ZLIB_STREAM_CENSUS")])

    def test_adaptive_candidate_catalog_uses_verified_streams_for_new_coordinate_experiments(self) -> None:
        from src.readers.ncdx_record_probe import ZLIB_COORDINATE_PROFILE_PARAMETERS
        rows = [{"region": region, "relative_path": f"{region}/DB/{region}.MG2",
            "sha256": f"{index + 1:064x}", "size_bytes": 4096}
            for index, region in enumerate(("SW", "Italy", "Scandinavia"))]
        prior_id = project_director._data_profile_task_id(
            "MG2", "STANDALONE_ZLIB_STREAM_CENSUS", rows)
        prior = {"status": "PASS", "observations": [
            {"region": row["region"], "source_sha256": row["sha256"],
             "stream_count": 12, "stream_inventory_sha256": f"{index + 10:064x}"}
            for index, row in enumerate(rows)]}

        def task_status(task_id):
            return None if "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS" in task_id else "DONE"

        with mock.patch.object(project_director.coordinator_runtime,
                "available_target_suffixes", return_value=("MG2",)), \
             mock.patch.object(project_director, "_data_profile_sources", return_value=rows), \
             mock.patch.object(project_director, "_task_status", side_effect=task_status), \
             mock.patch.object(project_director, "_task_result", return_value=prior):
            candidates = project_director._data_profile_candidates()
        selected = [row for row in candidates
                    if row["mode"] == "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS"]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["prior_task_id"], prior_id)
        self.assertEqual(selected[0]["profile_parameters"], ZLIB_COORDINATE_PROFILE_PARAMETERS)
        self.assertIn("AUTO_NCDX_DATA_MG2_ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS_",
                      selected[0]["goal_id"])

    def test_expanded_coordinate_candidate_waits_for_base_task_and_independent_supervisor(self) -> None:
        from src.readers.ncdx_record_probe import (ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS,
            ZLIB_COORDINATE_PROFILE_PARAMETERS)
        rows = [{"region": region, "relative_path": f"{region}/DB/{region}.MG2",
            "sha256": f"{index + 1:064x}", "size_bytes": 4096}
            for index, region in enumerate(("SW", "Italy", "Scandinavia"))]
        prior_id = project_director._data_profile_task_id(
            "MG2", "STANDALONE_ZLIB_STREAM_CENSUS", rows)
        base_id = project_director._data_profile_task_id("MG2",
            "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", rows,
            upstream_task_id=prior_id,
            profile_parameters=ZLIB_COORDINATE_PROFILE_PARAMETERS)
        completed = {prior_id, "AUTO_SUPERVISOR_" + prior_id, base_id}
        prior = {"status": "PASS", "observations": [
            {"region": row["region"], "source_sha256": row["sha256"],
             "stream_count": 12, "stream_inventory_sha256": f"{index + 10:064x}"}
            for index, row in enumerate(rows)]}

        def task_status(task_id: str) -> str | None:
            return "DONE" if task_id in completed else None

        with mock.patch.object(project_director.coordinator_runtime,
                "available_target_suffixes", return_value=("MG2",)), \
             mock.patch.object(project_director, "_data_profile_sources", return_value=rows), \
             mock.patch.object(project_director, "_task_status", side_effect=task_status), \
             mock.patch.object(project_director, "_task_result", return_value=prior):
            before_verifier = project_director._data_profile_candidates()
            self.assertFalse(any(row.get("profile_parameters") ==
                ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS for row in before_verifier))
            completed.add("AUTO_SUPERVISOR_" + base_id)
            after_verifier = project_director._data_profile_candidates()

        expanded = [row for row in after_verifier
                    if row.get("profile_parameters") == ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS]
        self.assertEqual(len(expanded), 1)
        self.assertEqual(expanded[0]["prior_task_id"], prior_id)
        self.assertNotEqual(expanded[0]["goal_id"], base_id)

    def test_stream_hit_index_requires_repeatable_verified_expanded_geometry_evidence(self) -> None:
        from src.readers.ncdx_record_probe import (ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS,
            ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS, ZLIB_COORDINATE_PROFILE_PARAMETERS,
            ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS)
        rows = [{"region": region, "relative_path": f"{region}/DB/{region}.MG1",
            "sha256": f"{index + 1:064x}", "size_bytes": 4096}
            for index, region in enumerate(("SW", "Italy", "Scandinavia"))]
        prior_id = project_director._data_profile_task_id(
            "MG1", "STANDALONE_ZLIB_STREAM_CENSUS", rows)
        base_id = project_director._data_profile_task_id("MG1",
            "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", rows,
            upstream_task_id=prior_id, profile_parameters=ZLIB_COORDINATE_PROFILE_PARAMETERS)
        expanded_id = project_director._data_profile_task_id("MG1",
            "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", rows,
            upstream_task_id=prior_id,
            profile_parameters=ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS)
        hit_index_id = project_director._data_profile_task_id("MG1",
            "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", rows,
            upstream_task_id=prior_id,
            profile_parameters=ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS)
        completed = {prior_id, "AUTO_SUPERVISOR_" + prior_id,
                     base_id, "AUTO_SUPERVISOR_" + base_id, expanded_id}
        prior = {"status": "PASS", "observations": [
            {"region": row["region"], "source_sha256": row["sha256"],
             "stream_count": 12, "stream_inventory_sha256": f"{index + 10:064x}"}
            for index, row in enumerate(rows)]}
        expanded = {"status": "PASS", "observations": [{
            "region": row["region"], "measurements": {"alignment_7/scale_100000_lon_lat": {
                "region_candidate_pairs": 25, "adjacent_pairs_within_5km": 3}}}
            for row in rows]}
        hit_index = {"status": "PASS", "observations": [{
            "region": row["region"], "candidate_stream_summaries": [{
                "stream_index": index, "candidate_measurements": [{
                    "measurement": "alignment_7/scale_100000_lon_lat",
                    "region_candidate_pairs": 4, "adjacent_pairs_within_5km": 2}]}]}
            for index, row in enumerate(rows)]}

        def task_status(task_id: str) -> str | None:
            return "DONE" if task_id in completed else None

        def task_result(task_id: str) -> dict[str, object]:
            return hit_index if task_id == hit_index_id else expanded if task_id == expanded_id else prior

        with mock.patch.object(project_director.coordinator_runtime,
                "available_target_suffixes", return_value=("MG1",)), \
             mock.patch.object(project_director, "_data_profile_sources", return_value=rows), \
             mock.patch.object(project_director, "_task_status", side_effect=task_status), \
             mock.patch.object(project_director, "_task_result", side_effect=task_result):
            before_verifier = project_director._data_profile_candidates()
            self.assertFalse(any(row.get("profile_parameters") ==
                ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS for row in before_verifier))
            completed.add("AUTO_SUPERVISOR_" + expanded_id)
            after_verifier = project_director._data_profile_candidates()
            indexed = [row for row in after_verifier
                if row.get("profile_parameters") == ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS]
            self.assertEqual(len(indexed), 1)
            self.assertEqual(indexed[0]["selection_evidence_task_id"], expanded_id)
            self.assertNotEqual(indexed[0]["goal_id"], expanded_id)
            self.assertFalse(any(row.get("profile_parameters") ==
                ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS for row in after_verifier))
            completed.add(hit_index_id)
            completed.add("AUTO_SUPERVISOR_" + hit_index_id)
            after_hit_verifier = project_director._data_profile_candidates()

        deep = [row for row in after_hit_verifier
            if row.get("profile_parameters") == ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS]
        self.assertEqual(len(deep), 1)
        self.assertEqual(deep[0]["selection_evidence_task_id"], hit_index_id)
        self.assertNotEqual(deep[0]["goal_id"], indexed[0]["goal_id"])

    def test_full_payload_candidate_is_generated_only_from_verified_deep_streams(self) -> None:
        from src.readers.ncdx_record_probe import (ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS,
            ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS, ZLIB_COORDINATE_PROFILE_PARAMETERS,
            ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS, ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS)
        rows = [{"region": region, "relative_path": f"{region}/DB/{region}.MG1",
            "sha256": f"{index + 1:064x}", "size_bytes": 4096}
            for index, region in enumerate(("SW", "Italy", "Scandinavia"))]
        prior_id = project_director._data_profile_task_id("MG1", "STANDALONE_ZLIB_STREAM_CENSUS", rows)
        prior = {"status": "PASS", "observations": [
            {"region": row["region"], "source_sha256": row["sha256"],
             "stream_count": 12, "stream_inventory_sha256": f"{index + 10:064x}"}
            for index, row in enumerate(rows)]}
        params_by_stage = [ZLIB_COORDINATE_PROFILE_PARAMETERS,
            ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS,
            ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS,
            ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS]
        ids = [project_director._data_profile_task_id("MG1",
            "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", rows,
            upstream_task_id=prior_id, profile_parameters=parameters)
            for parameters in params_by_stage]
        expanded = {"status": "PASS", "observations": [{"region": row["region"],
            "measurements": {"candidate": {"region_candidate_pairs": 10,
                "adjacent_pairs_within_5km": 2}}} for row in rows]}
        stream_summaries = []
        deep_observations = []
        for index, row in enumerate(rows):
            streams = []
            for rank in range(4):
                stream = {"stream_index": index * 10 + rank,
                    "source_offset": 100 + index * 10 + rank,
                    "compressed_bytes": 40, "decompressed_bytes": 128,
                    "decompressed_sha256": f"{index * 10 + rank + 100:064x}",
                    "sample_prefix_sha256": f"{index * 10 + rank + 200:064x}",
                    "candidate_measurements": [{"measurement": "candidate",
                        "region_candidate_pairs": 9 - rank, "adjacent_pairs_within_5km": 3}]}
                streams.append(stream)
            streams.append({"stream_index": index * 10 + 4,
                "source_offset": 104 + index * 10,
                "compressed_bytes": 44, "decompressed_bytes": 132,
                "decompressed_sha256": f"{index * 10 + 104:064x}",
                "sample_prefix_sha256": f"{index * 10 + 204:064x}",
                "candidate_measurements": [{"measurement": "single_pair_candidate",
                    "region_candidate_pairs": 7, "adjacent_pairs_within_5km": 1}]})
            stream_summaries.append(streams[0])
            deep_observations.append({"region": row["region"],
                "candidate_stream_summaries": streams})
        hit_index = {"status": "PASS", "observations": [{"region": row["region"],
            "candidate_stream_summaries": [stream_summaries[index]]}
            for index, row in enumerate(rows)]}
        deep = {"status": "PASS", "profile_parameters": ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS,
            "observations": deep_observations}
        selected_by_region = project_director._selected_coordinate_payloads_from_deep_result(deep)
        selected_parameters = {**ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS,
            "selected_streams_by_region": selected_by_region}
        selected_id = project_director._data_profile_task_id("MG1",
            "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", rows,
            upstream_task_id=prior_id, profile_parameters=selected_parameters)
        result_by_id = dict(zip(ids, [prior, expanded, hit_index, deep]))
        completed = {prior_id, "AUTO_SUPERVISOR_" + prior_id, *ids,
                     *["AUTO_SUPERVISOR_" + item for item in ids]}

        def status(task_id: str) -> str | None:
            return "DONE" if task_id in completed else None

        def result(task_id: str) -> dict[str, object]:
            return result_by_id.get(task_id, prior)

        with mock.patch.object(project_director.coordinator_runtime,
                "available_target_suffixes", return_value=("MG1",)), \
             mock.patch.object(project_director, "_data_profile_sources", return_value=rows), \
             mock.patch.object(project_director, "_task_status", side_effect=status), \
             mock.patch.object(project_director, "_task_result", side_effect=result):
            candidates = project_director._data_profile_candidates()
        selected = [row for row in candidates if row.get("profile_parameters") == selected_parameters]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["selection_evidence_task_id"], ids[-1])
        self.assertEqual(selected[0]["profile_parameters"]["selected_streams_by_region"],
                         selected_by_region)
        self.assertEqual(selected[0]["goal_id"], selected_id)
        completed.update({selected_id, "AUTO_SUPERVISOR_" + selected_id})
        batch_one_selection = project_director._selected_coordinate_payloads_from_deep_result(
            deep, batch_index=1)
        batch_one_parameters = {**ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS,
            "selected_streams_by_region": batch_one_selection, "batch_index": 1}
        batch_one_id = project_director._data_profile_task_id("MG1",
            "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", rows,
            upstream_task_id=prior_id, profile_parameters=batch_one_parameters)
        with mock.patch.object(project_director.coordinator_runtime,
                "available_target_suffixes", return_value=("MG1",)), \
             mock.patch.object(project_director, "_data_profile_sources", return_value=rows), \
             mock.patch.object(project_director, "_task_status", side_effect=status), \
             mock.patch.object(project_director, "_task_result", side_effect=result):
            next_candidates = project_director._data_profile_candidates()
        batch_one = [row for row in next_candidates
                     if row.get("profile_parameters") == batch_one_parameters]
        self.assertEqual(len(batch_one), 1)
        self.assertEqual(batch_one[0]["goal_id"], batch_one_id)
        self.assertTrue(all(
            {row["stream_index"] for row in streams}.isdisjoint({row["stream_index"] for row in
                selected_by_region.get(region, [])})
            for region, streams in batch_one_selection.items()))
        completed.update({batch_one_id, "AUTO_SUPERVISOR_" + batch_one_id})
        single_selection = project_director._selected_coordinate_payloads_from_deep_result(
            deep, selection_class="single_pair")
        single_parameters = {**ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS,
            "selection_class": "single_pair", "selected_streams_by_region": single_selection}
        single_id = project_director._data_profile_task_id("MG1",
            "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", rows,
            upstream_task_id=prior_id, profile_parameters=single_parameters)
        with mock.patch.object(project_director.coordinator_runtime,
                "available_target_suffixes", return_value=("MG1",)), \
             mock.patch.object(project_director, "_data_profile_sources", return_value=rows), \
             mock.patch.object(project_director, "_task_status", side_effect=status), \
             mock.patch.object(project_director, "_task_result", side_effect=result):
            single_candidates = project_director._data_profile_candidates()
        single = [row for row in single_candidates
                  if row.get("profile_parameters") == single_parameters]
        self.assertEqual(len(single), 1)
        self.assertEqual(single[0]["goal_id"], single_id)
        self.assertEqual([len(streams) for streams in single_selection.values()], [1, 1, 1])

    def test_blocked_full_payload_verifier_does_not_starve_next_independent_batch(self) -> None:
        from src.readers.ncdx_record_probe import (ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS,
            ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS, ZLIB_COORDINATE_PROFILE_PARAMETERS,
            ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS, ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS)
        rows = [{"region": region, "relative_path": f"{region}/DB/{region}.MG2",
            "sha256": f"{index + 1:064x}", "size_bytes": 4096}
            for index, region in enumerate(("SW", "Italy", "Scandinavia"))]
        prior_id = project_director._data_profile_task_id("MG2", "STANDALONE_ZLIB_STREAM_CENSUS", rows)
        prior = {"status": "PASS", "observations": [
            {"region": row["region"], "source_sha256": row["sha256"],
             "stream_count": 12, "stream_inventory_sha256": f"{index + 10:064x}"}
            for index, row in enumerate(rows)]}
        params_by_stage = [ZLIB_COORDINATE_PROFILE_PARAMETERS,
            ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS,
            ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS,
            ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS]
        stage_ids = [project_director._data_profile_task_id("MG2",
            "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", rows,
            upstream_task_id=prior_id, profile_parameters=params)
            for params in params_by_stage]
        deep_observations = []
        hit_observations = []
        for region_index, row in enumerate(rows):
            streams = []
            for rank in range(3):
                streams.append({"stream_index": region_index * 10 + rank,
                    "source_offset": 100 + region_index * 10 + rank,
                    "compressed_bytes": 40, "decompressed_bytes": 128,
                    "decompressed_sha256": f"{region_index * 10 + rank + 100:064x}",
                    "sample_prefix_sha256": f"{region_index * 10 + rank + 200:064x}",
                    "candidate_measurements": [{"region_candidate_pairs": 5 - rank,
                        "adjacent_pairs_within_5km": 1}]})
            deep_observations.append({"region": row["region"],
                "candidate_stream_summaries": streams})
            hit_stream = {**streams[0], "candidate_measurements": [{
                "region_candidate_pairs": 5, "adjacent_pairs_within_5km": 2}]}
            hit_observations.append({"region": row["region"],
                "candidate_stream_summaries": [hit_stream]})
        deep = {"status": "PASS", "profile_parameters": ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS,
            "observations": deep_observations}
        hit_index = {"status": "PASS", "observations": hit_observations}
        expanded = {"status": "PASS", "observations": [{"region": row["region"],
            "measurements": {"candidate": {"region_candidate_pairs": 10,
                "adjacent_pairs_within_5km": 2}}} for row in rows]}

        batch_zero = project_director._selected_coordinate_payloads_from_deep_result(
            deep, selection_class="single_pair", batch_index=0)
        batch_zero_parameters = {**ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS,
            "selection_class": "single_pair", "selected_streams_by_region": batch_zero}
        batch_zero_id = project_director._data_profile_task_id("MG2",
            "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", rows,
            upstream_task_id=prior_id, profile_parameters=batch_zero_parameters)
        completed = {prior_id, "AUTO_SUPERVISOR_" + prior_id,
                     *stage_ids, *["AUTO_SUPERVISOR_" + item for item in stage_ids],
                     batch_zero_id}
        result_by_id = {prior_id: prior, stage_ids[0]: prior,
            stage_ids[1]: expanded, stage_ids[2]: hit_index, stage_ids[3]: deep}

        def status(task_id: str) -> str | None:
            if task_id == "AUTO_SUPERVISOR_" + batch_zero_id:
                return "BLOCKED"
            return "DONE" if task_id in completed else None

        def result(task_id: str) -> dict[str, object]:
            return result_by_id.get(task_id, prior)

        with mock.patch.object(project_director.coordinator_runtime,
                "available_target_suffixes", return_value=("MG2",)), \
             mock.patch.object(project_director, "_data_profile_sources", return_value=rows), \
             mock.patch.object(project_director, "_task_status", side_effect=status), \
             mock.patch.object(project_director, "_task_result", side_effect=result):
            candidates = project_director._data_profile_candidates()

        batch_one = [row for row in candidates
            if row.get("profile_parameters", {}).get("selection_class") == "single_pair"
            and row.get("profile_parameters", {}).get("batch_index") == 1]
        self.assertEqual(len(batch_one), 1)
        self.assertEqual(batch_one[0]["selection_evidence_task_id"], stage_ids[-1])
        self.assertNotEqual(batch_one[0]["goal_id"], batch_zero_id)

    def test_verified_zlib_census_unlocks_coordinate_candidate_worker_and_fresh_verifier(self) -> None:
        import struct
        from src.readers.ncdx_record_probe import (ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS,
            ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS, ZLIB_COORDINATE_PROFILE_PARAMETERS,
            ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS,
            ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS,
            scan_standalone_zlib_streams)
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            source_root = root / "originals"
            source_root.mkdir()
            regional = {"SW": (50.0, 20.0), "Italy": (45.46, 9.19),
                        "Scandinavia": (60.0, 15.0)}
            sources = []
            prior_observations = []
            for region, (latitude, longitude) in regional.items():
                payload = bytearray(128)
                for index in range(12):
                    struct.pack_into("<ii", payload, index * 8,
                        int((latitude + index * 0.0001) * 1_000_000),
                        int((longitude + index * 0.0001) * 1_000_000))
                relative = f"{region}/fixture.MG1"
                source = source_root / relative
                source.parent.mkdir(parents=True)
                encoded = zlib.compress(bytes(payload)) + bytes(4096)
                source.write_bytes(encoded)
                digest = hashlib.sha256(encoded).hexdigest()
                census = scan_standalone_zlib_streams(source, expected_sha256=digest)
                sources.append({"region": region, "relative_path": relative,
                    "sha256": digest, "size_bytes": len(encoded)})
                prior_observations.append({"region": region, "source_sha256": digest,
                    "stream_count": census["stream_count"],
                    "stream_inventory_sha256": census["stream_inventory_sha256"]})
            prior_id = project_director._data_profile_task_id(
                "MG1", "STANDALONE_ZLIB_STREAM_CENSUS", sources)
            parameters = dict(ZLIB_COORDINATE_PROFILE_PARAMETERS)
            task_id = project_director._data_profile_task_id("MG1",
                "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", sources,
                upstream_task_id=prior_id, profile_parameters=parameters)
            previous = {"status": "PASS", "observations": prior_observations}
            saved_results = {}
            def task_result(task_id):
                return saved_results.get(task_id, previous)
            task = {"id": task_id, "budget": {"data_family_profile": True,
                "suffix": "MG1", "profile_mode": "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS",
                "sources": sources, "prior_task_id": prior_id,
                "profile_parameters": parameters}}
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director.coordinator_runtime, "SOURCE_ROOT", source_root), \
                 mock.patch.object(project_director, "_data_profile_sources", return_value=sources), \
                 mock.patch.object(project_director, "_task_status", return_value="DONE"), \
                 mock.patch.object(project_director, "_task_result", side_effect=task_result), \
                 mock.patch.object(project_director, "_ledger_hash",
                     side_effect=lambda relative: next(row["sha256"] for row in sources
                         if row["relative_path"] == relative)), \
                 mock.patch.object(project_director.manager, "_artifact", return_value={"path": "fixture.json"}), \
                 mock.patch.object(project_director, "_register_supervisor", return_value=True):
                result = project_director._execute_zlib_decoded_coordinate_candidate_census(task, sources)
                saved_results[task_id] = result
                independent = project_director._verify_zlib_decoded_coordinate_candidate_target(
                    task_id, task, result)
                expanded_task_id = project_director._data_profile_task_id("MG1",
                    "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", sources,
                    upstream_task_id=prior_id,
                    profile_parameters=ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS)
                expanded_task = {"id": expanded_task_id, "budget": {
                    **task["budget"],
                    "selection_evidence_task_id": task_id,
                    "profile_parameters": ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS}}
                expanded_result = project_director._execute_zlib_decoded_coordinate_candidate_census(
                    expanded_task, sources)
                saved_results[expanded_task_id] = expanded_result
                expanded_independent = project_director._verify_zlib_decoded_coordinate_candidate_target(
                    expanded_task_id, expanded_task, expanded_result)
                indexed_task_id = project_director._data_profile_task_id("MG1",
                    "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", sources,
                    upstream_task_id=prior_id,
                    profile_parameters=ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS)
                indexed_task = {"id": indexed_task_id, "budget": {
                    **task["budget"],
                    "selection_evidence_task_id": expanded_task_id,
                    "profile_parameters": ZLIB_COORDINATE_STREAM_HIT_INDEX_PARAMETERS}}
                indexed_result = project_director._execute_zlib_decoded_coordinate_candidate_census(
                    indexed_task, sources)
                saved_results[indexed_task_id] = indexed_result
                indexed_independent = project_director._verify_zlib_decoded_coordinate_candidate_target(
                    indexed_task_id, indexed_task, indexed_result)
                deep_task_id = project_director._data_profile_task_id("MG1",
                    "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", sources,
                    upstream_task_id=prior_id,
                    profile_parameters=ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS)
                deep_task = {"id": deep_task_id, "budget": {
                    **task["budget"],
                    "selection_evidence_task_id": indexed_task_id,
                    "profile_parameters": ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS}}
                deep_result = project_director._execute_zlib_decoded_coordinate_candidate_census(
                    deep_task, sources)
                deep_independent = project_director._verify_zlib_decoded_coordinate_candidate_target(
                    deep_task_id, deep_task, deep_result)
                saved_results[deep_task_id] = deep_result
                selected_by_region = project_director._selected_coordinate_payloads_from_deep_result(
                    deep_result)
                selected_parameters = {**ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS,
                    "selected_streams_by_region": selected_by_region}
                selected_task_id = project_director._data_profile_task_id("MG1",
                    "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", sources,
                    upstream_task_id=prior_id, profile_parameters=selected_parameters)
                selected_task = {"id": selected_task_id, "budget": {
                    **task["budget"], "selection_evidence_task_id": deep_task_id,
                    "profile_parameters": selected_parameters}}
                selected_result = project_director._execute_zlib_decoded_coordinate_candidate_census(
                    selected_task, sources)
                selected_independent = project_director._verify_zlib_decoded_coordinate_candidate_target(
                    selected_task_id, selected_task, selected_result)
                single_deep_result = json.loads(json.dumps(deep_result))
                for observation in single_deep_result["observations"]:
                    for stream in observation.get("candidate_stream_summaries", []):
                        for measurement in stream.get("candidate_measurements", []):
                            measurement["adjacent_pairs_within_5km"] = 1
                saved_results[deep_task_id] = single_deep_result
                single_by_region = project_director._selected_coordinate_payloads_from_deep_result(
                    single_deep_result, selection_class="single_pair")
                single_parameters = {**ZLIB_COORDINATE_SELECTED_PAYLOAD_PARAMETERS,
                    "selection_class": "single_pair",
                    "selected_streams_by_region": single_by_region}
                single_task_id = project_director._data_profile_task_id("MG1",
                    "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS", sources,
                    upstream_task_id=prior_id, profile_parameters=single_parameters)
                single_task = {"id": single_task_id, "budget": {
                    **task["budget"], "selection_evidence_task_id": deep_task_id,
                    "profile_parameters": single_parameters}}
                single_result = project_director._execute_zlib_decoded_coordinate_candidate_census(
                    single_task, sources)
                single_independent = project_director._verify_zlib_decoded_coordinate_candidate_target(
                    single_task_id, single_task, single_result)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(independent["independent_region_count"], 3)
            self.assertEqual(independent["stream_count_by_region"], {region: 1 for region in regional})
            self.assertTrue(all(row["raw_payload_bytes_retained"] is False
                                for row in result["observations"]))
            self.assertTrue(all(any(metric["adjacent_pairs_within_5km"] > 0
                                    for metric in row["measurements"].values())
                                for row in result["observations"]))
            self.assertEqual(expanded_result["profile_parameters"],
                             ZLIB_COORDINATE_EXPANDED_PROFILE_PARAMETERS)
            self.assertEqual(expanded_independent["independent_region_count"], 3)
            self.assertTrue(all(row["sampled_stream_count"] == 1
                                for row in expanded_result["observations"]))
            self.assertEqual(indexed_independent["independent_region_count"], 3)
            self.assertTrue(all(row["candidate_stream_summaries"]
                                for row in indexed_result["observations"]))
            self.assertTrue(all(len(row["candidate_stream_summaries"][0]["decompressed_sha256"]) == 64
                                for row in indexed_result["observations"]))
            self.assertEqual(deep_independent["independent_region_count"], 3)
            self.assertTrue(all(row["sampled_payload_bytes"] == 128
                                for row in deep_result["observations"]))
            self.assertEqual(deep_result["profile_parameters"],
                             ZLIB_COORDINATE_DEEP_PREFIX_PARAMETERS)
            self.assertEqual(selected_independent["independent_region_count"], 3)
            self.assertTrue(selected_independent["fresh_selected_full_payload_audit"])
            self.assertEqual(selected_independent["selected_stream_count_by_region"],
                             {region: 1 for region in regional})
            self.assertTrue(all(row["selected_full_payload_audit"]["selected_stream_count"] == 1
                                for row in selected_result["observations"]))
            self.assertTrue(all(row["raw_payload_bytes_retained"] is False
                                for row in selected_result["observations"]))
            self.assertTrue(single_independent["fresh_selected_full_payload_audit"])
            self.assertEqual(single_independent["selected_stream_count_by_region"],
                             {region: 1 for region in regional})

    def test_standalone_zlib_worker_and_supervisor_reproduce_three_regional_files(self) -> None:
        from src.readers.ncdx_record_probe import (MAX_STANDALONE_ZLIB_COMPRESSED_BYTES,
            MAX_STANDALONE_ZLIB_FILE_BYTES, MAX_STANDALONE_ZLIB_HEADER_CANDIDATES,
            MAX_STANDALONE_ZLIB_OUTPUT_BYTES)
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            rows = []
            payload = b"one repeated payload proves the same stream across regions" * 24
            compressed = zlib.compress(payload)
            for index, region in enumerate(("SW", "Italy", "Scandinavia")):
                relative = f"{region}/DB/{region}.RL"
                source = root / relative
                source.parent.mkdir(parents=True)
                raw = bytes([0x31 + index]) * (128 + index * 4) + compressed + bytes([0x60 + index]) * 5000
                source.write_bytes(raw)
                rows.append({"region": region, "relative_path": relative,
                    "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)})
            parameters = {"max_file_bytes": MAX_STANDALONE_ZLIB_FILE_BYTES,
                "max_compressed_bytes": MAX_STANDALONE_ZLIB_COMPRESSED_BYTES,
                "max_output_bytes": MAX_STANDALONE_ZLIB_OUTPUT_BYTES,
                "max_header_candidates": MAX_STANDALONE_ZLIB_HEADER_CANDIDATES}
            task_id = project_director._data_profile_task_id(
                "RL", "STANDALONE_ZLIB_STREAM_CENSUS", rows)
            task = {"id": task_id, "budget": {"data_family_profile": True, "suffix": "RL",
                "profile_mode": "STANDALONE_ZLIB_STREAM_CENSUS", "sources": rows,
                "profile_parameters": parameters}}
            artifact = lambda _task_id, path, _description, acceptance: {
                "path": str(path.relative_to(root)), "acceptance": acceptance}
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director.coordinator_runtime, "SOURCE_ROOT", root), \
                 mock.patch.object(project_director.coordinator_runtime,
                                   "available_target_suffixes", return_value=("RL",)), \
                 mock.patch.object(project_director, "_data_profile_sources", return_value=rows), \
                 mock.patch.object(project_director, "_ledger_hash",
                     side_effect=lambda relative: next(row["sha256"] for row in rows
                         if row["relative_path"] == relative)), \
                 mock.patch.object(project_director.manager, "_artifact", side_effect=artifact), \
                 mock.patch.object(project_director, "_register_supervisor"):
                result = project_director.execute_data_family_profile(task)
                self.assertEqual(result["status"], "PASS")
                self.assertEqual([row["stream_count"] for row in result["observations"]], [1, 1, 1])
                self.assertEqual(len(result["cross_region_shared_payloads"]), 1)
                self.assertEqual(result["cross_region_shared_payload_count"], 1)
                self.assertEqual(len(result["cross_region_shared_inventory_sha256"]), 64)
                self.assertEqual([len(row["streams"]) for row in result["observations"]], [1, 1, 1])
                fresh = project_director._verify_standalone_zlib_stream_census_target(
                    task_id, task, result)
                with mock.patch.object(project_director, "_task_result", return_value=result), \
                     mock.patch.object(project_director.manager, "_task", return_value=task):
                    accepted = project_director._verified_target(task_id)
                supervisor_id = "AUTO_SUPERVISOR_" + task_id
                with mock.patch.object(project_director, "_task_status",
                        side_effect=lambda item: "DONE" if item in {task_id, supervisor_id} else None), \
                     mock.patch.object(project_director, "_task_result", return_value=result):
                    boundary_candidate = next(row for row in project_director._data_profile_candidates()
                        if row["mode"] == "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE")
                self.assertEqual(boundary_candidate["prior_task_id"], task_id)
                boundary_task_id = boundary_candidate["goal_id"]
                boundary_parameters = boundary_candidate["profile_parameters"]
                boundary_task = {"id": boundary_task_id, "budget": {
                    "data_family_profile": True, "suffix": "RL",
                    "profile_mode": "ZLIB_STREAM_BOUNDARY_CONTEXT_PROFILE",
                    "sources": rows, "plan_goal_id": boundary_task_id,
                    "prior_task_id": task_id, "profile_parameters": boundary_parameters}}
                with mock.patch.object(project_director, "_task_status", return_value="DONE"), \
                     mock.patch.object(project_director, "_task_result", return_value=result):
                    boundary_result = project_director.execute_data_family_profile(boundary_task)
                self.assertEqual(boundary_result["status"], "PASS")
                self.assertEqual(boundary_result["profile_parameters"], boundary_parameters)
                self.assertTrue(all(row["raw_context_bytes_retained"] is False
                                    for row in boundary_result["observations"]))
                with mock.patch.object(project_director, "_task_status", return_value="DONE"), \
                     mock.patch.object(project_director, "_task_result",
                        side_effect=lambda item: result if item == task_id else boundary_result), \
                     mock.patch.object(project_director.manager, "_task", return_value=boundary_task):
                    accepted_boundary = project_director._verified_target(boundary_task_id)
            self.assertTrue(fresh["fresh_manifest_bound_rescan"])
            self.assertTrue(accepted["deterministic_proof"]["fresh_manifest_bound_rescan"])
            self.assertTrue(accepted_boundary["deterministic_proof"]["fresh_manifest_bound_boundary_rescan"])
            self.assertEqual(fresh["confirmed_stream_count_by_region"],
                             {"SW": 1, "Italy": 1, "Scandinavia": 1})
            self.assertEqual(fresh["cross_region_shared_payload_count"], 1)

    def test_mission_a01_baseline_reads_available_models_from_manager(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            state_db = root / "project_state.sqlite"
            for name in ("project_state.sqlite", "TASK_BACKLOG.sqlite", "EVIDENCE_LEDGER.sqlite"):
                conn = sqlite3.connect(root / name)
                try:
                    if name == "project_state.sqlite":
                        conn.execute("CREATE TABLE tasks(id TEXT,status TEXT,result_json TEXT)")
                    else:
                        conn.execute("CREATE TABLE integrity_fixture(value TEXT)")
                finally:
                    conn.close()
            task = {"id": "A01-fixture", "budget": {"mission_pack_task": "A01"}}
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director.manager, "_task", return_value=task), \
                 mock.patch.object(project_director.manager, "_control", return_value={"worker_pid": 123}), \
                 mock.patch.object(project_director.manager, "available_models", return_value=(["qwen-fixture"], None)), \
                 mock.patch.object(project_director.manager, "_artifact", return_value={"path": "baseline.json"}), \
                 mock.patch.object(project_director.manager.shutil, "which", return_value=None), \
                 mock.patch.object(project_director.subprocess, "run", return_value=mock.Mock(returncode=1, stdout="", stderr="")):
                result = project_director.execute_mission_pack_task(task["id"])
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["acceptance"]["available_local_models"], ["qwen-fixture"])

    def test_local_capability_quota_wait_parks_original_mission(self) -> None:
        from src.agent import capability_broker, mission_pack
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            state_db = root / "project_state.sqlite"
            mission_pack.import_pack(db_path=state_db)
            previous = {"verifier": "checkpoint_fixture", "verdict": "PASS",
                        "checkpoint": {"token": "source-hash-123"}}
            mission_pack.mark_status("D03", "WAITING_LOCAL", evidence=previous,
                reason="local capability request is pending", runtime_task_id="D03-SOURCE",
                db_path=state_db)
            capability_task = {"id": "CAPABILITY-TASK", "budget": {
                "capability_request_id": "CAP_D03_TEST", "source_task_id": "D03-SOURCE",
                "timeout_s": 1800}}
            source_task = {"id": "D03-SOURCE", "budget": {"mission_pack_task": "D03"}}
            outcomes = [{"status": "LOCAL_FAILED", "reason": "local coder produced no diff"},
                        {"status": "WAITING_CODEX_QUOTA", "request_id": "CAP_D03_TEST",
                         "reason": "daily quota exhausted", "quota": {"allowed": False}}]
            with (
                mock.patch.object(project_director, "PROJECT_ROOT", root),
                mock.patch.object(project_director, "STATE_DB", state_db),
                mock.patch.object(project_director.manager, "_task", side_effect=[capability_task, source_task]),
                mock.patch.object(project_director.manager, "_artifact", return_value={"path": "capability.json"}),
                mock.patch.object(capability_broker, "execute_request", side_effect=outcomes) as execute,
            ):
                result = project_director.execute_capability_request("CAPABILITY-TASK")
            self.assertEqual(result["status"], "WAITING_CODEX_QUOTA")
            self.assertEqual([call.kwargs["executor"] for call in execute.call_args_list], ["local", "codex"])
            with closing(sqlite3.connect(state_db)) as conn:
                status, evidence_json = conn.execute(
                    "SELECT status,evidence_json FROM mission_tasks WHERE canonical_id='D03'").fetchone()
            evidence = json.loads(evidence_json)
            self.assertEqual(status, "WAITING_CODEX_QUOTA")
            self.assertEqual(evidence["previous_evidence"], previous)
            self.assertEqual(evidence["request_id"], "CAP_D03_TEST")

    def test_osm_failure_review_accepts_only_advisory_allowlisted_model_output(self) -> None:
        from src.agent import coordinator_runtime
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            (root / "work" / "autonomous_manager" / "osm_pipeline" / "failure_reviews").mkdir(parents=True)
            task = {"id": "AUTO_OSM_FAILURE_REVIEW_TEST", "budget": {
                "osm_failure_review": True, "failure_task_id": "AUTO_OSM_NATIONAL_CONVERSION_01",
                "failure_text": "out of memory at a saved checkpoint", "checkpoint_token": "abc123",
                "source_pbf_sha256": "a" * 64, "extract_sha256": "b" * 64}}
            response = {"root_cause_class": "MEMORY_MONOLITH",
                "explanation": "The old full-tree parser accumulated XML in memory.",
                "next_action": "RESUME_CHECKPOINTED_SLICES",
                "safety_note": "Keep original sources read-only; treat this as advisory."}
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director.manager, "_task", return_value=task), \
                 mock.patch.object(project_director.manager, "_artifact", return_value={"path": "review.json"}), \
                 mock.patch.object(coordinator_runtime, "_call_model", return_value=("qwen3.5:9b", json.dumps(response), response)) as call:
                result = project_director.execute_osm_failure_review(task["id"])
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["recommendation"], "RESUME_CHECKPOINTED_SLICES")
            self.assertFalse(result["model_output_executed"])
            self.assertIn("saved checkpoint", call.call_args.args[2])
            saved = json.loads((root / "work" / "autonomous_manager" / "osm_pipeline" / "failure_reviews" / "auto_osm_failure_review_test.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["validation"][1]["status"], "PASS")

    def test_osm_continuation_task_is_idempotent_for_a_checkpoint_token(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            state_db = root / "state.sqlite"
            parent = {"id": project_director.OSM_NATIONAL_TASK_ID, "budget": {
                "resumable_national_osm": True, "ukraine_national_osm": True,
                "source_pbf_sha256": "a" * 64, "extract_sha256": "b" * 64,
                "output_directory": "work/autonomous_manager/osm_pipeline/ukraine_national/test"}}
            with mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director.manager, "_task", return_value=parent), \
                 mock.patch.object(project_director, "reconcile_national_osm_continuations",
                     return_value={"complete": False, "checkpoint_token": "0123456789abcdef",
                         "source_pbf_sha256": "a" * 64, "extract_sha256": "b" * 64,
                         "superseded_task_ids": []}), \
                 mock.patch.object(project_director.manager, "_event"):
                first = project_director.queue_national_osm_continuation(
                    parent["id"], "0123456789abcdef", reason="fixture restart")
                second = project_director.queue_national_osm_continuation(
                    parent["id"], "0123456789abcdef", reason="same fixture restart")
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            conn = sqlite3.connect(state_db)
            try:
                count = conn.execute("SELECT count(*) FROM tasks WHERE id LIKE 'AUTO_OSM_NATIONAL_STEP_%'").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 1)

    def test_stale_osm_checkpoint_is_superseded_and_current_checkpoint_is_queued(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            state_db = Path(temporary) / "state.sqlite"
            old_token, new_token = "822ba7a5e9bdb9d4", "c03cc6b57b6f3dff"
            old_id = "AUTO_OSM_NATIONAL_STEP_" + old_token.upper()
            old = {"id": old_id, "stage": "F4", "depends_on": [],
                "hypothesis": "stale checkpoint", "evidence": [], "agent": "osm-national-conversion",
                "budget": {"resumable_national_osm": True, "checkpoint_token": old_token},
                "deliverables": [], "tests": [], "next_action": "do not replay", "retry_limit": 1}
            state_store.add_task(old, db_path=state_db)
            conn = sqlite3.connect(state_db)
            try:
                conn.execute("UPDATE tasks SET status='BLOCKED',verdict='BLOCKED',result_json=? WHERE id=?",
                    ('{"error":"stale checkpoint"}', old_id))
                conn.commit()
            finally:
                conn.close()
            parent_id = project_director.OSM_NATIONAL_TASK_ID
            parent = {"id": parent_id, "budget": {"resumable_national_osm": True,
                "ukraine_national_osm": True, "source_path": "data/osm/ukraine-latest.osm.pbf",
                "source_pbf_sha256": "a" * 64, "extract_sha256": "b" * 64,
                "output_directory": "work/autonomous_manager/osm_pipeline/ukraine_national/test"}}
            live_state = {"complete": False, "checkpoint_token": new_token,
                "source_pbf_sha256": "a" * 64, "extract_sha256": "b" * 64,
                "superseded_task_ids": []}
            with mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director.manager, "_task", return_value=parent), \
                 mock.patch.object(project_director, "_national_osm_state_from_budget", return_value=live_state), \
                 mock.patch.object(project_director.manager, "_event"):
                reconciled = project_director.reconcile_national_osm_continuations(parent["budget"])
                queued = project_director.queue_national_osm_continuation(parent_id, old_token,
                    reason="late task response", after_failure=True)
            self.assertEqual(reconciled["superseded_task_ids"], [old_id])
            self.assertTrue(queued["created"])
            self.assertEqual(queued["checkpoint_token"], new_token)
            self.assertEqual(queued["task_id"], "AUTO_OSM_NATIONAL_STEP_" + new_token.upper())
            conn = sqlite3.connect(state_db)
            try:
                statuses = dict(conn.execute("SELECT id,status FROM tasks"))
                old_result = json.loads(conn.execute("SELECT result_json FROM tasks WHERE id=?", (old_id,)).fetchone()[0])
            finally:
                conn.close()
            self.assertEqual(statuses[old_id], "SUPERSEDED")
            self.assertEqual(statuses[queued["task_id"]], "PENDING")
            self.assertEqual(old_result["error"], "stale checkpoint")
            self.assertEqual(old_result["superseded"]["evidence"]["current_checkpoint"], new_token)

    def test_completed_source_bound_osm_publication_supersedes_slices_and_never_requeues(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            state_db = Path(temporary) / "state.sqlite"
            ids = ["AUTO_OSM_NATIONAL_STEP_822BA7A5E9BDB9D4",
                   "AUTO_OSM_NATIONAL_STEP_78A9CBADA5CFA3A8"]
            for task_id in ids:
                state_store.add_task({"id": task_id, "stage": "F4", "depends_on": [],
                    "hypothesis": "old import slice", "evidence": [], "agent": "osm-national-conversion",
                    "budget": {"checkpoint_token": task_id.rsplit("_", 1)[1].lower()},
                    "deliverables": [], "tests": [], "next_action": "none", "retry_limit": 1}, db_path=state_db)
            conn = sqlite3.connect(state_db)
            try:
                conn.execute("UPDATE tasks SET status='BLOCKED',verdict='BLOCKED'")
                conn.commit()
            finally:
                conn.close()
            parent_id = project_director.OSM_NATIONAL_TASK_ID
            parent = {"id": parent_id, "budget": {"resumable_national_osm": True,
                "source_pbf_sha256": "a" * 64, "extract_sha256": "b" * 64}}
            proof = {"complete": True, "checkpoint_token": None,
                "source_pbf_sha256": "a" * 64, "extract_sha256": "b" * 64,
                "published_proof": {"counts": {"nodes": 1}}, "superseded_task_ids": []}
            with mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director.manager, "_task", return_value=parent), \
                 mock.patch.object(project_director, "_national_osm_state_from_budget", return_value=proof), \
                 mock.patch.object(project_director.manager, "_event"):
                reconciled = project_director.reconcile_national_osm_continuations(parent["budget"])
                queued = project_director.queue_national_osm_continuation(parent_id, "822ba7a5e9bdb9d4",
                    reason="late success response")
            self.assertEqual(set(reconciled["superseded_task_ids"]), set(ids))
            self.assertFalse(queued["created"])
            conn = sqlite3.connect(state_db)
            try:
                self.assertEqual(conn.execute("SELECT count(*) FROM tasks WHERE status='PENDING'").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT count(*) FROM tasks WHERE status='SUPERSEDED'").fetchone()[0], 2)
            finally:
                conn.close()

    def test_mp0_readback_task_is_created_only_after_verified_copy_writer(self) -> None:
        writer = {"status": "PASS_COPY_ONLY", "source_write_count": 0,
            "original_media_protection": "PASS", "regional_roundtrips": [{}, {}, {}]}
        with mock.patch.object(project_director, "_task_status", side_effect=["DONE", None]), \
             mock.patch.object(project_director, "_task_result", return_value=writer), \
             mock.patch.object(project_director, "_registered_task", return_value=True) as register, \
             mock.patch.object(project_director.manager, "_event"):
            result = project_director.seed_next_mp0_independent_readback_task()
        self.assertTrue(result["created"])
        args = register.call_args.args
        self.assertEqual(args[0], "AUTO_MP0_INDEPENDENT_READBACK_01")
        self.assertEqual(args[1], "F3")
        self.assertEqual(args[2], "AUTO_F3_EXPERIMENTAL_MP0_ROUNDTRIP_001")
        self.assertEqual(args[4], "mp0-independent-readback")

    def test_director_accepts_only_complete_allowlisted_plan_schema(self) -> None:
        valid = {"goal_id": "OSM_REAL_CONVERSION", "depends_on": [],
                 "acceptance_criteria": project_director._acceptance_criteria("OSM_REAL_CONVERSION"),
                 "requires_hardware": False, "writes_original_media": False,
                 "reason": "The local PBF is present and software-verifiable."}
        result = project_director._evaluate_plan(valid, "OSM_REAL_CONVERSION", None,
                                                project_director._acceptance_criteria("OSM_REAL_CONVERSION"))
        self.assertEqual(result["score"], result["maximum"])
        invalid = dict(valid, goal_id="RUN_ARBITRARY_CODE", writes_original_media=True)
        rejected = project_director._evaluate_plan(invalid, "OSM_REAL_CONVERSION", None,
                                                   project_director._acceptance_criteria("OSM_REAL_CONVERSION"))
        self.assertLess(rejected["score"], rejected["maximum"])
        self.assertFalse(rejected["passed"]["allowlisted_goal"])
        self.assertFalse(rejected["passed"]["original_media_unchanged"])
        malformed = dict(valid, acceptance_criteria=[{}])
        self.assertFalse(project_director._evaluate_plan(
            malformed, "OSM_REAL_CONVERSION", None,
            project_director._acceptance_criteria("OSM_REAL_CONVERSION"))["passed"]["fixed_acceptance_criteria"])

    def test_scheduler_persists_one_director_plan_in_existing_sqlite_queue(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp_dir:
            db = Path(temp_dir) / "director.sqlite"
            with mock.patch.object(project_director, "STATE_DB", db), \
                 mock.patch.object(project_director, "_candidate_goal", return_value="OSM_REAL_CONVERSION"), \
                 mock.patch.object(project_director.manager, "_event"):
                first = project_director.seed_next_plan_task()
                second = project_director.seed_next_plan_task()
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            conn = sqlite3.connect(db)
            try:
                rows = conn.execute("SELECT id,agent,budget_json,objective_tests_json FROM tasks").fetchall()
            finally:
                conn.close()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], project_director.PLAN_ID["OSM_REAL_CONVERSION"])
            self.assertEqual(rows[0][1], "ollama-project-director")
            self.assertGreaterEqual(len(json.loads(rows[0][3])), 3)

    def test_national_osm_task_is_unique_and_waits_for_city_readback(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp_dir:
            root = Path(temp_dir)
            state_db = root / "state.sqlite"
            source = root / "ukraine-latest.osm.pbf"
            source.write_bytes(b"read-only source fixture")
            with mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director, "SOURCE_PBF", source), \
                 mock.patch.object(project_director.manager, "_event"):
                self.assertFalse(project_director.seed_next_national_osm_task()["created"])
                state_store.add_task({"id": "AUTO_SUPERVISOR_OSM_READBACK_01", "stage": "R3",
                    "depends_on": [], "hypothesis": "fresh city readback", "evidence": [],
                    "agent": "deterministic", "budget": {}, "deliverables": [], "tests": [],
                    "next_action": "continue", "status": "DONE"}, db_path=state_db)
                first = project_director.seed_next_national_osm_task()
                second = project_director.seed_next_national_osm_task()
            self.assertTrue(first["created"])
            self.assertFalse(second["created"])
            conn = sqlite3.connect(state_db)
            try:
                row = conn.execute("SELECT status,agent,depends_on_json,budget_json FROM tasks WHERE id=?",
                    (project_director.OSM_NATIONAL_TASK_ID,)).fetchone()
            finally:
                conn.close()
            self.assertEqual(row[0], "PENDING")
            self.assertEqual(row[1], "osm-national-conversion")
            self.assertEqual(json.loads(row[2]), ["AUTO_SUPERVISOR_OSM_READBACK_01"])
            self.assertTrue(json.loads(row[3])["ukraine_national_osm"])

    def test_failed_published_readback_gets_a_bounded_retry_without_reimport(self) -> None:
        from src.osm import resumable_national
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            state_db = root / "state.sqlite"
            output_dir = root / "work" / "autonomous_manager" / "osm_pipeline" / "ukraine_national" / "fixture"
            output_dir.mkdir(parents=True)
            (output_dir / "ukraine.sqlite").write_bytes(b"published fixture")
            (output_dir / "ukraine.osm.gz").write_bytes(b"extract fixture")
            source = root / "ukraine-latest.osm.pbf"
            source.write_bytes(b"immutable fixture")
            for task_id, status, budget in (
                (project_director.OSM_NATIONAL_TASK_ID, "BLOCKED", {
                    "resumable_national_osm": True, "output_directory": str(output_dir.relative_to(root)),
                    "source_pbf_sha256": "a" * 64, "extract_sha256": "b" * 64}),
                (project_director.OSM_NATIONAL_PUBLISHED_RECOVERY_ID, "BLOCKED", {
                    "resumable_national_osm": True, "national_osm_published_recovery": True}),
            ):
                state_store.add_task({"id": task_id, "stage": "F4", "depends_on": [],
                    "hypothesis": "fixture", "evidence": [], "agent": "osm-national-conversion",
                    "budget": budget, "deliverables": [], "tests": [], "next_action": "retry",
                    "status": status}, db_path=state_db)
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director, "SOURCE_PBF", source), \
                 mock.patch.object(project_director, "WORK_ROOT", output_dir.parents[1]), \
                  mock.patch.object(project_director, "reconcile_national_osm_continuations",
                      return_value={"complete": False, "superseded_task_ids": []}), \
                 mock.patch.object(resumable_national, "_published_database_result", return_value={"status": "PASS"}), \
                 mock.patch.object(project_director, "_registered_task", return_value=True) as register, \
                 mock.patch.object(project_director.manager, "_event"):
                result = project_director.seed_next_national_osm_task()
            self.assertTrue(result["created"])
            self.assertIn("_RETRY_01", result["task_id"])
            self.assertIsNone(register.call_args.args[2])
            self.assertTrue(register.call_args.args[9]["national_osm_published_recovery"])

    def test_supervised_published_readback_is_not_requeued_for_another_large_scan(self) -> None:
        from src.osm import resumable_national
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            state_db = root / "state.sqlite"
            output_dir = root / "work" / "autonomous_manager" / "osm_pipeline" / "ukraine_national" / "fixture"
            output_dir.mkdir(parents=True)
            (output_dir / "ukraine.sqlite").write_bytes(b"published fixture")
            (output_dir / "ukraine.osm.gz").write_bytes(b"extract fixture")
            source = root / "ukraine-latest.osm.pbf"
            source.write_bytes(b"immutable fixture")
            tasks = (
                (project_director.OSM_NATIONAL_TASK_ID, "BLOCKED", {
                    "resumable_national_osm": True, "output_directory": str(output_dir.relative_to(root)),
                    "source_pbf_sha256": "a" * 64, "extract_sha256": "b" * 64}, {}),
                (project_director.OSM_NATIONAL_PUBLISHED_RECOVERY_ID, "BLOCKED", {
                    "resumable_national_osm": True, "national_osm_published_recovery": True}, {}),
                (f"{project_director.OSM_NATIONAL_PUBLISHED_RECOVERY_ID}_RETRY_01", "DONE", {
                    "national_osm_published_recovery": True}, {"status": "PASS_PENDING_INDEPENDENT_SUPERVISOR"}),
                (project_director.OSM_NATIONAL_SUPERVISOR_ID, "DONE", {
                    "supervises_task": f"{project_director.OSM_NATIONAL_PUBLISHED_RECOVERY_ID}_RETRY_01"}, {
                        "status": "PASS",
                        "target_task": f"{project_director.OSM_NATIONAL_PUBLISHED_RECOVERY_ID}_RETRY_01"}),
            )
            for task_id, status, budget, result in tasks:
                state_store.add_task({"id": task_id, "stage": "F4", "depends_on": [],
                    "hypothesis": "fixture", "evidence": [], "agent": "osm-national-conversion",
                    "budget": budget, "deliverables": [], "tests": [], "next_action": "continue",
                    "status": status, "result_json": result}, db_path=state_db)
                if result:
                    conn = sqlite3.connect(state_db)
                    try:
                        conn.execute("UPDATE tasks SET result_json=? WHERE id=?",
                            (json.dumps(result), task_id))
                        conn.commit()
                    finally:
                        conn.close()
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director, "SOURCE_PBF", source), \
                 mock.patch.object(project_director, "WORK_ROOT", output_dir.parents[1]), \
                  mock.patch.object(project_director, "reconcile_national_osm_continuations",
                      return_value={"complete": True, "published_proof": {"status": "COMPLETE"},
                          "superseded_task_ids": []}), \
                 mock.patch.object(resumable_national, "_published_database_result", return_value={"status": "PASS"}), \
                 mock.patch.object(project_director, "_registered_task") as register, \
                 mock.patch.object(project_director.manager, "_event"):
                result = project_director.seed_next_national_osm_task()
            self.assertFalse(result["created"])
            self.assertIn("already passed independent Supervisor", result["reason"])
            register.assert_not_called()

    def test_national_osm_supervisor_has_time_for_independent_large_database_readback(self) -> None:
        with mock.patch.object(project_director, "_registered_task", return_value=True) as register:
            self.assertTrue(project_director._register_supervisor(
                project_director.OSM_NATIONAL_SUPERVISOR_ID, project_director.OSM_NATIONAL_TASK_ID))
        self.assertEqual(register.call_args.args[7], 3600)

    def test_timed_out_national_build_resumes_once_from_source_bound_complete_gzip(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp_dir:
            root = Path(temp_dir)
            state_db = root / "state.sqlite"
            source = root / "ukraine-latest.osm.pbf"
            source.write_bytes(b"immutable pbf fixture")
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            work_root = root / "osm_pipeline"
            output = work_root / "ukraine_national" / f"ukraine-2026-09-08-{source_sha[:12]}"
            output.mkdir(parents=True)
            extract = output / "ukraine.osm.gz"
            with gzip.open(extract, "wb") as stream:
                stream.write(b'<?xml version="1.0"?><osm version="0.6"><node id="1" lat="47.9" lon="33.4"/></osm>')
            progress = {"source_pbf_sha256": source_sha, "extraction": {
                "source_pbf": str(source), "extract_xml_gz": str(extract), "whole_source": True,
                "nodes_in_bbox": 1, "nodes_written": 1, "selected_ways": 1}}
            (output / "progress.json").write_text(json.dumps(progress), encoding="utf-8")
            state_store.add_task({"id": project_director.OSM_NATIONAL_TASK_ID, "stage": "F4",
                "depends_on": [], "hypothesis": "resume verified national map import", "evidence": [],
                "agent": "osm-national-conversion", "budget": {"timeout_s": 3600,
                    "ukraine_national_osm": True}, "deliverables": [], "tests": [],
                "next_action": "resume", "status": "BLOCKED", "retry_limit": 1}, db_path=state_db)
            conn = sqlite3.connect(state_db)
            try:
                conn.execute("UPDATE tasks SET attempts=1,result_json=? WHERE id=?",
                    (json.dumps({"error": "RuntimeError: задача перевищила ліміт 3600 секунд"}),
                     project_director.OSM_NATIONAL_TASK_ID))
                conn.commit()
            finally:
                conn.close()
            (root / "reports").mkdir()
            with mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director, "SOURCE_PBF", source), \
                 mock.patch.object(project_director, "WORK_ROOT", work_root), \
                 mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director.manager, "_artifact", return_value={"sha256": "fixture"}), \
                 mock.patch.object(project_director.manager, "_event"), \
                 mock.patch.object(state_store, "_event"):
                result = project_director._resume_national_osm_task_from_checkpoint()
                second = project_director._resume_national_osm_task_from_checkpoint()
            self.assertTrue(result["requeued"], result)
            self.assertFalse(second["requeued"])
            conn = sqlite3.connect(state_db)
            try:
                row = conn.execute("SELECT status,attempts,retry_limit,budget_json FROM tasks WHERE id=?",
                    (project_director.OSM_NATIONAL_TASK_ID,)).fetchone()
            finally:
                conn.close()
            budget = json.loads(row[3])
            self.assertEqual(row[:3], ("PENDING", 0, 1))
            self.assertEqual(budget["timeout_s"], 900)
            self.assertTrue(budget["verified_extract_resume_used"])
            self.assertTrue(budget["resumable_national_osm"])
            self.assertRegex(budget["source_pbf_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(budget["extract_sha256"], r"^[0-9a-f]{64}$")

    def test_component_scheduler_advances_through_unique_inventory_backed_sources(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp_dir:
            root = Path(temp_dir)
            source_root = root / "media"
            executable = "SW/LK841/HU_HARDWARE_LOC_0000000001/HU_MMIDIS_LOC_0130170000/WINDOWS/MMIDIS.EXE"
            library = "SW/LK841/HU_HARDWARE_LOC_0000000001/HU_TMC_LOC_0000100001/TMCUPDATE01.DLL"
            excluded = "SW/LK841/HU_HARDWARE_LOC_0000000001/HU_MMIDIS_LOC_0130170000/WINDOWS/NAVIMAIN.EXE"
            ledger = root / "EVIDENCE_LEDGER.sqlite"
            conn = sqlite3.connect(ledger)
            conn.execute("CREATE TABLE artifacts(source_path TEXT,sha256 TEXT,size_bytes INTEGER,extension TEXT,source_group TEXT)")
            rows = []
            for rel, ext, data in ((executable, ".EXE", b"MZ nav"), (library, ".DLL", b"MZ tmc"),
                                   (excluded, ".EXE", b"MZ known survey")):
                path = source_root.joinpath(*Path(rel).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                import hashlib
                rows.append((rel.replace("/", "\\"), hashlib.sha256(data).hexdigest(), len(data), ext, "SW"))
            conn.executemany("INSERT INTO artifacts VALUES(?,?,?,?,?)", rows)
            conn.commit()
            conn.close()
            state_db = root / "state.sqlite"
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director.coordinator_runtime, "SOURCE_ROOT", source_root), \
                 mock.patch.object(project_director.manager, "_event"):
                first = project_director.seed_next_component_survey_task()
                second = project_director.seed_next_component_survey_task()
                third = project_director.seed_next_component_survey_task()
            self.assertTrue(first["created"])
            self.assertTrue(first["source_path"].endswith("MMIDIS.EXE"))
            self.assertTrue(second["created"])
            self.assertNotEqual(first["task_id"], second["task_id"])
            self.assertTrue(second["source_path"].endswith("TMCUPDATE01.DLL"))
            self.assertFalse(third["created"])
            self.assertIn("All 2", third["reason"])

    def test_component_survey_verifies_hash_and_registers_qwen_supervisor(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp_dir:
            root = Path(temp_dir)
            source_root = root / "media"
            relative = "SW/SW/AR2MATE.ABS"
            source = source_root.joinpath(*Path(relative).parts)
            source.parent.mkdir(parents=True)
            contents = b"MZ\x90\x00\x03\x00NCDR synthetic executable header"
            source.write_bytes(contents)
            import hashlib
            digest = hashlib.sha256(contents).hexdigest()
            ledger = root / "EVIDENCE_LEDGER.sqlite"
            conn = sqlite3.connect(ledger)
            conn.execute("CREATE TABLE artifacts(source_path TEXT,sha256 TEXT,size_bytes INTEGER,extension TEXT,source_group TEXT)")
            conn.execute("INSERT INTO artifacts VALUES(?,?,?,?,?)",
                         (relative.replace("/", "\\"), digest, len(contents), ".ABS", "SW"))
            conn.commit()
            conn.close()
            state_db = root / "state.sqlite"
            def task_from_state(task_id: str) -> dict:
                with closing(sqlite3.connect(state_db)) as connection:
                    connection.row_factory = sqlite3.Row
                    row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None:
                    raise KeyError(task_id)
                item = dict(row)
                item["budget"] = json.loads(item["budget_json"])
                item["depends_on"] = json.loads(item["depends_on_json"])
                return item
            task_id = "AUTO_SW_COMPONENT_SCAN_TEST01"
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director.coordinator_runtime, "SOURCE_ROOT", source_root), \
                 mock.patch.object(project_director.manager, "STATE_DB", state_db), \
                 mock.patch.object(project_director.manager, "_task", side_effect=task_from_state), \
                 mock.patch.object(project_director.manager, "_artifact",
                                   return_value={"path": f"work/{task_id}.json"}):
                task_created = project_director._registered_task(task_id, "F2", None,
                    "Read-only component survey", "ncdx-component-survey", "unused.json",
                    ["hash unchanged"], 60, 10,
                    {"component_scan": True, "source_path": relative, "sha256": digest,
                     "size_bytes": len(contents), "extension": ".ABS"})
                self.assertTrue(task_created)
                result = project_director.execute_sw_component_survey(project_director.manager._task(task_id))
                independent = project_director._verify_sw_component_survey_target(
                    task_id, project_director.manager._task(task_id), result)
            self.assertEqual(result["status"], "PASS")
            self.assertTrue(result["verified"]["original_hash_unchanged"])
            self.assertTrue(result["verified"]["manifest_hash_match"])
            self.assertTrue(independent["fresh_manifest_bound_readback"])
            self.assertEqual(result["source_write_count"], 0)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
            self.assertTrue(Path(result["artifact"]["path"]).name.startswith(task_id))
            conn = sqlite3.connect(state_db)
            try:
                supervisor = conn.execute("SELECT status,agent FROM tasks WHERE id=?",
                    ("AUTO_SUPERVISOR_" + task_id,)).fetchone()
            finally:
                conn.close()
            self.assertEqual(supervisor, ("PENDING", "ollama-research-supervisor"))

    def test_local_component_director_queues_one_unseen_manifest_candidate(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp_dir:
            root = Path(temp_dir)
            source_root = root / "media"
            relative = "SW/SW/AR2MATE.ABS"
            source = source_root.joinpath(*Path(relative).parts)
            source.parent.mkdir(parents=True)
            contents = b"ABS test input\x00" * 64
            source.write_bytes(contents)
            import hashlib
            digest = hashlib.sha256(contents).hexdigest()
            ledger = root / "EVIDENCE_LEDGER.sqlite"
            conn = sqlite3.connect(ledger)
            conn.execute("CREATE TABLE artifacts(source_path TEXT,sha256 TEXT,size_bytes INTEGER,extension TEXT,source_group TEXT)")
            conn.execute("INSERT INTO artifacts VALUES(?,?,?,?,?)",
                         (relative.replace("/", "\\"), digest, len(contents), ".ABS", "SW"))
            conn.commit()
            conn.close()
            state_db = root / "state.sqlite"
            def task_from_state(task_id: str) -> dict:
                with closing(sqlite3.connect(state_db)) as connection:
                    connection.row_factory = sqlite3.Row
                    row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None:
                    raise KeyError(task_id)
                item = dict(row)
                item["budget"] = json.loads(item["budget_json"])
                item["depends_on"] = json.loads(item["depends_on_json"])
                return item
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director.coordinator_runtime, "SOURCE_ROOT", source_root), \
                 mock.patch.object(project_director.manager, "STATE_DB", state_db), \
                 mock.patch.object(project_director.manager, "_task", side_effect=task_from_state), \
                 mock.patch.object(project_director.manager, "_artifact",
                                   return_value={"path": "reports/director.json"}), \
                 mock.patch.object(project_director.manager, "_event"), \
                 mock.patch.object(project_director, "_director_context", return_value="verified state"), \
                 mock.patch.object(project_director.project_scope, "global_goal", return_value="NCDR map research"), \
                 mock.patch.object(project_director.project_scope, "load_scope", return_value={"active_tracks": [], "excluded_tracks": []}):
                plan = project_director.seed_next_component_survey_director_task()
                self.assertTrue(plan["created"])
                director = project_director.manager._task(plan["task_id"])
                selected_id = director["budget"]["candidates"][0]["candidate_id"]
                with mock.patch.object(project_director.coordinator_runtime, "_available_models",
                                       return_value=["qwen3.5:9b"]), \
                     mock.patch.object(project_director.coordinator_runtime, "_choose_model",
                                       return_value="qwen3.5:9b"), \
                     mock.patch.object(project_director.coordinator_runtime, "_call_model",
                                       return_value=("qwen3.5:9b", "{}", {
                                           "candidate_id": selected_id, "reason": "manifest-backed input",
                                           "requires_hardware": False, "writes_original_media": False})):
                    result = project_director.execute_component_survey_director(plan["task_id"])
                queued = project_director.manager._task(selected_id)
                next_plan = project_director.seed_next_component_survey_director_task()
            self.assertEqual(result["selection_source"], "Qwen3.5")
            self.assertEqual(queued["agent"], "ncdx-component-survey")
            self.assertEqual(queued["depends_on"], [plan["task_id"]])
            self.assertFalse(next_plan["created"])
            self.assertIn("No manifest-backed SW binary", next_plan["reason"])

    def test_local_director_chains_manifest_pe_probe_to_independent_verifier(self) -> None:
        from tests.unit.test_ncdx_binary_headers import _synthetic_pe
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp_dir:
            root = Path(temp_dir)
            source_root = root / "media"
            relative = "SW/SW/NAVUPDATE.DLL"
            source = source_root.joinpath(*Path(relative).parts)
            source.parent.mkdir(parents=True)
            contents = _synthetic_pe()
            source.write_bytes(contents)
            digest = hashlib.sha256(contents).hexdigest()
            ledger = root / "EVIDENCE_LEDGER.sqlite"
            conn = sqlite3.connect(ledger)
            conn.execute("CREATE TABLE artifacts(source_path TEXT,sha256 TEXT,size_bytes INTEGER,extension TEXT,source_group TEXT)")
            conn.execute("INSERT INTO artifacts VALUES(?,?,?,?,?)",
                         (relative.replace("/", "\\"), digest, len(contents), ".DLL", "SW"))
            conn.commit()
            conn.close()
            state_db = root / "state.sqlite"
            def task_from_state(task_id: str) -> dict:
                with closing(sqlite3.connect(state_db)) as connection:
                    connection.row_factory = sqlite3.Row
                    row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                if row is None:
                    raise KeyError(task_id)
                item = dict(row)
                item["budget"] = json.loads(item["budget_json"])
                item["depends_on"] = json.loads(item["depends_on_json"])
                return item
            survey_id = project_director._component_scan_task_id(relative)
            survey_result = {"status": "PASS", "source_path": relative, "source_sha256": digest,
                "manifest_sha256": digest, "observed_signatures_and_offsets": {"MZ": 0, "PE": 0x80},
                "verified": {"original_hash_unchanged": True}}
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director.coordinator_runtime, "SOURCE_ROOT", source_root), \
                 mock.patch.object(project_director.manager, "STATE_DB", state_db), \
                 mock.patch.object(project_director.manager, "_task", side_effect=task_from_state), \
                 mock.patch.object(project_director.manager, "_artifact",
                                   return_value={"path": "reports/pe_probe.json"}), \
                 mock.patch.object(project_director.manager, "_event"), \
                 mock.patch.object(project_director, "_director_context", return_value="verified state"), \
                 mock.patch.object(project_director.project_scope, "global_goal", return_value="NCDR map research"), \
                 mock.patch.object(project_director.project_scope, "load_scope", return_value={"active_tracks": [], "excluded_tracks": []}):
                self.assertTrue(project_director._registered_task(survey_id, "F2", None,
                    "Prior bounded signature survey", "ncdx-component-survey", "survey.json",
                    ["source hash unchanged"], 60, 24,
                    {"component_scan": True, "source_path": relative, "sha256": digest,
                     "size_bytes": len(contents), "extension": ".DLL"}))
                with closing(sqlite3.connect(state_db)) as connection:
                    connection.execute("UPDATE tasks SET status='DONE',result_json=? WHERE id=?",
                        (json.dumps(survey_result), survey_id))
                    connection.commit()
                plan = project_director.seed_next_component_survey_director_task()
                self.assertTrue(plan["created"])
                director = task_from_state(plan["task_id"])
                candidates = director["budget"]["candidates"]
                self.assertEqual(candidates[0]["experiment"], "pe_coff_header_parse_v1")
                selected_id = candidates[0]["candidate_id"]
                with mock.patch.object(project_director.coordinator_runtime, "_available_models",
                                       return_value=["qwen3.5:9b"]), \
                     mock.patch.object(project_director.coordinator_runtime, "_choose_model",
                                       return_value="qwen3.5:9b"), \
                     mock.patch.object(project_director.coordinator_runtime, "_call_model",
                                       return_value=("qwen3.5:9b", "{}", {
                                           "candidate_id": selected_id, "reason": "prior MZ/PE evidence",
                                           "requires_hardware": False, "writes_original_media": False})):
                    director_result = project_director.execute_component_survey_director(plan["task_id"])
                probe_task = task_from_state(selected_id)
                worker_result = project_director.execute_ncdx_pe_header_probe(selected_id)
                proof = project_director._verify_ncdx_pe_header_target(
                    selected_id, probe_task, worker_result)
            self.assertEqual(director_result["selection_source"], "Qwen3.5")
            self.assertEqual(probe_task["agent"], "ncdx-pe-header-probe")
            self.assertEqual(worker_result["header_observation"]["architecture"], "ARM or Thumb")
            self.assertTrue(proof["fresh_manifest_bound_readback"])
            self.assertEqual(proof["machine_code"], 0x01C2)

    def test_data_profile_director_chooses_allowlisted_family_and_chains_verified_work(self) -> None:
        import hashlib
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp_dir:
            root = Path(temp_dir)
            source_root = root / "media"
            regions = (("SW", Path("SW") / "DB", "EUZ"),
                       ("Italy", Path("Italy") / "DB", "IZ"),
                       ("Scandinavia", Path("Scandinavia") / "DB", "SCZ"))
            data = [bytes((index * multiplier + seed) % 256 for index in range(90_000))
                    for seed, multiplier in ((1, 3), (2, 5), (3, 7))]
            ledger = root / "EVIDENCE_LEDGER.sqlite"
            conn = sqlite3.connect(ledger)
            conn.execute("CREATE TABLE artifacts(source_path TEXT,sha256 TEXT,size_bytes INTEGER,extension TEXT,source_group TEXT)")
            for (label, relative, prefix), content in zip(regions, data):
                file_prefix = {"EUZ": "EU", "IZ": "I", "SCZ": "SC"}[prefix]
                source = source_root / relative / f"{file_prefix}.RD"
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(content)
                conn.execute("INSERT INTO artifacts VALUES(?,?,?,?,?)", (
                    source.relative_to(source_root).as_posix().replace("/", "\\"),
                    hashlib.sha256(content).hexdigest(), len(content), ".RD", label))
            conn.commit()
            conn.close()
            state_db = root / "state.sqlite"
            legacy_plan_id = "AUTO_DIRECTOR_NCDX_DATA_" + hashlib.sha256(
                b"initial-ncdx-profile-plan").hexdigest()[:12]
            self.assertTrue(state_store.add_task({"id": legacy_plan_id, "stage": "F2",
                "depends_on": [], "hypothesis": "previous bounded NCDx profile plan",
                "evidence": [], "agent": "ollama-data-family-director", "budget": {},
                "deliverables": [], "tests": [], "next_action": "preserve prior plan",
                "retry_limit": 1, "priority": 20}, db_path=state_db))
            with closing(sqlite3.connect(state_db)) as conn:
                conn.execute("UPDATE tasks SET status='DONE',verdict='PASS' WHERE id=?", (legacy_plan_id,))
                conn.commit()
            def temp_task(task_id):
                temp_conn = sqlite3.connect(state_db)
                temp_conn.row_factory = sqlite3.Row
                try:
                    row = temp_conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
                    if row is None:
                        raise KeyError(task_id)
                    value = dict(row)
                    for key in ("depends_on_json", "evidence_json", "budget_json", "deliverables_json", "objective_tests_json"):
                        value[key.removesuffix("_json")] = json.loads(value.pop(key) or "[]")
                    return value
                finally:
                    temp_conn.close()
            def fake_director_call(task_id, role, prompt, *, attempt, fixed_model):
                self.assertEqual(role, "project-director")
                self.assertEqual(attempt, 1)
                goals = project_director._data_profile_candidates(include_legacy_modes=True)
                chosen = next(row for row in goals if row["mode"] == "CROSS_REGION_WINDOW_COMPARE")
                parsed = {"goal_id": chosen["goal_id"]}
                return fixed_model, json.dumps(parsed), parsed
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "STATE_DB", state_db), \
                 mock.patch.object(project_director, "SOURCE_PBF", root / "missing.osm.pbf"), \
                 mock.patch.object(project_director, "DIRECTOR_BENCHMARK", root / "director-benchmark.json"), \
                 mock.patch.object(project_director.coordinator_runtime, "SOURCE_ROOT", source_root), \
                 mock.patch.object(project_director.coordinator_runtime, "REGIONS", regions), \
                 mock.patch.object(project_director.coordinator_runtime, "available_target_suffixes", return_value=("RD",)), \
                 mock.patch.object(project_director.coordinator_runtime, "_available_models", return_value={"qwen3.5:9b"}), \
                 mock.patch.object(project_director.coordinator_runtime, "_call_model", side_effect=fake_director_call), \
                 mock.patch.object(project_director.manager, "STATE_DB", state_db), \
                 mock.patch.object(project_director.manager, "_task", side_effect=temp_task), \
                 mock.patch.object(project_director.manager, "_artifact",
                                   side_effect=lambda _tid, path, _desc, acceptance:
                                   {"path": str(path.relative_to(root)), "acceptance": acceptance}), \
                 mock.patch.object(project_director.manager, "_event"):
                plan = project_director.seed_next_data_family_director_task(include_legacy_modes=True)
                self.assertTrue(plan["created"])
                self.assertNotEqual(plan["task_id"], legacy_plan_id)
                director = project_director.execute_data_family_director(plan["task_id"])
                self.assertEqual(director["selection_source"], "Ollama", director)
                self.assertTrue(director["safe_schema_validated"])
                self.assertEqual(director["selected_goal_id"].split("_")[4], "CROSS")
                profile_task = project_director.manager._task(director["next_task_id"])
                result = project_director.execute_data_family_profile(profile_task)
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["profile_mode"], "CROSS_REGION_WINDOW_COMPARE")
                self.assertEqual(result["verified"]["source_count"], 3)
                self.assertEqual(result["verified"]["source_write_count"], 0)
                self.assertTrue(result["verified"]["source_stat_unchanged_during_read"])
                self.assertEqual(len(result["cross_region_comparisons"]), 15)
                self.assertTrue(all(row["compared_bytes"] == 4096
                                    for row in result["cross_region_comparisons"]))
                self.assertNotIn("_comparison_windows", result["observations"][0])
                supervisor_id = "AUTO_SUPERVISOR_" + director["next_task_id"]
                conn = sqlite3.connect(state_db)
                try:
                    supervisor = conn.execute("SELECT status,agent,depends_on_json FROM tasks WHERE id=?",
                                              (supervisor_id,)).fetchone()
                finally:
                    conn.close()
                self.assertEqual(supervisor[0:2], ("PENDING", "ollama-research-supervisor"))
                self.assertEqual(json.loads(supervisor[2]), [director["next_task_id"]])
                self.assertTrue((root / "work" / "autonomous_manager" / "ncdx" / "data_family_profiles" /
                                 f"{director['next_task_id']}.json").is_file())
                for mode, expected_comparisons in (("LAG_CORRELATION_SCAN", 135),
                                                   ("BYTE_TRANSITION_PROFILE", 15),
                                                   ("DEFLATE_COMPRESSIBILITY_PROFILE", 9),
                                                   ("EXACT_BLOCK_ANCHOR_SCAN", 4)):
                    candidate = next(row for row in project_director._data_profile_candidates(include_legacy_modes=True)
                                     if row["mode"] == mode)
                    self.assertTrue(project_director._register_data_profile_task(
                        candidate, dependency=director["task_id"]))
                    profile = project_director.execute_data_family_profile(
                        project_director.manager._task(candidate["goal_id"]))
                    self.assertEqual(profile["status"], "PASS")
                    self.assertEqual(profile["profile_mode"], mode)
                    self.assertEqual(profile["verified"]["source_write_count"], 0)
                    self.assertEqual(len(profile["cross_region_comparisons"]), expected_comparisons)
                    self.assertTrue(all(row["source_stat_unchanged_during_read"]
                                        for row in profile["observations"]))
                    if mode == "DEFLATE_COMPRESSIBILITY_PROFILE":
                        self.assertEqual(profile["verified"]["read_limit_bytes_per_source"], 5 * 64 * 1024)
                        self.assertFalse(profile["observations"][0]["raw_sample_bytes_retained"])
                        fresh = project_director._verify_deflate_profile_target(
                            candidate["goal_id"], project_director.manager._task(candidate["goal_id"]), profile)
                        self.assertTrue(fresh["all_window_hashes_and_zlib_ratios_match"])
                        self.assertEqual(fresh["sample_count"],
                            sum(len(row["samples"]) for row in profile["observations"]))
                    if mode == "EXACT_BLOCK_ANCHOR_SCAN":
                        self.assertEqual(profile["verified"]["read_limit_bytes_per_source"], 4 * 1024 * 1024)
                        self.assertTrue(all("_block_offsets" not in row for row in profile["observations"]))
                        fresh = project_director._verify_exact_block_anchor_profile_target(
                            candidate["goal_id"], project_director.manager._task(candidate["goal_id"]), profile)
                        self.assertTrue(fresh["regional_comparisons_match"])
                        self.assertEqual(fresh["full_blocks_rescanned"], 63)

    def test_small_window_lag_comparison_reports_insufficient_bytes_without_failing(self) -> None:
        short = project_director._lag_match_stats(b"\x01")
        self.assertTrue(all(row["match_ratio"] is None for row in short))
        self.assertIsNone(project_director._absolute_ratio_delta(None, None))
        self.assertIsNone(project_director._absolute_ratio_delta(0.25, None))
        repeated = project_director._lag_match_stats(bytes((0, 1, 2, 3) * 1024))
        lag_four = next(row for row in repeated if row["lag_bytes"] == 4)
        self.assertEqual(lag_four["match_ratio"], 1.0)
        transitions = project_director._byte_transition_profile(b"ABABAB")
        self.assertEqual(transitions[0], {"pair_hex": "4142", "count": 3, "ratio": 0.6})

    def test_director_plan_creates_only_fixed_dependent_osm_handler(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp_dir:
            root = Path(temp_dir)
            db = root / "state.sqlite"
            output = root / "reports" / "plan.json"
            criteria = project_director._acceptance_criteria("OSM_REAL_CONVERSION")
            parsed = {"goal_id": "OSM_REAL_CONVERSION", "depends_on": [],
                "acceptance_criteria": criteria, "requires_hardware": False,
                "writes_original_media": False, "reason": "Local source and checks are available."}
            with mock.patch.object(project_director, "STATE_DB", db), \
                 mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "DIRECTOR_BENCHMARK", root / "benchmark.json"), \
                 mock.patch.object(project_director, "benchmark_directors", return_value={"selected_model": "qwen3.5:9b"}), \
                 mock.patch.object(project_director, "_director_context", return_value={"queue_counts": {"DONE": 1}}), \
                 mock.patch.object(project_director.coordinator_runtime, "_call_model",
                                   return_value=("qwen3.5:9b", json.dumps(parsed), parsed)), \
                 mock.patch.object(project_director.manager, "_artifact", return_value={"path": "reports/plan.json"}):
                result = project_director.execute_director(project_director.PLAN_ID["OSM_REAL_CONVERSION"])
            self.assertEqual(result["created_task_id"], project_director.PLAN_TASKS["OSM_REAL_CONVERSION"])
            self.assertEqual(result["schema_validation"]["score"], result["schema_validation"]["maximum"])
            conn = sqlite3.connect(db)
            try:
                row = conn.execute("SELECT agent,depends_on_json FROM tasks WHERE id=?",
                    (project_director.PLAN_TASKS["OSM_REAL_CONVERSION"],)).fetchone()
            finally:
                conn.close()
            self.assertEqual(row[0], "osm-real-conversion")
            self.assertEqual(json.loads(row[1]), [project_director.PLAN_ID["OSM_REAL_CONVERSION"]])

    def test_model_benchmark_keeps_director_pinned_to_qwen_9b(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp_dir:
            report_path = Path(temp_dir) / "benchmark.json"
            calls: list[str] = []
            def fake_call(_task, _role, _prompt, *, attempt, fixed_model):
                calls.append(fixed_model)
                goal = "OSM_REAL_CONVERSION" if attempt in {1, 3} else "NCDX_NK_SURVEY"
                dependency = None if goal == "OSM_REAL_CONVERSION" else "AUTO_SUPERVISOR_OSM_READBACK_01"
                parsed = {"goal_id": goal, "depends_on": [dependency] if dependency else [],
                    "acceptance_criteria": project_director._acceptance_criteria(goal),
                    "requires_hardware": False, "writes_original_media": False, "reason": "Use a local testable goal."}
                if "Qwythos" in fixed_model:
                    parsed["reason"] = ""
                return fixed_model, json.dumps(parsed), parsed
            with mock.patch.object(project_director, "DIRECTOR_BENCHMARK", report_path), \
                 mock.patch.object(project_director.coordinator_runtime, "_available_models",
                                   return_value=set(project_director.DIRECTOR_MODELS)), \
                 mock.patch.object(project_director.coordinator_runtime, "_call_model", side_effect=fake_call), \
                 mock.patch.object(project_director.manager, "_artifact", return_value={"path": "benchmark.json"}):
                result = project_director.benchmark_directors("benchmark-test")
            self.assertEqual(result["selected_model"], project_director.DIRECTOR_MODELS[0])
            self.assertEqual(calls, ["qwen3.5:9b"] * 2)
            self.assertTrue(report_path.is_file())

    def test_visual_progress_counts_formal_passed_criteria_and_separates_hardware(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp_dir:
            root = Path(temp_dir)
            reports = root / "reports"
            reports.mkdir()
            all_passed = {name: {"pass": True} for name in (
                "map_database_integrity", "versioned_osm_provenance", "city_search_and_connected_route",
                "map_gui_visible", "poi_editor_gui_visible", "poi_persistence", "autonomous_coordinator_e2e")}
            (reports / "product_acceptance.json").write_text(json.dumps({"checks": all_passed}), encoding="utf-8")
            live = {name: {"pass": True} for name in (
                "gui_window_visible", "map_rendered", "ukrainian_street_search", "connected_city_route",
                "custom_poi_saved", "poi_persistence_reopen")}
            (reports / "virtual_cid_live_acceptance.json").write_text(json.dumps({"checks": live}), encoding="utf-8")
            writer = {"status": "PASS_COPY_ONLY", "source_write_count": 0,
                "original_media_protection": "PASS",
                "regional_roundtrips": [{"no_op": {"no_op_roundtrip_pass": True}} for _ in range(3)],
                "controlled_header_change": {"source_sha256_before": "same", "source_sha256_after": "same",
                    "controlled_change_pass": True}}
            (reports / "autonomous_writer_roundtrip.json").write_text(json.dumps(writer), encoding="utf-8")
            gate_criteria = {
                "F0": {"hash_manifest": 2, "previous_results_review": 2, "local_model_check": 2,
                       "portable_entrypoint": 2, "runnable_healthcheck": 2},
                "F1": {"target_device_identity": 4, "disc_acceptance_evidence": 4,
                       "format_matrix": 2, "image_layout_evidence": 2},
                "F2": {"header_reader": 3, "independent_disc_golden_tests": 3, "unknowns_documented": 2,
                       "corruption_detection": 2, "semantic_records": 6},
                "F3": {"no_op_roundtrip": 3, "controlled_change": 4, "independent_readback": 5},
                "F4": {"dated_osm_source": 2, "road_graph_tests": 4, "target_conversion": 6},
                "F5": {"encoding_support_proof": 3, "ukrainian_names_test": 2},
                "F6": {"poi_editor_tests": 7}, "F7": {"simulator": 2, "final_image_interpreter": 5},
                "F8": {"target_disc_layout": 3, "independent_image_verifier": 3},
                "F9": {"software_acceptance": 8, "hardware_acceptance": 5},
            }
            gate_proofs = {
                "F0": {key: True for key in gate_criteria["F0"]},
                "F2": {"header_reader": True, "independent_disc_golden_tests": True,
                       "unknowns_documented": True, "corruption_detection": True, "semantic_records": False},
            }
            gates = [{"stage": stage, "criteria_json": json.dumps(criteria),
                      "proof_json": json.dumps({"criteria_pass": gate_proofs.get(stage, {})})}
                     for stage, criteria in gate_criteria.items()]
            result = verified_progress({"project": {"stage_gates": gates}}, root)
            self.assertEqual((result["earned"], result["total"], result["percent"]), (23, 79, 29))
            self.assertEqual(result["hardware_unverified_points"], 17)
            self.assertEqual(result["components"]["OSM data preparation"]["percent"], 73)
            self.assertEqual(result["components"]["NCDx reverse engineering"]["percent"], 57)
            self.assertEqual(result["components"]["NCDx reader/writer"]["percent"], 58)
            self.assertNotIn("Virtual CID", result["components"])
            self.assertNotIn("POI Editor", result["components"])

            # F3 independent readback receives credit only from a separate parser proof.
            writer["independent_readback"] = {"status": "PASS", "regional_source_count": 3,
                "no_op_copies_match_manifest_sources": True, "controlled_change_field_limited": True,
                "separate_parser": True, "original_media_write_count": 0}
            (reports / "autonomous_writer_roundtrip.json").write_text(json.dumps(writer), encoding="utf-8")
            independently_verified = verified_progress({"project": {"stage_gates": gates}}, root)
            self.assertEqual(independently_verified["components"]["NCDx reader/writer"]["percent"], 100)
            self.assertEqual(independently_verified["gates"]["F3"], {"earned": 12, "total": 12})

            # Historic inventory/model/statistical gate completions never change product readiness.
            altered = [dict(gate) for gate in gates]
            for gate in altered:
                if gate["stage"] == "F0":
                    gate["proof_json"] = json.dumps({"criteria_pass": {key: False for key in gate_criteria["F0"]}})
            unchanged = verified_progress({"project": {"stage_gates": altered}}, root)
            self.assertEqual((independently_verified["earned"], independently_verified["total"]),
                             (unchanged["earned"], unchanged["total"]))

    def test_codex_daily_handoff_uses_saved_queue_and_model_evidence(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as folder:
            root = Path(folder)
            database = root / "state.sqlite"
            conn = sqlite3.connect(database)
            conn.executescript("""
                CREATE TABLE tasks(id TEXT, stage TEXT, status TEXT, verdict TEXT, result_json TEXT,
                                   updated_utc TEXT, priority INTEGER, next_action TEXT);
                CREATE TABLE research_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, role TEXT, model TEXT, decision TEXT,
                                           elapsed_ms INTEGER, error TEXT, created_utc TEXT);
                CREATE TABLE autonomy_events(id INTEGER PRIMARY KEY AUTOINCREMENT, created_utc TEXT, event TEXT, severity TEXT, task_id TEXT, detail_json TEXT);
                CREATE TABLE autonomy_artifacts(task_id TEXT, path TEXT, sha256 TEXT, size_bytes INTEGER,
                                                description TEXT, acceptance TEXT, created_utc TEXT);
                CREATE TABLE autonomy_control(singleton INTEGER PRIMARY KEY, desired_state TEXT, worker_pid INTEGER, current_task TEXT,
                                              last_error TEXT, health_json TEXT, updated_utc TEXT);
                INSERT INTO tasks VALUES('AUTO_REAL_OSM','F4','DONE','PASS','{"status":"PASS"}',
                    strftime('%Y-%m-%dT%H:%M:%f+00:00','now'),10,'');
                INSERT INTO research_runs(task_id,role,model,decision,elapsed_ms,error,created_utc) VALUES('AUTO_REAL_OSM','project-director','qwen3.5:9b','RESPONSE_RECEIVED',1200,NULL,
                    strftime('%Y-%m-%dT%H:%M:%f+00:00','now'));
                INSERT INTO autonomy_control VALUES(1,'RUNNING',1234,NULL,'','{}',
                    strftime('%Y-%m-%dT%H:%M:%f+00:00','now'));
            """)
            conn.commit()
            conn.close()
            with mock.patch.object(project_director, "PROJECT_ROOT", root), \
                 mock.patch.object(project_director, "STATE_DB", database), \
                 mock.patch.object(project_director.manager, "queue_diagnosis", return_value={"status": "NO_TASKS", "message": "all bounded targets used"}), \
                 mock.patch.object(project_director.manager, "_event"):
                result = project_director.write_codex_daily_report(trigger="unit_test")
            md = root / result["markdown"]
            payload = json.loads((root / result["json"]).read_text(encoding="utf-8"))
            self.assertTrue(md.is_file())
            markdown = md.read_text(encoding="utf-8")
            self.assertIn("Codex daily handoff", markdown)
            self.assertIn("excluded tracks remain archived", markdown)
            self.assertEqual(payload["audience"], "Codex")
            self.assertTrue(payload["active_scope"]["director_policy"]["never_reactivate_excluded_tracks_from_history"])
            self.assertTrue(payload["active_scope"]["reporting_policy"]["exclude_archived_tracks_from_readiness_and_active_reports"])
            self.assertEqual(payload["local_model_runs_today"][0]["model"], "qwen3.5:9b")
            self.assertEqual(payload["task_updates_today"][0]["id"], "AUTO_REAL_OSM")


if __name__ == "__main__":
    unittest.main()
