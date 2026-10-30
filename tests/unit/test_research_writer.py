from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.writers.research_writer import controlled_dataset_code_change, no_op_roundtrip


def sample_mp0() -> bytes:
    head = bytearray(b"?" * 64)
    head[:13] = b"(*$SIEMENS&^)"
    head[16:32] = b"Copyright 1998\0\0"
    head[32:48] = b"2.0.0\0" + b"\0" * 10
    head[48:64] = b"EU44420940.82\0\0\0"
    return bytes(head) + bytes(range(64))


class ResearchWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "EUZ.MP0"
        self.source.write_bytes(sample_mp0())

    def test_noop_copy_roundtrip_preserves_every_byte_and_source(self) -> None:
        before = self.source.read_bytes()
        result = no_op_roundtrip(self.source, self.root / "copy.MP0")
        self.assertTrue(result["no_op_roundtrip_pass"])
        self.assertEqual((self.root / "copy.MP0").read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), before)

    def test_controlled_change_only_changes_confirmed_code_bytes(self) -> None:
        before = self.source.read_bytes()
        result = controlled_dataset_code_change(self.source, self.root / "altered.MP0", "SC44442940.82")
        self.assertTrue(result["controlled_change_pass"])
        self.assertEqual(result["new_code"], "SC44442940.82")
        self.assertTrue(all(48 <= offset < 61 for offset in result["changed_offsets"]))
        self.assertEqual(self.source.read_bytes(), before)

    def test_refuses_overwrite_and_in_place_write(self) -> None:
        with self.assertRaises(ValueError):
            no_op_roundtrip(self.source, self.source)
        destination = self.root / "copy.MP0"
        destination.write_bytes(b"leave me")
        with self.assertRaises(FileExistsError):
            no_op_roundtrip(self.source, destination)
        self.assertEqual(destination.read_bytes(), b"leave me")


if __name__ == "__main__":
    unittest.main()
