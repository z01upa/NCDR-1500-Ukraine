import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from sh4_scan import (EXPECTED_ENTRY_FILE_OFFSET, EXPECTED_ENTRY_VA, LANGUAGE,
                      analyze)
import pypcode  # noqa: E402


class Sh4RoutingScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = analyze()

    def test_decoder_control_opcodes_match_sh4_little_endian(self):
        context = pypcode.Context(LANGUAGE)
        samples = ((bytes.fromhex("0900"), "nop"),
                   (bytes.fromhex("0b00"), "rts"),
                   (bytes.fromhex("0b40"), "jsr"))
        for raw, expected in samples:
            with self.subTest(raw=raw.hex()):
                instruction = context.disassemble(raw, 0x1000,
                                                  max_instructions=1).instructions[0]
                self.assertEqual(instruction.mnem.lower(), expected)
        self.assertTrue(all(row["pass"] for row in self.report["decoder_controls"]))

    def test_existing_pe_reader_entry_mapping_and_source_manifest(self):
        source = self.report["source"]
        pe = self.report["pe"]
        self.assertEqual(source["sha256_before"], source["expected_sha256"])
        self.assertEqual(source["sha256_after"], source["expected_sha256"])
        self.assertFalse(source["changed_by_scan"])
        self.assertEqual(pe["entry_va"], EXPECTED_ENTRY_VA)
        self.assertEqual(pe["entry_file_offset"], EXPECTED_ENTRY_FILE_OFFSET)
        self.assertEqual(pe["architecture_from_existing_reader"], "SH4")

    def test_all_pdata_roots_are_in_text_and_decode(self):
        roots = self.report["pdata_roots"]
        self.assertEqual(len(roots), 45)
        self.assertTrue(all(row["va"] < row["range_end_va_exclusive"] for row in roots))
        self.assertEqual(self.report["scan"]["cfg_decode_failure_count"], 0)
        self.assertEqual(self.report["scan"]["pdata_root_count"], 45)

    def test_entrypoint_dispatch_targets_are_literal_backed(self):
        targets = {row["loaded_value"] for row in self.report["entrypoint_pc_literal_targets"]}
        self.assertTrue({0x11CD4, 0x113F8, 0x11D08}.issubset(targets))
        rows = self.report["entrypoint_window"]
        self.assertEqual(rows[11].get("va"), 0x11E3A)
        self.assertEqual(rows[11]["mnem"], "jsr")

    def test_runtime_import_xrefs_are_to_named_commgr_api(self):
        calls = {row["call_va"]: row["import"]
                 for row in self.report["import_call_xrefs"]}
        expected = {
            0x11398: "?GetProcessName@MI_CF_ObjectDescription@@QBAPBGXZ",
            0x116AE: "?GetInstance@MI_CF_RemoteComManager@@SAPAV1@PBG0II@Z",
            0x116C0: "?GetInstance@MI_CF_CommunicationBroker@@SAAAV1@PBG0II@Z",
            0x116CC: "?RegisterStatusHandler@MI_CF_CommunicationBroker@@QAAXPAVMI_CF_StatusHandler@@@Z",
            0x116E4: "?CreateInstance@MI_CF_RemoteComManager@@QAAJABU_GUID@@PAUIUnknown@@K0PAPAX@Z",
            0x118A8: "?ReleaseInstance@MI_CF_RemoteComManager@@SAXXZ",
        }
        for address, symbol in expected.items():
            with self.subTest(address=hex(address)):
                self.assertEqual(calls[address]["module"], "commgr.dll")
                self.assertEqual(calls[address]["symbol"], symbol)

    def test_dynamic_navi_trace_module_and_export_strings_are_referenced(self):
        sequence = self.report["dynamic_module_sequence"]
        strings = {row["va"]: row.get("loaded_utf16le")
                   for row in sequence["instructions"] if "loaded_utf16le" in row}
        self.assertEqual(strings[0x115F0], "NaviTrace.dll")
        self.assertEqual(strings[0x115F6], "Initialize")
        calls = {row["call_va"]: row["import"]
                 for row in sequence["import_call_xrefs"]}
        self.assertEqual((calls[0x115F2]["module"], calls[0x115F2]["ordinal"]),
                         ("coredll.dll", 528))
        self.assertEqual((calls[0x115FC]["module"], calls[0x115FC]["ordinal"]),
                         ("coredll.dll", 530))
        self.assertEqual(sequence["following_indirect_call_va"], 0x11602)
        self.assertEqual(sequence["exact_basename_search"]["matches"], [])
        thunks = {row["thunk_va"]: row for row in self.report["import_thunks"]}
        self.assertEqual(thunks[0x11B10]["import_iat_va"], 0x13000)
        self.assertEqual(thunks[0x11B34]["import_iat_va"], 0x13038)
        self.assertEqual([row["mnem"] for row in thunks[0x11B10]["instructions"]],
                         ["mov.l", "mov.l", "jmp", "nop"])

    def test_record_stride_marker_result_is_exactly_reproducible(self):
        # This asserts the bounded search result only. Its absence is not proof
        # that equivalent arithmetic or an indirect parser is absent.
        self.assertEqual(self.report["scan"]["immediate_10_or_14_hits"], [])
        self.assertIn("indirect jump-table targets are not followed",
                      self.report["scan"]["scope"])

    def test_read_only_source_and_prior_evidence_hashes_are_recorded(self):
        self.assertFalse(self.report["source"]["changed_by_scan"])
        anchors = self.report["inputs_reused_read_only"]["anchor_sha256"]
        self.assertEqual(set(anchors), {
            "xref_v4_firmware_xref.json",
            "astra_core_v5_NODE_GRAPH_SPEC.md",
            "astra_core_v5_BINARY_FINDINGS.md",
            "astra_core_v5_pass_a_frozen_rule.json",
        })
        self.assertTrue(all(len(value) == 64 for value in anchors.values()))


if __name__ == "__main__":
    unittest.main()
