"""Offline OSM XML import, local search, and shortest-path routing.

This module handles the documented OSM XML format only. It preserves every
source tag as JSON and keeps OSM identifiers on all imported objects. It does
not know or imply any NCDR binary/export format.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import unicodedata
from typing import Any, Iterator
import xml.etree.ElementTree as ET


IMPORTER_VERSION = "0.1.0"
EARTH_RADIUS_M = 6_371_008.8
MAP_WAY_TAGS = {
    "highway", "building", "landuse", "natural", "waterway", "leisure",
    "railway", "barrier", "amenity", "tourism", "boundary",
}
CAR_EXCLUDED_HIGHWAYS = {
    "bridleway", "cycleway", "corridor", "elevator", "footway", "path",
    "pedestrian", "platform", "steps",
}
POI_KEYS = {
    "amenity", "shop", "tourism", "leisure", "healthcare", "office",
    "public_transport", "historic", "craft", "emergency", "sport",
    "club", "man_made",
}


@dataclass(frozen=True)
class ImportSummary:
    source_path: str
    source_sha256: str
    database_path: str
    node_count: int
    way_count: int
    relation_count: int
    routable_way_count: int
    directed_edge_count: int
    feature_count: int
    address_count: int
    poi_count: int
    unresolved_node_refs: int


@dataclass(frozen=True)
class SearchResult:
    element_type: str
    element_id: str
    kind: str
    name: str
    category: str | None
    latitude: float | None
    longitude: float | None
    address: str | None
    tags: dict[str, str]


@dataclass(frozen=True)
class RouteResult:
    node_ids: tuple[str, ...]
    way_ids: tuple[str, ...]
    distance_m: float
    profile: str
    limitations: tuple[str, ...] = ()


def normalize_name(value: str) -> str:
    """Return a search key while leaving the original OSM value untouched."""
    value = unicodedata.normalize("NFC", value).casefold().strip()
    chars: list[str] = []
    for char in value:
        if unicodedata.category(char).startswith("P") or char.isspace():
            chars.append(" ")
        else:
            chars.append(char)
    return " ".join("".join(chars).split())


def _name_values(tags: dict[str, str]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for key in ("name", "name:uk", "official_name", "short_name", "loc_name", "old_name"):
        value = tags.get(key, "").strip()
        if value:
            result.append((value, key))
    for key in ("alt_name", "alt_name:uk", "name:alt", "name:ru", "name:en"):
        value = tags.get(key, "").strip()
        if value:
            for part in value.replace("|", ";").split(";"):
                if part.strip():
                    result.append((part.strip(), key))
    street = tags.get("addr:street", "").strip()
    house = tags.get("addr:housenumber", "").strip()
    city = tags.get("addr:city", tags.get("addr:place", "")).strip()
    address = " ".join(part for part in (street, house, city) if part)
    if address:
        result.append((address, "address"))
    # Keep insertion order and avoid duplicate searchable aliases.
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for value, source in result:
        normalized = normalize_name(value)
        if normalized and normalized not in seen:
            unique.append((value, source))
            seen.add(normalized)
    return unique


def _tags(element: ET.Element) -> dict[str, str]:
    return {child.attrib["k"]: child.attrib["v"] for child in element if _local_name(child.tag) == "tag" and "k" in child.attrib and "v" in child.attrib}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _open_xml(path: Path):
    return gzip.open(path, "rb") if path.suffix.casefold() == ".gz" else path.open("rb")


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE nodes(
          id TEXT PRIMARY KEY, latitude REAL NOT NULL, longitude REAL NOT NULL,
          tags_json TEXT NOT NULL
        );
        CREATE INDEX idx_nodes_lat_lon ON nodes(latitude, longitude);
        CREATE TABLE ways(id TEXT PRIMARY KEY, tags_json TEXT NOT NULL);
        CREATE TABLE way_nodes(
          way_id TEXT NOT NULL, node_index INTEGER NOT NULL, node_id TEXT NOT NULL,
          PRIMARY KEY(way_id,node_index)
        );
        CREATE INDEX idx_way_nodes_node ON way_nodes(node_id);
        CREATE TABLE edges(
          way_id TEXT NOT NULL, segment_index INTEGER NOT NULL,
          from_node TEXT NOT NULL, to_node TEXT NOT NULL,
          distance_m REAL NOT NULL, highway TEXT NOT NULL,
          oneway INTEGER NOT NULL, tags_json TEXT NOT NULL,
          PRIMARY KEY(way_id,segment_index,from_node,to_node)
        );
        CREATE INDEX idx_edges_from ON edges(from_node);
        CREATE INDEX idx_edges_to ON edges(to_node);
        CREATE TABLE relations(
          id TEXT PRIMARY KEY, tags_json TEXT NOT NULL, members_json TEXT NOT NULL
        );
        CREATE TABLE features(
          element_type TEXT NOT NULL, element_id TEXT NOT NULL,
          kind TEXT NOT NULL, name TEXT NOT NULL, category TEXT,
          latitude REAL, longitude REAL, address TEXT,
          tags_json TEXT NOT NULL,
          PRIMARY KEY(element_type,element_id)
        );
        CREATE INDEX idx_features_kind ON features(kind);
        CREATE TABLE feature_names(
          element_type TEXT NOT NULL, element_id TEXT NOT NULL,
          original_name TEXT NOT NULL, normalized_name TEXT NOT NULL,
          source_key TEXT NOT NULL,
          PRIMARY KEY(element_type,element_id,normalized_name)
        );
        CREATE INDEX idx_feature_names_normalized ON feature_names(normalized_name);
        """
    )


