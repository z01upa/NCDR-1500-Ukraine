from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.readers import ncdx_geography_portability as geography


def _logical_table(type_id: int, stride: int, records: bytes) -> bytes:
    header = bytearray(94)
    header[:7] = b"SIEMENS"
    struct.pack_into("<H", header, 84, type_id)
    struct.pack_into("<I", header, 86, len(records) // stride)
    struct.pack_into("<I", header, 90, len(records))
    return bytes(header) + records


def _container(logical: bytes, block_size: int = 3072) -> bytes:
    blocks = [logical[offset:offset + block_size]
              for offset in range(0, len(logical), block_size)]
    table_end = 16 + 4 * (len(blocks) + 1)
    payloads = [zlib.compress(block) for block in blocks]
    offsets = [table_end]
    for payload in payloads:
        offsets.append(offsets[-1] + len(payload))
    return (b"zip\x01" + struct.pack("<III", block_size, len(logical), 0)
            + struct.pack(f"<{len(offsets)}I", *offsets) + b"".join(payloads))


class NcdxGeographyPortabilityTests(unittest.TestCase):
    def _fixture_sources(self, root: Path) -> list[dict[str, object]]:
        cny = bytearray(174)
        struct.pack_into("<H", cny, 0, 0)
        cny[30:38] = b"Region 0"
        cty = bytearray(178)
        struct.pack_into("<II", cty, 0, 0, 0)
        struct.pack_into("<iiii", cty, 18, -10000, 20000, 10000, 30000)
        cty[34:39] = b"City0"
        logical = {"CTY": _logical_table(3, 178, bytes(cty)),
                   "CNY": _logical_table(12, 174, bytes(cny))}
        sources: list[dict[str, object]] = []
        bbox = (-20000, 10000, 20000, 40000)
        for region in ("SW", "Italy", "Scandinavia"):
            blobs = {name: _container(value) for name, value in logical.items()}
            for name in geography.MAP_HEADERS:
                header = bytearray(110)
                header[4:11] = b"SIEMENS"
                struct.pack_into("<H", header, 84, 7)
                struct.pack_into("<I", header, 86, 4)
                struct.pack_into("<I", header, 90, 0x12345678)
                struct.pack_into("<iiii", header, 94, *bbox)
                blobs[name] = bytes(header) + b"test payload"
            for table, data in blobs.items():
                relative = f"{region}/{region}.{table}"
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                sources.append({"region": region, "relative_path": relative,
                    "absolute_path": str(path), "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        return sources

    def test_checks_three_region_geography_and_spatial_headers(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            sources = self._fixture_sources(root)
            result = geography.analyze(sources)
            self.assertEqual(result["hypothesis_result"], "SUPPORTED")
            self.assertEqual(len(result["regions"]), 3)
            self.assertTrue(all(all(row["checks"].values()) for row in result["regions"]))
            artifact = root / "evidence.json"
            artifact.write_text(json.dumps(result), encoding="utf-8")
            proof = geography.verify_artifact(artifact, sources,
                hashlib.sha256(artifact.read_bytes()).hexdigest())
            self.assertEqual(proof["verified_source_count"], 18)

    def test_rejects_a_source_not_bound_to_its_inventory_hash(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            sources = self._fixture_sources(Path(temporary))
            sources[0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "source differs from inventory"):
                geography.analyze(sources)


if __name__ == "__main__":
    unittest.main()
