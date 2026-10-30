from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.readers import ncdx_embedded_pe, ncdx_embedded_pe_verifier
from tests.unit.test_ncdx_pe_imports import _pe_fixture


class EmbeddedPeSearchTests(unittest.TestCase):
    def test_embedded_mz_and_invalid_marker_are_distinguished(self) -> None:
        data = bytearray(b"\x00" * 0x100 + _pe_fixture())
        data[0x20:0x22] = b"MZ"
        scan = ncdx_embedded_pe.scan_embedded_pe(bytes(data))
        self.assertEqual(scan["mz_marker_count_scanned"], 2)
        self.assertEqual(scan["pe_signature_candidate_count"], 1)
        self.assertEqual(scan["valid_pe_image_count"], 1)
        self.assertEqual(scan["valid_images"][0]["base_offset"], 0x100)
        self.assertEqual(scan["valid_images"][0]["architecture"], "SH4")
        self.assertEqual(scan["valid_images"][0]["raw_image_end_offset"], 0x900)

    def test_independent_source_and_artifact_replay(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            source_root = root / "original"
            source_root.mkdir()
            source = source_root / "NK.BIN"
            source.write_bytes(b"\0" * 0x100 + _pe_fixture())
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            scan = ncdx_embedded_pe.scan_embedded_pe(source.read_bytes())
            artifact = root / "embedded.json"
            artifact.write_text(json.dumps({"source_path": "NK.BIN",
                "source_size_bytes": source.stat().st_size,
                "source_sha256": source_hash, "original_media_write_count": 0,
                **scan}, sort_keys=True), encoding="utf-8")
            artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
            proof = ncdx_embedded_pe_verifier.verify_artifact(artifact,
                source_root=source_root, project_root=PROJECT_ROOT,
                relative_path="NK.BIN", expected_sha256=source_hash,
                expected_size=source.stat().st_size, artifact_sha256=artifact_hash)
            self.assertEqual(proof["valid_pe_image_count"], 1)
            altered = json.loads(artifact.read_text(encoding="utf-8"))
            altered["valid_images"][0]["base_offset"] = 0
            artifact.write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "artifact"):
                ncdx_embedded_pe_verifier.verify_artifact(artifact,
                    source_root=source_root, project_root=PROJECT_ROOT,
                    relative_path="NK.BIN", expected_sha256=source_hash,
                    expected_size=source.stat().st_size, artifact_sha256=artifact_hash)


if __name__ == "__main__":
    unittest.main()
