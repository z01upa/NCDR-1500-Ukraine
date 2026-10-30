from __future__ import annotations

import hashlib
import io
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from src.readers.ncdx_container import (
    NcdxContainerError,
    decode_bytes,
    read_index,
)
from src.writers.ncdx_container_writer import (
    encode_container,
    rewrite_container,
    write_lossless_roundtrip,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class NcdxContainerTests(unittest.TestCase):
    def test_encoded_fixture_decodes_and_byte_exact_reencodes(self) -> None:
        logical = bytes((index * 23 + index // 7) % 256 for index in range(17_321))
        encoded = encode_container(logical, block_size_bytes=3072, opaque_header_u32_le=0x12345678)
        index, decoded = decode_bytes(encoded)
        self.assertEqual(decoded, logical)
        self.assertEqual(index.block_count, 6)
        self.assertEqual(index.opaque_header_u32_le, 0x12345678)
        self.assertEqual(rewrite_container(encoded, decoded), encoded)

    def test_controlled_payload_change_preserves_framing_and_independent_decode(self) -> None:
        original = bytes((index * 5) % 256 for index in range(9_000))
        encoded = encode_container(original, block_size_bytes=3072, opaque_header_u32_le=711)
        changed = bytearray(original)
        changed[4097] ^= 0x20
        rewritten = rewrite_container(encoded, bytes(changed))
        index, decoded = decode_bytes(rewritten)
        self.assertEqual(decoded, bytes(changed))
        self.assertEqual(index.block_size_bytes, 3072)
        self.assertEqual(index.opaque_header_u32_le, 711)
        self.assertNotEqual(rewritten, encoded)

    def test_rejects_bad_table_and_corrupt_zlib_block(self) -> None:
        encoded = bytearray(encode_container(b"NCDx" * 2000))
        index = read_index(io.BytesIO(encoded))
        malformed_table = bytearray(encoded)
        struct.pack_into("<I", malformed_table, 16, index.offsets[0] + 1)
        with self.assertRaises(NcdxContainerError):
            read_index(io.BytesIO(malformed_table))
        corrupted = bytearray(encoded)
        corrupted[index.offsets[0] + 3] ^= 0xFF
        with self.assertRaises(NcdxContainerError):
            decode_bytes(bytes(corrupted))

    def test_rejects_declared_output_smaller_than_zlib_payload(self) -> None:
        compressed = zlib.compress(b"A" * 5000, level=9)
        table_end = 16 + 8
        encoded = (b"zip\x01" + struct.pack("<III", 4, 4, 0)
                   + struct.pack("<II", table_end, table_end + len(compressed)) + compressed)
        with self.assertRaises(NcdxContainerError):
            decode_bytes(encoded)

    def test_lossless_roundtrip_writes_only_new_file_below_work_root(self) -> None:
        logical = b"verified fixture payload" * 400
        encoded = encode_container(logical, opaque_header_u32_le=0xA5A5)
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp:
            root = Path(temp)
            work = root / "work"
            media = root / "media"
            work.mkdir()
            media.mkdir()
            source = media / "fixture.PDX"
            source.write_bytes(encoded)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            output = work / "roundtrip" / "fixture.PDX"
            result = write_lossless_roundtrip(source, output, expected_sha256=before, work_root=work)
            self.assertEqual(result["status"], "PASS_COPY_ONLY")
            self.assertTrue(result["byte_identical"])
            self.assertEqual(output.read_bytes(), source.read_bytes())
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            with self.assertRaises(FileExistsError):
                write_lossless_roundtrip(source, output, expected_sha256=before, work_root=work)
            with self.assertRaises(ValueError):
                write_lossless_roundtrip(source, media / "forbidden.PDX",
                    expected_sha256=before, work_root=work)


if __name__ == "__main__":
    unittest.main()
