from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.osm import resumable_national
from src.osm.engine import OSMStore


class ResumableNationalImportTests(unittest.TestCase):
    def test_published_final_database_recovers_before_stale_token_check(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            extract = root / "fixture.osm.gz"
            extract.write_bytes(b"already-imported-source")
            extract_hash = hashlib.sha256(extract.read_bytes()).hexdigest()
            source_hash = hashlib.sha256(b"bound source PBF").hexdigest()
            final = root / "ukraine.sqlite"
            conn = sqlite3.connect(final)
            try:
                conn.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
                                   "CREATE TABLE build_checkpoint(key TEXT PRIMARY KEY,value TEXT NOT NULL);")
                conn.executemany("INSERT INTO meta(key,value) VALUES(?,?)", [
                    ("source_sha256", extract_hash), ("source_pbf_sha256", source_hash),
                    ("node_count", "3"), ("way_count", "1"),
                    ("directed_edge_count", "4"), ("feature_count", "2"),
                    ("unresolved_node_refs", "0"), ("importer_version", "fixture"),
                    ("imported_utc", "2026-10-26T00:00:00+00:00")])
                conn.execute("INSERT INTO build_checkpoint VALUES('phase','FINALIZE')")
                conn.commit()
            finally:
                conn.close()

            result = resumable_national.run_step(
                extract, root / "work", root / "ukraine.sqlite.building", final,
                extract_sha256=extract_hash, source_pbf_sha256=source_hash,
                expected_checkpoint_token="stale-token-from-before-publication")
            self.assertEqual(result["status"], "COMPLETE")
            self.assertTrue(result["recovered_published_result"])
            self.assertEqual(result["counts"]["nodes"], 3)

    def test_published_final_database_with_foreign_source_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            extract = root / "fixture.osm.gz"
            extract.write_bytes(b"scheduled source")
            extract_hash = hashlib.sha256(extract.read_bytes()).hexdigest()
            source_hash = hashlib.sha256(b"scheduled PBF").hexdigest()
            final = root / "ukraine.sqlite"
            conn = sqlite3.connect(final)
            try:
                conn.executescript("CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
                                   "CREATE TABLE build_checkpoint(key TEXT PRIMARY KEY,value TEXT NOT NULL);")
                conn.executemany("INSERT INTO meta(key,value) VALUES(?,?)", [
                    ("source_sha256", "0" * 64), ("source_pbf_sha256", source_hash),
                    ("node_count", "3"), ("way_count", "1"),
                    ("directed_edge_count", "4"), ("feature_count", "2"),
                    ("unresolved_node_refs", "0"), ("importer_version", "fixture"),
                    ("imported_utc", "2026-10-26T00:00:00+00:00")])
                conn.execute("INSERT INTO build_checkpoint VALUES('phase','FINALIZE')")
                conn.commit()
            finally:
                conn.close()

            with self.assertRaisesRegex(RuntimeError, "different source"):
                resumable_national.run_step(
                    extract, root / "work", root / "ukraine.sqlite.building", final,
                    extract_sha256=extract_hash, source_pbf_sha256=source_hash,
                    expected_checkpoint_token="stale-token")

    def test_interrupted_stream_resumes_after_last_transaction_without_reprocessing(self) -> None:
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "work") as temporary:
            root = Path(temporary)
            extract = root / "fixture.osm.gz"
            work = root / "work"
            building = root / "ukraine.sqlite.building"
            final = root / "ukraine.sqlite"
            xml = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="fixture">
