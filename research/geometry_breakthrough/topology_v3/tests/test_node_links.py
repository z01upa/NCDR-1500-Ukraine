from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from node_link_decoder import decode_node_record, validate_inline_links
from node_link_validator import EXPECTED_SHA256, SOURCE, validate
from topology_editor import (TopologyMutationRefused, noop_roundtrip,
                             permute_edges, preflight_edge_permutation,
                             source_fingerprint)


class NodeLinkEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = validate(write_evidence=True)

    def test_read_only_full_container_and_all_2956_blocks(self):
        report = self.report
        self.assertEqual(report["block_count_pass"], 2956)
        self.assertEqual(report["source_sha256_before"], EXPECTED_SHA256)
        self.assertEqual(report["source_sha256_after"], EXPECTED_SHA256)
        self.assertFalse(report["original_bytes_written"])
        self.assertEqual(report["section5_endpoint_out_of_range"], 0)

    def test_low_degree_inline_rule_on_independent_holdout_blocks(self):
        holdout = self.report["holdout_blocks_mod5_eq0"]
        self.assertEqual(holdout["blocks"], 592)
        self.assertEqual(holdout["nodes_degree_le4"], 188795)
        self.assertEqual(holdout["exact"] + holdout["mismatch"], 188795)
        self.assertEqual(holdout["exact"], 188658)
        self.assertEqual(holdout["mismatch"], 137)
        self.assertEqual(self.report["hypothesis_blocks_mod5_ne0"]["exact"], 763622)

    def test_real_examples_for_degrees_zero_through_four(self):
        samples = self.report["low_degree_identity_adjacency"]["samples_degree_0_to_4"]
        for degree in range(5):
            self.assertTrue(samples[str(degree)], f"missing real degree-{degree} record")
            matching = [sample for sample in samples[str(degree)] if sample["exact_identity_match"]]
            self.assertTrue(matching, f"no exact identity example for degree {degree}")
            for sample in matching:
                checked = validate_inline_links(bytes.fromhex(sample["record_hex"]),
                    sample["actual_primary_endpoint_edges"],
                    local_edge_count=sample["local_edge_count"])
                self.assertEqual(checked["status"], "CONFIRMED_FOR_RECORD")

    def test_slot_plus8_below_degree_four_is_opaque_not_free(self):
        by_degree = self.report["word_at_plus8_when_low_nibble_below4"]
        self.assertEqual(by_degree["3"]["records"], 281608)
        self.assertEqual(by_degree["3"]["nonzero"], 280356)
        self.assertEqual(by_degree["3"]["is_identity_incident_edge"], 2650)
        self.assertGreater(by_degree["1"]["nonzero"], 0)
        self.assertGreater(by_degree["2"]["nonzero"], 0)
        self.assertGreater(by_degree["0"]["nonzero"], 0)
        inactive = self.report["inactive_u16_words_preserved_by_degree_and_slot"]
        self.assertGreater(inactive["degree_0_slot_0"]["nonzero"], 0)
        self.assertGreater(inactive["degree_1_slot_1"]["nonzero"], 0)
        self.assertGreater(inactive["degree_2_slot_2"]["nonzero"], 0)
        by_type = self.report["word_at_plus8_by_high_and_low_nibble"]
        self.assertEqual(sum(item["records"] for item in by_type.values()), 919772)
        self.assertGreater(len(by_type), 4)

    def test_high_nibble_population_is_reported_without_degree_guess(self):
        high = self.report["high_nibble_gt4_records"]
        self.assertEqual(high["count"], 3280)
        matrix = high["actual_primary_incidence_by_stored_low_nibble_and_incidence"]
        self.assertEqual(matrix["low=5,actual_primary_incidence=5"], 1712)
        self.assertEqual(matrix["low=6,actual_primary_incidence=6"], 222)
        self.assertEqual(matrix["low=7,actual_primary_incidence=7"], 21)
        self.assertEqual(matrix["low=5,actual_primary_incidence=0"], 111)
        tail = high["tail_three_word_link_checks_by_low_nibble"]
        self.assertEqual(tail["5"]["tail_word_set_is_subset_of_incident_set"], 1712)
        self.assertEqual(tail["6"]["tail_word_set_is_subset_of_incident_set"], 222)
        self.assertEqual(tail["7"]["tail_word_set_is_subset_of_incident_set"], 21)
        self.assertEqual(tail["5"]["holdout_tail_word_set_is_subset_of_incident_set"], 405)
        self.assertTrue(high["real_record_samples"]["low_5_incidence_5"])
        sample = bytes.fromhex(high["real_record_samples"]["low_5_incidence_5"][0]["record_hex"])
        self.assertEqual(decode_node_record(sample)["interpretation_status"],
                         "HIGH_DEGREE_CONTINUATION_UNRESOLVED")

    def test_duplicate_coordinates_remain_distinct_node_identities(self):
        evidence = self.report["low_degree_identity_adjacency"]
        self.assertEqual(evidence["mismatches"], 511)
        self.assertEqual(evidence["mismatch_duplicate_coordinate_groups"], 511)
        example = evidence["all_mismatch_records"][0]
        self.assertGreater(example["same_coordinate_count"], 1)
        self.assertNotEqual(example["active_candidate_refs"],
                            example["section5_primary_incident_edge_ids"])
        self.assertIn(example["node"], example["same_coordinate_node_ids"])

    def test_section7_to9_edge_domain_candidates_and_ranges(self):
        sections = self.report["sections_7_8_9"]
        expected = {"7": (1471866, 2956, 177977),
                    "8": (126436, 1903, 15140),
                    "9": (51, 26, 5)}
        for sec, (rows, blocks, edge_only) in expected.items():
            item = sections[sec]
            self.assertEqual(item["rows"], rows)
            self.assertEqual(item["populated_blocks"], blocks)
            self.assertEqual(item["layout_errors"], 0)
            self.assertEqual(item["all_key_lt_edge_count_blocks"], blocks)
            self.assertEqual(item["nondecreasing_blocks"], blocks)
            self.assertEqual(item["records_with_key_only_edge_domain"], edge_only)
            self.assertEqual(item["records_with_key_only_node_domain"], 0)
            self.assertEqual(item["holdout_populated_blocks"], {"7": 592, "8": 379, "9": 4}[sec])
            self.assertEqual(item["holdout_all_key_lt_edge_count_blocks"], item["holdout_populated_blocks"])
            self.assertEqual(item["holdout_nondecreasing_blocks"], item["holdout_populated_blocks"])
            self.assertIn("EDGE_INDEX_CANDIDATE_ONLY", item["semantic_status"])
            self.assertTrue(item["key_only_edge_examples"])

    def test_noop_is_byte_identical_and_mutation_gate_refuses(self):
        original = SOURCE.read_bytes()
        candidate = noop_roundtrip(original)
        self.assertEqual(candidate, original)
        self.assertEqual(source_fingerprint(candidate), EXPECTED_SHA256)
        gate = preflight_edge_permutation(block=0, edge_a=0, edge_b=1)
        self.assertEqual(gate["status"], "REFUSED_BEFORE_MUTATION")
        self.assertFalse(gate["original_bytes_written"])
        with self.assertRaises(TopologyMutationRefused):
            permute_edges(block=0, edge_a=0, edge_b=1)
        self.assertEqual(source_fingerprint(SOURCE.read_bytes()), EXPECTED_SHA256)


if __name__ == "__main__":
    unittest.main(verbosity=2)
