from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.firmware.intel_hex import IntelHexError, summarize_stream
from src.firmware.verify_intel_hex import verify_file_independently


def record(address: int, kind: int, data: bytes = b"") -> bytes:
    prefix = bytes((len(data),)) + address.to_bytes(2, "big") + bytes((kind,)) + data
    checksum = (-sum(prefix)) & 0xFF
    return b":" + (prefix + bytes((checksum,))).hex().upper().encode("ascii") + b"\r\n"


class IntelHexTests(unittest.TestCase):
    def test_valid_linear_address_records_and_hash(self) -> None:
        payload = record(0, 4, b"\x00\x01") + record(0x20, 0, b"ABC") + record(0, 5, b"\x00\x01\x00\x20") + record(0, 1)
        result = summarize_stream(io.BytesIO(payload))
        self.assertEqual(result["record_type_counts"], {"00": 1, "01": 1, "04": 1, "05": 1})
        self.assertEqual(result["unique_image_bytes"], 3)
        self.assertEqual(result["address_ranges_preview"], [[0x10020, 0x10023]])
        self.assertEqual(result["start_address_records"], [{"type": 5, "address": 0x10020}])
        self.assertTrue(result["eof_seen"])

    def test_valid_extended_segment(self) -> None:
        result = summarize_stream(io.BytesIO(record(0, 2, b"\x12\x34") + record(0x10, 0, b"Z") + record(0, 1)))
        self.assertEqual(result["address_ranges_preview"], [[0x12350, 0x12351]])

    def test_bad_checksum_is_rejected(self) -> None:
        bad = record(0, 0, b"X")[:-4] + b"00\r\n"
        with self.assertRaisesRegex(IntelHexError, "checksum mismatch"):
            summarize_stream(io.BytesIO(bad + record(0, 1)))

    def test_requires_terminal_eof(self) -> None:
        with self.assertRaisesRegex(IntelHexError, "missing EOF"):
            summarize_stream(io.BytesIO(record(0, 0, b"X")))
        with self.assertRaisesRegex(IntelHexError, "after EOF"):
            summarize_stream(io.BytesIO(record(0, 1) + record(0, 0, b"X")))

    def test_conflicting_overlap_is_rejected(self) -> None:
        payload = record(0, 0, b"AB") + record(1, 0, b"C") + record(0, 1)
        with self.assertRaisesRegex(IntelHexError, "conflicting overlapping byte"):
            summarize_stream(io.BytesIO(payload))

    def test_record_and_input_limits_are_enforced(self) -> None:
        with self.assertRaisesRegex(IntelHexError, "record count exceeds"):
            summarize_stream(io.BytesIO(record(0, 1)), max_records=0)
        with self.assertRaisesRegex(IntelHexError, "bounded read limit"):
            summarize_stream(io.BytesIO(record(0, 1)), max_bytes=2)

    def test_independent_reader_matches_primary_reader(self) -> None:
        payload = record(0, 4, b"\x00\x01") + record(0x10, 0, b"firmware") + record(0, 1)
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp_dir:
            path = Path(temp_dir) / "fixture.hex"
            path.write_bytes(payload)
            primary = summarize_stream(io.BytesIO(payload))
            independent = verify_file_independently(path)
        for key in ("record_count", "record_type_counts", "data_record_bytes", "unique_image_bytes",
                    "address_range_count", "address_ranges_preview", "address_image_sha256", "eof_seen"):
            self.assertEqual(independent[key], primary[key])


if __name__ == "__main__":
    unittest.main()
