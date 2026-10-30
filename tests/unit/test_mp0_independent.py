from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from src.readers.mp0_independent import IndependentMp0Error, inspect_mp0_independently


def _fixture(*, code: bytes = b"EU44420940.82", marker: bytes = b"(*$SIEMENS&^)") -> bytes:
    header = bytearray(64)
    header[:len(marker)] = marker
    header[16:32] = b"Copyright 1998\x00"
    header[32:48] = b"2.0.0\x00"
    header[48:64] = code + b"\x00" * (16 - len(code))
    return bytes(header) + b"payload bytes are opaque"


class IndependentMp0Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2] / "work")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_reads_observed_fixed_header_without_using_main_reader(self) -> None:
        path = self.root / "EUZ.MP0"
        raw = _fixture()
        path.write_bytes(raw)
        result = inspect_mp0_independently(path)
        self.assertEqual(result["dataset_code"], "EU44420940.82")
        self.assertEqual(result["internal_format_version"], "2.0.0")
        self.assertEqual(result["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["file_size"], len(raw))
        self.assertIn("payload semantics unknown", result["claim_scope"])

    def test_accepts_other_observed_region_code_shapes(self) -> None:
        path = self.root / "IZ.MP0"
        path.write_bytes(_fixture(code=b"I44431940.82"))
        self.assertEqual(inspect_mp0_independently(path)["dataset_code"], "I44431940.82")

    def test_rejects_truncated_and_wrong_marker(self) -> None:
        short = self.root / "short.MP0"
        short.write_bytes(b"tiny")
        with self.assertRaises(IndependentMp0Error):
            inspect_mp0_independently(short)
        wrong = self.root / "wrong.MP0"
        wrong.write_bytes(_fixture(marker=b"not-a-Siemens!"))
        with self.assertRaises(IndependentMp0Error):
            inspect_mp0_independently(wrong)

    def test_rejects_unterminated_and_unknown_dataset_code(self) -> None:
        no_nul = self.root / "no-nul.MP0"
        no_nul.write_bytes(_fixture(code=b"EU44420940.82X"))
        with self.assertRaises(IndependentMp0Error):
            inspect_mp0_independently(no_nul)
        unknown = self.root / "unknown.MP0"
        unknown.write_bytes(_fixture(code=b"XX44420940.82"))
        with self.assertRaises(IndependentMp0Error):
            inspect_mp0_independently(unknown)

    def test_rejects_non_mp0_suffix(self) -> None:
        path = self.root / "EUZ.bin"
        path.write_bytes(_fixture())
        with self.assertRaises(IndependentMp0Error):
            inspect_mp0_independently(path)


if __name__ == "__main__":
    unittest.main()
