from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from src.readers.ncdx_index_integrity import analyze_index_integrity


def _container(block_size: int, payload: bytes) -> bytes:
    blocks = [payload[offset:offset + block_size]
              for offset in range(0, len(payload), block_size)]
    compressed = [zlib.compress(block) for block in blocks]
    table_end = 16 + 4 * (len(blocks) + 1)
    offsets = [table_end]
    for block in compressed:
        offsets.append(offsets[-1] + len(block))
    header = struct.pack("<4sIII", b"zip\x01", block_size, len(payload), 0xA5A5A5A5)
    return header + struct.pack(f"<{len(offsets)}I", *offsets) + b"".join(compressed)


class NcdxIndexIntegrityTests(unittest.TestCase):
    def test_real_read_only_file_matrix_and_bad_offset_controls(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / "work") as temp:
            root = Path(temp)
            inputs = []
            for region, suffix, payload in (
                ("EUZ", "MG3", b"A" * 64 + b"tail"),
                ("IZ", "CTY", b"B" * 45 + b"last"),
            ):
                relative = f"{region}/{suffix}.NCDX"
                path = root / Path(*relative.split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(_container(64, payload))
                inputs.append({"region": region, "suffix": suffix,
                    "relative_path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size_bytes": path.stat().st_size})
            report = analyze_index_integrity(root, inputs)
            self.assertEqual(report["source_count"], 2)
            self.assertEqual(report["independent_suffix_count"], 2)
            self.assertEqual(report["valid_source_absolute_offset_error_count"], 0)
            self.assertEqual(report["invalid_reference_negative_control_rejection_count"], 3)
            self.assertTrue(all(row["absolute_offsets_validated"] for row in report["observations"]))
            self.assertEqual(report["interpretation"]["original_media_write_count"], 0)

    def test_manifest_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / "work") as temp:
            root = Path(temp)
            relative = "EUZ/MG3.NCDX"
            path = root / Path(*relative.split("/"))
            path.parent.mkdir(parents=True)
            path.write_bytes(_container(64, b"bounded fixture"))
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                analyze_index_integrity(root, [
                    {"region": "EUZ", "suffix": "MG3", "relative_path": relative,
                     "sha256": "0" * 64, "size_bytes": path.stat().st_size},
                    {"region": "IZ", "suffix": "MG3", "relative_path": "IZ/MG3.NCDX",
                     "sha256": "1" * 64, "size_bytes": 1},
                ])


if __name__ == "__main__":
    unittest.main()
