from __future__ import annotations

import json
import struct
from pathlib import Path
import tempfile
import unittest
import zlib

from research.ncdx_container_experiment.inspect_container import (
    ContainerError,
    PROJECT_ROOT,
    inspect_container,
    write_immutable_report,
)


def make_container(payload: bytes, block_size: int = 3072) -> bytes:
    chunks = [payload[i:i + block_size] for i in range(0, len(payload), block_size)]
    if not chunks:
        chunks = [b""]
    compressed = [zlib.compress(chunk) for chunk in chunks]
    offsets = [16 + 4 * (len(chunks) + 1)]
    for block in compressed:
        offsets.append(offsets[-1] + len(block))
    header = b"zip\x01" + struct.pack("<III", block_size, len(payload), 0xA5A5)
    table = struct.pack(f"<{len(offsets)}I", *offsets)
    return header + table + b"".join(compressed)


class CandidateContainerTests(unittest.TestCase):
    def test_valid_multiblock_container_reaches_declared_logical_size(self) -> None:
        payload = bytes(range(256)) * 40
        parsed = inspect_container(make_container(payload))
        self.assertEqual(parsed["status"], "PASS")
        self.assertEqual(parsed["decoded_size_bytes"], len(payload))
        self.assertEqual(parsed["chunk_count"], 4)
        self.assertTrue(parsed["offset_table_covers_file"])

    def test_rejects_non_candidate_magic(self) -> None:
        with self.assertRaisesRegex(ContainerError, "does not start"):
            inspect_container(b"nope" + b"\0" * 64)

    def test_rejects_non_monotonic_or_out_of_file_offsets(self) -> None:
        valid = bytearray(make_container(b"x" * 3073))
        struct.pack_into("<I", valid, 20, len(valid) + 1)
        with self.assertRaisesRegex(ContainerError, "increasing"):
            inspect_container(bytes(valid))

    def test_rejects_corrupt_zlib_block(self) -> None:
        valid = bytearray(make_container(b"x" * 20))
        valid[-1] ^= 0xFF
        with self.assertRaises(ContainerError):
            inspect_container(bytes(valid))

    def test_rejects_declared_logical_size_above_bound(self) -> None:
        valid = bytearray(make_container(b"x" * 20))
        struct.pack_into("<I", valid, 8, 65 * 1024 * 1024)
        with self.assertRaisesRegex(ContainerError, "logical size"):
            inspect_container(bytes(valid))

    def test_immutable_report_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            path = Path(temporary) / "nested" / "report.json"
            write_immutable_report(path, {"status": "PASS"})
            before = path.read_text(encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_immutable_report(path, {"status": "CHANGED"})
            self.assertEqual(path.read_text(encoding="utf-8"), before)
            self.assertEqual(json.loads(before)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
