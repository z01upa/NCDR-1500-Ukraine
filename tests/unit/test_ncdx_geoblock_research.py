from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

from src.agent import geoblock_research as research, project_director
from src.readers import ncdx_geoblock_analyzer as analyzer


def _candidate(region: str, profile: str, offset: int) -> dict:
    return {
        "profile_task_id": profile,
        "profile_artifact": {"path": "reports/profile.json", "sha256": "b" * 64},
        "region": region,
        "relative_path": "SW/DB/EUZ.MG2" if region == "SW" else
            "OPEL NCDx Scandinavia 2010-2011/DB/SCZ.MG2",
        "source_sha256": "c" * 64,
        "stream_count": 2000,
        "stream_inventory_sha256": "d" * 64,
        "stream_index": 528,
        "source_offset": offset,
        "compressed_bytes": 6337,
        "decompressed_bytes": 10915,
        "decompressed_sha256": "a" * 64,
        "measurement": "alignment_3/scale_1000000_lon_lat",
        "prior_region_pairs": 106,
        "prior_adjacent_pairs": 6,
        "selected_full_payload": True,
    }


class NcdxGeoblockResearchTests(unittest.TestCase):
    def test_pair_builder_requires_same_full_payload_measurement_and_two_regions(self):
        sw = _candidate("SW", "AUTO_NCDX_DATA_MG2_ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS_1234abcd", 1000)
        sc = _candidate("Scandinavia", "AUTO_NCDX_DATA_MG2_ZLIB_DECODED_COORDINATE_CENSUS_5678abcd", 2000)
        pair = research._build_candidate_pairs([sw, sc])
        self.assertEqual(len(pair), 1)
        self.assertEqual(pair[0]["minimum_prior_adjacent_pairs"], 6)
        self.assertEqual(pair[0]["payload_sha256"], "a" * 64)
        self.assertEqual(research._build_candidate_pairs([sw]), [])

        different_measurement = dict(sc, measurement="alignment_0/scale_100000_lat_lon")
        self.assertEqual(research._build_candidate_pairs([sw, different_measurement]), [])
        not_full = dict(sc, selected_full_payload=False)
        self.assertEqual(research._build_candidate_pairs([sw, not_full]), [])

    def test_candidate_id_is_stable_for_source_pair_not_profile_or_stream_offset(self):
        sw = _candidate("SW", "AUTO_NCDX_DATA_MG2_ZLIB_DECODED_COORDINATE_CENSUS_1234abcd", 1000)
        sc = _candidate("Scandinavia", "AUTO_NCDX_DATA_MG2_ZLIB_DECODED_COORDINATE_CENSUS_5678abcd", 2000)
        pair = research._build_candidate_pairs([sw, sc])[0]
        self.assertEqual(pair["candidate_id"], research._candidate_id(pair))
        changed = dict(pair)
        changed["inputs"] = [dict(pair["inputs"][0]), dict(pair["inputs"][1])]
        changed["inputs"][1]["source_offset"] += 8
        self.assertEqual(pair["candidate_id"], research._candidate_id(changed))
        changed["inputs"][1]["source_sha256"] = "e" * 64
        self.assertNotEqual(pair["candidate_id"], research._candidate_id(changed))

    def test_independent_city_box_enumerator_matches_analyzer_for_overlaps(self):
        payload = struct.pack("<ii", 5_000_000, 200_000)
        boxes = [(190_000, 4_900_000, 210_000, 5_100_000),
                 (195_000, 4_950_000, 205_000, 5_050_000)]
        measurement = "alignment_0/scale_100000_lat_lon"
        helper = analyzer.analyze_payload(payload, measurement, (49, 1, 51, 3), (30, 30, 32, 32), boxes)
        independent = research._independent_all_city_box_counts(payload, measurement, "SW", boxes)
        self.assertEqual(helper["points_inside_cty_city_bounding_boxes"], independent["points_inside_cty_city_bounding_boxes"])
        self.assertEqual(helper["distinct_cty_city_boxes_hit"], independent["distinct_cty_city_boxes_hit"])
        self.assertEqual(independent["distinct_cty_city_boxes_hit"], 2)

    def test_handler_registry_requires_all_exact_file_hashes_and_refuses_changes(self):
        temp_root = Path.cwd() / "work" / "geoblock_registry_test"
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as directory:
            root = Path(directory)
            paths = ("src/readers/ncdx_geoblock_analyzer.py", "src/agent/geoblock_research.py",
                     *research.TEST_PATHS)
            hashes = {}
            for index, relative in enumerate(paths):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                data = f"fixture-{index}".encode()
                path.write_bytes(data)
                hashes[relative] = hashlib.sha256(data).hexdigest()
            manifest = root / "evidence/verified_handlers/ncdx_geoblock_research.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"status": "VERIFIED_MANUAL", "handler": research.AGENT_NAME,
                "files": hashes, "verification_method": "independent unit tests"}), encoding="utf-8")
            self.assertTrue(research.tool_registry_status(root, manifest)["allowed"])
            (root / paths[0]).write_text("changed", encoding="utf-8")
            self.assertFalse(research.tool_registry_status(root, manifest)["allowed"])

    def test_project_director_dispatches_and_supervises_the_allowlisted_handler(self):
        expected = {"status": "PASS", "task_id": "AUTO_NCDX_GEOBLOCK_UNIT"}
        with mock.patch.object(research, "execute_task", return_value=expected):
            self.assertEqual(project_director.dispatch("AUTO_NCDX_GEOBLOCK_UNIT", research.AGENT_NAME), expected)
        target = {"id": "AUTO_NCDX_GEOBLOCK_UNIT", "budget": {"ncdx_geoblock_research": True}}
        with mock.patch.object(project_director, "_task_result", return_value={"status": "PASS"}), \
             mock.patch.object(project_director.manager, "_task", return_value=target), \
             mock.patch.object(research, "verify_target", return_value={"fresh_replay": True}) as verify:
            self.assertEqual(project_director._verified_target(target["id"]), {"fresh_replay": True})
            verify.assert_called_once_with(target, {"status": "PASS"})


if __name__ == "__main__":
    unittest.main()
