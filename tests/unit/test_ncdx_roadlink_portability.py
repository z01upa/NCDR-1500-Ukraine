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

from src.readers import ncdx_roadlink_portability as roadlinks


def _logical_table(type_id: int, count: int, records: bytes) -> bytes:
    header = bytearray(94)
    header[:7] = b"SIEMENS"
    struct.pack_into("<H", header, 84, type_id)
    struct.pack_into("<I", header, 86, count)
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


class NcdxRoadlinkPortabilityTests(unittest.TestCase):
    def _fixture_sources(self, root: Path) -> list[dict[str, object]]:
        rl_rows = []
        for link_id in (0, 1):
            row = bytearray(61)
            struct.pack_into("<I", row, 0, link_id)
            row[7:7 + len(f"ROAD {link_id}")] = f"ROAD {link_id}".encode("ascii")
            rl_rows.append(bytes(row))
        iof_rows = [struct.pack("<IH", 94, 2), struct.pack("<IH", 0, 0x8000)]
        il_rows = []
        for link_id in (0, 1):
            il_rows.append(struct.pack("<I", link_id) + b"\0" * 7
                           + f"ROAD {link_id}".encode("ascii") + b"\0")
        logical = {
            "RL": _logical_table(21, 2, b"".join(rl_rows)),
            "IOF": _logical_table(21, 2, b"".join(iof_rows)),
            "IL": _logical_table(20, 2, b"".join(il_rows)),
        }
        sources: list[dict[str, object]] = []
        for region in ("SW", "Italy", "Scandinavia"):
            for table, data in logical.items():
                relative = f"{region}/{region}.{table}"
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(_container(data))
                sources.append({"region": region, "relative_path": relative,
                    "absolute_path": str(path), "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        return sources

    def test_reads_and_checks_three_region_rl_iof_il_sets(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            sources = self._fixture_sources(root)
            report = roadlinks.analyze(sources)
            self.assertEqual(report["hypothesis_result"], "SUPPORTED")
            self.assertEqual(len(report["regions"]), 3)
            self.assertTrue(all(all(row["checks"].values()) for row in report["regions"]))
            artifact = root / "evidence.json"
            artifact.write_text(json.dumps(report), encoding="utf-8")
            proof = roadlinks.verify_artifact(artifact, sources,
                hashlib.sha256(artifact.read_bytes()).hexdigest())
            self.assertEqual(proof["verified_source_count"], 9)

    def test_rejects_changed_original_or_inventory_hash(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            sources = self._fixture_sources(Path(temporary))
            sources[0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "existing SHA-256 inventory"):
                roadlinks.analyze(sources)


if __name__ == "__main__":
    unittest.main()
