from __future__ import annotations

import unittest
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from edge_insertion_gate import build_gate_report
from independent_topology_reader import validate_independently
from topology_validator import SOURCE, _read_container, _section_pairs, validate


class MP0TopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = validate()
        cls.independent_topology = validate_independently()
        cls.gate = build_gate_report()

    def test_all_2956_blocks_and_streams_are_structurally_valid(self):
        self.assertEqual(self.report["block_count_pass"], 2956)
        self.assertEqual(self.report["exact_decompression_pass"], 2956)
        self.assertEqual(self.report["blocks_with_structural_errors"], 0)
        self.assertEqual(self.report["edge_endpoint_out_of_range"], 0)

    def test_independent_reader_matches_every_edge_geometry(self):
        reader = self.report["independent_reader"]
        self.assertFalse(reader["writer_imported"])
        self.assertFalse(reader["current_decoder_imported"])
        self.assertEqual(reader["edges_point_for_point_pass"], 1_090_323)
        self.assertEqual(reader["edges_fail"], 0)

    def test_standalone_parser_independently_confirms_topology_counts(self):
        independent = self.independent_topology
        self.assertEqual(independent["status"], "PASS_WITH_REPORTED_UNRESOLVED_CASES")
        self.assertEqual(independent["blocks_inflated"], 2956)
        self.assertEqual(independent["nodes"], 956_071)
        self.assertEqual(independent["edges"], 1_090_323)
        self.assertEqual(independent["edge_endpoint_out_of_range"], 0)
        adj = independent["degree_le4_local_adjacency_exact"]
        self.assertEqual(adj["pass"], 952_280)
        self.assertEqual(adj["fail"], 511)
        self.assertEqual(adj["failures_at_duplicate_coordinates"], 511)
        self.assertEqual(independent["primary_endpoint_reference_membership_for_degree_le4"], {
            "pass": 2_141_367, "fail": 0,
        })

    def test_low_degree_inline_adjacency_matches_with_reported_alias_exceptions(self):
        evidence = self.report["degree_le4_exact_local_adjacency_nodes"]
        self.assertEqual(evidence["pass"], 952_280)
        self.assertEqual(evidence["fail"], 511)
        self.assertEqual(evidence["fail_coordinate_duplication"], {"duplicate_coordinate": 511})
        self.assertEqual(evidence["candidate_refs_geometry_relation"]["any_candidate_ref_touches_coordinate"], 511)
        examples = self.report["confirmed_low_degree_adjacency_examples"]
        self.assertEqual({"1", "2", "3", "4"} - set(examples), set())
        fourth = examples["4"][0]
        self.assertEqual(len(fourth["active_refs"]), 4)
        self.assertEqual(sorted(fourth["active_refs"]), sorted(fourth["local_primary_edges"]))
        self.assertEqual(fourth["record_hex"][16:20],
                         int(fourth["active_refs"][3]).to_bytes(2, "little").hex())
        trailing = self.report["section4_trailing_u16_words_when_degree_below_four"]
        self.assertGreater(trailing["degree3_slot3_nonzero"], 0)
        self.assertGreater(trailing["degree3_slot3_within_local_edge_id_range"], 0)
        self.assertLess(trailing["degree3_slot3_is_local_incidence"],
                        trailing["degree3_slot3_records"])

    def test_unknown_overflow_is_reported_not_counted_as_pass(self):
        self.assertEqual(self.report["degree_gt4_overflow_unresolved_nodes"], 3280)
        self.assertEqual(self.report["degree_le4_exact_local_adjacency_nodes"]["fail"], 511)
        self.assertEqual(self.report["status"], "PASS_WITH_TOPOLOGY_UNRESOLVED")

    def test_roundtrip_preserves_all_graph_bytes_and_secondary_cross_links(self):
        rt = self.report["decode_encode_graph_roundtrip"]
        self.assertEqual(rt["blocks_byte_identical_pass"], 2956)
        self.assertEqual(rt["blocks_byte_identical_fail"], 0)
        self.assertEqual(rt["section4_5_byte_identical_pass"], 2956)
        links = self.report["secondary_coordinate_cross_block_matches"]
        self.assertEqual(links["pass"], 29_240)
        self.assertEqual(links["fail"], 0)

    def test_section5_duplicate_edges_preserve_raw_attribute_fields(self):
        copies = self.report["cross_block_exact_geometry_duplicate_groups"]
        self.assertEqual(copies["groups"], 14_619)
        self.assertEqual(copies["attributes_identical_groups"], 14_619)
        self.assertEqual(copies["unresolved_identical_groups"], 14_618)
        self.assertEqual(copies["flags_other_than_coordinate_table_selectors_identical_groups"], 14_618)
        # This tests byte-level preservation across duplicate records; it does
        # not assign routing or direction semantics to those fields.

    def test_section5_fourteen_byte_field_offsets_on_real_record(self):
        _, blocks = _read_container(SOURCE)
        raw = blocks[0]
        offsets, counts = _section_pairs(raw)
        edge_at = offsets[5] + 33 * 14
        record = raw[edge_at:edge_at + 14]
        self.assertEqual(len(record), 14)
        fields = struct.unpack("<5HI", record)
        self.assertEqual(record[:2], fields[0].to_bytes(2, "little"))
        self.assertEqual(record[2:4], fields[1].to_bytes(2, "little"))
        self.assertEqual(record[4:6], fields[2].to_bytes(2, "little"))
        self.assertEqual(record[6:8], fields[3].to_bytes(2, "little"))
        self.assertEqual(record[8:10], fields[4].to_bytes(2, "little"))
        self.assertEqual(record[10:14], fields[5].to_bytes(4, "little"))
        self.assertEqual(counts[5] * 14, offsets[6] - offsets[5])

    def test_section7_to_9_record_widths_are_exactly_reproduced(self):
        layout = self.report["auxiliary_sections_7_to_9_layout"]["record_size_by_populated_block"]
        self.assertEqual(layout["7"], {"7": 2956})
        self.assertEqual(layout["8"], {"empty_blocks": 1053, "11": 1903})
        self.assertEqual(layout["9"], {"empty_blocks": 2930, "13": 26})

    def test_candidate_edge_is_refused_before_any_mp0_mutation(self):
        self.assertEqual(self.gate["status"], "REFUSED_BEFORE_MP0_MUTATION")
        candidate = self.gate["candidate"]
        self.assertEqual(candidate["block"], 886)
        self.assertEqual(candidate["nodes"][0]["node"], 412)
        self.assertEqual(candidate["nodes"][1]["node"], 414)
        self.assertTrue(candidate["known_inline_adjacency_capacity"])
        self.assertEqual([row["next_slot_u16_at_plus_8"] for row in candidate["nodes"]], [518, 271])
        self.assertFalse(self.gate["layout_only_if_supported"]["mutation_performed"])
        self.assertFalse(self.gate["layout_only_if_supported"]["mp0_file_written"])
        self.assertIn("Section 5 attributes", " ".join(self.gate["specific_write_blockers"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
