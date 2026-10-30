"""Durable local AI Director requests and interval scheduling.

The GUI only writes a request/configuration and reads snapshots.  All Director
work is claimed and executed by the long-lived research Worker under a SQLite
lease, so closing the window cannot stop or duplicate planning.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Callable


INTERVAL_SECONDS = (300, 900, 1800, 3600, 7200, 21600)
DEFAULT_INTERVAL_SECONDS = 1800
DECISIONS = {"CREATED", "EXECUTED", "REJECTED", "NO_NEW_EVIDENCE",
             "MISSING_HANDLER", "BLOCKED_EXTERNAL", "ERROR"}


def _utc(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def ensure_schema(db_path: Path) -> None:
    """Additive-only tables; existing task/evidence/checkpoint data is untouched."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(db_path)) as conn:
        conn.executescript("""
          CREATE TABLE IF NOT EXISTS director_scheduler_config(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            enabled INTEGER NOT NULL DEFAULT 1,
            interval_seconds INTEGER NOT NULL DEFAULT 1800,
            next_run_utc TEXT,
            last_run_utc TEXT,
            last_task_id TEXT,
            last_result TEXT NOT NULL DEFAULT 'NOT_RUN',
            last_reason TEXT NOT NULL DEFAULT '',
            last_evidence_fingerprint TEXT NOT NULL DEFAULT '',
            pending_request_id TEXT,
            pending_request_utc TEXT,
            lease_owner TEXT,
            lease_until_utc TEXT,
            updated_utc TEXT NOT NULL
          );
          CREATE TABLE IF NOT EXISTS director_decisions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL UNIQUE,
            created_utc TEXT NOT NULL,
            decision TEXT NOT NULL,
            task_id TEXT,
            model TEXT,
            reason TEXT NOT NULL DEFAULT '',
            evidence_fingerprint TEXT NOT NULL DEFAULT '',
            detail_json TEXT NOT NULL DEFAULT '{}'
          );
          CREATE INDEX IF NOT EXISTS idx_director_decisions_created
            ON director_decisions(created_utc DESC);
        """)
        row = conn.execute("SELECT singleton FROM director_scheduler_config WHERE singleton=1").fetchone()
        if row is None:
            now = datetime.now(timezone.utc)
            conn.execute("""INSERT INTO director_scheduler_config(
                singleton,enabled,interval_seconds,next_run_utc,updated_utc)
                VALUES(1,1,?,?,?)""",
                (DEFAULT_INTERVAL_SECONDS, _utc(now + timedelta(seconds=DEFAULT_INTERVAL_SECONDS)), _utc(now)))
        conn.commit()


def configure(enabled: bool, interval_seconds: int, *, db_path: Path) -> dict[str, Any]:
    if interval_seconds not in INTERVAL_SECONDS:
        raise ValueError("unsupported Director interval")
    ensure_schema(db_path)
    now = datetime.now(timezone.utc)
    next_run = _utc(now + timedelta(seconds=interval_seconds)) if enabled else None
    with closing(_connect(db_path)) as conn:
        conn.execute("""UPDATE director_scheduler_config SET enabled=?,interval_seconds=?,
            next_run_utc=?,updated_utc=? WHERE singleton=1""",
            (int(enabled), interval_seconds, next_run, _utc(now)))
        conn.commit()
    return snapshot(db_path=db_path)


