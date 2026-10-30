"""Persistent file projections for the existing SQLite-backed research manager.

SQLite remains authoritative. This layout stores bounded status/checkpoint
manifests and pointers to artifacts; it never copies the project databases or
the original NCDR/OSM media.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAYOUT_ROOT = PROJECT_ROOT / "AUTONOMOUS_RESEARCH"
TASK_BUCKETS = {
    "PENDING": "INBOX", "LEASED": "RUNNING", "DONE": "COMPLETED",
    "BLOCKED": "FAILED", "WAITING_CODEX": "WAITING_CODEX_QUOTA",
    "WAITING_CODEX_QUOTA": "WAITING_CODEX_QUOTA",
    "WAITING_EXTERNAL": "INBOX", "WAITING_LOCAL": "INBOX",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
            prefix=path.name + ".", suffix=".tmp", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def ensure_layout(project_root: Path = PROJECT_ROOT) -> Path:
    root = Path(project_root).resolve() / "AUTONOMOUS_RESEARCH"
    for relative in (
        "TASKS/INBOX", "TASKS/RUNNING", "TASKS/COMPLETED", "TASKS/FAILED",
        "TASKS/WAITING_CODEX_QUOTA", "RESULTS/NEW", "RESULTS/VERIFIED",
        "RESULTS/REJECTED", "ENGINEERING/LOCAL_REPAIRS",
        "ENGINEERING/CODEX_WEEKLY_INBOX", "ENGINEERING/CODEX_WEEKLY_OUTBOX",
        "ENGINEERING/UNRESOLVED", "MISSION", "EVIDENCE", "REPORTS",
        "ARTIFACTS", "STATE", "LOGS",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(
            "# NCDR Autonomous Research\n\n"
            "This is a durable file view of the existing NCDR Autonomous Research Manager. "
            "The authoritative task queue, leases, evidence, and checkpoints remain in "
            "`project_state.sqlite`, `TASK_BACKLOG.sqlite`, and `EVIDENCE_LEDGER.sqlite` "
            "at the project root. This folder stores small status manifests and artifact "
            "pointers; it does not duplicate those databases or source media.\n",
            encoding="utf-8")
    _atomic_json(root / "STATE" / "layout.json", {
        "schema_version": 1, "updated_utc": _utc(),
        "authoritative_state": ["project_state.sqlite", "TASK_BACKLOG.sqlite", "EVIDENCE_LEDGER.sqlite"],
        "original_media_policy": "read-only",
        "excluded_tracks": ["Virtual CID", "standalone POI Editor"],
    })
    return root


def _task_key(task_id: str) -> str:
    key = re.sub(r"[^A-Za-z0-9_.-]", "_", str(task_id))[:180]
    if not key or key in {".", ".."}:
        raise ValueError("task id cannot be represented safely in the research projection")
    return key


def _artifact_pointers(value: Any, *, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            label = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(item, str) and (key.casefold().endswith("path") or key.casefold() in {"path", "artifact"}):
                candidate = Path(item)
                if not candidate.is_absolute() and ".." not in candidate.parts:
                    found.append(candidate.as_posix())
            else:
                found.extend(_artifact_pointers(item, prefix=label))
    elif isinstance(value, list):
        for item in value[:100]:
            found.extend(_artifact_pointers(item, prefix=prefix))
    return sorted(set(found))[:100]


def _project_task(task_id: str, status: str, *, result: dict[str, Any] | None = None,
                  project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = ensure_layout(project_root)
    key = _task_key(task_id)
    task_record = {"task_id": task_id, "status": status, "updated_utc": _utc(),
        "authoritative_record": "project_state.sqlite:tasks", "artifact_pointers": _artifact_pointers(result or {})}
    for bucket in set(TASK_BUCKETS.values()):
        (root / "TASKS" / bucket / f"{key}.json").unlink(missing_ok=True)
    target_bucket = TASK_BUCKETS.get(status, "INBOX")
    _atomic_json(root / "TASKS" / target_bucket / f"{key}.json", task_record)

    if status == "DONE":
        result_bucket = "NEW"
    elif status == "BLOCKED":
        result_bucket = "REJECTED"
    else:
        result_bucket = None
    if result_bucket:
        _atomic_json(root / "RESULTS" / result_bucket / f"{key}.json", task_record)
    return task_record


def sync_active_tasks(state_db: Path, *, project_root: Path = PROJECT_ROOT) -> int:
    if not Path(state_db).is_file():
        return 0
    with closing(sqlite3.connect(f"file:{Path(state_db).resolve().as_posix()}?mode=ro", uri=True, timeout=10)) as conn:
        rows = conn.execute("SELECT id,status FROM tasks WHERE status IN "
            "('PENDING','LEASED','WAITING_CODEX','WAITING_CODEX_QUOTA','WAITING_EXTERNAL','WAITING_LOCAL')").fetchall()
    for task_id, status in rows:
        _project_task(str(task_id), str(status), project_root=project_root)
    return len(rows)


def persist_manager_checkpoint(state_db: Path, worker_session: str, *,
                               project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Write a small startup snapshot pointing back to the authoritative SQLite checkpoint."""
    root = ensure_layout(project_root)
    if not Path(state_db).is_file():
        raise FileNotFoundError(f"authoritative state database is missing: {state_db}")
    with closing(sqlite3.connect(f"file:{Path(state_db).resolve().as_posix()}?mode=ro", uri=True, timeout=10)) as conn:
        control = conn.execute("SELECT desired_state,worker_pid,current_task,updated_utc FROM autonomy_control WHERE singleton=1").fetchone()
        counts = {str(status): int(count) for status, count in conn.execute(
            "SELECT status,count(*) FROM tasks GROUP BY status ORDER BY status")}
        last_done = conn.execute("SELECT id,updated_utc FROM tasks WHERE status='DONE' "
                                 "ORDER BY updated_utc DESC,id LIMIT 1").fetchone()
    snapshot = {"checkpoint_type": "worker_startup_or_resume", "updated_utc": _utc(),
        "worker_session": worker_session, "control": dict(zip(
            ("desired_state", "worker_pid", "current_task", "control_updated_utc"), control or ())),
        "task_counts": counts,
        "latest_completed_task": {"task_id": last_done[0], "updated_utc": last_done[1]} if last_done else None,
        "authoritative_state_db": str(Path(state_db).resolve()),
        "state_is_authoritative_in_sqlite": True, "original_media_write_count": 0}
    _atomic_json(root / "STATE" / "latest_checkpoint.json", snapshot)
    return snapshot


