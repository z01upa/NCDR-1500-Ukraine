"""Hard daily and per-request gate for every Codex CLI model invocation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, time as datetime_time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "project_state.sqlite"
DEFAULT_DAILY_BUDGET = 1
RATE_LIMIT_PATTERN = re.compile(r"rate.?limit|usage limit|quota|try again at", re.IGNORECASE)


class CodexQuotaDeferred(RuntimeError):
    """A Codex-only task was durably parked without invoking the CLI."""

    def __init__(self, reason: str, *, status: str = "WAITING_CODEX_QUOTA") -> None:
        super().__init__(reason)
        self.status = status


def _now(value: datetime | None = None) -> datetime:
    moment = value or datetime.now(timezone.utc)
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def _daily_budget() -> int:
    try:
        value = int(os.environ.get("NCDR_CODEX_DAILY_BUDGET", str(DEFAULT_DAILY_BUDGET)))
    except ValueError:
        value = DEFAULT_DAILY_BUDGET
    return max(0, min(value, 10))


@contextmanager
def _connection(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema(db_path: Path = DEFAULT_DB) -> None:
    with _connection(db_path) as conn:
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS codex_call_ledger(
            request_key TEXT PRIMARY KEY, day_utc TEXT NOT NULL, status TEXT NOT NULL,
            evidence_json TEXT NOT NULL, created_utc TEXT NOT NULL, updated_utc TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}'
          );
          CREATE INDEX IF NOT EXISTS idx_codex_call_ledger_day ON codex_call_ledger(day_utc,status);
          CREATE TABLE IF NOT EXISTS codex_quota_control(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            blocked_until_utc TEXT NOT NULL DEFAULT '', blocked_reason TEXT NOT NULL DEFAULT '',
            updated_utc TEXT NOT NULL
          );
          INSERT OR IGNORE INTO codex_quota_control(singleton,updated_utc) VALUES(1,'');
        """)


def rate_limit_detected(text: str) -> bool:
    return bool(RATE_LIMIT_PATTERN.search(text or ""))


def reserve_call(request_key: str, *, evidence: dict[str, Any],
                 local_failure_recorded: bool = False,
                 critical_architecture: bool = False,
                 db_path: Path = DEFAULT_DB,
                 now: datetime | None = None) -> dict[str, Any]:
    """Atomically reserve a single eligible call; never reserve on a retry."""
    if not request_key.strip():
        raise ValueError("Codex request key must be stable and non-empty")
    moment = _now(now)
    day = moment.date().isoformat()
    ensure_schema(db_path)
    if not (local_failure_recorded or critical_architecture):
        return {"allowed": False, "status": "NOT_ELIGIBLE",
                "reason": "A recorded local execution/verification failure or critical architecture flag is required."}
    encoded_evidence = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    with _connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        control = conn.execute("SELECT blocked_until_utc,blocked_reason FROM codex_quota_control WHERE singleton=1").fetchone()
        prior = conn.execute("SELECT status,day_utc FROM codex_call_ledger WHERE request_key=?", (request_key,)).fetchone()
        if prior:
            return {"allowed": False, "status": "WAITING_CODEX_QUOTA",
                    "reason": "The per-request Codex attempt has already been reserved; new evidence is required."}
        if control and control[0]:
            blocked_until = datetime.fromisoformat(str(control[0]))
            if moment < blocked_until:
                return {"allowed": False, "status": "WAITING_CODEX_QUOTA",
                        "reason": str(control[1] or "Codex rate limit cooldown is active."),
                        "blocked_until_utc": str(control[0])}
        used = int(conn.execute("SELECT count(*) FROM codex_call_ledger WHERE day_utc=?", (day,)).fetchone()[0])
        budget = _daily_budget()
        if used >= budget:
            return {"allowed": False, "status": "WAITING_CODEX_QUOTA",
                    "reason": f"Daily Codex budget exhausted ({used}/{budget})."}
        created = moment.isoformat()
        conn.execute("INSERT INTO codex_call_ledger(request_key,day_utc,status,evidence_json,created_utc,updated_utc) VALUES(?,?,?,?,?,?)",
                     (request_key, day, "STARTED", encoded_evidence, created, created))
    return {"allowed": True, "status": "RESERVED", "request_key": request_key,
            "day_utc": day, "used_today": used + 1, "daily_budget": budget}


