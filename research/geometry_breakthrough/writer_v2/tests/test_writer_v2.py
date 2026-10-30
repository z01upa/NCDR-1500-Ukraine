from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import uuid
import unittest

HERE = Path(__file__).resolve().parents[1]
PROJECT = HERE.parents[2]
WRITER_V1 = HERE.parent / "writer_v1"
EVIDENCE = HERE / "evidence"
EVIDENCE.mkdir(parents=True, exist_ok=True)
for path in (PROJECT, HERE, WRITER_V1):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from topology_validator import audit_topology  # noqa: E402
from routing_file_audit import audit_routing_files  # noqa: E402
from writer_v2 import TopologyWriteBlocked, preflight_add_edge, write_new_edge  # noqa: E402
from writer import DEFAULT_SOURCE, read_mp0, rebuild_mp0  # noqa: E402


def _load_independent_reader():
    path = HERE.parent / "topology_v2" / "independent_topology_reader.py"
    spec = importlib.util.spec_from_file_location("writer_v2_independent_reader", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import independent reader at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Keep all new run evidence inside writer_v2; don't overwrite existing work.
    module.HERE = EVIDENCE
    return module


class WriterV2TopologyEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_hash = hashlib.sha256(DEFAULT_SOURCE.read_bytes()).hexdigest()
        cls.topology = audit_topology(DEFAULT_SOURCE, write_evidence=True)
        cls.sidecars = audit_routing_files(write_evidence=True)
        cls.independent = _load_independent_reader().validate_independently(DEFAULT_SOURCE)

    def test_all_mp0_blocks_and_section_extents_parse(self) -> None:
        r = self.topology
        self.assertEqual(r["blocks_parsed"], 2956)
        self.assertEqual(r["section_layout_pass_blocks"], 2956)
        self.assertEqual(r["nodes"], 956071)
        self.assertEqual(r["edges"], 1090323)
        self.assertEqual(r["section5_endpoint_indices_out_of_range"], 0)
        self.assertEqual(r["source_sha256_before"], r["source_sha256_after"])

    def test_low_degree_links_and_independent_holdout_agree_on_mismatches(self) -> None:
        low = self.topology["section4_low_nibble_0_to4"]
        self.assertEqual(low["exact_nodes"], 952280)
        self.assertEqual(low["identity_mismatch_nodes"], 511)
        self.assertEqual(sum(low["primary_edge_endpoint_to_node_link_fail_by_degree"].values()), 0)
        external = self.independent
        self.assertEqual(external["blocks_inflated"], 2956)
        self.assertEqual(external["nodes"], 956071)
        self.assertEqual(external["edges"], 1090323)
        self.assertEqual(external["edge_endpoint_out_of_range"], 0)
        self.assertEqual(external["degree_le4_local_adjacency_exact"]["fail"], 511)
        self.assertEqual(external["degree_le4_local_adjacency_exact"]["failures_at_duplicate_coordinates"], 511)

    def test_degree_fourth_slot_is_bounded_but_overflow_is_not_decoded(self) -> None:
        low = self.topology["section4_low_nibble_0_to4"]
        high = self.topology["section4_low_nibble_gt4"]
        self.assertEqual(low["rows_by_degree"]["4"], 33019)
        self.assertEqual(low["exact_node_to_edge_multisets_by_degree"]["4"], 32892)
        self.assertEqual(set(low["real_record_samples_by_degree"]), {"0", "1", "2", "3", "4"})
        fourth = low["real_record_samples_by_degree"]["4"]
        self.assertEqual(len(fourth["record_hex"]), 20)
        self.assertEqual(sorted(fourth["active_candidate_refs"]),
                         sorted(fourth["actual_primary_incident_edge_ids"]))
        self.assertEqual(sum(high["rows_by_low_nibble"].values()), 3280)
        self.assertEqual(high["primary_endpoint_memberships_not_found_in_four_words"], 4174)
        self.assertEqual(set(high["real_record_samples_by_low_nibble"]),
                         {str(value) for value in range(5, 16)})
        self.assertIn("UNRESOLVED", high["overflow_semantics"])

    def test_section5_does_not_claim_direction_or_road_class(self) -> None:
        s5 = self.topology["section5"]
        self.assertEqual(s5["confirmed_bits"]["0x1000"], "selects secondary coordinate table for endpoint A")
        self.assertEqual(s5["confirmed_bits"]["0x2000"], "selects secondary coordinate table for endpoint B")
        self.assertEqual(s5["confirmed_bits"]["0x8000"], "signals a shape span in Section 10")
        self.assertIn("UNKNOWN", s5["road_type_direction_access_semantics"])
        self.assertIn("not accepted as reverse-direction evidence",
                      s5["road_type_direction_access_semantics"])

    def test_rt_and_rl_containers_decode_but_route_relationship_remains_unknown(self) -> None:
        self.assertEqual(self.sidecars["status"], "PASS_CONTAINERS_DECODED_SEMANTICS_UNKNOWN")
        self.assertEqual(self.sidecars["files"]["RT"]["logical_type_id_u16_at_84"], 22)
        self.assertEqual(self.sidecars["files"]["RT"]["logical_count_u32_at_86"], 0)
        self.assertTrue(self.sidecars["files"]["RT"]["all_streams_decoded"])
        self.assertTrue(self.sidecars["files"]["RL"]["all_streams_decoded"])
        self.assertIn("UNPROVEN", self.sidecars["routing_graph_inside_mp0_only"])
        for section in ("7", "8", "9"):
            self.assertEqual(self.topology["sections_7_8_9"][section]["layout_errors"], 0)
        self.assertGreater(self.topology["sections_7_8_9"]["7"]["records_edge_domain_only"], 0)

    def test_writer_v1_noop_roundtrip_is_byte_identical(self) -> None:
        original = DEFAULT_SOURCE.read_bytes()
        image = read_mp0(DEFAULT_SOURCE)
        self.assertEqual(image.block_count, 2956)
        self.assertEqual(rebuild_mp0(image, {}), original)
        self.assertEqual(hashlib.sha256(original).hexdigest(), self.source_hash)

    def test_new_edge_writer_refuses_before_creating_output(self) -> None:
        # Reuse the existing topology_v2 evidence candidate: nearby distinct
        # primary nodes, degree 3, no current local edge between them.
        report = preflight_add_edge(DEFAULT_SOURCE, block=886, node_a=412, node_b=414)
        self.assertEqual(report["status"], "REFUSED_BEFORE_MUTATION")
        self.assertEqual(len(report["candidate"]["node_records"]), 2)
        self.assertEqual(report["candidate"]["existing_primary_local_edges_between_pair"], [])
        self.assertEqual([row["four_u16_words"][3]
                          for row in report["candidate"]["node_records"]], [518, 271])
        (EVIDENCE / "edge_insertion_preflight.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        output = EVIDENCE / f"must_not_exist_{uuid.uuid4().hex}.MP0"
        with self.assertRaises(TopologyWriteBlocked) as caught:
            write_new_edge(source=DEFAULT_SOURCE, output=output, block=886,
                           node_a=412, node_b=414, geometry=[])
        self.assertFalse(output.exists())
        self.assertFalse(caught.exception.report["output_file_created"])
        self.assertGreaterEqual(len(caught.exception.report["blockers"]), 5)
        (EVIDENCE / "edge_insertion_refusal.json").write_text(
            json.dumps(caught.exception.report, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_original_and_sidecar_sources_remain_unchanged(self) -> None:
        self.assertEqual(hashlib.sha256(DEFAULT_SOURCE.read_bytes()).hexdigest(), self.source_hash)
        self.assertEqual(self.topology["source_write_count"], 0)
        for suffix in ("RT", "RL"):
            row = self.sidecars["files"][suffix]
            self.assertEqual(row["source_sha256_before"], row["source_sha256_after"])
            self.assertEqual(row["source_write_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
