from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import coordinator_runtime, mission_pack
from src.readers.ncdx_region_diff import analyze_ncdx_region_diff


def _container(logical: bytes, block_size: int = 256) -> bytes:
    blocks = [logical[i:i + block_size] for i in range(0, len(logical), block_size)]
    compressed = [zlib.compress(block) for block in blocks]
    table_end = 16 + 4 * (len(blocks) + 1)
    offsets = [table_end]
    for blob in compressed:
        offsets.append(offsets[-1] + len(blob))
    return (struct.pack("<4sIII", b"zip\x01", block_size, len(logical), 0)
            + struct.pack(f"<{len(offsets)}I", *offsets) + b"".join(compressed))


def _fixture_regions(root: Path) -> None:
    codes = {"EUZ": b"EU44420940.82", "IZ": b"I44431940.82", "SCZ": b"SC44442940.82"}
    type_ids = {"CTY": 3, "CNY": 12, "RL": 21, "IOF": 21, "IL": 20}
    strides = {"CTY": 178, "CNY": 174, "RL": 61, "IOF": 6, "IL": 128}
    for index, (_label, folder, prefix) in enumerate(coordinator_runtime.REGIONS, 1):
        directory = root / folder
        directory.mkdir(parents=True, exist_ok=True)
        for suffix in ("MP0", "MG1", "MG2", "MG3"):
            raw = bytearray([index]) * 8192
            if suffix == "MP0":
                raw[:13] = b"(*$SIEMENS&^)"
                raw[16:32] = b"Copyright 1998\0\0"
                raw[32:48] = b"2.0.0\0" + bytes(10)
                raw[48:64] = codes[prefix] + b"\0" * (16 - len(codes[prefix]))
            struct.pack_into("<HI", raw, 84, 7, 1)
            (directory / f"{prefix}.{suffix}").write_bytes(raw)
        for suffix, type_id in type_ids.items():
            logical = bytearray([index]) * (94 + strides[suffix])
            struct.pack_into("<HI", logical, 84, type_id, 1)
            (directory / f"{prefix}.{suffix}").write_bytes(_container(bytes(logical)))


class NcdxRegionDiffTests(unittest.TestCase):
    def test_bounded_three_region_diff_is_reproducible_and_independently_verified(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp:
            base = Path(temp)
            source_root = base / "source"
            project_root = base / "project"
            source_root.mkdir()
            project_root.mkdir()
            _fixture_regions(source_root)
            analysis = analyze_ncdx_region_diff(source_root=source_root,
                regions=coordinator_runtime.REGIONS, sample_bytes=1024, block_bytes=256)
            report = {"canonical_id": "B02", "status": "PASS", **analysis}
            evidence = project_root / "region-diff-records.json"
            evidence.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            verified = mission_pack.verify_b02_region_diff_records(evidence,
                source_root=source_root, project_root=project_root, require_prior_evidence=False)

        self.assertEqual(analysis["status"], "PASS")
        self.assertEqual(len(analysis["families"]), 9)
        self.assertEqual(verified["b02_independent_source_verification"], "PASS")
        self.assertEqual(verified["b02_verified_source_count"], 27)
        self.assertEqual(verified["b02_original_media_write_count"], 0)

    def test_analysis_rejects_source_path_escape_and_unbounded_sampling(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temp:
            root = Path(temp)
            _fixture_regions(root)
            with self.assertRaisesRegex(ValueError, "sample bound"):
                analyze_ncdx_region_diff(source_root=root, regions=coordinator_runtime.REGIONS,
                                         sample_bytes=8 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