def _feature_kind(tags: dict[str, str]) -> str | None:
    has_address = any(key.startswith("addr:") for key in tags)
    has_poi = any(key in tags for key in POI_KEYS)
    if has_address and has_poi:
        return "poi+address"
    if has_address:
        return "address"
    if has_poi:
        return "poi"
    # Named road ways are searchable features too. Keep their raw tags in the
    # same feature table so address/POI/street lookup shares one API.
    if tags.get("highway") and _name_values(tags):
        return "street"
    return None


def _feature_category(tags: dict[str, str]) -> str | None:
    for key in sorted(POI_KEYS):
        if tags.get(key):
            return f"{key}={tags[key]}"
    return None


def _format_address(tags: dict[str, str]) -> str | None:
    street = tags.get("addr:street", "").strip()
    house = tags.get("addr:housenumber", "").strip()
    place = tags.get("addr:place", "").strip()
    city = tags.get("addr:city", "").strip()
    locality = street or place
    value = " ".join(part for part in (locality, house, city) if part)
    return value or None


def _insert_feature(
    conn: sqlite3.Connection,
    element_type: str,
    element_id: str,
    tags: dict[str, str],
    latitude: float | None,
    longitude: float | None,
) -> bool:
    kind = _feature_kind(tags)
    if not kind:
        return False
    name = tags.get("name:uk") or tags.get("name") or tags.get("addr:street") or tags.get("addr:place") or ""
    category = _feature_category(tags)
    address = _format_address(tags)
    conn.execute(
        "INSERT OR REPLACE INTO features VALUES(?,?,?,?,?,?,?,?,?)",
        (element_type, element_id, kind, name, category, latitude, longitude, address,
         json.dumps(tags, ensure_ascii=False, sort_keys=True)),
    )
    for original, source_key in _name_values(tags):
        normalized = normalize_name(original)
        if normalized:
            conn.execute(
                "INSERT OR IGNORE INTO feature_names VALUES(?,?,?,?,?)",
                (element_type, element_id, original, normalized, source_key),
            )
    return True


