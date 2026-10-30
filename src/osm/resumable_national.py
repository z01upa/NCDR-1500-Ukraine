"""Checkpointed, bounded-memory importer for the verified national OSM extract.

All output is derived data beneath the project work tree. The source PBF and
compressed OSM extract are opened read-only. Import progress is committed in
the same SQLite transaction as imported rows, so a killed worker only repeats
the uncommitted batch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import xml.etree.ElementTree as ET
from typing import Any

from src.osm import engine


IMPORTER_VERSION = "national-resumable-0.2.0"
DECOMPRESS_CHUNK_BYTES = 32 * 1024 * 1024
STREAM_COMMIT_RECORDS = 5_000
MAX_XML_RECORD_BYTES = 1024 * 1024
INDEXES = (
    ("idx_nodes_lat_lon", "CREATE INDEX IF NOT EXISTS idx_nodes_lat_lon ON nodes(latitude,longitude)"),
    ("idx_way_nodes_node", "CREATE INDEX IF NOT EXISTS idx_way_nodes_node ON way_nodes(node_id)"),
    ("idx_edges_from", "CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_node)"),
    ("idx_edges_to", "CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_node)"),
    ("idx_features_kind", "CREATE INDEX IF NOT EXISTS idx_features_kind ON features(kind)"),
    ("idx_feature_names_normalized", "CREATE INDEX IF NOT EXISTS idx_feature_names_normalized ON feature_names(normalized_name)"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _identity(extract: Path, extract_sha256: str, source_sha256: str) -> str:
    if len(extract_sha256) != 64 or len(source_sha256) != 64:
        raise ValueError("expected SHA-256 bindings for source PBF and OSM extract")
    if not extract.is_file():
        raise FileNotFoundError(extract)
    return hashlib.sha256(f"{extract.resolve()}\n{extract_sha256}\n{source_sha256}".encode()).hexdigest()


def _raw_paths(work_dir: Path) -> tuple[Path, Path]:
    return work_dir / "ukraine.osm.raw", work_dir / "ukraine.osm.raw.checkpoint.json"


def _ensure_raw(extract: Path, work_dir: Path, extract_sha256: str,
                source_sha256: str, *, max_seconds: float) -> dict[str, Any]:
    """Make a seekable XML spool with durable chunk checkpoints.

    gzip seek is only used after interruption; the normal pass is one bounded,
    sequential decompression. If the process dies between a raw write and its
    manifest update, uncommitted trailing bytes are truncated on restart.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    raw, checkpoint = _raw_paths(work_dir)
    identity = _identity(extract, extract_sha256, source_sha256)
    saved: dict[str, Any] = {}
    if checkpoint.is_file():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if saved.get("identity") != identity:
            raise RuntimeError("raw XML checkpoint belongs to a different source; refusing to resume")
    saved_bytes = int(saved.get("decompressed_bytes", 0))
    if raw.exists():
        if raw.stat().st_size < saved_bytes:
            raise RuntimeError("raw XML file is shorter than its durable checkpoint")
        if raw.stat().st_size != saved_bytes:
            with raw.open("r+b") as stream:
                stream.truncate(saved_bytes)
    elif saved_bytes:
        raise RuntimeError("raw XML checkpoint exists but the corresponding spool is missing")
    if saved.get("complete") is True:
        return {"complete": True, "raw_bytes": saved_bytes, "checkpoint": str(checkpoint)}

    started = time.monotonic()
    raw.parent.mkdir(parents=True, exist_ok=True)
    if saved_bytes:
        source = gzip.open(extract, "rb")
        source.seek(saved_bytes)
    else:
        source = gzip.open(extract, "rb")
    try:
        with source, raw.open("ab") as output:
            written_since_checkpoint = 0
            while time.monotonic() - started < max_seconds:
                block = source.read(DECOMPRESS_CHUNK_BYTES)
                if not block:
                    output.flush()
                    os.fsync(output.fileno())
                    state = {"identity": identity, "extract_sha256": extract_sha256,
                             "source_pbf_sha256": source_sha256,
                             "decompressed_bytes": saved_bytes + written_since_checkpoint,
                             "complete": True, "updated_utc": datetime.now(timezone.utc).isoformat()}
                    _atomic_json(checkpoint, state)
                    return {"complete": True, "raw_bytes": state["decompressed_bytes"], "checkpoint": str(checkpoint)}
                output.write(block)
                written_since_checkpoint += len(block)
                if written_since_checkpoint >= DECOMPRESS_CHUNK_BYTES:
                    output.flush()
                    os.fsync(output.fileno())
                    saved_bytes += written_since_checkpoint
                    written_since_checkpoint = 0
                    _atomic_json(checkpoint, {"identity": identity, "extract_sha256": extract_sha256,
                        "source_pbf_sha256": source_sha256, "decompressed_bytes": saved_bytes,
                        "complete": False, "updated_utc": datetime.now(timezone.utc).isoformat()})
            output.flush()
            os.fsync(output.fileno())
            saved_bytes += written_since_checkpoint
            _atomic_json(checkpoint, {"identity": identity, "extract_sha256": extract_sha256,
                "source_pbf_sha256": source_sha256, "decompressed_bytes": saved_bytes,
                "complete": False, "updated_utc": datetime.now(timezone.utc).isoformat()})
    except BaseException:
        # The sidecar's byte offset is the commit marker; any trailing write is
        # intentionally ignored and truncated at the next invocation.
        raise
    return {"complete": False, "raw_bytes": saved_bytes, "checkpoint": str(checkpoint),
            "reason": "decompression slice time budget reached"}


