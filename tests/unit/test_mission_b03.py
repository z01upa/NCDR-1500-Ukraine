from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.b03_inventory_verifier import verify_b03_binary_format_inventory
from src.agent.project_director import build_b03_binary_format_inventory


def _minimal_arm_pe() -> bytes:
    data = bytearray(256)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 64)
    data[64:68] = b"PE\x00\x00"
    struct.pack_into("<HHIIIHH", data, 68, 0x01C0, 1, 0, 0, 0, 70, 0)
    optional = 88
    struct.pack_into("<H", data, optional, 0x10B)
    struct.pack_into("<I", data, optional + 28, 0x10000)
    struct.pack_into("<I", data, optional + 56, 0x2000)
    struct.pack_into("<H", data, optional + 68, 9)
    return bytes(data)


class MissionB03InventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.sources = self.root / "original"
        self.project.mkdir()
        (self.sources / "SW" / "test").mkdir(parents=True)
        self.files = {
            "SW/test/APP.EXE": _minimal_arm_pe(),
            "SW/test/NK.BIN": b"NK payload format intentionally unknown\x00\x01\x02",
        }
        self.ledger = self.project / "EVIDENCE_LEDGER.sqlite"
        conn = sqlite3.connect(self.ledger)
        try:
            conn.execute("CREATE TABLE artifacts(source_path TEXT, sha256 TEXT, size_bytes INTEGER, extension TEXT, source_group TEXT)")
            for relative, payload in self.files.items():
                source = self.sources.joinpath(*relative.split("/"))
                source.write_bytes(payload)
                conn.execute(
                    "INSERT INTO artifacts VALUES(?,?,?,?,?)",
                    (relative, hashlib.sha256(payload).hexdigest(), len(payload),
                     Path(relative).suffix.upper(), "SW"),
                )
            conn.commit()
        finally:
            conn.close()

    def _build(self) -> Path:
        summary = build_b03_binary_format_inventory(
            source_root=self.sources,
            ledger_path=self.ledger,
            project_root=self.project,
        )
        return self.project / summary["inventory_path"]

    def test_manifest_bound_inventory_and_independent_pe_readback(self) -> None:
        artifact = self._build()
        proof = verify_b03_binary_format_inventory(
            artifact, source_root=self.sources, project_root=self.project, ledger_path=self.ledger
        )
        self.assertEqual(proof["independent_source_readback"], "PASS")
        self.assertEqual(proof["component_count"], 2)
        self.assertEqual(proof["pe_header_count"], 1)
        self.assertEqual(proof["architecture_counts"], {"ARM": 1})
        self.assertTrue(proof["nk_bin_included"])

    def test_verifier_rejects_source_changed_after_inventory(self) -> None:
        artifact = self._build()
        (self.sources / "SW" / "test" / "NK.BIN").write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "size differs|hash/CRC/stat"):
            verify_b03_binary_format_inventory(
                artifact, source_root=self.sources, project_root=self.project, ledger_path=self.ledger
            )

    def test_repeated_worker_entry_resumes_verified_inventory_without_rewriting_it(self) -> None:
        artifact = self._build()
        first_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        summary = build_b03_binary_format_inventory(
            source_root=self.sources,
            ledger_path=self.ledger,
            project_root=self.project,
        )
        self.assertTrue(summary["resumed_existing_artifact"])
        self.assertEqual(summary["inventory_sha256"], first_hash)
        self.assertEqual(hashlib.sha256(artifact.read_bytes()).hexdigest(), first_hash)


if __name__ == "__main__":
    unittest.main()