def request_manual(*, db_path: Path) -> str:
    """Durably request exactly one immediate Director cycle, coalescing clicks."""
    ensure_schema(db_path)
    request_id = "MANUAL_" + uuid.uuid4().hex.upper()
    now = _utc()
    with closing(_connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT pending_request_id FROM director_scheduler_config WHERE singleton=1").fetchone()
        if row and row[0]:
            request_id = str(row[0])
        else:
            conn.execute("""UPDATE director_scheduler_config SET pending_request_id=?,
                pending_request_utc=?,updated_utc=? WHERE singleton=1""", (request_id, now, now))
        conn.commit()
    return request_id


def snapshot(*, db_path: Path) -> dict[str, Any]:
    if not db_path.is_file():
        return {"available": False, "decisions": []}
    with closing(_connect(db_path)) as conn:
        conn.execute("PRAGMA query_only=ON")
        config = conn.execute("SELECT * FROM director_scheduler_config WHERE singleton=1").fetchone()
        decisions = [dict(row) for row in conn.execute(
            "SELECT request_id,created_utc,decision,task_id,model,reason,evidence_fingerprint "
            "FROM director_decisions ORDER BY id DESC LIMIT 100")]
    return {"available": bool(config), "config": dict(config) if config else {},
            "decisions": decisions}


def _reserve_cycle(owner: str, *, db_path: Path, force: bool = False,
                   now: datetime | None = None) -> dict[str, Any] | None:
    ensure_schema(db_path)
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    moment_text = _utc(moment)
    with closing(_connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM director_scheduler_config WHERE singleton=1").fetchone()
        if not row:
            conn.rollback()
            return None
        lease_until = _parse(row["lease_until_utc"])
        if row["lease_owner"] and lease_until and lease_until > moment:
            conn.rollback()
            return None
        manual_id = row["pending_request_id"]
        next_run = _parse(row["next_run_utc"])
        due = bool(row["enabled"] and (force or next_run is None or next_run <= moment))
        if not manual_id and not due:
            conn.rollback()
            return None
        request_id = str(manual_id or ("AUTO_" + uuid.uuid4().hex.upper()))
        interval = int(row["interval_seconds"] or DEFAULT_INTERVAL_SECONDS)
        next_value = _utc(moment + timedelta(seconds=interval)) if row["enabled"] else None
        conn.execute("""UPDATE director_scheduler_config SET pending_request_id=NULL,
            pending_request_utc=NULL,lease_owner=?,lease_until_utc=?,last_run_utc=?,
            next_run_utc=?,updated_utc=? WHERE singleton=1""",
            (owner, _utc(moment + timedelta(minutes=15)), moment_text, next_value, moment_text))
        conn.commit()
        return {"request_id": request_id, "manual": bool(manual_id),
                "enabled": bool(row["enabled"]), "interval_seconds": interval}


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _safe_evidence_fields(raw: Any) -> str:
    """Keep only source/task identifiers and hashes; do not copy arbitrary payloads into the prompt."""
    try:
        value = json.loads(str(raw or "[]"))
    except (TypeError, json.JSONDecodeError):
        return "[]"
    allowed = {"source", "task_id", "artifact_path", "artifact_sha256", "candidate_fingerprint",
        "mission_task_id", "prior_task", "relative_path", "sha256", "goal_id", "selection_evidence_task_id"}
    records = value if isinstance(value, list) else [value]
    safe = []
    for item in records[:12]:
        if isinstance(item, dict):
            safe.append({str(key): str(val)[:240] for key, val in list(item.items())[:20]
                         if str(key) in allowed and isinstance(val, (str, int, float))})
        elif isinstance(item, str):
            safe.append(item[:200])
    return json.dumps(safe, ensure_ascii=False, sort_keys=True)[:1200]


def _evidence_snapshot(db_path: Path) -> dict[str, Any]:
    """Return compact, bounded verified results and Supervisor failures only."""
    with closing(_connect(db_path)) as conn:
        conn.execute("PRAGMA query_only=ON")
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        task_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)")} if "tasks" in tables else set()
        selected = [c for c in ("id", "stage", "status", "verdict", "agent", "hypothesis",
                    "result_json", "updated_utc") if c in task_columns]
        rows = [dict(row) for row in conn.execute(
            f"SELECT {','.join(selected)} FROM tasks WHERE status IN ('DONE','BLOCKED') "
            "ORDER BY updated_utc DESC LIMIT 30")] if selected else []
        verified = []
        rejections = []
        for row in rows:
            try:
                result = json.loads(row.get("result_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                result = {}
            if not isinstance(result, dict):
                result = {}
            artifact = result.get("artifact") if isinstance(result.get("artifact"), dict) else {}
            brief = {"task_id": row.get("id"), "stage": row.get("stage"),
                "status": row.get("status"), "verdict": row.get("verdict"),
                "agent": row.get("agent"), "hypothesis": str(row.get("hypothesis") or "")[:240],
                "updated_utc": row.get("updated_utc"),
                "result_status": str(result.get("status") or result.get("claim_status") or "")[:80],
                "artifact_path": str(artifact.get("path") or "")[:220],
                "artifact_sha256": str(artifact.get("sha256") or "")[:64],
                "error": str(result.get("error") or "")[:300]}
            if row.get("status") == "DONE" and str(row.get("verdict") or "").upper() in {"PASS", "ACCEPTED", "VERIFIED"}:
                verified.append(brief)
            if row.get("status") == "BLOCKED" and ("supervisor" in str(row.get("agent") or "").casefold()
                                                       or result.get("failure_diagnostic")):
                rejections.append(brief)
    missions: dict[str, Any] = {"available": False}
    try:
        from src.agent import mission_pack
        missions = mission_pack.planner_diagnosis(db_path=db_path)
    except Exception as exc:
        missions = {"available": False, "diagnostic_error": f"{type(exc).__name__}: {exc}"[:240]}
    material = {"verified": verified[:8], "supervisor_rejections": rejections[:8], "missions": missions}
    fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    return {**material, "evidence_fingerprint": fingerprint}


def _call_director(request_id: str, *, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    from src.agent import coordinator_runtime, project_director
    models = coordinator_runtime._available_models()
    model = "qwen3.5:9b"
    if model not in models:
        raise RuntimeError(f"потрібна локальна модель {model}; доступні: {', '.join(models[:12]) or 'немає'}")
    candidate = context.get("registered_candidate")
    choices = ["CONTINUE", "REJECT"] if candidate else ["NO_NEW_EVIDENCE"]
    prompt = json.dumps({
        "role": "NCDR local research Director",
        "project_state": project_director._director_context(),
        "new_verified_evidence": context.get("verified", [])[:8],
        "supervisor_rejections": context.get("supervisor_rejections", [])[:8],
        "unfinished_missions": context.get("missions", {}),
        "previous_evidence_fingerprint": context.get("previous_evidence_fingerprint"),
        "current_evidence_fingerprint": context.get("evidence_fingerprint"),
        "registered_candidate": candidate,
        "allowed_decisions": choices,
        "constraints": ["Only assess the exact registered task candidate, if present.",
            "Do not invent a task, tool, binary semantics, code, path, command or acceptance criterion.",
            "The candidate was selected by the deterministic registered-handler scheduler and may run only if its input, handler and verifier are named.",
            "If there is no candidate, return NO_NEW_EVIDENCE and name the concrete missing capability or external input.",
            "Never request writes to original Opel media; do not propose Virtual CID or a standalone POI editor."],
        "response_schema": {"decision": choices[0],
            "task_id": candidate.get("task_id") if candidate else None,
            "reason": "short evidence-based decision", "missing_proofs": []}},
        ensure_ascii=False)
    if candidate:
        task_id = str(candidate["task_id"])
        with closing(sqlite3.connect(coordinator_runtime.STATE_DB, timeout=10)) as conn:
            prior = conn.execute("SELECT COALESCE(MAX(sequence),0) FROM research_runs WHERE task_id=?",
                                 (task_id,)).fetchone()
        attempt = int(prior[0] or 0) + 1
    else:
        # A no-candidate analysis is correlated to its durable Director request
        # rather than pretending to belong to a research task that does not exist.
        task_id = "DIRECTOR_ANALYSIS_" + request_id
        attempt = 1
    _actual_model, _raw, parsed = coordinator_runtime._call_model(
        task_id, "project-director", prompt, attempt=attempt, fixed_model=model)
    if parsed.get("decision") not in choices:
        raise ValueError("local Director returned a decision outside the bounded schema")
    expected = candidate.get("task_id") if candidate else None
    if parsed.get("task_id") != expected:
        raise ValueError("local Director task ID does not match the registered candidate")
    reason = str(parsed.get("reason") or "Без пояснення моделі")[:700]
    missing = parsed.get("missing_proofs", [])
    if isinstance(missing, list) and missing:
        reason = (reason + " · відсутні докази: " + "; ".join(str(item)[:160] for item in missing[:5]))[:1000]
    return model, {**parsed, "reason": reason,
                   "missing_proofs": [str(item)[:240] for item in missing[:8]]
                   if isinstance(missing, list) else []}


def _record(db_path: Path, request_id: str, decision: str, *, task_id: str | None,
            model: str | None, reason: str, fingerprint: str, detail: dict[str, Any]) -> None:
    if decision not in DECISIONS:
        decision = "ERROR"
    now = _utc()
    detail_json = json.dumps(detail, ensure_ascii=False, sort_keys=True)[:12000]
    with closing(_connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""INSERT INTO director_decisions(
            request_id,created_utc,decision,task_id,model,reason,evidence_fingerprint,detail_json)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(request_id) DO UPDATE SET
            created_utc=excluded.created_utc,decision=excluded.decision,task_id=excluded.task_id,
            model=excluded.model,reason=excluded.reason,evidence_fingerprint=excluded.evidence_fingerprint,
            detail_json=excluded.detail_json""",
            (request_id, now, decision, task_id, model, reason[:1000], fingerprint, detail_json))
        conn.execute("""UPDATE director_scheduler_config SET last_task_id=?,last_result=?,
            last_reason=?,last_evidence_fingerprint=?,lease_owner=NULL,lease_until_utc=NULL,updated_utc=?
            WHERE singleton=1""",
            (task_id, decision, reason[:1000], fingerprint, now))
        conn.commit()


def process_due(owner: str, *, db_path: Path, force: bool = False) -> dict[str, Any]:
    """Run one serialized Director cycle in the worker process, never the GUI."""
    claim = _reserve_cycle(owner, db_path=db_path, force=force)
    if claim is None:
        return {"processed": False, "reason": "not due or another Director lease is active"}
    request_id = str(claim["request_id"])
    context: dict[str, Any] = {}
    model: str | None = None
    task_id: str | None = None
    candidate: dict[str, Any] | None = None
    try:
        context = _evidence_snapshot(db_path)
        context["previous_evidence_fingerprint"] = ""
        with closing(_connect(db_path)) as conn:
            row = conn.execute("SELECT last_evidence_fingerprint FROM director_scheduler_config WHERE singleton=1").fetchone()
            if row:
                context["previous_evidence_fingerprint"] = str(row[0] or "")
        # Local AI availability is verified before any new task is written.
        from src.agent import coordinator_runtime
        installed = coordinator_runtime._available_models()
        if "qwen3.5:9b" not in installed:
            raise RuntimeError("Ollama або обов'язкова qwen3.5:9b недоступна")
        from src.agent import autonomous_manager as manager
        queue = manager.queue_diagnosis(db_path=db_path)
        if queue.get("eligible_task_ids") or int(queue.get("leased_count", 0)):
            plan = {"created": False, "reason": "у черзі вже є придатна або орендована задача",
                    "queue": queue}
        else:
            plan = manager.schedule_next_goal_task()
        task_id = str(plan.get("task_id")) if plan.get("created") and plan.get("task_id") else None
        if task_id:
            row = manager._task(task_id)
            candidate = {"task_id": task_id, "stage": row.get("stage"), "agent": row.get("agent"),
                "hypothesis": str(row.get("hypothesis") or "")[:500],
                "input_evidence": _safe_evidence_fields(row.get("evidence_json")),
                "acceptance_criteria": str(row.get("objective_tests_json") or "")[:1200],
                "dependencies": row.get("depends_on", [])}
        context["registered_candidate"] = candidate
        model, parsed = _call_director(request_id, context=context)
        if candidate:
            if parsed["decision"] == "CONTINUE":
                decision = "CREATED"
                reason = str(parsed["reason"])
            else:
                from src.agent import state_store
                retired = state_store.supersede_task(task_id, str(parsed["reason"]),
                    evidence={"verifier": "bounded_local_director", "request_id": request_id,
                              "decision": "REJECT", "missing_proofs": parsed.get("missing_proofs", [])},
                    db_path=db_path)
                decision = "REJECTED" if retired else "ERROR"
                reason = (str(parsed["reason"]) if retired else
                          "Director відхилив задачу, але вона вже не перебуває у стані PENDING")
        else:
            decision = "NO_NEW_EVIDENCE"
            reason = str(parsed["reason"])
        details = {"manual": claim["manual"], "queue_diagnosis": plan.get("queue", queue),
            "scheduler_reason": str(plan.get("reason", ""))[:800],
            "missing_proofs": parsed.get("missing_proofs", []),
            "registered_candidate": candidate,
            "new_evidence_count": len(context.get("verified", [])),
            "supervisor_rejection_count": len(context.get("supervisor_rejections", []))}
        _record(db_path, request_id, decision, task_id=task_id, model=model,
                reason=reason, fingerprint=str(context["evidence_fingerprint"]), detail=details)
        return {"processed": True, "decision": decision, "task_id": task_id,
                "reason": reason, "model": model}
    except Exception as exc:
        decision = ("BLOCKED_EXTERNAL" if "недоступна" in str(exc).casefold()
                    or "потрібна локальна модель" in str(exc).casefold() else
                    "MISSING_HANDLER" if "handler" in str(exc).casefold() else "ERROR")
        if task_id:
            try:
                from src.agent import state_store
                state_store.supersede_task(task_id,
                    "Director cycle did not accept this task: " + f"{type(exc).__name__}: {exc}"[:700],
                    evidence={"request_id": request_id, "decision": decision}, db_path=db_path)
            except Exception:
                pass
        reason = f"{type(exc).__name__}: {exc}"[:1000]
        _record(db_path, request_id, decision, task_id=task_id, model=model,
                reason=reason, fingerprint=str(context.get("evidence_fingerprint", "")),
                detail={"manual": claim["manual"], "error": reason})
        return {"processed": True, "decision": decision, "task_id": task_id, "reason": reason}


def mark_executed(task_id: str, *, db_path: Path) -> None:
    with closing(_connect(db_path)) as conn:
        conn.execute("""UPDATE director_decisions SET decision='EXECUTED',created_utc=?
            WHERE task_id=? AND decision='CREATED'""", (_utc(), task_id))
        conn.execute("""UPDATE director_scheduler_config SET last_result='EXECUTED',
            updated_utc=? WHERE singleton=1 AND last_task_id=? AND last_result='CREATED'""",
            (_utc(), task_id))
        conn.commit()