def persist_checkpoint(task_id: str, status: str, result: dict[str, Any] | None = None, *,
                       state_db: Path | None = None, verified: bool = False,
                       project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = ensure_layout(project_root)
    record = _project_task(task_id, status, result=result, project_root=project_root)
    result_bytes = json.dumps(result or {}, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    result_hash = hashlib.sha256(result_bytes).hexdigest()
    checkpoint = {**record, "result_sha256": result_hash,
        "verified_by_independent_reviewer": bool(verified),
        "authoritative_state_db": str((state_db or (Path(project_root) / "project_state.sqlite")).resolve()),
        "original_media_write_count": 0}
    _atomic_json(root / "STATE" / "latest_checkpoint.json", checkpoint)
    key = _task_key(task_id)
    if verified:
        for bucket in ("NEW", "REJECTED"):
            (root / "RESULTS" / bucket / f"{key}.json").unlink(missing_ok=True)
        _atomic_json(root / "RESULTS" / "VERIFIED" / f"{key}.json", checkpoint)
    elif status == "BLOCKED":
        _atomic_json(root / "RESULTS" / "REJECTED" / f"{key}.json", checkpoint)
    elif status == "DONE":
        _atomic_json(root / "RESULTS" / "NEW" / f"{key}.json", checkpoint)
    return checkpoint
