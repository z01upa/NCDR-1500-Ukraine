"""Bounded, read-only OSM tile-boundary research over an existing SQLite map.

The probe measures how many ways span multiple cells in a small geographic
window. It deliberately avoids loading the national graph into Python memory:
SQLite uses a fixed page cache and file-backed temporary storage, while the
independent verification pass streams one way's cell memberships at a time.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sqlite3
import time
from typing import Any


def _validate(bbox: tuple[float, float, float, float], rows: int, columns: int,
              max_nodes: int, timeout_s: int) -> tuple[float, float, float, float]:
    if len(bbox) != 4:
        raise ValueError("bbox must be (south, west, north, east)")
    south, west, north, east = (float(value) for value in bbox)
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError("bbox must be an ordered geographic rectangle")
    if not (1 <= int(rows) <= 16 and 1 <= int(columns) <= 16):
        raise ValueError("grid dimensions must be between 1 and 16")
    if not (1 <= int(max_nodes) <= 500_000):
        raise ValueError("max_nodes must be between 1 and 500000")
    if not (1 <= int(timeout_s) <= 900):
        raise ValueError("timeout_s must be between 1 and 900")
    return south, west, north, east


def _tile(latitude: float, longitude: float, bbox: tuple[float, float, float, float],
          rows: int, columns: int) -> int:
    south, west, north, east = bbox
    y = min(rows - 1, max(0, int((latitude - south) / (north - south) * rows)))
    x = min(columns - 1, max(0, int((longitude - west) / (east - west) * columns)))
    return y * columns + x


def run_partition_probe(database: Path, *, bbox: tuple[float, float, float, float],
                        rows: int, columns: int, max_nodes: int = 200_000,
                        timeout_s: int = 300) -> dict[str, Any]:
    """Measure way-to-cell overlap and verify it with a bounded streaming pass."""
    bbox = _validate(bbox, rows, columns, max_nodes, timeout_s)
    path = Path(database).resolve(strict=True)
    if not path.is_file():
        raise ValueError("OSM database must be a regular file")
    before = path.stat()
    deadline = time.monotonic() + timeout_s
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA cache_size=-65536")
        conn.execute("PRAGMA temp_store=FILE")
        conn.execute("PRAGMA mmap_size=0")
        conn.execute("PRAGMA busy_timeout=20000")
        conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        tables = {str(row[0]) for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"nodes", "way_nodes", "meta"}.issubset(tables):
            raise ValueError("database does not have the expected OSM nodes/way_nodes/meta tables")
        indexes = {str(row[1]) for row in conn.execute("PRAGMA index_list(nodes)")}
        way_indexes = {str(row[1]) for row in conn.execute("PRAGMA index_list(way_nodes)")}
        if "idx_nodes_lat_lon" not in indexes or "idx_way_nodes_node" not in way_indexes:
            raise ValueError("database is missing the indexes required for bounded regional reads")

        south, west, north, east = bbox
        node_count = int(conn.execute(
            "SELECT count(*) FROM nodes WHERE latitude BETWEEN ? AND ? "
            "AND longitude BETWEEN ? AND ?", (south, north, west, east)).fetchone()[0])
        if node_count > max_nodes:
            raise ValueError(f"bbox contains {node_count} nodes, above the {max_nodes} node bound")
        if node_count == 0:
            raise ValueError("bbox contains no OSM nodes")

        tile_y = f"min({rows - 1}, max(0, cast((n.latitude - {south!r}) / ({north - south!r}) * {rows} as integer)))"
        tile_x = f"min({columns - 1}, max(0, cast((n.longitude - {west!r}) / ({east - west!r}) * {columns} as integer)))"
        measure_sql = f"""
            WITH local_nodes AS (
                SELECT id, {tile_y} AS tile_y, {tile_x} AS tile_x
                FROM nodes AS n
                WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?
            )
            SELECT wn.way_id, count(*) AS node_memberships,
                   count(DISTINCT local_nodes.tile_y * {columns} + local_nodes.tile_x) AS tile_count
            FROM local_nodes
            JOIN way_nodes AS wn ON wn.node_id = local_nodes.id
            GROUP BY wn.way_id
        """
        measured = Counter()
        way_count = 0
        membership_count = 0
        for row in conn.execute(measure_sql, (south, north, west, east)):
            way_count += 1
            membership_count += int(row["node_memberships"])
            measured[int(row["tile_count"])] += 1
            if membership_count > max_nodes * 32:
                raise ValueError("regional way-node memberships exceed the deterministic bound")

        # Independent check: calculate tiles from each coordinate and reduce a
        # single way at a time. No rows or national-size set are retained.
        stream_sql = """
            SELECT wn.way_id, n.latitude, n.longitude
            FROM nodes AS n
            JOIN way_nodes AS wn ON wn.node_id = n.id
            WHERE n.latitude BETWEEN ? AND ? AND n.longitude BETWEEN ? AND ?
            ORDER BY wn.way_id, wn.node_index
        """
        verified = Counter()
        streamed_memberships = 0
        current_way: str | None = None
        current_tiles: set[int] = set()

        def finish_way() -> None:
            if current_way is not None:
                verified[len(current_tiles)] += 1

        for row in conn.execute(stream_sql, (south, north, west, east)):
            way_id = str(row["way_id"])
            if way_id != current_way:
                finish_way()
                current_way, current_tiles = way_id, set()
            current_tiles.add(_tile(float(row["latitude"]), float(row["longitude"]), bbox, rows, columns))
            streamed_memberships += 1
            if streamed_memberships > max_nodes * 32:
                raise ValueError("verification memberships exceed the deterministic bound")
            if time.monotonic() >= deadline:
                raise TimeoutError("OSM partition probe exceeded its time budget")
        finish_way()
        if measured != verified or membership_count != streamed_memberships:
            raise RuntimeError("SQL tile aggregation and independent streaming verification disagree")

        source_meta = {str(key): str(value) for key, value in conn.execute(
            "SELECT key,value FROM meta WHERE key IN ('source_sha256','node_count','directed_edge_count')")}
        if not source_meta.get("source_sha256"):
            raise ValueError("OSM database has no source hash in meta")
        explain = [str(row[3]) for row in conn.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM nodes WHERE latitude BETWEEN ? AND ? "
            "AND longitude BETWEEN ? AND ?", (south, north, west, east))]
    finally:
        conn.close()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("read-only OSM database changed during the probe")
    crossing = sum(count for span, count in measured.items() if span > 1)
    return {
        "status": "PASS", "database": str(path), "database_size_bytes": before.st_size,
        "database_mtime_ns_unchanged": True, "source_meta": source_meta,
        "bbox_south_west_north_east": list(bbox), "grid_rows": rows,
        "grid_columns": columns, "node_count": node_count, "way_count": way_count,
        "way_node_memberships": membership_count,
        "cross_tile_way_count": crossing,
        "cross_tile_way_ratio": round(crossing / way_count, 8) if way_count else 0.0,
        "ways_by_tile_span": {str(span): count for span, count in sorted(measured.items())},
        "independent_streaming_verification": {
            "status": "PASS", "way_count": sum(verified.values()),
            "way_node_memberships": streamed_memberships,
            "ways_by_tile_span": {str(span): count for span, count in sorted(verified.items())}},
        "sqlite_limits": {"page_cache_bytes": 64 * 1024 * 1024,
                          "temp_store": "FILE", "mmap_bytes": 0,
                          "python_retained_way_state": "one way's tile set at a time"},
        "query_plan": explain,
        "claim_scope": "regional OSM tile-boundary evidence; no navigation-disc or Opel compatibility claim",
    }
