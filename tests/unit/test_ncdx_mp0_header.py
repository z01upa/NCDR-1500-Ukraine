from __future__ import annotations

import os
from pathlib import Path
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.readers.ncdx_mp0_header import NcdxHeaderError, parse_mp0_header, read_mp0_header


SOURCE_ROOT = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[2]))


class Mp0HeaderReaderTests(unittest.TestCase):
    def test_real_eu_file_header_and_sha256(self) -> None:
        result = read_mp0_header(
            SOURCE_ROOT / "SW" / "DB" / "EUZ.MP0",
            expected_sha256="73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e",
        )
        self.assertEqual(result.file_size, 30_281_958)
        self.assertEqual(result.magic, "(*$SIEMENS&^)")
        self.assertEqual(result.copyright, "Copyright 1998")
        self.assertEqual(result.internal_format_version, "2.0.0")
        self.assertEqual(result.dataset_code, "EU44420940.82")

    def test_regional_codes_match_three_independent_disc_trees(self) -> None:
        fixtures = (
            (SOURCE_ROOT / "SW" / "DB" / "EUZ.MP0", "EU44420940.82"),
            (SOURCE_ROOT / "OPEL NCDx Italia 2010-2011" / "DB" / "IZ.MP0", "I44431940.82"),
            (SOURCE_ROOT / "OPEL NCDx Scandinavia 2010-2011" / "DB" / "SCZ.MP0", "SC44442940.82"),
        )
        for path, expected_code in fixtures:
            with self.subTest(path=path.name):
                self.assertEqual(read_mp0_header(path).dataset_code, expected_code)

    def test_corrupt_marker_is_rejected(self) -> None:
        sample = bytearray(b"\0" * 80)
        sample[:13] = b"(*$SIEMENS&^)"
        sample[16:32] = b"Copyright 1998\0\0"
        sample[32:48] = b"2.0.0\0" + b"\0" * 10
        sample[48:64] = b"EU44420940.82\0\0\0"
        sample[0] = ord("X")
        with self.assertRaisesRegex(NcdxHeaderError, "marker"):
            parse_mp0_header(bytes(sample))

    def test_hash_mismatch_is_rejected_before_header_claim(self) -> None:
        path = SOURCE_ROOT / "SW" / "DB" / "EUZ.MP0"
        with self.assertRaisesRegex(NcdxHeaderError, "SHA-256 mismatch"):
            read_mp0_header(path, expected_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
