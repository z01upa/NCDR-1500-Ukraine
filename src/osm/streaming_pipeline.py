"""Offline D01 synthetic XML exercise of the durable streaming importer."""
from __future__ import annotations

from contextlib import closing
import hashlib
import gzip
import json
from pathlib import Path
import sqlite3
import tempfile

from src.osm import resumable_national as national


def _rows(database: Path) -> dict:
    """Independent read-only canonical row digests; timestamps are excluded."""
    result = {}
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("D01 independent integrity check failed")
        for table in ("nodes", "ways", "way_nodes", "edges", "relations", "features", "feature_names"):
            columns = len(conn.execute(f"PRAGMA table_info({table})").fetchall())
            digest, count = hashlib.sha256(), 0
            order = ",".join(str(i) for i in range(1, columns + 1))
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order}"):
                digest.update((json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
                count += 1
            result[table] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def verify_d01(project_root: Path, *, node_count: int = 20000, chunk_records: int = 1000) -> dict:
    """Use fresh synthetic paths only; never discover or resume national output."""
    if not 2 <= node_count <= 1000000 or not 1 <= chunk_records <= 5000:
        raise ValueError("D01 stress bounds exceeded")
    from src.agent.project_director import _a02_memory_evidence
    root = project_root.resolve(strict=True)
    work = root / "work"
    reports = root / "reports"
    for directory in (work, reports):
        if not directory.resolve().is_relative_to(root):
            raise ValueError("D01 output escapes project root")
        directory.mkdir(exist_ok=True)
    before_memory = _a02_memory_evidence()
    with tempfile.TemporaryDirectory(prefix="d01-synthetic-", dir=work) as temporary:
        folder = Path(temporary)
        source = folder / "synthetic.osm"
        # One bounded record per line, matching the resumable import contract.
        with source.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write('<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6">\n')
            for number in range(1, node_count + 1):
                stream.write(f'<node id="{number}" lat="{47.9 + number * 0.000001:.6f}" lon="33.4"/>\n')
            for number in range(1, node_count):
                stream.write(f'<way id="{number}"><nd ref="{number}"/><nd ref="{number + 1}"/>'
                             '<tag k="highway" v="residential"/><tag k="name" v="D01 synthetic"/></way>\n')
            stream.write('</osm>\n')
        source_hash = national.sha256_file(source)
        extract = folder / "synthetic.osm.gz"
        with source.open("rb") as stream, extract.open("wb") as output:
            with gzip.GzipFile(fileobj=output, mode="wb", mtime=0, filename="") as compressed:
                while block := stream.read(64 * 1024):
                    compressed.write(block)
        extract_hash = national.sha256_file(extract)
        extraction = {"format": "synthetic line-oriented OSM XML gzip",
                      "source_bytes": source.stat().st_size, "extract_bytes": extract.stat().st_size}
        proofs = []
        slices = []
        checkpoints = []
        for name, limit in (("baseline", 5000), ("resumed", chunk_records)):
            phase_work = folder / name
            building, final = folder / (name + ".building"), folder / (name + ".sqlite")
            token = None
            calls = 0
            first_checkpoint = None
            while True:
                step = national.run_step(extract, phase_work, building, final,
                    extract_sha256=extract_hash, source_pbf_sha256=source_hash,
                    max_records=limit, max_seconds=30, expected_checkpoint_token=token)
                calls += 1
                if step["status"] == "COMPLETE":
                    break
                token = step["checkpoint_token"]
                if first_checkpoint is None:
                    first_checkpoint = token
                if calls > node_count * 10 + 100:
                    raise RuntimeError("D01 continuation bound exceeded")
            slices.append(calls)
            checkpoints.append(first_checkpoint)
            proof = _rows(final)
            expected = {"nodes": node_count, "ways": node_count - 1,
                        "way_nodes": 2 * (node_count - 1), "edges": 2 * (node_count - 1)}
            if any(proof[table]["rows"] != count for table, count in expected.items()):
                raise RuntimeError("D01 synthetic fixture row counts differ from generator")
            proofs.append(proof)
        unchanged = source_hash == national.sha256_file(source) and extract_hash == national.sha256_file(extract)
        if proofs[0] != proofs[1] or not unchanged:
            raise RuntimeError("D01 resume rows or read-only source verification failed")
        memory = _a02_memory_evidence()
        measured = bool(memory.get("diagnostic_peak_working_set_bytes"))
        result = {"status": "PASS" if measured else "WAITING_FOR_EVIDENCE",
            "fixture": {"generator": "deterministic XML chain v1", "nodes": node_count,
                        "ways": node_count - 1, "chunk_records": chunk_records},
            "extraction": extraction, "source_sha256": source_hash, "extract_sha256": extract_hash,
            "committed_rows": proofs[1], "resume_matches_baseline": True, "slice_counts": slices,
            "first_checkpoint_tokens": checkpoints,
            "source_identity_scope": "temporary synthetic XML only; no national source accessed",
            "verification": "separate read-only SQLite connections and canonical ordered row hashes",
            "memory_before": before_memory, "memory": memory,
            "peak_rss_bytes": memory.get("diagnostic_peak_working_set_bytes"),
            "available_ram_bytes": memory.get("available_physical_memory_bytes") or "NOT_AVAILABLE",
            "max_xml_record_bytes": national.MAX_XML_RECORD_BYTES,
            "decompress_chunk_bytes": national.DECOMPRESS_CHUNK_BYTES,
            "measurement_scope": "current synthetic verification process lifetime high-water mark",
            "historical_oom_peak_rss_bytes": None, "historical_peak_status": "NOT_RECORDED", "source_hashes_unchanged": unchanged,
            "national_checkpoint_access_count": 0, "original_media_write_count": 0}
    output = reports / "osm-memory-profile.json"
    if not output.resolve().is_relative_to(root):
        raise ValueError("D01 report escapes project root")
    national._atomic_json(output, result)
    return result
