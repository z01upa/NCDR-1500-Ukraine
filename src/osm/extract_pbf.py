"""Filter a regional OSM PBF to a bounded city extract using PyOsmium.

This consumes an already downloaded regional extract; it does not contact any
service. The PBF remains an immutable source. Only roads and tagged map
features intersecting the configured bbox plus their referenced nodes are
written to the compressed XML working extract.
"""

from __future__ import annotations

from contextlib import closing
import gzip
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any
import xml.etree.ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS = PROJECT_ROOT / "build" / "osmium_runtime"
if TOOLS.exists():
    sys.path.insert(0, str(TOOLS))

try:
    import osmium
except ImportError as exc:
    raise RuntimeError("PyOsmium is not installed. Install the free wheel into build/osmium_runtime first.") from exc

from src.osm.engine import MAP_WAY_TAGS


class PbfExtractError(RuntimeError):
    pass


def _tags(obj: Any) -> dict[str, str]:
    return {str(tag.k): str(tag.v) for tag in obj.tags}


def _inside(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    south, west, north, east = bbox
    return south <= lat <= north and west <= lon <= east


def _node_xml(node_id: str, lat: float, lon: float, tags: dict[str, str]) -> bytes:
    element = ET.Element("node", {"id": node_id, "lat": f"{lat:.7f}", "lon": f"{lon:.7f}"})
    for key, value in sorted(tags.items()):
        ET.SubElement(element, "tag", {"k": key, "v": value})
    return ET.tostring(element, encoding="utf-8", short_empty_elements=True)


def _way_xml(way_id: str, refs: list[str], tags: dict[str, str]) -> bytes:
    element = ET.Element("way", {"id": way_id})
    for ref in refs:
        ET.SubElement(element, "nd", {"ref": ref})
    for key, value in sorted(tags.items()):
        ET.SubElement(element, "tag", {"k": key, "v": value})
    return ET.tostring(element, encoding="utf-8", short_empty_elements=True)


def extract_city(source_pbf: str | Path, destination_xml_gz: str | Path,
                 bbox: tuple[float, float, float, float] = (47.58, 32.50, 48.23, 33.95)) -> dict[str, Any]:
    source = Path(source_pbf).resolve(strict=True)
    destination = Path(destination_xml_gz).resolve()
    if source == destination:
        raise ValueError("source PBF and output XML must be different files")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite extract: {destination}")
    south, west, north, east = bbox
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError("invalid south,west,north,east bbox")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_before = source.stat()
    whole_source = bbox == (-90.0, -180.0, 90.0, 180.0)
    work_handle, work_name = tempfile.mkstemp(prefix="ncdr-osm-extract-", suffix=".sqlite", dir=destination.parent)
    os.close(work_handle)
    work = Path(work_name)
    counters = {"nodes_in_bbox": 0, "selected_ways": 0, "nodes_written": 0}
    try:
        with closing(sqlite3.connect(work)) as conn:
            conn.executescript("""
              PRAGMA journal_mode=OFF;
              PRAGMA synchronous=OFF;
              CREATE TABLE nodes(id TEXT PRIMARY KEY,lat REAL NOT NULL,lon REAL NOT NULL,tags_json TEXT NOT NULL);
              CREATE TABLE ways(id TEXT PRIMARY KEY,refs_json TEXT NOT NULL,tags_json TEXT NOT NULL);
            """)
            # The city path keeps only a bounded set of referenced nodes. The
            # country path uses the temporary SQLite index instead of Python
            # sets: a whole-country OSM extract can contain millions of IDs.
            inside_ids: set[int] = set()
            wanted_ids: set[int] = set()
            class FirstPass(osmium.SimpleHandler):
                def node(self, node: Any) -> None:
                    if not node.location.valid():
                        return
                    lat, lon = float(node.location.lat), float(node.location.lon)
                    if not _inside(lat, lon, bbox):
                        return
                    node_id = int(node.id)
                    if not whole_source:
                        inside_ids.add(node_id)
                    tags = _tags(node)
                    conn.execute("INSERT OR REPLACE INTO nodes VALUES(?,?,?,?)",
                                 (str(node_id), lat, lon, json.dumps(tags, ensure_ascii=False, sort_keys=True)))
                    if tags and not whole_source:
                        wanted_ids.add(node_id)
                    counters["nodes_in_bbox"] += 1
                    if counters["nodes_in_bbox"] % (100_000 if whole_source else 5000) == 0:
                        conn.commit()

                def way(self, way: Any) -> None:
                    refs = [int(node.ref) for node in way.nodes]
                    tags = _tags(way)
                    if whole_source:
                        # Keep map-bearing ways and address objects for the
                        # national preparation database; do not infer payload
                        # or target-device semantics from these OSM tags.
                        relevant = any(key in MAP_WAY_TAGS or key.startswith("addr:") for key in tags)
                        if not refs or not relevant:
                            return
                    elif not refs or not any(ref in inside_ids for ref in refs):
                        return
                    conn.execute("INSERT OR REPLACE INTO ways VALUES(?,?,?)",
                                 (str(int(way.id)), json.dumps([str(ref) for ref in refs]),
                                  json.dumps(tags, ensure_ascii=False, sort_keys=True)))
                    if not whole_source:
                        wanted_ids.update(refs)
                    counters["selected_ways"] += 1
                    if counters["selected_ways"] % (50_000 if whole_source else 2000) == 0:
                        conn.commit()

            first = FirstPass()
            # PBF nodes carry coordinates directly; no way-location index is
            # needed for this pass, avoiding a second full-country RAM index.
            first.apply_file(str(source), locations=False)
            conn.commit()
            if not whole_source and not inside_ids:
                raise PbfExtractError("no OSM nodes fell inside the configured bbox")
            if whole_source:
                counters["nodes_written"] = counters["nodes_in_bbox"]
            else:
                class NodeReadback(osmium.SimpleHandler):
                    def node(self, node: Any) -> None:
                        node_id = int(node.id)
                        if node_id not in wanted_ids or not node.location.valid():
                            return
                        tags = _tags(node)
                        conn.execute("INSERT OR REPLACE INTO nodes VALUES(?,?,?,?)",
                                     (str(node_id), float(node.location.lat), float(node.location.lon),
                                      json.dumps(tags, ensure_ascii=False, sort_keys=True)))
                        counters["nodes_written"] += 1
                        if counters["nodes_written"] % 5000 == 0:
                            conn.commit()

                second = NodeReadback()
                second.apply_file(str(source), locations=False)
                conn.commit()
            missing = conn.execute("""SELECT count(*) FROM ways w, json_each(w.refs_json) r
                 LEFT JOIN nodes n ON n.id=r.value WHERE n.id IS NULL""").fetchone()[0]
            if missing:
                raise PbfExtractError(f"{missing} selected way-node references are missing after second pass")
            temporary_output = destination.with_name(destination.name + ".part")
            with gzip.open(temporary_output, "wb", compresslevel=6) as out:
                out.write(b'<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="NCDR local PBF extract">\n')
                # OSM XML requires nodes before ways, but does not require IDs
                # to be sorted. Avoid a full-country external sort here.
                for row in conn.execute("SELECT id,lat,lon,tags_json FROM nodes"):
                    out.write(_node_xml(row[0], row[1], row[2], json.loads(row[3])))
                    out.write(b"\n")
                for row in conn.execute("SELECT id,refs_json,tags_json FROM ways"):
                    out.write(_way_xml(row[0], json.loads(row[1]), json.loads(row[2])))
                    out.write(b"\n")
                out.write(b"</osm>\n")
            temporary_output.replace(destination)
        source_after = source.stat()
        if (source_before.st_size, source_before.st_mtime_ns) != (source_after.st_size, source_after.st_mtime_ns):
            destination.unlink(missing_ok=True)
            raise PbfExtractError("source PBF changed during read-only filtering")
        return {"source_pbf": str(source), "source_bytes": source_before.st_size,
            "extract_xml_gz": str(destination), "extract_bytes": destination.stat().st_size,
            "bbox_south_west_north_east": [south, west, north, east], **counters,
            "selected_relations": 0,
            "whole_source": whole_source,
            "limitation": "Relations, including turn restrictions, are not exported by this first-pass map extractor."}
    except BaseException:
        destination.with_name(destination.name + ".part").unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    finally:
        work.unlink(missing_ok=True)

