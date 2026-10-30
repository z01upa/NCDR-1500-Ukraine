"""Shared SQLite setup and retry policy for catalog and run registration."""
from __future__ import annotations
import random, sqlite3, time
from pathlib import Path

BUSY_TIMEOUT_MS=45000

def connect_database(path, *, readonly=False, timeout_ms=BUSY_TIMEOUT_MS):
    path=Path(path)
    if readonly:
        conn=sqlite3.connect(f"file:{path.resolve()}?mode=ro",uri=True,timeout=timeout_ms/1000)
        conn.execute(f"PRAGMA busy_timeout={int(timeout_ms)}")
        conn.execute("PRAGMA query_only=ON")
        return conn
    path.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path,timeout=timeout_ms/1000)
    conn.execute(f"PRAGMA busy_timeout={int(timeout_ms)}")
    # WAL keeps Overview/history readers from blocking catalog writers.
    deadline=time.monotonic()+timeout_ms/1000
    while True:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            break
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                conn.close(); raise
            if time.monotonic()>=deadline:
                conn.close(); raise TimeoutError("SQLITE_WAL_INITIALIZATION_TIMEOUT") from exc
            time.sleep(min(.25+random.random()*.15,.5))
    return conn

def register_run_with_retry(path, values, *, attempts=8):
    sql="INSERT OR REPLACE INTO run_tasks(run_id,task_id,status,start_time,end_time,run_path,summary_json) VALUES(?,?,?,?,?,?,?)"
    for attempt in range(attempts):
        conn=None
        try:
            conn=connect_database(path,timeout_ms=BUSY_TIMEOUT_MS)
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(sql,values)
            conn.commit()
            return True
        except sqlite3.OperationalError as exc:
            if conn:
                try: conn.rollback()
                except sqlite3.Error: pass
            locked="locked" in str(exc).lower() or "busy" in str(exc).lower()
            if not locked or attempt+1>=attempts: raise
            time.sleep(min(.2*(2**attempt)+random.random()*.1,4.0))
        finally:
            if conn: conn.close()
    return False