def _centroid(conn: sqlite3.Connection, node_ids: list[str]) -> tuple[float | None, float | None, int]:
    coords: list[tuple[float, float]] = []
    missing = 0
    for node_id in node_ids:
        row = conn.execute("SELECT latitude,longitude FROM nodes WHERE id=?", (node_id,)).fetchone()
        if row:
            coords.append((float(row[0]), float(row[1])))
        else:
            missing += 1
    if not coords:
        return None, None, missing
    return sum(lat for lat, _ in coords) / len(coords), sum(lon for _, lon in coords) / len(coords), missing


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _is_accessible(tags: dict[str, str], profile: str) -> bool:
    highway = tags.get("highway", "")
    if profile != "car":
        raise ValueError("only the experimental 'car' routing profile is implemented")
    if highway in CAR_EXCLUDED_HIGHWAYS:
        return False
    if tags.get("access", "").casefold() in {"no", "private"}:
        return False
    if any(tags.get(key, "").casefold() in {"no", "private"} for key in ("motorcar", "motor_vehicle", "vehicle")):
        return False
    return True


def _oneway_mode(tags: dict[str, str]) -> int:
    value = tags.get("oneway", "").casefold()
    if value in {"yes", "true", "1"} or (not value and (tags.get("junction") == "roundabout" or tags.get("highway") == "motorway")):
        return 1
    if value == "-1":
        return -1
    return 0


