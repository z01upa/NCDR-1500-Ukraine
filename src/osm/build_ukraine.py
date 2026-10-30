"""Build and independently verify a dated Ukraine-wide OSM preparation DB.

All outputs are versioned beneath the project work area. The PBF is read-only;
this is an OSM preparation artifact, not an NCDx export or Opel compatibility
claim. The first extractor intentionally does not yet export OSM relations.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from src.osm.engine import OSMStore, import_osm_xml, normalize_name
from src.osm.extract_pbf import extract_city


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PBF = PROJECT_ROOT / "data" / "osm" / "ukraine-latest.osm.pbf"
SOURCE_METADATA = PROJECT_ROOT / "data" / "osm" / "source.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "work" / "autonomous_manager" / "osm_pipeline" / "ukraine_national"
UKRAINE_BBOX = (-90.0, -180.0, 90.0, 180.0)
CITY_BBOX = (47.58, 32.50, 48.23, 33.95)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _source_content_timestamp() -> str:
    try:
        metadata = json.loads(SOURCE_METADATA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    value = str(metadata.get("dataset_content_timestamp", "unknown"))
    return value[:120]


def _street_route_proof(database: Path) -> dict[str, Any]:
    store = OSMStore(database)
    sobornosti = [row for row in store.search("Соборності", limit=300)
                  if row.kind == "street" and normalize_name(row.name) == normalize_name("вулиця Соборності")]
    heroiv = [row for row in store.search("Героїв АТО", limit=300)
              if row.kind == "street" and normalize_name(row.name) == normalize_name("вулиця Героїв АТО")
              and 47.89 <= (row.latitude or 0) <= 47.92 and 33.39 <= (row.longitude or 0) <= 33.44]
    if not sobornosti or not heroiv:
        raise RuntimeError("Ukraine database readback did not find the two saved Kryvyi Rih street records")
    start_point = min(sobornosti, key=lambda row: abs((row.latitude or 0) - 47.9) + abs((row.longitude or 0) - 33.408))
    end_point = min(heroiv, key=lambda row: abs((row.latitude or 0) - 47.906) + abs((row.longitude or 0) - 33.407))
    start = store.nearest_routable_node(start_point.latitude, start_point.longitude, max_distance_m=5000)
    end = store.nearest_routable_node(end_point.latitude, end_point.longitude, max_distance_m=5000)
    if not start or not end:
        raise RuntimeError("Kryvyi Rih street records could not be snapped to the national road graph")
    # The national DB can contain millions of nodes. The bounded search keeps
    # only the test city's graph in memory while exercising its national DB.
    route = store.route(start[0], end[0], bounds=CITY_BBOX)
    if not route or not 0 < route.distance_m < 10_000 or len(route.node_ids) <= 2:
        raise RuntimeError("bounded Kryvyi Rih car route did not pass on the Ukraine-wide database")
    return {"start_street": start_point.name, "end_street": end_point.name,
            "start_node": start[0], "end_node": end[0], "distance_m": route.distance_m,
            "node_count": len(route.node_ids), "way_count": len(route.way_ids),
            "routing_bounds": list(CITY_BBOX), "limitations": list(route.limitations)}


def verify_snapshot(output_dir: Path, *, expected_source_sha256: str | None = None,
                    verify_source_hash: bool = True) -> dict[str, Any]:
    """Fresh read-only checks over a saved national extract/database pair."""
    output_dir = output_dir.resolve(strict=True)
    extract = output_dir / "ukraine.osm.gz"
    database = output_dir / "ukraine.sqlite"
    metadata_path = output_dir / "conversion.json"
    if not extract.is_file() or not database.is_file() or not metadata_path.is_file():
        raise RuntimeError("national snapshot is incomplete; extract, SQLite and provenance are all required")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source_sha = str(metadata.get("source_pbf_sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha):
        raise RuntimeError("national snapshot lacks a valid PBF source SHA-256")
    if expected_source_sha256 and source_sha != expected_source_sha256:
        raise RuntimeError("national snapshot source hash differs from the scheduled source")
    if verify_source_hash and sha256_file(SOURCE_PBF) != source_sha:
        raise RuntimeError("local Ukraine PBF hash changed since national conversion")
    extract_sha = sha256_file(extract)
    if metadata.get("extract_sha256") != extract_sha:
        raise RuntimeError("national extract SHA-256 differs from saved provenance")
    with gzip.open(extract, "rb") as stream:
        if b"<osm" not in stream.read(256):
            raise RuntimeError("national extract is not an OSM XML document")
        while stream.read(4 * 1024 * 1024):
            pass
    with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=30)) as conn:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        nodes, ways, edges, features = (int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
                                        for table in ("nodes", "ways", "edges", "features"))
        min_lat, min_lon, max_lat, max_lon = conn.execute(
            "SELECT min(latitude),min(longitude),max(latitude),max(longitude) FROM nodes").fetchone()
        unresolved = int(conn.execute("""SELECT count(*) FROM way_nodes w LEFT JOIN nodes n ON n.id=w.node_id
                                        WHERE n.id IS NULL""").fetchone()[0])
        db_meta = {str(key): str(value) for key, value in conn.execute(
            "SELECT key,value FROM meta WHERE key IN ('source_sha256','node_count','directed_edge_count','unresolved_node_refs')")}
    if integrity != "ok" or min(nodes, ways, edges, features) <= 0:
        raise RuntimeError(f"national map database is incomplete: integrity={integrity}, counts={(nodes, ways, edges, features)}")
    # Geofabrik Ukraine coverage is expected to reach the country's western,
    # eastern, northern and southern bounds. Loose limits tolerate coastline
    # and source boundary changes while rejecting a city-only extract.
    coverage = {"south": float(min_lat), "west": float(min_lon),
                "north": float(max_lat), "east": float(max_lon)}
    if not (coverage["south"] < 45 and coverage["north"] > 52 and
            coverage["west"] < 23 and coverage["east"] > 39):
        raise RuntimeError(f"OSM dataset extent does not demonstrate Ukraine-wide coverage: {coverage}")
    if unresolved:
        raise RuntimeError(f"national map database has {unresolved} dangling way-node references")
    if db_meta.get("source_sha256") != extract_sha:
        raise RuntimeError("SQLite import metadata does not identify the exact source extract")
    current_source_sha = sha256_file(SOURCE_PBF)
    current_extract_sha = sha256_file(extract)
    if current_source_sha != expected_source_sha256:
        raise RuntimeError("read-only PBF SHA-256 differs from the scheduled source")
    if current_extract_sha != extract_sha:
        raise RuntimeError("national extract changed during independent readback")
    kyiv_hits = OSMStore(database).search("Київ", limit=20)
    if not kyiv_hits:
        kyiv_hits = OSMStore(database).search("Kyiv", limit=20)
    if not kyiv_hits:
        raise RuntimeError("national map database does not return a Kyiv name-search result")
    city_route = _street_route_proof(database)
    return {"status": "PASS", "database": str(database.relative_to(PROJECT_ROOT)),
        "database_sha256": sha256_file(database), "extract": str(extract.relative_to(PROJECT_ROOT)),
        "extract_sha256": extract_sha, "source_pbf": str(SOURCE_PBF.relative_to(PROJECT_ROOT)),
        "source_pbf_sha256": source_sha, "source_sha256_unchanged": not verify_source_hash or sha256_file(SOURCE_PBF) == source_sha,
        "sqlite_integrity_check": integrity, "counts": {"nodes": nodes, "ways": ways, "directed_edges": edges, "features": features},
        "geographic_extent": coverage, "unresolved_way_node_references": unresolved,
        "kyiv_name_search_results": len(kyiv_hits), "kryvyi_rih_route": city_route,
        "read_only_readback": True, "source_write_count": 0,
        "limitations": ["OSM relations, including turn restrictions, are not yet exported by the extractor.",
                        "This is an internal OSM preparation database, not an NCDx image or Opel compatibility test."]}


def verify_published_recovery(output_dir: Path, *, expected_source_sha256: str,
                              expected_extract_sha256: str) -> dict[str, Any]:
    """Read back an atomically published national DB without rescanning 31 GB.

    The streaming importer runs ``PRAGMA integrity_check`` before it renames a
    completed build into place.  This recovery verifier checks the publisher's
    source bindings, final checkpoint, persisted counts/extents, indexed Kyiv
    search and a bounded real-city route in a separate process. It rehashes the
    PBF, compressed extract and published DB, but does not repeat the much more
    expensive full-database integrity scan or recount the 112 million nodes.
    """
    output_dir = output_dir.resolve(strict=True)
    database = output_dir / "ukraine.sqlite"
    extract = output_dir / "ukraine.osm.gz"
    if not database.is_file() or not extract.is_file():
        raise RuntimeError("published national OSM database or its source extract is missing")
    actual_source_sha = sha256_file(SOURCE_PBF)
    if actual_source_sha != expected_source_sha256:
        raise RuntimeError("read-only PBF SHA-256 differs from the scheduled source")
    current_extract_sha = sha256_file(extract)
    if current_extract_sha != expected_extract_sha256:
        raise RuntimeError("saved OSM extract SHA-256 differs from its published database binding")
    actual_source_sha = sha256_file(SOURCE_PBF)
    if actual_source_sha != expected_source_sha256:
        raise RuntimeError("read-only PBF SHA-256 differs from the scheduled source")
    current_extract_sha = sha256_file(extract)
    if current_extract_sha != expected_extract_sha256:
        raise RuntimeError("saved OSM extract SHA-256 differs from its published database binding")
    with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=30)) as conn:
        rows = {str(key): str(value) for key, value in conn.execute("SELECT key,value FROM meta")}
        checkpoint = {str(key): str(value) for key, value in conn.execute("SELECT key,value FROM build_checkpoint")}
        objects = {str(name) for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
    if rows.get("source_pbf_sha256") != expected_source_sha256:
        raise RuntimeError("published national database PBF source binding differs from the scheduled input")
    if rows.get("source_sha256") != expected_extract_sha256 or checkpoint.get("extract_sha256") != expected_extract_sha256:
        raise RuntimeError("published national database extract binding differs from the scheduled input")
    if checkpoint.get("source_pbf_sha256") != expected_source_sha256 or checkpoint.get("phase") != "FINALIZE":
        raise RuntimeError("published national database is not at its source-bound finalization checkpoint")
    required = {"nodes", "ways", "way_nodes", "edges", "features", "feature_names",
                "relations", "build_checkpoint", "idx_nodes_lat_lon", "idx_edges_from",
                "idx_feature_names_normalized"}
    missing = sorted(required - objects)
    if missing:
        raise RuntimeError(f"published national database is missing required tables or indexes: {missing}")
    try:
        counts = {"nodes": int(rows["node_count"]), "ways": int(rows["way_count"]),
                  "directed_edges": int(rows["directed_edge_count"]), "features": int(rows["feature_count"])}
        unresolved = int(rows["unresolved_node_refs"])
        coverage = {"south": float(rows["minimum_latitude"]), "west": float(rows["minimum_longitude"]),
                    "north": float(rows["maximum_latitude"]), "east": float(rows["maximum_longitude"])}
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("published national database has incomplete finalization metadata") from exc
    if min(counts.values()) <= 0 or unresolved != 0:
        raise RuntimeError("published national database counts or unresolved references are invalid")
    if not (coverage["south"] < 45 and coverage["north"] > 52 and
            coverage["west"] < 23 and coverage["east"] > 39):
        raise RuntimeError(f"published database metadata does not show Ukraine-wide coverage: {coverage}")
    kyiv_hits = OSMStore(database).search("Київ", limit=20)
    if not kyiv_hits:
        kyiv_hits = OSMStore(database).search("Kyiv", limit=20)
    if not kyiv_hits:
        raise RuntimeError("published national database did not return a Kyiv name-search result")
    city_route = _street_route_proof(database)
    stat = database.stat()
    database_sha = sha256_file(database)
    return {"status": "PASS", "database": str(database.relative_to(PROJECT_ROOT)),
        "database_size_bytes": stat.st_size, "extract": str(extract.relative_to(PROJECT_ROOT)),
        "extract_sha256": current_extract_sha, "source_pbf": str(SOURCE_PBF.relative_to(PROJECT_ROOT)),
        "source_pbf_sha256": actual_source_sha, "source_sha256_unchanged": True,
        "sqlite_integrity_check": "ok", "integrity_evidence_source": "streaming importer before atomic publication",
        "independent_full_integrity_check_repeated": False,
        "counts": counts, "geographic_extent": coverage,
        "unresolved_way_node_references": unresolved, "kyiv_name_search_results": len(kyiv_hits),
        "kryvyi_rih_route": city_route, "read_only_readback": True, "source_write_count": 0,
        "database_sha256": database_sha,
        "limitations": ["Full PRAGMA integrity_check was not repeated during recovery; the publisher ran it before atomic publication.",
            "OSM relations, including turn restrictions, are not yet exported by the extractor.",
            "This is an internal OSM preparation database, not an NCDx image or Opel compatibility test."]}


def build(source_pbf: Path = SOURCE_PBF, output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    source = source_pbf.resolve(strict=True)
    allowed_root = (PROJECT_ROOT / "data" / "osm").resolve(strict=True)
    if source != allowed_root / "ukraine-latest.osm.pbf":
        raise ValueError("national builder only accepts the configured immutable Ukraine PBF")
    source_before = sha256_file(source)
    source_stat = source.stat()
    upstream = json.loads(SOURCE_METADATA.read_text(encoding="utf-8")) if SOURCE_METADATA.is_file() else {}
    expected = str(upstream.get("pbf_download", {}).get("sha256", ""))
    if expected and expected != source_before:
        raise RuntimeError("PBF SHA-256 differs from the saved source manifest")
    content_date = re.search(r"\d{4}-\d{2}-\d{2}", _source_content_timestamp())
    date_key = content_date.group(0) if content_date else "undated"
    output_dir = output_root.resolve() / f"ukraine-{date_key}-{source_before[:12]}"
    output_dir.mkdir(parents=True, exist_ok=True)
    extract = output_dir / "ukraine.osm.gz"
    database = output_dir / "ukraine.sqlite"
    metadata_path = output_dir / "conversion.json"
    if metadata_path.is_file() and database.is_file() and extract.is_file():
        return verify_snapshot(output_dir, expected_source_sha256=source_before) | {
            "output_directory": str(output_dir.relative_to(PROJECT_ROOT)),
            "dataset_content_timestamp": _source_content_timestamp(),
            "status": "PASS_PENDING_INDEPENDENT_SUPERVISOR"}
    progress_path = output_dir / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.is_file() else {}
    if progress.get("source_pbf_sha256") not in {None, source_before}:
        raise RuntimeError("saved national build state belongs to a different PBF hash")
    if not extract.is_file():
        extraction = extract_city(source, extract, UKRAINE_BBOX)
        progress = {"source_pbf_sha256": source_before, "extraction": extraction,
                    "updated_utc": datetime.now(timezone.utc).isoformat()}
        progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        with gzip.open(extract, "rb") as stream:
            if b"<osm" not in stream.read(256):
                raise RuntimeError("existing national extract is not a valid OSM XML stream")
            while stream.read(4 * 1024 * 1024):
                pass
        extraction = progress.get("extraction", {"status": "RESUMED_VERIFIED_GZIP"})
    if not database.is_file():
        imported = import_osm_xml(extract, database).__dict__
    else:
        imported = progress.get("import", {"status": "RESUMED_EXISTING_DATABASE"})
    source_after = sha256_file(source)
    source_stat_after = source.stat()
    if (source_before != source_after or
            (source_stat.st_size, source_stat.st_mtime_ns) != (source_stat_after.st_size, source_stat_after.st_mtime_ns)):
        raise RuntimeError("read-only national conversion detected a change to its source PBF")
    metadata = {"status": "BUILT_PENDING_SUPERVISOR", "created_utc": datetime.now(timezone.utc).isoformat(),
        "source": "OpenStreetMap via Geofabrik Ukraine regional PBF",
        "source_url": "https://download.geofabrik.de/europe/ukraine.html",
        "source_pbf": str(source.relative_to(PROJECT_ROOT)), "source_pbf_bytes": source_stat.st_size,
        "source_pbf_sha256": source_before, "dataset_content_timestamp": _source_content_timestamp(),
        "snapshot_date_key": date_key, "extract_sha256": sha256_file(extract),
        "extract_bytes": extract.stat().st_size, "extraction": extraction, "import": imported,
        "bbox_south_west_north_east": list(UKRAINE_BBOX),
        "attribution": "© OpenStreetMap contributors", "license": "Open Database License (ODbL)",
        "license_url": "https://www.openstreetmap.org/copyright",
        "safety": {"source_opened_read_only": True, "original_disc_write_count": 0,
                   "outputs_under_project_work_area": True},
        "limitations": ["First extractor omits relations, including turn restrictions.",
                         "This is a data-preparation database; NCDx export and physical Opel compatibility are not claimed."]}
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    proof = verify_snapshot(output_dir, expected_source_sha256=source_before)
    metadata["status"] = "PASS_PENDING_INDEPENDENT_SUPERVISOR"
    metadata["deterministic_readback"] = proof
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    progress.update({"source_pbf_sha256": source_before, "extraction": extraction, "import": imported,
                     "verification": proof, "updated_utc": datetime.now(timezone.utc).isoformat()})
    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return proof | {"status": "PASS_PENDING_INDEPENDENT_SUPERVISOR", "output_directory": str(output_dir.relative_to(PROJECT_ROOT)),
                    "dataset_content_timestamp": _source_content_timestamp()}


def main() -> int:
    print(json.dumps(build(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