def _connect(database: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(database, timeout=60)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=FILE")
    conn.execute("PRAGMA cache_size=-262144")
    return conn


def _schema(conn: sqlite3.Connection, identity: str, extract_sha256: str,
            source_sha256: str) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY,latitude REAL NOT NULL,longitude REAL NOT NULL,tags_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS ways(id TEXT PRIMARY KEY,tags_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS way_nodes(way_id TEXT NOT NULL,node_index INTEGER NOT NULL,node_id TEXT NOT NULL,PRIMARY KEY(way_id,node_index));
    CREATE TABLE IF NOT EXISTS edges(way_id TEXT NOT NULL,segment_index INTEGER NOT NULL,from_node TEXT NOT NULL,to_node TEXT NOT NULL,
      distance_m REAL NOT NULL,highway TEXT NOT NULL,oneway INTEGER NOT NULL,tags_json TEXT NOT NULL,PRIMARY KEY(way_id,segment_index,from_node,to_node));
    CREATE TABLE IF NOT EXISTS relations(id TEXT PRIMARY KEY,tags_json TEXT NOT NULL,members_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS features(element_type TEXT NOT NULL,element_id TEXT NOT NULL,kind TEXT NOT NULL,name TEXT NOT NULL,
      category TEXT,latitude REAL,longitude REAL,address TEXT,tags_json TEXT NOT NULL,PRIMARY KEY(element_type,element_id));
    CREATE TABLE IF NOT EXISTS feature_names(element_type TEXT NOT NULL,element_id TEXT NOT NULL,original_name TEXT NOT NULL,
      normalized_name TEXT NOT NULL,source_key TEXT NOT NULL,PRIMARY KEY(element_type,element_id,normalized_name));
    CREATE TABLE IF NOT EXISTS feature_work(work_id INTEGER PRIMARY KEY AUTOINCREMENT,element_id TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS edge_work(work_id INTEGER PRIMARY KEY AUTOINCREMENT,way_id TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS build_checkpoint(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    """)
    row = conn.execute("SELECT value FROM build_checkpoint WHERE key='identity'").fetchone()
    if row and row[0] != identity:
        raise RuntimeError("SQLite build checkpoint belongs to a different extract/source pair")
    conn.execute("INSERT OR IGNORE INTO build_checkpoint VALUES('identity',?)", (identity,))
    defaults = {"phase": "STREAM", "offset": "0", "stream_records": "0", "feature_cursor": "0",
                "edge_cursor": "0", "index_cursor": "0", "extract_sha256": extract_sha256,
                "source_pbf_sha256": source_sha256}
    for key, value in defaults.items():
        row = conn.execute("SELECT value FROM build_checkpoint WHERE key=?", (key,)).fetchone()
        if row and row[0] != value and key in {"extract_sha256", "source_pbf_sha256"}:
            raise RuntimeError(f"SQLite checkpoint {key} binding differs from the scheduled task")
        conn.execute("INSERT OR IGNORE INTO build_checkpoint VALUES(?,?)", (key, value))
    conn.commit()


def checkpoint_token(work_dir: Path, database: Path | None = None) -> str | None:
    raw, raw_checkpoint = _raw_paths(work_dir)
    if database and database.is_file():
        try:
            with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=10)) as conn:
                values = dict(conn.execute("SELECT key,value FROM build_checkpoint"))
            if values:
                serialized = json.dumps(values, sort_keys=True, separators=(",", ":"))
                return hashlib.sha256(serialized.encode()).hexdigest()[:16]
        except sqlite3.Error:
            return None
    if raw_checkpoint.is_file():
        try:
            state = json.loads(raw_checkpoint.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if int(state.get("decompressed_bytes", 0)) or state.get("complete"):
            serialized = json.dumps(state, sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(serialized.encode()).hexdigest()[:16]
    return "START"


def progress_snapshot(work_dir: Path, database: Path | None = None) -> dict[str, Any]:
    raw, raw_checkpoint = _raw_paths(work_dir)
    if database and database.is_file():
        with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=10)) as conn:
            values = dict(conn.execute("SELECT key,value FROM build_checkpoint"))
            counts = {table: int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
                      for table in ("nodes", "ways", "way_nodes", "features", "edges")}
        return {"phase": values.get("phase"), "offset": int(values.get("offset", 0)),
                "stream_records": int(values.get("stream_records", 0)), "cursors": {
                    "feature": int(values.get("feature_cursor", 0)), "edge": int(values.get("edge_cursor", 0)),
                    "index": int(values.get("index_cursor", 0))}, "counts": counts,
                "checkpoint_token": checkpoint_token(work_dir, database)}
    state = json.loads(raw_checkpoint.read_text(encoding="utf-8")) if raw_checkpoint.is_file() else {}
    return {"phase": "DECOMPRESS", "raw_bytes": int(state.get("decompressed_bytes", 0)),
            "raw_file_bytes": raw.stat().st_size if raw.is_file() else 0,
            "complete": bool(state.get("complete")), "checkpoint_token": checkpoint_token(work_dir)}


def _checkpoint(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key,value FROM build_checkpoint"))


def _set_checkpoint(conn: sqlite3.Connection, values: dict[str, Any]) -> None:
    conn.executemany("INSERT INTO build_checkpoint(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     ((key, str(value)) for key, value in values.items()))


def _parse_element(line: bytes) -> ET.Element | None:
    stripped = line.strip()
    if (not stripped or stripped.startswith(b"<?xml") or stripped.startswith(b"<osm ")
            or stripped == b"</osm>"):
        return None
    try:
        return ET.fromstring(stripped)
    except ET.ParseError as exc:
        raise RuntimeError(f"invalid line-oriented OSM record near raw byte stream: {exc}") from exc


def _stream_step(conn: sqlite3.Connection, raw: Path, *, max_records: int,
                 max_seconds: float) -> tuple[bool, int]:
    cp = _checkpoint(conn)
    offset, total = int(cp["offset"]), int(cp["stream_records"])
    started = time.monotonic()
    processed = 0
    eof = False
    with raw.open("rb") as stream:
        stream.seek(offset)
        while processed < max_records and time.monotonic() - started < max_seconds:
            batch_start = stream.tell()
            batch_records = 0
            conn.execute("BEGIN IMMEDIATE")
            while batch_records < STREAM_COMMIT_RECORDS and processed < max_records:
                line = stream.readline(MAX_XML_RECORD_BYTES + 1)
                if len(line) > MAX_XML_RECORD_BYTES:
                    raise RuntimeError("OSM record exceeds the bounded XML record size")
                if not line:
                    eof = True
                    break
                next_offset = stream.tell()
                stripped = line.strip()
                if stripped == b"</osm>":
                    eof = True
                    break
                element = _parse_element(line)
                if element is None:
                    offset = next_offset
                    continue
                element_type = engine._local_name(element.tag)
                if element_type == "node":
                    node_id = element.attrib.get("id")
                    if node_id:
                        try:
                            latitude, longitude = float(element.attrib["lat"]), float(element.attrib["lon"])
                        except (KeyError, ValueError) as exc:
                            raise RuntimeError(f"OSM node {node_id} has invalid coordinates") from exc
                        tags = engine._tags(element)
                        tags_json = json.dumps(tags, ensure_ascii=False, sort_keys=True)
                        conn.execute("INSERT OR REPLACE INTO nodes VALUES(?,?,?,?)", (node_id, latitude, longitude, tags_json))
                        engine._insert_feature(conn, "node", node_id, tags, latitude, longitude)
                elif element_type == "way":
                    way_id = element.attrib.get("id")
                    if way_id:
                        tags = engine._tags(element)
                        tags_json = json.dumps(tags, ensure_ascii=False, sort_keys=True)
                        refs = [child.attrib["ref"] for child in element if engine._local_name(child.tag) == "nd" and "ref" in child.attrib]
                        conn.execute("INSERT OR REPLACE INTO ways VALUES(?,?)", (way_id, tags_json))
                        conn.execute("DELETE FROM way_nodes WHERE way_id=?", (way_id,))
                        conn.executemany("INSERT INTO way_nodes VALUES(?,?,?)", ((way_id, index, ref) for index, ref in enumerate(refs)))
                        if engine._feature_kind(tags):
                            conn.execute("INSERT OR IGNORE INTO feature_work(element_id) VALUES(?)", (way_id,))
                        if tags.get("highway"):
                            try:
                                if engine._is_accessible(tags, "car"):
                                    conn.execute("INSERT OR IGNORE INTO edge_work(way_id) VALUES(?)", (way_id,))
                            except ValueError:
                                pass
                elif element_type == "relation":
                    relation_id = element.attrib.get("id")
                    if relation_id:
                        tags = engine._tags(element)
                        members = [{key: child.attrib[key] for key in ("type", "ref", "role") if key in child.attrib}
                                   for child in element if engine._local_name(child.tag) == "member"]
                        conn.execute("INSERT OR REPLACE INTO relations VALUES(?,?,?)", (relation_id,
                            json.dumps(tags, ensure_ascii=False, sort_keys=True),
                            json.dumps(members, ensure_ascii=False, sort_keys=True)))
                        if engine._feature_kind(tags):
                            engine._insert_feature(conn, "relation", relation_id, tags, None, None)
                batch_records += 1
                processed += 1
                offset = next_offset
                total += 1
                if processed >= max_records or time.monotonic() - started >= max_seconds:
                    break
            if eof:
                conn.execute("UPDATE build_checkpoint SET value='FEATURES' WHERE key='phase'")
            _set_checkpoint(conn, {"offset": offset, "stream_records": total})
            conn.commit()
            if eof or processed >= max_records or time.monotonic() - started >= max_seconds:
                break
            if offset == batch_start and batch_records == 0:
                raise RuntimeError("OSM stream made no forward progress")
    return eof, processed


def _feature_step(conn: sqlite3.Connection, *, max_records: int, max_seconds: float) -> tuple[bool, int]:
    cp = _checkpoint(conn)
    cursor = int(cp["feature_cursor"])
    started, processed = time.monotonic(), 0
    conn.execute("BEGIN IMMEDIATE")
    rows = conn.execute("SELECT work_id,element_id FROM feature_work WHERE work_id>? ORDER BY work_id LIMIT ?",
                        (cursor, max_records)).fetchall()
    for work_id, way_id in rows:
        row = conn.execute("SELECT tags_json FROM ways WHERE id=?", (way_id,)).fetchone()
        if row:
            tags = json.loads(row[0])
            refs = [r[0] for r in conn.execute("SELECT node_id FROM way_nodes WHERE way_id=? ORDER BY node_index", (way_id,))]
            lat, lon, _missing = engine._centroid(conn, refs)
            engine._insert_feature(conn, "way", way_id, tags, lat, lon)
        cursor = int(work_id)
        processed += 1
        if time.monotonic() - started >= max_seconds:
            break
    if processed < len(rows):
        # Remove any rows read but not processed from this transaction's local
        # view by only advancing the cursor to the last committed work ID.
        pass
    has_more = conn.execute("SELECT 1 FROM feature_work WHERE work_id>? LIMIT 1", (cursor,)).fetchone() is not None
    _set_checkpoint(conn, {"feature_cursor": cursor, "phase": "FEATURES" if has_more else "EDGES"})
    conn.commit()
    return not has_more, processed


def _edge_step(conn: sqlite3.Connection, *, max_records: int, max_seconds: float) -> tuple[bool, int]:
    cp = _checkpoint(conn)
    cursor = int(cp["edge_cursor"])
    started, processed = time.monotonic(), 0
    conn.execute("BEGIN IMMEDIATE")
    rows = conn.execute("SELECT work_id,way_id FROM edge_work WHERE work_id>? ORDER BY work_id LIMIT ?",
                        (cursor, max_records)).fetchall()
    for work_id, way_id in rows:
        row = conn.execute("SELECT tags_json FROM ways WHERE id=?", (way_id,)).fetchone()
        if row:
            tags_json = str(row[0])
            tags = json.loads(tags_json)
            refs = [r[0] for r in conn.execute("SELECT node_id FROM way_nodes WHERE way_id=? ORDER BY node_index", (way_id,))]
            mode = engine._oneway_mode(tags)
            for index, (first, second) in enumerate(zip(refs, refs[1:])):
                first_row = conn.execute("SELECT latitude,longitude FROM nodes WHERE id=?", (first,)).fetchone()
                second_row = conn.execute("SELECT latitude,longitude FROM nodes WHERE id=?", (second,)).fetchone()
                if not first_row or not second_row:
                    continue
                distance = engine._haversine_m(float(first_row[0]), float(first_row[1]), float(second_row[0]), float(second_row[1]))
                directions = [(first, second)] if mode >= 0 else []
                if mode <= 0:
                    directions.append((second, first))
                if mode == -1:
                    directions = [(second, first)]
                for source, target in directions:
                    conn.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?,?,?,?,?,?)",
                        (way_id, index, source, target, distance, tags["highway"], mode, tags_json))
        cursor = int(work_id)
        processed += 1
        if time.monotonic() - started >= max_seconds:
            break
    has_more = conn.execute("SELECT 1 FROM edge_work WHERE work_id>? LIMIT 1", (cursor,)).fetchone() is not None
    _set_checkpoint(conn, {"edge_cursor": cursor, "phase": "EDGES" if has_more else "INDEXES"})
    conn.commit()
    return not has_more, processed


def _index_step(conn: sqlite3.Connection) -> tuple[bool, str]:
    cp = _checkpoint(conn)
    cursor = int(cp["index_cursor"])
    if cursor >= len(INDEXES):
        return True, "all indexes built"
    name, sql = INDEXES[cursor]
    conn.execute(sql)
    conn.execute("BEGIN IMMEDIATE")
    _set_checkpoint(conn, {"index_cursor": cursor + 1,
                           "phase": "FINALIZE" if cursor + 1 == len(INDEXES) else "INDEXES"})
    conn.commit()
    return False, name


def _published_database_result(database: Path, *, extract_sha256: str,
                               source_pbf_sha256: str) -> dict[str, Any]:
    """Validate the durable provenance marker for a previously published DB.

    A published national database is large enough that re-running a full
    ``integrity_check`` on every stale continuation would be needlessly
    expensive.  Finalization already ran that check before the atomic rename;
    here we reopen SQLite read-only and validate the exact source bindings and
    required finalization metadata before accepting that durable result.
    """
    uri = f"file:{database.as_posix()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=30)) as conn:
            meta = {str(key): str(value) for key, value in conn.execute(
                "SELECT key,value FROM meta WHERE key IN "
                "('source_sha256','source_pbf_sha256','node_count','way_count',"
                "'directed_edge_count','feature_count','unresolved_node_refs',"
                "'importer_version','imported_utc')")}
            checkpoint = dict(conn.execute("SELECT key,value FROM build_checkpoint"))
    except sqlite3.Error as exc:
        raise RuntimeError(f"published national OSM database cannot be opened read-only: {exc}") from exc
    expected = {"source_sha256": extract_sha256,
                "source_pbf_sha256": source_pbf_sha256}
    mismatches = {key: {"expected": value, "actual": meta.get(key)}
                  for key, value in expected.items() if meta.get(key) != value}
    if mismatches:
        raise RuntimeError(f"published national OSM database is bound to a different source: {mismatches}")
    required_counts = ("node_count", "way_count", "directed_edge_count", "feature_count")
    try:
        counts = {"nodes": int(meta["node_count"]), "ways": int(meta["way_count"]),
                  "directed_edges": int(meta["directed_edge_count"]),
                  "features": int(meta["feature_count"])}
        unresolved = int(meta["unresolved_node_refs"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("published national OSM database lacks complete finalization metadata") from exc
    if min(counts.values()) <= 0 or unresolved != 0 or not meta.get("imported_utc") or not meta.get("importer_version"):
        raise RuntimeError("published national OSM database has incomplete or invalid finalization metadata")
    if checkpoint.get("phase") != "FINALIZE":
        raise RuntimeError("published national OSM database checkpoint is not in FINALIZE phase")
    return {"status": "COMPLETE", "phase": "FINALIZE", "database": str(database),
            "counts": counts, "unresolved_node_refs": unresolved,
            "source_sha256": extract_sha256, "source_pbf_sha256": source_pbf_sha256,
            "importer_version": meta["importer_version"], "checkpoint_token": None,
            "recovered_published_result": True,
            "sqlite_integrity_check": "verified before atomic publication"}


def run_step(extract_path: Path, work_dir: Path, building_database: Path, final_database: Path,
             *, extract_sha256: str, source_pbf_sha256: str, max_records: int = 50_000,
             max_seconds: float = 180.0, decompression_seconds: float = 240.0,
             expected_checkpoint_token: str | None = None) -> dict[str, Any]:
    """Run exactly one durable phase slice; never replace an existing final DB."""
    extract_path, work_dir = extract_path.resolve(strict=True), work_dir.resolve()
    building_database, final_database = building_database.resolve(), final_database.resolve()
    identity = _identity(extract_path, extract_sha256, source_pbf_sha256)
    if final_database.is_file():
        # Final publication wins over stale continuation tokens.  The exact
        # source binding is checked first so a foreign database is never
        # mistaken for a completed import.
        return _published_database_result(final_database, extract_sha256=extract_sha256,
                                          source_pbf_sha256=source_pbf_sha256)
    live_database = building_database if building_database.is_file() else (final_database if final_database.is_file() else None)
    live_token = checkpoint_token(work_dir, live_database)
    if expected_checkpoint_token and expected_checkpoint_token != live_token:
        raise RuntimeError(f"stale OSM continuation: expected checkpoint {expected_checkpoint_token}, current is {live_token}")
    raw_path, _raw_checkpoint = _raw_paths(work_dir)
    if not raw_path.is_file() or not json.loads(_raw_paths(work_dir)[1].read_text(encoding="utf-8")).get("complete"):
        decompression = _ensure_raw(extract_path, work_dir, extract_sha256, source_pbf_sha256,
                                    max_seconds=decompression_seconds)
        if not decompression["complete"]:
            return {"status": "CONTINUE", "phase": "DECOMPRESS", **decompression,
                    "checkpoint_token": checkpoint_token(work_dir),
                    "progress": progress_snapshot(work_dir)}
        # Keep each worker invocation bounded: decompression and database
        # import are separate scheduled tasks, even if decompression fit in one.
        return {"status": "CONTINUE", "phase": "STREAM", **decompression,
                "checkpoint_token": checkpoint_token(work_dir),
                "progress": progress_snapshot(work_dir)}

    building_database.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(building_database)
    try:
        _schema(conn, identity, extract_sha256, source_pbf_sha256)
        cp = _checkpoint(conn)
        phase = cp["phase"]
        if phase == "STREAM":
            complete, processed = _stream_step(conn, raw_path, max_records=max_records, max_seconds=max_seconds)
            detail = {"phase": "STREAM", "slice_records": processed, "phase_complete": complete}
        elif phase == "FEATURES":
            complete, processed = _feature_step(conn, max_records=max_records, max_seconds=max_seconds)
            detail = {"phase": "FEATURES", "slice_records": processed, "phase_complete": complete}
        elif phase == "EDGES":
            complete, processed = _edge_step(conn, max_records=max_records, max_seconds=max_seconds)
            detail = {"phase": "EDGES", "slice_records": processed, "phase_complete": complete}
        elif phase == "INDEXES":
            complete, index = _index_step(conn)
            detail = {"phase": "INDEXES", "index": index, "phase_complete": complete}
        elif phase == "FINALIZE":
            counts = {table: int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
                      for table in ("nodes", "ways", "way_nodes", "edges", "features", "relations")}
            min_lat, min_lon, max_lat, max_lon = conn.execute(
                "SELECT min(latitude),min(longitude),max(latitude),max(longitude) FROM nodes").fetchone()
            metadata = {"source_sha256": extract_sha256, "source_pbf_sha256": source_pbf_sha256,
                "imported_utc": datetime.now(timezone.utc).isoformat(), "importer_version": IMPORTER_VERSION,
                "turn_restrictions_enforced": "false", "node_count": str(counts["nodes"]),
                "way_count": str(counts["ways"]), "relation_count": str(counts["relations"]),
                "directed_edge_count": str(counts["edges"]), "feature_count": str(counts["features"]),
                "address_count": str(conn.execute("SELECT count(*) FROM features WHERE kind IN ('address','poi+address')").fetchone()[0]),
                "poi_count": str(conn.execute("SELECT count(*) FROM features WHERE kind IN ('poi','poi+address')").fetchone()[0]),
                "minimum_latitude": str(min_lat), "minimum_longitude": str(min_lon),
                "maximum_latitude": str(max_lat), "maximum_longitude": str(max_lon)}
            conn.executemany("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", metadata.items())
            # The unresolved-reference scan is indexed and bounded by disk, not
            # a Python object graph. It is part of the database's final proof.
            unresolved = int(conn.execute("SELECT count(*) FROM way_nodes w LEFT JOIN nodes n ON n.id=w.node_id WHERE n.id IS NULL").fetchone()[0])
            conn.execute("INSERT INTO meta(key,value) VALUES('unresolved_node_refs',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(unresolved),))
            if counts["nodes"] <= 0 or counts["ways"] <= 0 or counts["edges"] <= 0:
                raise RuntimeError(f"national database has empty required tables: {counts}")
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                raise RuntimeError(f"national SQLite integrity check failed: {integrity}")
            if final_database.exists():
                raise FileExistsError(f"refusing to overwrite final database: {final_database}")
            conn.commit()
            conn.close()
            os.replace(building_database, final_database)
            return {"status": "COMPLETE", "phase": "FINALIZE", "counts": counts,
                    "unresolved_node_refs": unresolved, "sqlite_integrity_check": integrity,
                    "database": str(final_database), "checkpoint_token": None}
        else:
            raise RuntimeError(f"unknown national import phase {phase!r}")
        progress = progress_snapshot(work_dir, building_database)
        return {"status": "CONTINUE", **detail, "checkpoint_token": progress["checkpoint_token"],
                "progress": progress, "database_building": str(building_database)}
    finally:
        try:
            conn.close()
        except Exception:
            pass

