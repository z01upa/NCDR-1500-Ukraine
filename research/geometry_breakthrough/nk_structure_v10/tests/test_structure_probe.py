import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from nk_structure_probe import (  # noqa: E402
    AddressMap,
    Segment,
    ecec_scan,
    flat_toc,
    parse_b000ff,
    parse_romhdr,
    scan_headers,
    make_address_map,
    module_record_family_scan,
)


def b000ff_image(records):
    image = bytearray(b"B000FF\n" + struct.pack("<II", 0x80000000, 0x20000000))
    for base, payload in records:
        image.extend(struct.pack("<III", base, len(payload), 0x12345678))
        image.extend(payload)
    image.extend(struct.pack("<III", 0, 0, 0))
    return bytes(image)


class SparseAddressMappingTests(unittest.TestCase):
    def test_noncontiguous_sections_map_in_physical_record_order(self):
        high = bytearray(b"H" * 32)
        low = bytearray(b"L" * 32)
        high[4:8] = b"ECEC"
        low[12:16] = b"ECEC"
        image = b000ff_image([(0x90000000, bytes(high)), (0x80000000, bytes(low))])
        parsed = parse_b000ff(image)
        self.assertTrue(parsed["valid"])
        amap = make_address_map(image, parsed)
        self.assertIsNotNone(amap)
        hi = amap.offset(0x90000004, 4)
        lo = amap.offset(0x8000000C, 4)
        self.assertIsNotNone(hi)
        self.assertIsNotNone(lo)
        self.assertEqual(image[hi:hi + 4], b"ECEC")
        self.assertEqual(image[lo:lo + 4], b"ECEC")
        self.assertIsNone(amap.offset(0x88000000))
        found = ecec_scan(image, parsed, amap, {"candidates": []})
        self.assertEqual(len(found), 2)
        self.assertEqual({x["mapped_va"] for x in found}, {0x90000004, 0x8000000C})

    def test_map_rejects_ambiguous_overlapping_ranges(self):
        amap = AddressMap(b"A" * 64, [Segment(0x8000, 32, 0), Segment(0x8000, 32, 32)])
        self.assertIsNone(amap.offset(0x8004))
        self.assertIsNone(amap.read(0x8004, 4))


class RomhdrCandidateTests(unittest.TestCase):
    def test_unaligned_header_and_nonfirst_kernel_name_are_not_rejected(self):
        data = bytearray(0x600)
        origin = 0x80000000
        name_offset = 0x90
        data[name_offset:name_offset + 10] = b"route.dll\0"
        header_offset = 0x103  # deliberately 4-byte unaligned
        fields = (
            origin, origin + 0x1000, origin, origin + 0x1000, 1,
            origin + 0x2000, origin + 0x2000, origin + 0x3000,
            0, 0, 0, 0, 0, 0, 0, 0, 0,
            0x01A6, 0, 0, 0, 0,
        )
        struct.pack_into("<17I2HI2I", data, header_offset, *fields)
        row = (0, 0, 0, 0x20, origin + name_offset, origin + 0x200, origin + 0x220, origin + 0x100)
        struct.pack_into("<8I", data, header_offset + struct.calcsize("<17I2HI2I"), *row)

        scan = scan_headers(bytes(data), "flat")
        matches = [c for c in scan["candidates"] if c["header_file_offset"] == header_offset]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["header_offset_mod4"], 3)
        self.assertTrue(matches[0]["toc_coherent"])
        toc = next(t for t in matches[0]["toc_hypotheses"] if t["flat_origin"] == 0)
        self.assertIsNone(toc["nk_exe_index"])
        self.assertTrue(toc["coherent_without_kernel_order_assumption"])


class ModuleRecordPatternTests(unittest.TestCase):
    def test_reports_repeated_ce_record_candidate_without_assigning_semantics(self):
        image = bytearray(256)
        entries = []
        for i, (name, va, padding) in enumerate((("a.dll", 0x8C001000, b""),
                                                  ("b.dll", 0x8C002000, b"XYZ"))):
            off = 16 + i * 64
            encoded = name.encode("ascii")
            image[off:off + len(encoded)] = encoded
            image[off + len(encoded)] = 0
            marker = off + len(encoded) + 1 + len(padding)
            image[off + len(encoded) + 1:marker] = padding
            image[marker:marker + 16] = b"CE" + struct.pack("<HIII", 7 + i, va, 0x220, 0x330)
            entries.append({"index": i, "name": name, "offset": off})
        image[200:204] = struct.pack("<I", 0x8C001000)

        result = module_record_family_scan(bytes(image), entries)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["plus_4_strictly_increasing_transitions"], 1)
        self.assertEqual(result["plus_4_transition_count"], 1)
        self.assertEqual(result["rows"][0]["field_plus_4_exact_secondary_reference_offsets"], [200])
        self.assertIn("semantics", result["interpretation"])


if __name__ == "__main__":
    unittest.main()
