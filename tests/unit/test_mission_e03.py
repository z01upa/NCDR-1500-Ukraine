from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.e03_optical_layout import build_e03_optical_layout_evidence
from src.agent.e03_optical_layout_verifier import verify_e03_optical_layout_evidence


class MissionE03OpticalEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.sources = self.root / "original"
        self.project.mkdir()
        self.files = {
            ("SW", "SW/VERSION.TXT"): (
                b"Note:\r\nThe filesystem on CD must be ISO9660 level 2\r\n"
                b"(with long filenames up to 30 characters)\r\n"
            ),
            ("SW", "SW/CDROM.TOC"): b"Volume: CD_7190\r\nArea: EU\r\n",
            ("OPEL NCDx Italia 2010-2011", "OPEL NCDx Italia 2010-2011/CDROM.TOC"):
                b"Volume: CD_7185\r\nArea: Italy\r\n",
            ("OPEL NCDx Scandinavia 2010-2011", "OPEL NCDx Scandinavia 2010-2011/CDROM.TOC"):
                b"Volume: CD_7186\r\nArea: Scandinavia\r\n",
        }
        self.ledger = self.project / "EVIDENCE_LEDGER.sqlite"
        conn = sqlite3.connect(self.ledger)
        try:
            conn.execute(
                "CREATE TABLE artifacts(source_group TEXT, source_path TEXT, sha256 TEXT, size_bytes INTEGER, extension TEXT)"
            )
            for (group, relative), payload in self.files.items():
                source = self.sources.joinpath(*relative.split("/"))
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(payload)
                conn.execute(
                    "INSERT INTO artifacts VALUES(?,?,?,?,?)",
                    (group, relative, hashlib.sha256(payload).hexdigest(), len(payload), Path(relative).suffix.upper()),
                )
            conn.commit()
        finally:
            conn.close()

    def _build(self) -> Path:
        result = build_e03_optical_layout_evidence(
            source_root=self.sources,
            project_root=self.project,
            ledger_path=self.ledger,
        )
        self.assertEqual(result["status"], "WAITING_EXTERNAL")
        return self.project / result["artifact_path"]

    def test_reports_documented_requirement_without_claiming_track_geometry(self) -> None:
        artifact = self._build()
        proof = verify_e03_optical_layout_evidence(
            artifact, source_root=self.sources, project_root=self.project, ledger_path=self.ledger
        )
        self.assertEqual(proof["independent_manifest_readback"], "PASS")
        self.assertEqual(proof["source_entry_count"], 4)
        self.assertEqual(proof["sector_image_candidate_count"], 0)
        saved = __import__("json").loads(artifact.read_text(encoding="utf-8"))
        self.assertEqual(saved["filesystem_requirement_classification"], "DOCUMENTED_REQUIREMENT_ONLY")
        self.assertEqual(saved["track_layout"], "NOT_PROVEN")
        self.assertEqual(saved["sector_geometry"], "NOT_PROVEN")

    def test_verifier_rejects_changed_original_text_source(self) -> None:
        artifact = self._build()
        source = self.sources / "SW" / "VERSION.TXT"
        source.write_bytes(b"altered source")
        with self.assertRaisesRegex(RuntimeError, "readback differs"):
            verify_e03_optical_layout_evidence(
                artifact, source_root=self.sources, project_root=self.project, ledger_path=self.ledger
            )


if __name__ == "__main__":
    unittest.main()