def import_osm_xml(source_path: str | Path, database_path: str | Path) -> ImportSummary:
    """Atomically import a plain or gzip-compressed OSM XML file into SQLite.

    The input is only read. Existing destination files are always refused;
    successful imports are published with an atomic no-clobber hard link.
    """
    source = Path(source_path).resolve()
    destination = Path(database_path).resolve()
    if source == destination:
        raise ValueError("OSM XML input and SQLite output must be different files")
    if not source.is_file():
        raise FileNotFoundError(source)
    if destination.suffix.casefold() not in {".sqlite", ".db"}:
        raise ValueError("SQLite output must use a .sqlite or .db extension")
    if destination.exists():
        raise FileExistsError(f"refusing to replace an existing file: {destination}; choose a new derived-data path")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = _source_hash(source)
    node_count = way_count = relation_count = feature_count = address_count = poi_count = 0
    routable_way_count = directed_edge_count = unresolved_node_refs = 0

    with tempfile.TemporaryDirectory(prefix="osm-import-", dir=destination.parent) as temp_dir:
        staged = Path(temp_dir) / "import.sqlite"
        conn = sqlite3.connect(staged)
        try:
            _schema(conn)
            root: ET.Element | None = None
            with _open_xml(source) as stream:
                for event, element in ET.iterparse(stream, events=("start", "end")):
                    if event == "start":
                        if root is None:
                            root = element
                        continue
                    element_type = _local_name(element.tag)
                    if element_type == "node":
                        node_id = element.attrib.get("id")
                        if node_id is None:
                            if root is not None:
                                root.remove(element)
                            element.clear()
                            continue
                        try:
                            latitude = float(element.attrib["lat"])
                            longitude = float(element.attrib["lon"])
                        except (KeyError, ValueError) as exc:
                            raise ValueError(f"OSM node {node_id} has invalid coordinates") from exc
                        tags = _tags(element)
                        conn.execute(
                            "INSERT OR REPLACE INTO nodes VALUES(?,?,?,?)",
                            (node_id, latitude, longitude, json.dumps(tags, ensure_ascii=False, sort_keys=True)),
                        )
                        if _insert_feature(conn, "node", node_id, tags, latitude, longitude):
                            feature_count += 1
                            address_count += int(_feature_kind(tags) in {"address", "poi+address"})
                            poi_count += int(_feature_kind(tags) in {"poi", "poi+address"})
                        node_count += 1
                        if root is not None:
                            root.remove(element)
                    elif element_type == "way":
                        way_id = element.attrib.get("id")
                        if way_id is None:
                            if root is not None:
                                root.remove(element)
                            element.clear()
                            continue
                        tags = _tags(element)
                        refs = [child.attrib["ref"] for child in element if _local_name(child.tag) == "nd" and "ref" in child.attrib]
                        conn.execute("INSERT OR REPLACE INTO ways VALUES(?,?)", (way_id, json.dumps(tags, ensure_ascii=False, sort_keys=True)))
                        conn.executemany("INSERT OR REPLACE INTO way_nodes VALUES(?,?,?)", ((way_id, index, ref) for index, ref in enumerate(refs)))
                        way_count += 1
                        if root is not None:
                            root.remove(element)
                    elif element_type == "relation":
                        relation_id = element.attrib.get("id")
                        if relation_id is None:
                            if root is not None:
                                root.remove(element)
                            element.clear()
                            continue
                        tags = _tags(element)
                        members = [
                            {key: child.attrib[key] for key in ("type", "ref", "role") if key in child.attrib}
                            for child in element if _local_name(child.tag) == "member"
                        ]
                        conn.execute(
                            "INSERT OR REPLACE INTO relations VALUES(?,?,?)",
                            (relation_id, json.dumps(tags, ensure_ascii=False, sort_keys=True), json.dumps(members, ensure_ascii=False, sort_keys=True)),
                        )
                        relation_count += 1
                        if root is not None:
                            root.remove(element)
                    elif element_type == "bounds" and root is not None:
                        root.remove(element)
            # Resolve way and relation centroids after all nodes have been read.
            # This tolerates valid-but-unusual XML ordering and keeps provenance.
            for way_id, tags_json in conn.execute("SELECT id,tags_json FROM ways ORDER BY id"):
                tags = json.loads(tags_json)
                # Most mapped ways are neither named nor address/POI records.
                # Avoid one way-node query per such way on national extracts.
                if _feature_kind(tags) is None:
                    continue
                refs = [row[0] for row in conn.execute("SELECT node_id FROM way_nodes WHERE way_id=? ORDER BY node_index", (way_id,))]
                centroid_lat, centroid_lon, _missing = _centroid(conn, refs)
                if _insert_feature(conn, "way", way_id, tags, centroid_lat, centroid_lon):
                    feature_count += 1
                    address_count += int(_feature_kind(tags) in {"address", "poi+address"})
                    poi_count += int(_feature_kind(tags) in {"poi", "poi+address"})
            for relation_id, tags_json, members_json in conn.execute("SELECT id,tags_json,members_json FROM relations ORDER BY id"):
                tags = json.loads(tags_json)
                members = json.loads(members_json)
                member_nodes: list[str] = []
                for member in members:
                    if member.get("type") == "node":
                        member_nodes.append(member.get("ref", ""))
                    elif member.get("type") == "way":
                        member_nodes.extend(row[0] for row in conn.execute(
                            "SELECT node_id FROM way_nodes WHERE way_id=? ORDER BY node_index", (member.get("ref", ""),)
                        ))
                centroid_lat, centroid_lon, _missing = _centroid(conn, member_nodes)
                if _insert_feature(conn, "relation", relation_id, tags, centroid_lat, centroid_lon):
                    feature_count += 1
                    address_count += int(_feature_kind(tags) in {"address", "poi+address"})
                    poi_count += int(_feature_kind(tags) in {"poi", "poi+address"})
            unresolved_node_refs = conn.execute(
                """SELECT count(*) FROM way_nodes wn LEFT JOIN nodes n ON n.id=wn.node_id
                   WHERE n.id IS NULL"""
            ).fetchone()[0]
            # Build directed routable segments after all node records exist.
            for way_id, tags_json in conn.execute("SELECT id,tags_json FROM ways ORDER BY id"):
                tags = json.loads(tags_json)
                if not tags.get("highway"):
                    continue
                try:
                    if not _is_accessible(tags, "car"):
                        continue
                except ValueError:
                    continue
                refs = [row[0] for row in conn.execute("SELECT node_id FROM way_nodes WHERE way_id=? ORDER BY node_index", (way_id,))]
                if len(refs) < 2:
                    continue
                mode = _oneway_mode(tags)
                inserted = 0
                for segment_index, (first, second) in enumerate(zip(refs, refs[1:])):
                    first_row = conn.execute("SELECT latitude,longitude FROM nodes WHERE id=?", (first,)).fetchone()
                    second_row = conn.execute("SELECT latitude,longitude FROM nodes WHERE id=?", (second,)).fetchone()
                    if not first_row or not second_row:
                        continue
                    distance = _haversine_m(float(first_row[0]), float(first_row[1]), float(second_row[0]), float(second_row[1]))
                    edges = [(first, second)] if mode >= 0 else []
                    if mode <= 0:
                        edges.append((second, first))
                    if mode == -1:
                        edges = [(second, first)]
                    for from_node, to_node in edges:
                        conn.execute(
                            "INSERT OR IGNORE INTO edges VALUES(?,?,?,?,?,?,?,?)",
                            (way_id, segment_index, from_node, to_node, distance, tags["highway"], mode, tags_json),
                        )
                        inserted += 1
                if inserted:
                    routable_way_count += 1
                    directed_edge_count += inserted
            now = datetime.now(timezone.utc).isoformat()
            metadata = {
                "source_path": str(source),
                "source_sha256": digest,
                "imported_utc": now,
                "importer_version": IMPORTER_VERSION,
                "turn_restrictions_enforced": "false",
                "node_count": str(node_count), "way_count": str(way_count),
                "relation_count": str(relation_count), "routable_way_count": str(routable_way_count),
                "directed_edge_count": str(directed_edge_count), "feature_count": str(feature_count),
                "address_count": str(address_count), "poi_count": str(poi_count),
                "unresolved_node_refs": str(unresolved_node_refs),
            }
            conn.executemany("INSERT INTO meta(key,value) VALUES(?,?)", metadata.items())
            conn.commit()
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"staged OSM database failed integrity_check: {integrity}")
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
        if destination.exists():
            raise FileExistsError(f"refusing to replace an existing file: {destination}")
        # A same-directory hard link provides atomic no-clobber publication on
        # POSIX. Some Windows policies/filesystems deny hard links; os.rename
        # has no-replace semantics on Windows, so use that as the safe fallback.
        try:
            os.link(staged, destination)
        except OSError as exc:
            if os.name != "nt" or getattr(exc, "winerror", None) not in {1, 5, 50}:
                raise
            if destination.exists():
                raise FileExistsError(f"refusing to replace an existing file: {destination}") from exc
            os.rename(staged, destination)

    return ImportSummary(
        str(source), digest, str(destination), node_count, way_count,
        relation_count, routable_way_count, directed_edge_count,
        feature_count, address_count, poi_count, unresolved_node_refs,
    )


