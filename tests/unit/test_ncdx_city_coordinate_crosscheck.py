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

from src.readers import ncdx_city_coordinate_crosscheck as crosscheck


def _logical(type_id: int, count: int, stride: int, records: bytes) -> bytes:
    header = bytearray(94)
    header[:7] = b"SIEMENS"
    struct.pack_into("<H", header, 84, type_id)
    struct.pack_into("<I", header, 86, count)
    struct.pack_into("<I", header, 90, len(records))
    return bytes(header) + records


def _container(logical: bytes, block_size: int = 256) -> bytes:
    blocks = [logical[offset:offset + block_size]
              for offset in range(0, len(logical), block_size)]
    table_end = 16 + 4 * (len(blocks) + 1)
    payloads = [zlib.compress(block) for block in blocks]
    offsets = [table_end]
    for payload in payloads:
        offsets.append(offsets[-1] + len(payload))
    return (b"zip\x01" + struct.pack("<III", block_size, len(logical), 0)
            + struct.pack(f"<{len(offsets)}I", *offsets) + b"".join(payloads))


class NcdxCityCoordinateCrosscheckTests(unittest.TestCase):
    def _fixture(self, root: Path):
        sources = []
        candidates = []
        for region, lat, lon in (("SW", 50.0, 10.0), ("Scandinavia", 60.0, 10.0)):
            cny = bytearray(174)
            struct.pack_into("<H", cny, 0, 0)
            cny[30:41] = b"Test region"
            cty = bytearray(178)
            struct.pack_into("<II", cty, 0, 0, 0)
            struct.pack_into("<iiii", cty, 18,
                int((lon - 1) * 100000), int((lat - 1) * 100000),
                int((lon + 1) * 100000), int((lat + 1) * 100000))
            cty[34:44] = b"Test city\0"
            files = {"CTY": _container(_logical(3, 1, 178, bytes(cty))),
                     "CNY": _container(_logical(12, 1, 174, bytes(cny)))}
            coords = b"".join(struct.pack("<ii", int((lat + i * 0.01) * 1_000_000),
                                           int((lon + i * 0.01) * 1_000_000))
                              for i in range(4))
            offset = 8
            files["MG1"] = b"header!!" + zlib.compress(coords) + b"tail"
            for table, data in files.items():
                relative = f"{region}/{region}.{table}"
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                sources.append({"region": region, "relative_path": relative,
                    "absolute_path": str(path), "size_bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            stream = zlib.compress(coords)
            self.assertEqual(files["MG1"][offset:offset + len(stream)], stream)
            prior_task_id = f"prior_{region}"
            relative = f"{region}/{region}.MG1"
            map_source = next(row for row in sources
                              if row["region"] == region and row["relative_path"] == relative)
            summary = {"stream_index": 0, "source_offset": offset,
                "compressed_bytes": len(stream), "decompressed_bytes": len(coords),
                "decompressed_sha256": hashlib.sha256(coords).hexdigest(),
                "candidate_measurements": [{"measurement": crosscheck.MEASUREMENT,
                    "region_candidate_pairs": 4, "adjacent_pairs_within_5km": 3}]}
            prior = {"status": "PASS", "task_id": prior_task_id,
                "profile_mode": "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS",
                "observations": [{"region": region, "relative_path": relative,
                    "source_sha256": map_source["sha256"], "stream_count": 1,
                    "stream_inventory_sha256": "a" * 64,
                    "candidate_stream_summaries": [summary],
                    "selected_full_payload_audit": {"selected_streams": [{"stream_index": 0,
                        "full_payload_sha256": summary["decompressed_sha256"]}]}}]}
            prior_path = root / f"{prior_task_id}.json"
            prior_path.write_text(json.dumps(prior), encoding="utf-8")
            candidates.append({"region": region, "prior_task_id": prior_task_id,
                "prior_artifact_path": str(prior_path),
                "prior_artifact_sha256": hashlib.sha256(prior_path.read_bytes()).hexdigest(),
                "map_relative_path": relative, "map_sha256": map_source["sha256"],
                "stream_count": 1, "stream_inventory_sha256": "a" * 64,
                "stream_index": 0, "source_offset": offset,
                "compressed_bytes": len(stream), "decompressed_bytes": len(coords),
                "decompressed_sha256": hashlib.sha256(coords).hexdigest(),
                "measurement": crosscheck.MEASUREMENT, "prior_adjacent_pairs": 3})
        return sources, candidates

    def test_replays_two_selected_streams_against_manifest_bound_city_boxes(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            sources, candidates = self._fixture(root)
            result = crosscheck.analyze(sources, candidates)
            self.assertEqual(result["hypothesis_result"], "SUPPORTED")
            self.assertEqual(len(result["regions"]), 2)
            self.assertTrue(all(all(row["checks"].values()) for row in result["regions"]))
            artifact = root / "crosscheck.json"
            artifact.write_text(json.dumps(result), encoding="utf-8")
            proof = crosscheck.verify_artifact(artifact, sources, candidates,
                hashlib.sha256(artifact.read_bytes()).hexdigest())
            self.assertEqual(proof["verified_source_count"], 6)

    def test_rejects_modified_prior_census_artifact(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            sources, candidates = self._fixture(root)
            Path(candidates[0]["prior_artifact_path"]).write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "prior accepted coordinate report hash changed"):
                crosscheck.analyze(sources, candidates)

    def test_replays_novel_italy_100k_lon_lat_stream_against_city_boxes(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            region = "Italy"
            lat, lon = 41.90, 12.50
            cny = bytearray(174)
            cny[30:42] = b"Test region\0"
            cty = bytearray(178)
            struct.pack_into("<II", cty, 0, 0, 0)
            struct.pack_into("<iiii", cty, 18,
                int((lon - 0.05) * 100000), int((lat - 0.05) * 100000),
                int((lon + 0.05) * 100000), int((lat + 0.05) * 100000))
            cty[34:44] = b"Test city\0"
            records = {"CTY": _container(_logical(3, 1, 178, bytes(cty))),
                       "CNY": _container(_logical(12, 1, 174, bytes(cny)))}
            measurement = "alignment_6/scale_100000_lon_lat"
            payload = b"\0" * 6 + b"".join(
                struct.pack("<ii", int((lon + index * 0.001) * 100000),
                            int((lat + index * 0.001) * 100000))
                for index in range(4))
            stream = zlib.compress(payload)
            offset = 8
            records["MG1"] = b"header!!" + stream + b"tail"
            sources = []
            for table, data in records.items():
                relative = f"Italy/IZ.{table}"
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                sources.append({"region": region, "relative_path": relative,
                    "absolute_path": str(path), "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()})
            mg1 = next(row for row in sources if row["relative_path"].endswith(".MG1"))
            payload_sha = hashlib.sha256(payload).hexdigest()
            prior_task_id = "prior_italy"
            summary = {"stream_index": 3001, "source_offset": offset,
                "compressed_bytes": len(stream), "decompressed_bytes": len(payload),
                "decompressed_sha256": payload_sha,
                "candidate_measurements": [{"measurement": measurement,
                    "region_candidate_pairs": 4, "adjacent_pairs_within_5km": 3}]}
            prior = {"status": "PASS", "task_id": prior_task_id,
                "profile_mode": "ZLIB_DECODED_COORDINATE_CANDIDATE_CENSUS",
                "observations": [{"region": region, "relative_path": "Italy/IZ.MG1",
                    "source_sha256": mg1["sha256"], "stream_count": 1,
                    "stream_inventory_sha256": "a" * 64,
                    "candidate_stream_summaries": [summary],
                    "selected_full_payload_audit": {"selected_streams": [
                        {"stream_index": 3001, "full_payload_sha256": payload_sha}]}}]}
            prior_path = root / "prior_italy.json"
            prior_path.write_text(json.dumps(prior), encoding="utf-8")
            prior_sha = hashlib.sha256(prior_path.read_bytes()).hexdigest()
            candidates = [{"region": region, "prior_task_id": prior_task_id,
                "prior_artifact_path": str(prior_path), "prior_artifact_sha256": prior_sha,
                "map_relative_path": "Italy/IZ.MG1", "map_sha256": mg1["sha256"],
                "stream_count": 1, "stream_inventory_sha256": "a" * 64,
                "stream_index": 3001, "source_offset": offset,
                "compressed_bytes": len(stream), "decompressed_bytes": len(payload),
                "decompressed_sha256": payload_sha, "measurement": measurement,
                "prior_adjacent_pairs": 3}]
            result = crosscheck.analyze(sources, candidates)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["hypothesis_result"], "SUPPORTED")
            self.assertEqual(result["regions"][0]["region"], region)
            self.assertEqual(result["regions"][0]["coordinate_association"][
                "points_inside_cty_city_bounding_boxes"], 4)
            artifact = root / "italy-crosscheck.json"
            artifact.write_text(json.dumps(result), encoding="utf-8")
            proof = crosscheck.verify_artifact(artifact, sources, candidates,
                hashlib.sha256(artifact.read_bytes()).hexdigest())
            self.assertEqual(proof["verified_source_count"], 3)


if __name__ == "__main__":
    unittest.main()
