from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.readers import ncdx_pe_imports, ncdx_pe_imports_verifier


def _pe_fixture() -> bytes:
    data = bytearray(0x800)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, 0x01A6, 1, 0, 0, 0, 224, 0x210E)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x10B)
    struct.pack_into("<I", data, optional + 56, 0x3000)
    struct.pack_into("<I", data, optional + 60, 0x400)
    struct.pack_into("<I", data, optional + 92, 16)
    struct.pack_into("<II", data, optional + 96 + 8, 0x2020, 40)
    section = optional + 224
    data[section:section + 8] = b".rdata\0\0"
    struct.pack_into("<IIII", data, section + 8, 0x400, 0x2000, 0x400, 0x400)
    struct.pack_into("<IIIII", data, 0x420, 0x2060, 0, 0, 0x2050, 0x2080)
    data[0x450:0x45F] = b"coredll.dll\0" + b"\0" * 3
    struct.pack_into("<II", data, 0x460, 0x20A0, 0)
    struct.pack_into("<II", data, 0x480, 0x20A0, 0)
    struct.pack_into("<H", data, 0x4A0, 7)
    data[0x4A2:0x4AE] = b"CreateFileW\0"
    return bytes(data)


class NcdxPeImportTests(unittest.TestCase):
    def test_import_parser_reports_module_name_and_raw_iat_offset(self) -> None:
        parsed = ncdx_pe_imports.parse_imports(_pe_fixture())
        self.assertEqual(parsed["import_count"], 1)
        self.assertEqual(parsed["modules"][0]["module"], "coredll.dll")
        item = parsed["modules"][0]["imports"][0]
        self.assertEqual((item["name"], item["hint"], item["iat_rva"], item["iat_file_offset"]),
                         ("CreateFileW", 7, 0x2080, 0x480))
        self.assertEqual(parsed["io_api_candidates"][0]["classification"],
                         "NAME_MATCH_ONLY; call sites and behavior not analyzed")

    def test_independent_verifier_reparses_artifact_and_detects_source_change(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            source_root = root / "original"
            source_root.mkdir()
            source = source_root / "NAVIMAIN.EXE"
            source.write_bytes(_pe_fixture())
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            parsed = ncdx_pe_imports.parse_imports(source.read_bytes())
            artifact = root / "evidence.json"
            artifact.write_text(json.dumps({"source_path": "NAVIMAIN.EXE",
                "source_size_bytes": source.stat().st_size, "source_sha256": source_hash,
                "original_media_write_count": 0, **parsed}, sort_keys=True), encoding="utf-8")
            artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
            proof = ncdx_pe_imports_verifier.verify_artifact(artifact,
                source_root=source_root, project_root=PROJECT_ROOT,
                relative_path="NAVIMAIN.EXE", expected_sha256=source_hash,
                expected_size=source.stat().st_size, artifact_sha256=artifact_hash)
            self.assertEqual(proof["status"], "PASS")
            self.assertEqual(proof["import_count"], 1)
            changed = bytearray(source.read_bytes())
            changed[-1] ^= 1
            source.write_bytes(changed)
            with self.assertRaisesRegex(ValueError, "hash differs"):
                ncdx_pe_imports_verifier.verify_artifact(artifact,
                    source_root=source_root, project_root=PROJECT_ROOT,
                    relative_path="NAVIMAIN.EXE", expected_sha256=source_hash,
                    expected_size=len(changed), artifact_sha256=artifact_hash)

    def test_out_of_section_rva_is_rejected(self) -> None:
        data = bytearray(_pe_fixture())
        struct.pack_into("<II", data, 0x98 + 96 + 8, 0x5000, 40)
        with self.assertRaisesRegex(ValueError, "RVA"):
            ncdx_pe_imports.parse_imports(bytes(data))


if __name__ == "__main__":
    unittest.main()
