from __future__ import annotations

import struct
import unittest

from src.agent.project_director import _independent_pe_header_summary
from src.readers.ncdx_binary_headers import inspect_pe_headers


def _synthetic_pe(machine: int = 0x01C2) -> bytes:
    image = bytearray(0x220)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 0x80)
    image[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<HHIIIHH", image, 0x84, machine, 1, 0, 0, 0, 0xE0, 0x2102)
    optional = 0x98
    struct.pack_into("<H", image, optional, 0x10B)
    struct.pack_into("<I", image, optional + 28, 0x400000)
    struct.pack_into("<I", image, optional + 56, 0x2000)
    struct.pack_into("<I", image, optional + 64, 0x12345678)
    struct.pack_into("<H", image, optional + 68, 9)
    section = optional + 0xE0
    image[section:section + 8] = b".text\x00\x00\x00"
    struct.pack_into("<IIII", image, section + 8, 0x100, 0x1000, 0x20, 0x200)
    image[0x200:0x220] = bytes(range(0x20))
    return bytes(image)


class NcdxBinaryHeaderTests(unittest.TestCase):
    def test_worker_and_independent_supervisor_parsers_agree_on_pe32_arm_image(self) -> None:
        data = _synthetic_pe()
        worker = inspect_pe_headers(data)
        verifier = _independent_pe_header_summary(data)
        self.assertEqual(worker, verifier)
        self.assertEqual(worker["architecture"], "ARM or Thumb")
        self.assertEqual(worker["optional_header_kind"], "PE32")
        self.assertEqual(worker["sections"][0]["name"], ".text")
        self.assertEqual(worker["raw_section_ranges"], [[0x200, 0x220]])

    def test_worker_rejects_section_ranges_outside_the_manifest_file(self) -> None:
        data = bytearray(_synthetic_pe())
        struct.pack_into("<I", data, 0x178 + 20, 0x1FFFFFFF)
        with self.assertRaisesRegex(ValueError, "raw range extends beyond"):
            inspect_pe_headers(bytes(data))

    def test_worker_rejects_invalid_pe_header_offsets(self) -> None:
        data = bytearray(_synthetic_pe())
        struct.pack_into("<I", data, 0x3C, len(data) - 8)
        with self.assertRaisesRegex(ValueError, "outside the source"):
            inspect_pe_headers(bytes(data))

    def test_sh4_machine_code_is_named_without_claiming_runtime_compatibility(self) -> None:
        result = inspect_pe_headers(_synthetic_pe(machine=0x01A6))
        self.assertEqual(result["machine_code"], 0x01A6)
        self.assertEqual(result["architecture"], "SH4")


if __name__ == "__main__":
    unittest.main()
