from __future__ import annotations

import gzip
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from src.osm import extract_pbf


class _Location:
    def __init__(self, lat: float, lon: float):
        self.lat, self.lon = lat, lon

    def valid(self) -> bool:
        return True


class _Tag:
    def __init__(self, key: str, value: str):
        self.k, self.v = key, value


class _Node:
    def __init__(self, node_id: int, lat: float, lon: float, tags: dict[str, str] | None = None):
        self.id, self.location = node_id, _Location(lat, lon)
        self.tags = [_Tag(key, value) for key, value in (tags or {}).items()]


class _WayNode:
    def __init__(self, ref: int):
        self.ref = ref


class _Way:
    def __init__(self, way_id: int, refs: list[int], tags: dict[str, str]):
        self.id, self.nodes = way_id, [_WayNode(ref) for ref in refs]
        self.tags = [_Tag(key, value) for key, value in tags.items()]


class _Handler:
    def apply_file(self, _path: str, locations: bool = False) -> None:
        for node in (_Node(1, 47.9, 33.4), _Node(2, 47.91, 33.41), _Node(3, 50.45, 30.52)):
            if hasattr(self, "node"):
                self.node(node)
        for way in (_Way(10, [1, 2], {"highway": "residential", "name": "Вулиця Тестова"}),
                    _Way(11, [2, 3], {"custom:tag": "outside-map-schema"})):
            if hasattr(self, "way"):
                self.way(way)


class WholeSourceExtractorTests(unittest.TestCase):
    def test_country_mode_uses_database_path_and_keeps_only_map_ways(self) -> None:
        with tempfile.TemporaryDirectory(dir=extract_pbf.PROJECT_ROOT / "work") as folder:
            root = Path(folder)
            source = root / "source.pbf"
            source.write_bytes(b"fake PBF fixture; reader is replaced")
            before = source.read_bytes()
            output = root / "whole.osm.gz"
            fake_osmium = types.SimpleNamespace(SimpleHandler=_Handler)
            with patch.object(extract_pbf, "osmium", fake_osmium):
                report = extract_pbf.extract_city(source, output, (-90.0, -180.0, 90.0, 180.0))
            self.assertTrue(report["whole_source"])
            self.assertEqual(report["nodes_written"], 3)
            self.assertEqual(report["selected_ways"], 1)
            self.assertEqual(source.read_bytes(), before)
            with gzip.open(output, "rb") as stream:
                root_xml = ET.fromstring(stream.read())
            self.assertEqual(len(root_xml.findall("node")), 3)
            ways = root_xml.findall("way")
            self.assertEqual([way.attrib["id"] for way in ways], ["10"])
            self.assertEqual([ref.attrib["ref"] for ref in ways[0].findall("nd")], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