def finish_call(request_key: str, status: str, *, detail: dict[str, Any] | None = None,
                db_path: Path = DEFAULT_DB) -> None:
    if status not in {"SUCCEEDED", "FAILED", "RATE_LIMITED"}:
        raise ValueError(f"invalid Codex call result: {status}")
    moment = _now()
    ensure_schema(db_path)
    with _connection(db_path) as conn:
        conn.execute("UPDATE codex_call_ledger SET status=?,updated_utc=?,detail_json=? WHERE request_key=?",
                     (status, moment.isoformat(), json.dumps(detail or {}, ensure_ascii=False), request_key))
        if status == "RATE_LIMITED":
            blocked_until = datetime.combine(moment.date() + timedelta(days=1), datetime_time.min,
                                             tzinfo=timezone.utc)
            conn.execute("UPDATE codex_quota_control SET blocked_until_utc=?,blocked_reason=?,updated_utc=? WHERE singleton=1",
                         (blocked_until.isoformat(), str((detail or {}).get("reason", "Codex rate limit reached."))[:1000],
                          moment.isoformat()))


def record_rate_limit(request_key: str, reason: str, *, db_path: Path = DEFAULT_DB,
                      now: datetime | None = None) -> None:
    """Persist externally observed rate-limit evidence without making a call."""
    moment = _now(now)
    ensure_schema(db_path)
    blocked_until = datetime.combine(moment.date() + timedelta(days=1), datetime_time.min,
                                     tzinfo=timezone.utc)
    detail = {"reason": reason[:2000], "source": "observed_existing_worker_log"}
    with _connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT OR IGNORE INTO codex_call_ledger(request_key,day_utc,status,evidence_json,created_utc,updated_utc,detail_json) VALUES(?,?,?,?,?,?,?)",
            (request_key, moment.date().isoformat(), "RATE_LIMITED",
             json.dumps({"historical_rate_limit": True}, ensure_ascii=False),
             moment.isoformat(), moment.isoformat(), json.dumps(detail, ensure_ascii=False)))
        existing = conn.execute("SELECT blocked_until_utc FROM codex_quota_control WHERE singleton=1").fetchone()
        old_until = str(existing[0] or "") if existing else ""
        if not old_until or datetime.fromisoformat(old_until) < blocked_until:
            conn.execute("UPDATE codex_quota_control SET blocked_until_utc=?,blocked_reason=?,updated_utc=? WHERE singleton=1",
                (blocked_until.isoformat(), reason[:1000], moment.isoformat()))


def snapshot(db_path: Path = DEFAULT_DB, *, now: datetime | None = None) -> dict[str, Any]:
    moment = _now(now)
    ensure_schema(db_path)
    with _connection(db_path) as conn:
        used = int(conn.execute("SELECT count(*) FROM codex_call_ledger WHERE day_utc=?", (moment.date().isoformat(),)).fetchone()[0])
        rows = [dict(zip(("request_key", "day_utc", "status", "created_utc", "updated_utc"), row))
                for row in conn.execute("SELECT request_key,day_utc,status,created_utc,updated_utc FROM codex_call_ledger ORDER BY created_utc DESC LIMIT 50")]
        control = conn.execute("SELECT blocked_until_utc,blocked_reason FROM codex_quota_control WHERE singleton=1").fetchone()
    return {"daily_budget": _daily_budget(), "used_today": used,
            "blocked_until_utc": control[0] if control else "",
            "blocked_reason": control[1] if control else "", "recent_calls": rows}
