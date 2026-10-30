from __future__ import annotations

import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.readers import ncdx_roadlink_name_consistency as reader


def _logical(type_id: int, count: int, records: bytes) -> bytes:
    header = bytearray(94)
    header[:7] = b"SIEMENS"
    struct.pack_into("<H", header, 84, type_id)
    struct.pack_into("<I", header, 86, count)
    struct.pack_into("<I", header, 90, len(records))
    return bytes(header) + records


def _container(data: bytes, block_size: int = 128) -> bytes:
    blocks = [data[offset:offset + block_size] for offset in range(0, len(data), block_size)]
    table_end = 16 + 4 * (len(blocks) + 1)
    payloads = [zlib.compress(block) for block in blocks]
    offsets = [table_end]
    for payload in payloads:
        offsets.append(offsets[-1] + len(payload))
    return (b"zip\x01" + struct.pack("<III", block_size, len(data), 0)
        + struct.pack(f"<{len(offsets)}I", *offsets) + b"".join(payloads))


class NcdxRoadlinkNameConsistencyTests(unittest.TestCase):
    def _sources(self, root: Path) -> list[dict[str, object]]:
        result = []
        for region, prefix in (("SW", "EUZ"), ("Italy", "IZ"), ("Scandinavia", "SCZ")):
            first_name, second_name = b"MAIN STREET", b"OTHER ROAD"
            rl_records = bytearray()
            for link_id, name in ((0, first_name), (1, second_name)):
                row = bytearray(61)
                struct.pack_into("<I", row, 0, link_id)
                row[7:7 + len(name)] = name
                rl_records.extend(row)
            il_records = []
            for link_id, name in ((0, first_name), (1, second_name)):
                row = bytearray(11)
                struct.pack_into("<I", row, 0, link_id)
                il_records.append(bytes(row) + name + b"\0")
            iof_records = bytearray()
            offset = 94
            for il_record in il_records:
                row = bytearray(6)
                struct.pack_into("<IH", row, 0, offset, 1)
                iof_records.extend(row)
                offset += len(il_record)
            data_by_table = {
                "RL": _container(_logical(21, 2, bytes(rl_records))),
                "IOF": _container(_logical(21, 2, bytes(iof_records))),
                "IL": _container(_logical(20, 2, b"".join(il_records))),
            }
            for suffix, data in data_by_table.items():
                relative = f"{region}/{prefix}.{suffix}"
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                result.append({"region": region, "relative_path": relative,
                    "absolute_path": str(path), "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()})
        return result

    def test_three_region_name_links_beat_displaced_control(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            sources = self._sources(root)
            result = reader.analyze(sources)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["hypothesis_result"], "SUPPORTED")
            for region in result["regions"]:
                self.assertTrue(all(region["checks"].values()))
                self.assertEqual(region["name_link_counts"]["normalized_direct_matches"], 2)
                self.assertLess(region["name_link_counts"]["normalized_displaced_control_matches"], 2)
            artifact = root / "names.json"
            artifact.write_text(__import__("json").dumps(result), encoding="utf-8")
            proof = reader.verify_artifact(artifact, sources,
                hashlib.sha256(artifact.read_bytes()).hexdigest())
            self.assertEqual(proof["verified_source_count"], 9)

    def test_manifest_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            sources = self._sources(Path(temporary))
            sources[0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "source differs from the pinned evidence ledger"):
                reader.analyze(sources)


if __name__ == "__main__":
    unittest.main()
