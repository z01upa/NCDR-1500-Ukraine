"""Per-user logon watchdog fallback when Task Scheduler management is unavailable."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    # Task Scheduler starts this file by path, which otherwise puts only the
    # windows/ directory on sys.path and breaks STOPPED-checkpoint recovery.
    sys.path.insert(0, str(PROJECT_ROOT))
MANAGER_WORK = PROJECT_ROOT / "work" / "autonomous_manager"
STATE_DB = PROJECT_ROOT / "project_state.sqlite"
WORKER_LOCK = MANAGER_WORK / "worker.lock"
WATCHDOG_LOCK = MANAGER_WORK / "worker_watchdog.lock"
LOG_PATH = MANAGER_WORK / "logs" / "worker_watchdog.jsonl"
POLL_SECONDS = 2
RESTART_DELAY_SECONDS = 5


def _log_event(event: str, **details: object) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(),
                "event": event, "watchdog_pid": os.getpid(), **details}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _desired_state() -> str:
    if not STATE_DB.is_file():
        return "STOPPED"
    try:
        with closing(sqlite3.connect(f"file:{STATE_DB.as_posix()}?mode=ro", uri=True, timeout=5)) as conn:
            row = conn.execute("SELECT desired_state FROM autonomy_control WHERE singleton=1").fetchone()
        return str(row[0]) if row else "STOPPED"
    except sqlite3.Error:
        return "UNKNOWN"


def _worker_environment() -> dict[str, str]:
    """Give the long-lived local worker no route to the Codex CLI."""
    env = os.environ.copy()
    path_entries = env.get("PATH", "").split(os.pathsep)
    env["PATH"] = os.pathsep.join(entry for entry in path_entries
                                  if "codex" not in entry.casefold())
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8:backslashreplace",
                "PYTHONDONTWRITEBYTECODE": "1"})
    return env


def _wait_for_worker_exit(child: subprocess.Popen | None) -> tuple[bool, int | None]:
    """Wait boundedly for a child to finish without abandoning a live worker."""
    if child is None:
        return True, None
    if child.poll() is not None:
        return True, child.returncode
    try:
        child.wait(timeout=POLL_SECONDS)
    except subprocess.TimeoutExpired:
        return False, None
    return True, child.returncode


def _lock_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if os.name == "nt":
        import msvcrt
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            handle.close()
            return None
    return handle


def _unlock_file(handle) -> None:
    if not handle:
        return
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    handle.close()


def _worker_lock_held() -> bool:
    handle = _lock_file(WORKER_LOCK)
    if handle is None:
        return True
    _unlock_file(handle)
    return False


def _resume_on_logon() -> str:
    """Resume a saved stopped worker when Windows starts the installed watchdog."""
    state = _desired_state()
    if state in {"STOPPED", "STOPPING"} and not _worker_lock_held():
        from src.agent import autonomous_manager
        autonomous_manager.set_control("RUNNING")
        _log_event("logon_resume", previous_state=state, desired_state="RUNNING")
        return "RUNNING"
    return state


def run() -> int:
    watchdog_lock = _lock_file(WATCHDOG_LOCK)
    if watchdog_lock is None:
        return 0
    initial_state = _resume_on_logon()
    _log_event("watchdog_started", desired_state=initial_state)
    child: subprocess.Popen | None = None
    try:
        while True:
            state = _desired_state()
            if state in {"STOPPED", "STOPPING"}:
                exited, exit_code = _wait_for_worker_exit(child)
                if not exited:
                    # The Worker completes its current checkpoint/task first.
                    # Returning here would let Windows terminate this process
                    # tree and leave a live SQLite lease behind.
                    continue
                if child is not None:
                    _log_event("worker_exited", worker_pid=child.pid, exit_code=exit_code,
                        desired_state=state)
                    child = None
                if _worker_lock_held():
                    # A GUI or another supervisor may own the Worker lock.
                    time.sleep(POLL_SECONDS)
                    continue
                return 0
            if state == "PAUSED":
                if child is not None and child.poll() is not None:
                    child = None
                time.sleep(POLL_SECONDS)
                continue
            if state != "RUNNING":
                time.sleep(POLL_SECONDS)
                continue
            if child is None or child.poll() is not None:
                child = None
                if _worker_lock_held():
                    # The GUI or another instance already owns the worker lock.
                    time.sleep(RESTART_DELAY_SECONDS)
                    continue
                flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                child = subprocess.Popen([sys.executable, "-B", "-m", "src.agent.autonomous_manager", "worker"],
                    cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags,
                    env=_worker_environment())
                _log_event("worker_started", worker_pid=child.pid)
            try:
                child.wait(timeout=POLL_SECONDS)
                exit_code = child.returncode
                _log_event("worker_exited", worker_pid=child.pid, exit_code=exit_code,
                    desired_state=_desired_state())
                child = None
                if _desired_state() == "RUNNING":
                    time.sleep(RESTART_DELAY_SECONDS)
            except subprocess.TimeoutExpired:
                pass
    finally:
        _unlock_file(watchdog_lock)


if __name__ == "__main__":
    raise SystemExit(run())
