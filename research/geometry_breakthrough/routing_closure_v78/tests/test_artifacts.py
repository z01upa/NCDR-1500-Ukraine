"""Small standard-library acceptance tests for generated v78 evidence."""
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class RoutingClosureEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.replay = json.loads((ROOT / "DIFFERENTIAL_REPLAY.json").read_text(encoding="utf-8"))
        cls.r8 = json.loads((ROOT / "R8_REPLAY.json").read_text(encoding="utf-8"))
        cls.consumer = json.loads((ROOT / "CONSUMER_TRACE.json").read_text(encoding="utf-8"))
        cls.producers = json.loads((ROOT / "MASK_PRODUCERS.json").read_text(encoding="utf-8"))
        cls.lineage = json.loads((ROOT / "MEMORY_LINEAGE.json").read_text(encoding="utf-8"))
        cls.cfg = json.loads((ROOT / "CFG.json").read_text(encoding="utf-8"))

    def test_original_source_hashes_unchanged(self):
        self.assertEqual(self.replay["status"], "PASS_BOUNDED_REPLAY")
        self.assertEqual(self.replay["mp0_sha256_before"], self.replay["mp0_sha256_after"])
        self.assertTrue(self.replay["assertions"]["original_mp0_unchanged"])

    def test_all_individual_mask_bits_on_three_edges(self):
        labels = {case["case"] for case in self.replay["cases"]}
        for edge in (0, 1, 593):
            self.assertIn(f"edge{edge}_baseline_side0", labels)
            self.assertIn(f"edge{edge}_baseline_side1", labels)
            for off in (4, 5):
                for bit in range(8):
                    self.assertIn(f"edge{edge}_byte{off}_bit{bit}", labels)
            self.assertIn(f"edge{edge}_toggle_first_u32_bit13", labels)
            self.assertIn(f"edge{edge}_swap_endpoint_ids", labels)
        self.assertEqual(len(self.replay["cases"]), 60)

    def test_replays_contain_instruction_and_memory_evidence(self):
        for case in self.replay["cases"]:
            self.assertEqual(len(case["input"]["initial_registers_r0_r15"]), 16)
            self.assertTrue(case["instruction_trace_pc"])
            self.assertTrue(case["executed_instructions"])
            self.assertIsInstance(case["memory_reads"], list)
            self.assertIsInstance(case["memory_writes"], list)
            self.assertIsInstance(case["branch_decisions"], list)
            self.assertIn(case["candidate_gate"]["decision_pc"],
                          ("0x010AC1DE", "0x010AC204"))

    def test_r8_zero_branch_is_refuted(self):
        self.assertEqual(self.r8["status"], "PASS")
        paths = {case["input_r8"]: case["path"] for case in self.r8["cases"]}
        self.assertEqual(paths["0x00000000"], "indexed_byte_seed")
        for value in ("0x00000001", "0x00000002", "0x80000000", "0xFFFFFFFF"):
            self.assertEqual(paths[value], "generator_010AC72C")

    def test_cover_path_is_not_claimed_as_routing_dataflow(self):
        self.assertEqual(len(self.consumer["direct_literal_callers"]), 11)
        self.assertEqual(len(self.consumer["differential_replay"]), 9)
        self.assertEqual(self.consumer["differential_replay"][0]["same_buffer_in_production"], "UNKNOWN")
        self.assertTrue(any("R11" in item and "dataflow" in item for item in self.consumer["limits"]))

    def test_route_state_field_writes_are_distinguished(self):
        fields = self.producers["route_state_selection"]["010AC610"]["writes"]
        self.assertEqual(fields["+0x3A"], "selected candidate ordinal R11")
        self.assertIn("(state+0x38 >> ordinal)&1", fields["+0x3C"])
        self.assertIn("bits 12..14", fields["+0x44"])
        proof = " ".join(self.producers["route_state_selection"]["010AC610"]["instruction_proof"])
        for address in ("010AC6C8", "010AC6DA", "010AC6F2", "010AC7E8"):
            self.assertIn(address, proof)

    def test_disassembly_omits_inline_literal_pool_as_code(self):
        listing = (ROOT / "ORIGINAL_DISASSEMBLY.md").read_text(encoding="utf-8").lower()
        self.assertNotIn("010ac6ac 68a8 bra", listing)
        self.assertIn("010ac6f2 1224 mov.l r1,@r4", listing)

    def test_full_cfgs_include_requested_consumers(self):
        for addr in ("010AC04C", "010AC72C", "0108C1F0", "010AC610", "010AB4D0",
                     "01098AE8", "010718AC", "0106D104", "0107AC78"):
            self.assertGreater(self.cfg[addr]["instructions_reachable"], 0)

    def test_higher_level_caller_chain_is_static_but_bounded(self):
        chain = self.lineage["higher_level_status_chain"]
        self.assertEqual([link["call_pc"] for link in chain["links"]],
                         ["0x0109904A", "0x01071960", "0x0106D2C4", "0x0107AC98"])
        self.assertIn("UNKNOWN", chain["unresolved"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
