from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parents[1]
PROJECT = HERE.parents[2]
for path in (PROJECT, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from firmware_xref import (  # noqa: E402
    NAVIMAIN, NAVIMAIN_SHA256, NK_BIN, NK_SHA256, analyze,
)


class FirmwareCrossReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = analyze()
        (HERE / "evidence").mkdir(exist_ok=True)
        (HERE / "evidence" / "firmware_xref.json").write_text(
            json.dumps(cls.report, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_manifest_hashes_and_readonly_integrity(self) -> None:
        nav = self.report["sources"]["NAVIMAIN.EXE"]
        nk = self.report["sources"]["NK.BIN"]
        self.assertEqual(nav["sha256"], NAVIMAIN_SHA256)
        self.assertEqual(nav["sha256_after"], NAVIMAIN_SHA256)
        self.assertEqual(nk["sha256"], NK_SHA256)
        self.assertEqual(nk["sha256_after"], NK_SHA256)
        self.assertEqual(nav["source_write_count"], 0)
        self.assertEqual(nk["source_write_count"], 0)
        self.assertEqual(hashlib.sha256(NAVIMAIN.read_bytes()).hexdigest(), NAVIMAIN_SHA256)
        self.assertEqual(hashlib.sha256(NK_BIN.read_bytes()).hexdigest(), NK_SHA256)

    def test_entrypoint_is_in_sh4_text_and_exact_raw_bytes_are_saved(self) -> None:
        pe = self.report["sources"]["NAVIMAIN.EXE"]["pe"]
        self.assertEqual(pe["entry_point_rva"], "0x00001e24")
        self.assertEqual(pe["entry_point_va"], "0x00011e24")
        self.assertEqual(pe["entry_point_file_offset"], "0x00001224")
        self.assertEqual(pe["entry_point_section"], ".text")
        self.assertEqual(len(pe["entry_point_hex_64_bytes"]), 128)
        self.assertEqual(len(pe["sections"]), 5)
        self.assertEqual(self.report["sources"]["NAVIMAIN.EXE"]["pe"]["machine_code"], 0x01A6)

    def test_iat_ordinal_calls_are_observed_but_not_mislabelled(self) -> None:
        imports = self.report["sources"]["NAVIMAIN.EXE"]["imports"]
        self.assertEqual(imports["total"], 39)
        self.assertEqual(imports["modules"][0]["module"], "coredll.dll")
        self.assertEqual(imports["modules"][0]["ordinal_count"], 18)
        self.assertEqual(imports["modules"][1]["module"], "commgr.dll")
        self.assertEqual(imports["modules"][1]["named_count"], 7)
        self.assertEqual(imports["named_io_api_candidates"], [])
        self.assertEqual(imports["preferred_va_iat_literals_found_in_text"], 45)
        self.assertTrue(any(row["literal_file_offset"] == 0xEA0
                            and row["preferred_va_literal"] == "0x00013004"
                            and row["ordinal"] == 455
                            for row in imports["iat_literal_reference_samples"]))
        self.assertIn("ordinal targets are unresolved", imports["interpretation"])

    def test_unpacking_and_reader_code_remain_unproven(self) -> None:
        nav = self.report["sources"]["NAVIMAIN.EXE"]
        self.assertEqual(nav["reader_procedure"], "NOT_LOCATED; no SH4 instruction decoder is available in the current environment")
        self.assertIn("NOT_ESTABLISHED", nav["packer_check"]["requires_unpacking"])
        self.assertTrue(all(offsets == [] for offsets in nav["packer_check"]["known_marker_offsets"].values()))
        self.assertTrue(all(path is None for path in self.report["tooling"]["disassembler_paths"].values()))
        self.assertTrue(all(path is None for path in self.report["tooling"]["rom_extractor_paths"].values()))

    def test_nk_alternative_embedded_pe_and_module_string_checks(self) -> None:
        nk = self.report["sources"]["NK.BIN"]
        self.assertEqual(nk["mz_marker_count"], 15)
        self.assertEqual(nk["embedded_pe_scan"]["valid_pe_image_count"], 0)
        self.assertEqual(nk["raw_pe_signature_count"], 1)
        self.assertFalse(nk["raw_pe_signature_candidates"][0]["matches_NAVIMAIN_SH4_machine"])
        for term in ("NAVIMAIN", "NAVIMAIN.EXE", "EUZ.MP0", "MP0"):
            self.assertEqual(nk["target_strings"][term]["ascii_offsets"], [])
            self.assertEqual(nk["target_strings"][term]["utf16le_offsets"], [])
        self.assertEqual(nk["ce00ff_marker_offsets"], [0x400])
        self.assertEqual(nk["ecec_marker_offsets"], [0x9CEAD3])
        self.assertEqual(nk["ecec_marker_contexts"][0]["following_u32_le_untyped"], 0x8D2F66CC)
        self.assertEqual(nk["ecec_marker_contexts"][0]["same_dword_occurrence_offsets"],
                         [3513, 0x9CEAD7, 0x9CEADF])
        self.assertIn("UNKNOWN", nk["image_format"])

    def test_existing_high_degree_observation_is_referenced_not_recomputed(self) -> None:
        context = self.report["prior_topology_context"]
        self.assertEqual(context["high_low_nibble_gt4_rows_without_local_primary_endpoint_incidence"], 1325)
        self.assertEqual(context["node_identity_mismatches"], 511)
        self.assertEqual(context["section5_endpoints_out_of_range"], 0)

    def test_no_node_record_algorithm_is_claimed(self) -> None:
        self.assertEqual(self.report["status"], "PASS_BOUNDED_XREF_WITH_CODE_READER_UNRESOLVED")
        self.assertEqual(self.report["sources"]["NAVIMAIN.EXE"]["section4_section5_algorithm"],
                         "NOT_RECOVERED_FROM_NAVIMAIN")
        self.assertEqual(self.report["sources"]["NK.BIN"]["node_reader_code"].split(";")[0],
                         "NOT_LOCATED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
