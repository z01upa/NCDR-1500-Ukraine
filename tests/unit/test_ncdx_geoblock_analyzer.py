from __future__ import annotations

import ast
from pathlib import Path
import struct
import unittest

from src.readers import ncdx_geoblock_analyzer as analyzer


class NcdxGeoblockAnalyzerContractTests(unittest.TestCase):
    def test_generated_module_is_a_pure_bounded_helper(self):
        source = Path(analyzer.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        allowed_imports = {"__future__", "math", "re", "struct", "typing"}
        forbidden_calls = {"open", "exec", "eval", "compile", "__import__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertTrue(all(alias.name.split(".", 1)[0] in allowed_imports for alias in node.names))
            elif isinstance(node, ast.ImportFrom):
                self.assertIn((node.module or "").split(".", 1)[0], allowed_imports)
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else None
                self.assertNotIn(name, forbidden_calls)

    def test_mp0_and_mg_header_bbox_is_decoded_from_observed_fixed_fields(self):
        header = bytearray(110)
        header[:13] = b"(*$SIEMENS&^)"
        struct.pack_into("<H", header, 84, 7)
        struct.pack_into("<I", header, 86, 2956)
        struct.pack_into("<I", header, 90, 30199076)
        struct.pack_into("<iiii", header, 94, -916181, 3626352, 3020566, 7317051)

        facts = analyzer.parse_geographic_header(bytes(header))

        self.assertEqual(facts["type_id"], 7)
        self.assertEqual(facts["record_count"], 2956)
        self.assertEqual(facts["field_90_u32_uninterpreted"], 30199076)
        self.assertEqual(facts["bbox_i32"], [-916181, 3626352, 3020566, 7317051])
        self.assertEqual(facts["bbox_degrees"], [-9.16181, 36.26352, 30.20566, 73.17051])
        self.assertTrue(facts["bbox_valid"])

    def test_unwrapped_siemens_marker_is_also_accepted(self):
        header = bytearray(110)
        header[:7] = b"SIEMENS"
        struct.pack_into("<iiii", header, 94, -100000, 4000000, 200000, 5000000)
        facts = analyzer.parse_geographic_header(bytes(header))
        self.assertEqual(facts["magic"], "SIEMENS")
        self.assertTrue(facts["bbox_valid"])

    def test_coordinate_sequence_requires_geography_and_records_geometry_metrics(self):
        values = [
            (5000000, 200000), (5000100, 200100),
            (5000200, 200200), (5000300, 200300),
            (5000400, 200400), (5000500, 200500),
        ]
        payload = b"".join(struct.pack("<ii", lat, lon) for lat, lon in values)
        boxes = [
            (190000, 4999900, 200250, 5000250),
            (200251, 5000251, 200600, 5000600),
        ]

        result = analyzer.analyze_payload(
            payload,
            "alignment_0/scale_100000_lat_lon",
            (49.0, 1.0, 51.0, 3.0),
            (30.0, 30.0, 32.0, 32.0),
            boxes,
            max_step_km=5.0,
        )

        self.assertEqual(result["coordinate_candidate_pairs_in_region"], 6)
        self.assertEqual(result["coordinate_pairs_in_displaced_control"], 0)
        self.assertEqual(result["points_inside_cty_city_bounding_boxes"], 6)
        self.assertEqual(result["distinct_cty_city_boxes_hit"], 2)
        self.assertEqual(result["adjacent_pairs_within_5km"], 5)
        self.assertEqual(result["max_continuous_region_candidate_points"], 6)
        self.assertFalse(result["raw_coordinate_values_retained"])

    def test_displaced_control_is_measured_separately(self):
        payload = struct.pack("<ii", 3100000, 3100000)
        result = analyzer.analyze_payload(
            payload,
            "alignment_0/scale_100000_lat_lon",
            (49.0, 1.0, 51.0, 3.0),
            (30.0, 30.0, 32.0, 32.0),
            [],
        )
        self.assertEqual(result["coordinate_candidate_pairs_in_region"], 0)
        self.assertEqual(result["coordinate_pairs_in_displaced_control"], 1)
        self.assertEqual(result["points_inside_cty_city_bounding_boxes"], 0)

    def test_overlapping_city_boxes_are_all_counted_without_retaining_coordinates(self):
        payload = struct.pack("<ii", 5_000_000, 200_000)
        boxes = [
            (190_000, 4_900_000, 210_000, 5_100_000),
            (195_000, 4_950_000, 205_000, 5_050_000),
        ]
        result = analyzer.analyze_payload(
            payload, "alignment_0/scale_100000_lat_lon", (49.0, 1.0, 51.0, 3.0),
            (30.0, 30.0, 32.0, 32.0), boxes,
        )
        self.assertEqual(result["points_inside_cty_city_bounding_boxes"], 1)
        self.assertEqual(result["distinct_cty_city_boxes_hit"], 2)
        self.assertFalse(result["raw_coordinate_values_retained"])
        self.assertFalse(result["road_geometry_decoded"])

    def test_unknown_measurement_and_invalid_header_are_rejected(self):
        with self.assertRaises(ValueError):
            analyzer.analyze_payload(b"\0" * 16, "unknown", (0, 0, 1, 1), (2, 2, 3, 3), [])
        with self.assertRaises(ValueError):
            analyzer.parse_geographic_header(b"not a Siemens header")


if __name__ == "__main__":
    unittest.main()