class OSMStore:
    """Read-only query API for an imported local OSM graph."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path).resolve()
        if not self.database_path.is_file():
            raise FileNotFoundError(self.database_path)

    def _connect(self) -> sqlite3.Connection:
        uri = self.database_path.as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    @property
    def metadata(self) -> dict[str, str]:
        conn = self._connect()
        try:
            return {row["key"]: row["value"] for row in conn.execute("SELECT key,value FROM meta")}
        finally:
            conn.close()

    def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        normalized = normalize_name(query)
        if not normalized or limit <= 0:
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT f.element_type,f.element_id,f.kind,f.name,f.category,f.latitude,f.longitude,f.address,f.tags_json,
                          MIN(CASE WHEN fn.normalized_name=? THEN 0 ELSE 1 END) AS exact_match,
                          MIN(CASE WHEN f.kind='street' THEN 0 ELSE 1 END) AS street_rank
                   FROM feature_names fn JOIN features f USING(element_type,element_id)
                   WHERE fn.normalized_name LIKE ?
                   GROUP BY f.element_type,f.element_id
                   ORDER BY exact_match, street_rank, f.name COLLATE NOCASE, f.element_type, f.element_id
                   LIMIT ?""",
                (normalized, f"%{normalized}%", int(limit)),
            ).fetchall()
            return [
                SearchResult(row["element_type"], row["element_id"], row["kind"], row["name"], row["category"],
                             row["latitude"], row["longitude"], row["address"], json.loads(row["tags_json"]))
                for row in rows
            ]
        finally:
            conn.close()

    def nearest_node(self, latitude: float, longitude: float, max_distance_m: float | None = None) -> tuple[str, float] | None:
        conn = self._connect()
        try:
            best: tuple[str, float] | None = None
            for row in conn.execute("SELECT id,latitude,longitude FROM nodes"):
                distance = _haversine_m(latitude, longitude, float(row["latitude"]), float(row["longitude"]))
                if best is None or (distance, row["id"]) < (best[1], best[0]):
                    best = (row["id"], distance)
            if best and max_distance_m is not None and best[1] > max_distance_m:
                return None
            return best
        finally:
            conn.close()

    def nearest_routable_node(self, latitude: float, longitude: float,
                              max_distance_m: float | None = None) -> tuple[str, float] | None:
        """Snap a coordinate to an endpoint in the car graph, not a building node."""
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise ValueError("latitude must be within -90..90")
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise ValueError("longitude must be within -180..180")
        if max_distance_m is not None and (not math.isfinite(max_distance_m) or max_distance_m < 0):
            raise ValueError("max_distance_m must be a finite non-negative number")
        conn = self._connect()
        try:
            sql = """SELECT n.id,n.latitude,n.longitude FROM nodes n
                     WHERE EXISTS(SELECT 1 FROM edges e WHERE e.from_node=n.id)
                        OR EXISTS(SELECT 1 FROM edges e WHERE e.to_node=n.id)"""
            params: tuple[Any, ...] = ()
            if max_distance_m is not None:
                lat_margin = max_distance_m / 110_574.0
                lon_margin = max_distance_m / max(1.0, 111_320.0 * abs(math.cos(math.radians(latitude))))
                sql += " AND n.latitude BETWEEN ? AND ? AND n.longitude BETWEEN ? AND ?"
                params = (latitude-lat_margin, latitude+lat_margin, longitude-lon_margin, longitude+lon_margin)
            best: tuple[str, float] | None = None
            for row in conn.execute(sql, params):
                distance = _haversine_m(latitude, longitude, float(row["latitude"]), float(row["longitude"]))
                if best is None or (distance, row["id"]) < (best[1], best[0]):
                    best = (row["id"], distance)
            if best and max_distance_m is not None and best[1] > max_distance_m:
                return None
            return best
        finally:
            conn.close()

    def route(self, start_node: str, end_node: str, profile: str = "car",
              bounds: tuple[float, float, float, float] | None = None) -> RouteResult | None:
        """Find a deterministic shortest-distance path over directed OSM edges.

        OSM relations are retained, but turn restrictions are not enforced by
        this first experimental graph version. Callers should show that limit.
        """
        if profile != "car":
            raise ValueError("only the experimental 'car' routing profile is implemented")
        if bounds is not None:
            south, west, north, east = bounds
            if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
                raise ValueError("bounds must be south,west,north,east within valid coordinates")
        conn = self._connect()
        try:
            if bounds is None:
                coords_sql, coords_params = "SELECT id,latitude,longitude FROM nodes", ()
            else:
                coords_sql = "SELECT id,latitude,longitude FROM nodes WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?"
                coords_params = (bounds[0], bounds[2], bounds[1], bounds[3])
            coords = {row["id"]: (float(row["latitude"]), float(row["longitude"]))
                      for row in conn.execute(coords_sql, coords_params)}
            if start_node not in coords or end_node not in coords:
                return None
            adjacency: dict[str, list[tuple[str, float, str]]] = {}
            has_restrictions = False
            for row in conn.execute("SELECT id,tags_json FROM relations"):
                tags = json.loads(row["tags_json"])
                if tags.get("type") == "restriction":
                    has_restrictions = True
                    break
            if bounds is None:
                edges_sql = "SELECT way_id,from_node,to_node,distance_m,highway,tags_json FROM edges"
                edge_params: tuple[float, ...] = ()
            else:
                edges_sql = """SELECT e.way_id,e.from_node,e.to_node,e.distance_m,e.highway,e.tags_json
                    FROM edges e JOIN nodes a ON a.id=e.from_node JOIN nodes b ON b.id=e.to_node
                    WHERE a.latitude BETWEEN ? AND ? AND a.longitude BETWEEN ? AND ?
                      AND b.latitude BETWEEN ? AND ? AND b.longitude BETWEEN ? AND ?"""
                edge_params = (bounds[0], bounds[2], bounds[1], bounds[3],
                               bounds[0], bounds[2], bounds[1], bounds[3])
            for row in conn.execute(edges_sql, edge_params):
                tags = json.loads(row["tags_json"])
                if not _is_accessible(tags, profile):
                    continue
                adjacency.setdefault(row["from_node"], []).append((row["to_node"], float(row["distance_m"]), row["way_id"]))
            for neighbors in adjacency.values():
                neighbors.sort(key=lambda item: (item[0], item[2]))

            def heuristic(node: str) -> float:
                lat1, lon1 = coords[node]
                lat2, lon2 = coords[end_node]
                return _haversine_m(lat1, lon1, lat2, lon2)

            open_heap: list[tuple[float, float, str]] = [(heuristic(start_node), 0.0, start_node)]
            best_distance = {start_node: 0.0}
            previous: dict[str, tuple[str, str]] = {}
            settled: set[str] = set()
            while open_heap:
                _estimated, distance, current = heapq.heappop(open_heap)
                if distance != best_distance.get(current):
                    continue
                if current in settled:
                    continue
                settled.add(current)
                if current == end_node:
                    break
                for neighbor, segment_m, way_id in adjacency.get(current, []):
                    if neighbor in settled:
                        continue
                    candidate = distance + segment_m
                    old = best_distance.get(neighbor)
                    predecessor = previous.get(neighbor)
                    tie_key = (current, way_id)
                    if old is None or candidate < old - 1e-9 or (abs(candidate - old) <= 1e-9 and (predecessor is None or tie_key < predecessor)):
                        best_distance[neighbor] = candidate
                        previous[neighbor] = tie_key
                        heapq.heappush(open_heap, (candidate + heuristic(neighbor), candidate, neighbor))
            if end_node not in best_distance:
                return None
            reversed_nodes = [end_node]
            reversed_ways: list[str] = []
            cursor = end_node
            while cursor != start_node:
                parent, way_id = previous[cursor]
                reversed_ways.append(way_id)
                reversed_nodes.append(parent)
                cursor = parent
            node_ids = tuple(reversed(reversed_nodes))
            way_ids = tuple(reversed(reversed_ways))
            limitations = ("turn restrictions are imported but not yet enforced",) if has_restrictions else ()
            return RouteResult(node_ids, way_ids, best_distance[end_node], profile, limitations)
        finally:
            conn.close()

    def iter_map_ways(self, limit: int = 20_000) -> Iterator[dict[str, Any]]:
        """Yield raw geometry for common OSM map layers, preserving source tags."""
        if limit <= 0:
            return
        conn = self._connect()
        try:
            rows = conn.execute("SELECT id,tags_json FROM ways ORDER BY CAST(id AS INTEGER)")
            yielded = 0
            for row in rows:
                tags = json.loads(row["tags_json"])
                if not any(key in tags for key in MAP_WAY_TAGS):
                    continue
                coordinates = [
                    {"id": node["node_id"], "latitude": node["latitude"], "longitude": node["longitude"]}
                    for node in conn.execute(
                        """SELECT wn.node_id,n.latitude,n.longitude FROM way_nodes wn
                           JOIN nodes n ON n.id=wn.node_id WHERE wn.way_id=? ORDER BY wn.node_index""",
                        (row["id"],),
                    )
                ]
                if len(coordinates) < 2:
                    continue
                yield {"id": row["id"], "tags": tags, "coordinates": coordinates}
                yielded += 1
                if yielded >= limit:
                    break
        finally:
            conn.close()