<node id="1" lat="47.9000" lon="33.4000" />
<node id="2" lat="47.9010" lon="33.4010" />
<node id="3" lat="47.9020" lon="33.4020" />
<node id="4" lat="47.9030" lon="33.4030" />
<way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><tag k="highway" v="residential"/><tag k="name:uk" v="вулиця Тестова"/></way>
</osm>
""".encode("utf-8")
            with gzip.open(extract, "wb") as stream:
                stream.write(xml)
            extract_hash = hashlib.sha256(extract.read_bytes()).hexdigest()
            source_hash = hashlib.sha256(b"read-only pbf fixture").hexdigest()

            # Process A checkpoints decompression and exits. Process B then
            # commits exactly two nodes and exits; the parent never invokes the
            # importer, so process C must recover from durable SQLite state.
            first_code = r'''
import json,sys
from pathlib import Path
from src.osm.resumable_national import run_step
extract,work,building,final,extract_sha,source_sha=sys.argv[1:]
result=run_step(Path(extract),Path(work),Path(building),Path(final),extract_sha256=extract_sha,
 source_pbf_sha256=source_sha,max_records=2,max_seconds=5)
print(json.dumps(result))
'''
            first_run = subprocess.run([sys.executable, "-B", "-c", first_code,
                str(extract), str(work), str(building), str(final), extract_hash, source_hash],
                cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
            self.assertEqual(first_run.returncode, 0, first_run.stderr or first_run.stdout)
            first = json.loads(first_run.stdout.strip().splitlines()[-1])
            self.assertEqual(first["status"], "CONTINUE")
            self.assertEqual(first["phase"], "STREAM")
            slice_code = r'''
import json,sys
from pathlib import Path
from src.osm.resumable_national import run_step
extract,work,building,final,extract_sha,source_sha,token=sys.argv[1:]
result=run_step(Path(extract),Path(work),Path(building),Path(final),extract_sha256=extract_sha,
 source_pbf_sha256=source_sha,max_records=2,max_seconds=5,expected_checkpoint_token=token)
print(json.dumps(result))
'''
            committed_run = subprocess.run([sys.executable, "-B", "-c", slice_code,
                str(extract), str(work), str(building), str(final), extract_hash, source_hash,
                first["checkpoint_token"]], cwd=PROJECT_ROOT, capture_output=True, text=True,
                encoding="utf-8", timeout=30, check=False)
            self.assertEqual(committed_run.returncode, 0, committed_run.stderr or committed_run.stdout)
            committed = json.loads(committed_run.stdout.strip().splitlines()[-1])
            self.assertEqual(committed["status"], "CONTINUE")
            self.assertEqual(committed["progress"]["counts"]["nodes"], 2)
            token = committed["checkpoint_token"]
            intermediate = sqlite3.connect(building)
            try:
                self.assertEqual(intermediate.execute("SELECT count(*) FROM nodes").fetchone()[0], 2)
                self.assertEqual(dict(intermediate.execute("SELECT key,value FROM build_checkpoint"))["stream_records"], "2")
            finally:
                intermediate.close()

            # A genuinely fresh Python process reopens the on-disk checkpoint
            # and completes all remaining phases with tiny slices.
            code = r'''
import json,sys
from pathlib import Path
from src.osm.resumable_national import run_step
extract,work,building,final,extract_sha,source_sha,token=sys.argv[1:]
for _ in range(40):
 r=run_step(Path(extract),Path(work),Path(building),Path(final),extract_sha256=extract_sha,
   source_pbf_sha256=source_sha,max_records=2,max_seconds=5,expected_checkpoint_token=token)
 token=r.get("checkpoint_token") or token
 if r.get("status")=="COMPLETE":
  print(json.dumps(r)); break
else:
 raise SystemExit("fixture importer did not finish within its bounded continuation count")
'''
            completed = subprocess.run([sys.executable, "-B", "-c", code,
                str(extract), str(work), str(building), str(final), extract_hash, source_hash, token],
                cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            final_step = json.loads(completed.stdout.strip().splitlines()[-1])
            self.assertEqual(final_step["status"], "COMPLETE")
            self.assertEqual(final_step["sqlite_integrity_check"], "ok")

            conn = sqlite3.connect(final)
            try:
                self.assertEqual(conn.execute("SELECT count(*) FROM nodes").fetchone()[0], 4)
                self.assertEqual(conn.execute("SELECT count(*) FROM ways").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT count(*) FROM way_nodes").fetchone()[0], 4)
                self.assertEqual(conn.execute("SELECT count(*) FROM edges").fetchone()[0], 6)
                checkpoint = dict(conn.execute("SELECT key,value FROM build_checkpoint"))
            finally:
                conn.close()
            self.assertEqual(checkpoint["stream_records"], "5")
            self.assertEqual(extract_hash, hashlib.sha256(extract.read_bytes()).hexdigest())
            hits = OSMStore(final).search("Тестова", limit=5)
            self.assertEqual([hit.name for hit in hits], ["вулиця Тестова"])


if __name__ == "__main__":
    unittest.main()
