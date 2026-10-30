"""Persistent, bounded Ollama research coordinator and local dashboard controls."""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
import urllib.error
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
from src.agent import state_store
from src.agent import project_scope
from src.agent.resource_probe import resource_snapshot
from src.agent.safe_python import ScriptRejected, run_research_script

STATE_DB = state_store.STATE_DB
SOURCE_ROOT = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[2]))
API_BASE = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
MODEL_TEXT_SETTINGS = PROJECT_ROOT / "work" / "autonomous_manager" / "model_text_settings.json"
MODEL_PROMPT_TEXT_LIMIT = 12_000
MODEL_RESPONSE_TEXT_LIMIT = 30_000
MAX_RESEARCH_DEPTH = 2
MAX_TASKS_PER_CYCLE = 10
MAX_CALLS_PER_TASK = 2
MAX_IDLE_SECONDS = 5
# The existing checkpoint already covers ten map/index extensions. Continue
# through the thirteen other same-name regional files in the original manifest.
# One hypothesis per extension is capped at this exact inventory; source
# fingerprints and atomic claims prevent duplicate work or an unbounded loop.
MAX_DYNAMIC_HYPOTHESES = 23
ALLOWED_SUFFIXES = {
    "PDX", "MP0", "FEA", "RL", "RT", "IL", "IOF", "MG1", "MG2", "MG3",
    "ABC", "RD", "STT", "AFF", "ASC", "CL", "CNY", "CT", "CTY", "PTI", "PTP", "TYP", "CFG",
}
REGIONS = (
    ("SW", Path("SW") / "DB", "EUZ"),
    ("Italy", Path("OPEL NCDx Italia 2010-2011") / "DB", "IZ"),
    ("Scandinavia", Path("OPEL NCDx Scandinavia 2010-2011") / "DB", "SCZ"),
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_text_recording_enabled() -> bool:
    """Full model text is opt-in; malformed or missing settings mean metadata only."""
    try:
        settings = json.loads(MODEL_TEXT_SETTINGS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(settings, dict) and settings.get("store_model_text") is True


def _redact_model_text(value: str, limit: int) -> str:
    """Bound and redact common credential forms before optional local persistence."""
    text = str(value or "")
    text = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/-]+=*",
                  r"\1[REDACTED]", text)
    key = r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)"
    text = re.sub(rf'(?i)((?:"?{key}"?)\s*[:=]\s*")([^"\r\n]*)(")',
                  r"\1[REDACTED]\3", text)
    text = re.sub(rf"(?i)((?:{key})\s*[:=]\s*)([^\s,;}}]+)",
                  r"\1[REDACTED]", text)
    return text[:limit]


def _redact_model_value(value: Any, *, depth: int = 0) -> Any:
    """Sanitize JSON output recursively while keeping it structurally parseable."""
    secret_key = re.compile(r"api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret", re.I)
    if depth > 24:
        return "[DEPTH_LIMIT]"
    if isinstance(value, dict):
        return {str(key)[:160]: ("[REDACTED]" if secret_key.search(str(key)) else
                _redact_model_value(item, depth=depth + 1)) for key, item in list(value.items())[:500]}
    if isinstance(value, list):
        return [_redact_model_value(item, depth=depth + 1) for item in value[:500]]
    if isinstance(value, str):
        return _redact_model_text(value, MODEL_RESPONSE_TEXT_LIMIT)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:500]


def ensure_runtime_schema() -> None:
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS coordinator_control(
              id INTEGER PRIMARY KEY CHECK(id=1), desired_state TEXT NOT NULL,
              worker_state TEXT NOT NULL, current_task TEXT, message TEXT NOT NULL DEFAULT '',
              updated_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_runs(
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, sequence INTEGER NOT NULL,
              role TEXT NOT NULL, model TEXT NOT NULL, input_json TEXT NOT NULL,
              response_text TEXT NOT NULL, parsed_json TEXT NOT NULL DEFAULT '{}',
              artifact_paths_json TEXT NOT NULL DEFAULT '[]', tests_json TEXT NOT NULL DEFAULT '[]',
              decision TEXT NOT NULL, elapsed_ms INTEGER NOT NULL, resource_json TEXT NOT NULL,
              error TEXT, created_utc TEXT NOT NULL, UNIQUE(task_id,sequence)
            );
            CREATE TABLE IF NOT EXISTS research_experiments(
              fingerprint TEXT PRIMARY KEY, probe_type TEXT NOT NULL, target_suffix TEXT NOT NULL,
              hypothesis TEXT NOT NULL, depth INTEGER NOT NULL, parent_task TEXT NOT NULL,
              status TEXT NOT NULL, source_fingerprint TEXT NOT NULL, created_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_target_claims(
              target_suffix TEXT PRIMARY KEY, task_id TEXT NOT NULL, reason TEXT NOT NULL,
              created_utc TEXT NOT NULL
            );
            INSERT OR IGNORE INTO coordinator_control
              (id,desired_state,worker_state,current_task,message,updated_utc)
              VALUES(1,'STOPPED','STOPPED',NULL,'',CURRENT_TIMESTAMP);
            """
        )
        project_scope.sync_scope_in_connection(conn)
        # Migrate existing work into durable reservations. A failed or blocked
        # experiment still consumes its target until a diagnostic-specific
        # repair is created; generic scheduling must not repeat it.
        for row in conn.execute("SELECT fingerprint,target_suffix FROM research_experiments"):
            suffix = str(row[1] or "").upper()
            if suffix in ALLOWED_SUFFIXES:
                conn.execute("INSERT OR IGNORE INTO research_target_claims VALUES(?,?,?,?)",
                             (suffix, f"experiment:{row[0]}", "existing verified experiment", _utc()))
        try:
            task_rows = conn.execute("SELECT id,evidence_json,result_json FROM tasks").fetchall()
        except sqlite3.OperationalError:
            task_rows = []
        for task_id, evidence_text, result_text in task_rows:
            try:
                ev = json.loads(evidence_text or "[]")
                ev = ev[0] if isinstance(ev, list) and ev else ev
                result = json.loads(result_text or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            suffixes = set()
            if isinstance(ev, dict):
                suffixes.update(str(ev.get(k, "")).upper().strip()
                                for k in ("required_suffix", "target_suffix"))
            if isinstance(result, dict):
                suffixes.add(str(result.get("target_suffix", "")).upper().strip())
            for suffix in suffixes:
                if suffix in ALLOWED_SUFFIXES:
                    conn.execute("INSERT OR IGNORE INTO research_target_claims VALUES(?,?,?,?)",
                                 (suffix, str(task_id), "existing task assignment", _utc()))
        conn.commit()


def _log_event(event: str, payload: dict[str, Any]) -> None:
    state_store._event(event, payload)


def set_control(desired_state: str, message: str = "dashboard") -> None:
    if desired_state not in {"RUNNING", "PAUSED", "STOP_REQUESTED"}:
        raise ValueError("unsupported coordinator control state")
    ensure_runtime_schema()
    with closing(sqlite3.connect(STATE_DB, timeout=10)) as conn:
        conn.execute("UPDATE coordinator_control SET desired_state=?,message=?,updated_utc=? WHERE id=1",
                     (desired_state, message[:300], _utc()))
        conn.commit()
    _log_event("coordinator_control", {"desired_state": desired_state, "source": message[:80]})


def _control_row() -> dict[str, Any]:
    ensure_runtime_schema()
    with closing(sqlite3.connect(STATE_DB)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM coordinator_control WHERE id=1").fetchone()
    return dict(row)


def _set_worker_state(state: str, current_task: str | None = None, message: str = "") -> None:
    ensure_runtime_schema()
    with closing(sqlite3.connect(STATE_DB, timeout=10)) as conn:
        conn.execute("UPDATE coordinator_control SET worker_state=?,current_task=?,message=?,updated_utc=? WHERE id=1",
                     (state, current_task, message[:300], _utc()))
        conn.commit()


def _mark_service_stopped(message: str) -> None:
    ensure_runtime_schema()
    with closing(sqlite3.connect(STATE_DB, timeout=10)) as conn:
        conn.execute("UPDATE coordinator_control SET desired_state='STOPPED',worker_state='STOPPED',current_task=NULL,message=?,updated_utc=? WHERE id=1",
                     (message[:300], _utc()))
        conn.commit()


def _host_resources() -> dict[str, Any]:
    result = resource_snapshot()
    try:
        result["disk_free_bytes"] = shutil.disk_usage(PROJECT_ROOT).free
    except OSError as exc:
        result["disk_error"] = str(exc)
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        class FILETIME(ctypes.Structure):
            _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]
        idle1, kernel1, user1 = FILETIME(), FILETIME(), FILETIME()
        if kernel32.GetSystemTimes(ctypes.byref(idle1), ctypes.byref(kernel1), ctypes.byref(user1)):
            def ft(value: FILETIME) -> int:
                return (value.high << 32) | value.low
            time.sleep(0.12)
            idle2, kernel2, user2 = FILETIME(), FILETIME(), FILETIME()
            if kernel32.GetSystemTimes(ctypes.byref(idle2), ctypes.byref(kernel2), ctypes.byref(user2)):
                total = (ft(kernel2) - ft(kernel1)) + (ft(user2) - ft(user1))
                idle = ft(idle2) - ft(idle1)
                result["cpu_percent"] = round(max(0.0, min(100.0, 100 * (total-idle) / total)), 1) if total else None
    except Exception as exc:
        result["cpu_error"] = f"{type(exc).__name__}: {exc}"
    return result


def _model_report() -> dict[str, Any]:
    path = PROJECT_ROOT / "reports" / "model_benchmark.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "NOT_RUN", "models": [], "recommended_model": None}


def _api_json(endpoint: str, payload: dict[str, Any] | None = None, timeout: int = 120) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(API_BASE + endpoint, data=data,
        headers={"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _available_models() -> set[str]:
    data = _api_json("/api/tags", timeout=4)
    return {row.get("name", "") for row in data.get("models", []) if row.get("name")}


def _choose_model(role: str, installed: set[str]) -> str:
    if role == "code":
        required = "qwen2.5-coder:7b"
        if required not in installed:
            raise RuntimeError(f"LOCAL FIRST code role requires the installed model {required}")
        return required
    if role == "project-director":
        required = "qwen3.5:9b"
        if required not in installed:
            raise RuntimeError(f"LOCAL FIRST Director role requires the installed model {required}")
        return required
    report = _model_report()
    measured = {row.get("model"): row for row in report.get("models", []) if row.get("status") == "COMPLETE"}
    if role == "independent-review":
        # The previous hard-coded 9B reviewer reached the task timeout on the
        # 8 GiB GPU. Use the locally benchmarked 4B model first; the code
        # proposer remains Qwen2.5-Coder 7B, so the review is independent.
        options = [report.get("recommended_model"), "qwen3.5:4b", "qwen2.5-coder:7b",
                   "hf.co/empero-ai/Qwythos-9B-v2-GGUF:Q4_K_M", "qwen3.5:9b"]
    else:
        options = [report.get("recommended_model"), "qwen3.5:4b", "qwen2.5-coder:7b", "qwen3.5:9b"]
        options = sorted((name for name in options if name),
                         key=lambda name: (measured.get(name, {}).get("passed", 0), measured.get(name, {}).get("verified_results_per_minute", 0)),
                         reverse=True)
    for name in options:
        if name and name in installed:
            return name
    raise RuntimeError("No benchmarked, installed Ollama model is available")


def _start_ollama_if_needed() -> None:
    try:
        _api_json("/api/tags", timeout=3)
        return
    except Exception:
        pass
    executable = shutil.which("ollama") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe")
    if not Path(executable).is_file():
        raise RuntimeError("Ollama API is unavailable and its local executable was not found")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    subprocess.Popen([executable, "serve"], cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            _api_json("/api/tags", timeout=3)
            return
        except Exception:
            time.sleep(1)
    raise TimeoutError("Ollama API did not become available within 45 seconds")


class ResourceSampler:
    def __init__(self) -> None:
        self.samples: list[dict[str, Any]] = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._sample, name="ncdr-resource-sampler", daemon=True)

    def _sample(self) -> None:
        while not self.stop_event.is_set():
            try:
                snap = _host_resources()
                snap["monotonic"] = time.monotonic()
                self.samples.append(snap)
            except Exception as exc:
                self.samples.append({"error": f"{type(exc).__name__}: {exc}"})
            self.stop_event.wait(1.0)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop_event.set()
        self.thread.join(timeout=3)

    def summary(self) -> dict[str, Any]:
        ram = [s.get("ram", {}).get("used_bytes") for s in self.samples if s.get("ram", {}).get("used_bytes") is not None]
        vram = [s.get("gpu", {}).get("memory_used_mib") for s in self.samples if s.get("gpu", {}).get("memory_used_mib") is not None]
        cpu = [s.get("cpu_percent") for s in self.samples if s.get("cpu_percent") is not None]
        disk = [s.get("disk_free_bytes") for s in self.samples if s.get("disk_free_bytes") is not None]
        return {"sample_count": len(self.samples), "ram_peak_used_bytes": max(ram) if ram else None,
                "vram_peak_used_mib": max(vram) if vram else None, "cpu_peak_percent": max(cpu) if cpu else None,
                "disk_min_free_bytes": min(disk) if disk else None, "samples": self.samples[-3:]}


def _record_llm_run(task_id: str, sequence: int, role: str, model: str, prompt: str,
                    response: str, parsed: dict[str, Any], artifacts: list[str], tests: list[dict[str, Any]],
                    decision: str, elapsed_ms: int, resources: dict[str, Any], error: str | None = None) -> None:
    save_text = model_text_recording_enabled()
    if save_text:
        input_json = json.dumps({"prompt": _redact_model_text(prompt, MODEL_PROMPT_TEXT_LIMIT),
                                 "text_persisted": True}, ensure_ascii=False)
        response_text = _redact_model_text(response, MODEL_RESPONSE_TEXT_LIMIT)
        try:
            parsed_json = json.dumps(_redact_model_value(parsed), ensure_ascii=False)
        except (TypeError, ValueError):
            parsed_json = "{}"
    else:
        input_json = json.dumps({"prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                                 "prompt_characters": len(prompt), "text_persisted": False})
        response_text = ""
        parsed_json = "{}"
    saved_resources = dict(resources)
    saved_resources["model_text_persisted"] = save_text
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.execute("""INSERT OR REPLACE INTO research_runs
          (task_id,sequence,role,model,input_json,response_text,parsed_json,artifact_paths_json,tests_json,
           decision,elapsed_ms,resource_json,error,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (task_id, sequence, role, model, input_json, response_text, parsed_json,
           json.dumps(artifacts, ensure_ascii=False), json.dumps(tests, ensure_ascii=False),
           decision, elapsed_ms, json.dumps(saved_resources, ensure_ascii=False),
           _redact_model_text(error or "", 2000) or None, _utc()))
        conn.commit()


def _update_llm_validation(task_id: str, sequence: int, role: str,
                           tests: list[dict[str, Any]], decision: str,
                           error: str | None = None) -> None:
    """Attach sandbox results without erasing the model call's measured cost."""
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        cursor = conn.execute(
            "UPDATE research_runs SET tests_json=?,decision=?,error=? WHERE task_id=? AND sequence=? AND role=?",
            (json.dumps(tests, ensure_ascii=False), decision, error, task_id, sequence, role),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"missing persisted model-call row for {task_id} attempt {sequence}")
        conn.commit()


def _call_model(task_id: str, role: str, prompt: str, *, attempt: int = 1,
                fixed_model: str | None = None) -> tuple[str, str, dict[str, Any]]:
    _start_ollama_if_needed()
    installed = _available_models()
    model = fixed_model if fixed_model in installed else _choose_model(role, installed)
    before = _host_resources()
    if before.get("disk_free_bytes", 0) < 5 * 1024**3:
        raise RuntimeError("research paused: less than 5 GiB free on the project drive")
    if before.get("ram", {}).get("available_bytes", 0) < 3 * 1024**3:
        raise RuntimeError("research paused: less than 3 GiB of available RAM")
    if before.get("gpu") and before["gpu"].get("memory_free_mib", 0) < 1500:
        raise RuntimeError("research paused: less than 1.5 GiB free VRAM")
    request = {"model": model, "stream": False, "keep_alive": 0,
        "format": "json", "options": {"temperature": 0.1, "num_ctx": 4096, "num_predict": 1100},
        "messages": [{"role": "system", "content": "Return a single valid JSON object. Your output is an untrusted research suggestion, never a fact or permission. Do not invent bytes. Follow the exact schema in the user message."},
                     {"role": "user", "content": prompt}]}
    if role in {"independent-review", "project-director"} and ("qwen3.5" in model.casefold() or "qwythos" in model.casefold()):
        # Thinking models return reasoning and content separately. Disable the
        # reasoning channel for this bounded schema task so JSON reaches content.
        request["think"] = False
    started = time.monotonic()
    request_id = secrets.token_hex(12)
    _log_event("ollama_request_started", {"request_id": request_id, "task_id": task_id,
        "role": role, "model": model, "attempt": attempt, "started_utc": _utc()})
    try:
        with ResourceSampler() as sampler:
            response_obj = _api_json("/api/chat", request, timeout=150)
    except Exception as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        metrics = {"before": before, "sampled": sampler.summary(), "after": _host_resources(),
                   "attempt": attempt, "keep_alive": 0, "api_error": True}
        message = f"{type(exc).__name__}: {exc}"
        _record_llm_run(task_id, attempt, role, model, prompt, "", {}, [], [],
                        "API_ERROR", elapsed, metrics, message)
        _log_event("ollama_request_failed", {"request_id": request_id, "task_id": task_id, "role": role,
            "model": model, "elapsed_ms": elapsed, "error": message, "failure_kind": "API_ERROR"})
        raise RuntimeError(f"Ollama model {model} failed during {role} call: {message}") from exc
    elapsed = int((time.monotonic() - started) * 1000)
    content = str(response_obj.get("message", {}).get("content", ""))
    metrics = {"prompt_tokens": response_obj.get("prompt_eval_count"),
               "output_tokens": response_obj.get("eval_count"), "ollama_total_duration_ns": response_obj.get("total_duration"),
               "before": before, "sampled": sampler.summary(), "after": _host_resources(),
               "attempt": attempt, "keep_alive": 0}
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("response JSON must be an object")
    except (json.JSONDecodeError, ValueError) as exc:
        _record_llm_run(task_id, attempt, role, model, prompt, content, {}, [], [], "INVALID_JSON", elapsed, metrics, str(exc))
        _log_event("ollama_request_failed", {"request_id": request_id, "task_id": task_id,
            "role": role, "model": model, "elapsed_ms": elapsed,
            "error": f"{type(exc).__name__}: {exc}", "failure_kind": "INVALID_JSON"})
        raise ValueError(f"local model returned invalid structured JSON: {exc}") from exc
    _record_llm_run(task_id, attempt, role, model, prompt, content, parsed, [], [], "RESPONSE_RECEIVED", elapsed, metrics)
    _log_event("ollama_request_completed", {"request_id": request_id, "task_id": task_id,
        "role": role, "model": model, "elapsed_ms": elapsed,
        "prompt_tokens": metrics.get("prompt_tokens"), "output_tokens": metrics.get("output_tokens"),
        "finished_utc": _utc()})
    return model, content, parsed


def _write_json(relative: str, value: dict[str, Any]) -> str:
    path = (PROJECT_ROOT / relative).resolve()
    if not path.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError("artifact path escaped the project folder")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    digest = hashlib.sha256(data).hexdigest()
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.execute("INSERT OR REPLACE INTO artifacts(path,sha256,size_bytes,description,created_utc) VALUES(?,?,?,?,?)",
                     (str(path.relative_to(PROJECT_ROOT)), digest, len(data), "Autonomous research evidence", _utc()))
        conn.commit()
    return str(path.relative_to(PROJECT_ROOT))


def _allowed_source_path(relative: Path) -> Path:
    candidate = (SOURCE_ROOT / relative).resolve()
    if not candidate.is_relative_to(SOURCE_ROOT.resolve()):
        raise ValueError("source path escaped the read-only NCDR root")
    return candidate


def _target_path(relative: Path, prefix: str, suffix: str) -> Path:
    prefix = {
        ("EUZ", "ABC"): "EU", ("IZ", "ABC"): "I", ("SCZ", "ABC"): "SC",
        ("EUZ", "RD"): "EU", ("IZ", "RD"): "I", ("SCZ", "RD"): "SC",
        ("EUZ", "STT"): "EU", ("IZ", "STT"): "I", ("SCZ", "STT"): "SC",
        ("EUZ", "CFG"): "ZONE", ("IZ", "CFG"): "ZONE", ("SCZ", "CFG"): "ZONE",
    }.get((prefix, suffix), prefix)
    return _allowed_source_path(relative / f"{prefix}.{suffix}")


def available_target_suffixes() -> tuple[str, ...]:
    """Return only suffixes backed by all three read-only regional files."""
    ordered = ("PDX", "FEA", "RL", "RT", "IL", "IOF", "MG1", "MG2", "MG3", "MP0",
               "ABC", "RD", "STT", "AFF", "ASC", "CL", "CNY", "CT", "CTY", "PTI", "PTP", "TYP", "CFG")
    available = []
    for suffix in ordered:
        if suffix not in ALLOWED_SUFFIXES:
            continue
        try:
            present = all((_target_path(folder, prefix, suffix).is_file() and
                           _target_path(folder, prefix, suffix).stat().st_size >= 64)
                          for _label, folder, prefix in REGIONS)
        except OSError:
            present = False
        if present:
            available.append(suffix)
    return tuple(available)


def _preview_candidates() -> dict[str, list[dict[str, Any]]]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    for suffix in available_target_suffixes():
        items = []
        for label, folder, prefix in REGIONS:
            path = _target_path(folder, prefix, suffix)
            with path.open("rb") as stream:
                head = stream.read(64)
            items.append({"region": label, "bytes": path.stat().st_size,
                          "prefix_hex": head.hex(), "prefix_bytes": list(head)})
        candidates[suffix] = items
    return candidates


def _read_target(suffix: str) -> list[dict[str, Any]]:
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"unsupported NCDx suffix: {suffix}")
    records = []
    for label, folder, prefix in REGIONS:
        path = _target_path(folder, prefix, suffix)
        if not path.is_file():
            raise FileNotFoundError(f"required read-only comparison input missing: {path}")
        before = path.stat()
        digest = hashlib.sha256()
        head = bytearray()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                if len(head) < 64:
                    head.extend(chunk[:64-len(head)])
                digest.update(chunk)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError(f"source changed during read-only experiment: {path}")
        records.append({"region": label, "source_path": str(path), "bytes": before.st_size,
                        "mtime_ns": before.st_mtime_ns, "sha256": digest.hexdigest(),
                        "prefix_hex": bytes(head).hex(), "prefix_bytes": list(head)})
    return records


def _common_prefix_length(records: list[dict[str, Any]]) -> int:
    if len(records) < 2:
        return 0
    length = 0
    for bytes_at_position in zip(*(row["prefix_bytes"] for row in records)):
        if len(set(bytes_at_position)) != 1:
            break
        length += 1
    return length


def _prefix_script(prompt: str, data: dict[str, Any], task_id: str, role: str = "code") -> tuple[str, str, dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Generate a script, run only its data-only subset, and allow one diagnostic repair."""
    diagnostic = ""
    previous = ""
    last_error = ""
    for attempt in range(1, MAX_CALLS_PER_TASK + 1):
        retry_prompt = prompt if attempt == 1 else (
            prompt + "\n\nНова діагностика незалежної перевірки: " + diagnostic
            + "\nПопередня відповідь: " + previous
            + "\nВідповідь не пройшла тест. Згенеруй новий JSON з обов'язковим непорожнім рядковим полем script. "
              "Поле script повинно містити лише описаний обмежений код, без Markdown та пояснення. "
              "Інші обов'язкові ключі та цільовий суфікс залиш без змін; ця спроба дозволена саме через нову діагностику.")
        model, raw, parsed = _call_model(task_id, role, retry_prompt, attempt=attempt)
        code = parsed.get("script")
        if isinstance(code, str) and code.strip().startswith("```"):
            code = re.sub(r"^```(?:python)?\s*|\s*```$", "", code.strip(), flags=re.I)
        test = {"name": "sandbox_script_matches_independent_common_prefix", "status": "FAIL"}
        try:
            if not isinstance(code, str) or len(code.encode("utf-8")) > 4000:
                raise ScriptRejected("script field is missing or too large")
            executed = run_research_script(code, data)
            expected = _common_prefix_length([{"prefix_bytes": row} for row in data["prefixes"]])
            actual = executed.get("result", {}).get("common_prefix")
            if type(actual) is not int or actual != expected:
                raise ValueError(f"independent comparison expected common_prefix={expected}, received {actual!r}")
            test = {"name": "sandbox_script_matches_independent_common_prefix", "status": "PASS",
                    "expected": expected, "actual": actual, "runner": executed}
            _update_llm_validation(task_id, attempt, role, [test], "SCRIPT_VERIFIED")
            return model, raw, parsed, executed, [test]
        except (ScriptRejected, ValueError, TypeError, TimeoutError, RuntimeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            test["diagnostic"] = last_error
            _update_llm_validation(task_id, attempt, role, [test], "SCRIPT_TEST_FAILED", last_error)
            if attempt >= MAX_CALLS_PER_TASK:
                raise RuntimeError(f"model-generated script failed the isolated independent test: {last_error}") from exc
            diagnostic, previous = last_error, str(code or raw)[:4000]
    raise RuntimeError(last_error or "script validation did not run")


def _parse_task_evidence(task: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(task.get("evidence_json", "[]") or "[]")
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _create_task(task_id: str, stage: str, agent: str, hypothesis: str, evidence: dict[str, Any],
                 parent: str | None = None, priority: int = 60) -> bool:
    return state_store.add_task({
        "id": task_id, "stage": stage, "depends_on": [parent] if parent else [],
        "hypothesis": hypothesis[:600], "evidence": [evidence], "agent": agent,
        "budget": {"attempts": 1, "timeout_s": 180, "models_serial": True, "max_calls": MAX_CALLS_PER_TASK},
        "deliverables": ["research/runs/coordinator"],
        "tests": ["Persist input/output/provenance and pass independent acceptance checks before creating a child task."],
        "next_action": "Run once; do not repeat unless input evidence or diagnostic changes.",
        "retry_limit": 1, "priority": priority,
    })


def _claim_target_suffix(suffix: str, task_id: str, reason: str) -> bool:
    """Atomically reserve one target so concurrent schedulers cannot duplicate it."""
    suffix = suffix.upper().strip()
    if suffix not in ALLOWED_SUFFIXES:
        return False
    ensure_runtime_schema()
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        try:
            conn.execute("INSERT INTO research_target_claims VALUES(?,?,?,?)",
                         (suffix, task_id, reason[:200], _utc()))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            conn.rollback()
            row = conn.execute("SELECT task_id FROM research_target_claims WHERE target_suffix=?", (suffix,)).fetchone()
            return bool(row and row[0] == task_id)


def _assigned_target_suffixes(conn: sqlite3.Connection) -> set[str]:
    """Read every durable assignment, including failed/blocked tasks."""
    assigned = {str(r[0]).upper() for r in conn.execute("SELECT target_suffix FROM research_experiments")
                if r[0] and str(r[0]).upper() in ALLOWED_SUFFIXES}
    try:
        assigned.update(str(r[0]).upper() for r in conn.execute("SELECT target_suffix FROM research_target_claims")
                        if r[0] and str(r[0]).upper() in ALLOWED_SUFFIXES)
    except sqlite3.OperationalError:
        pass
    try:
        task_rows = conn.execute("SELECT id,evidence_json,result_json FROM tasks").fetchall()
    except sqlite3.OperationalError:
        task_rows = []
    for _task_id, evidence_text, result_text in task_rows:
        try:
            ev = json.loads(evidence_text or "[]")
            ev = ev[0] if isinstance(ev, list) and ev else ev
            result = json.loads(result_text or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(ev, dict):
            for key in ("required_suffix", "target_suffix"):
                suffix = str(ev.get(key, "")).upper().strip()
                if suffix in ALLOWED_SUFFIXES:
                    assigned.add(suffix)
        if isinstance(result, dict):
            suffix = str(result.get("target_suffix", "")).upper().strip()
            if suffix in ALLOWED_SUFFIXES:
                assigned.add(suffix)
    return assigned


def seed_research_chain() -> bool:
    ensure_runtime_schema()
    with closing(sqlite3.connect(STATE_DB)) as conn:
        existing = conn.execute("SELECT status FROM tasks WHERE id='AUTO_RESEARCH_BOOTSTRAP'").fetchone()
        repair_exists = conn.execute("SELECT 1 FROM tasks WHERE id='AUTO_SCRIPT_REPAIR_001'").fetchone()
        previous = conn.execute("SELECT response_text FROM research_runs WHERE task_id='AUTO_RESEARCH_BOOTSTRAP' ORDER BY sequence DESC LIMIT 1").fetchone()
    if existing:
        if existing[0] != "BLOCKED" or repair_exists or not previous:
            return False
        prior = json.loads(previous[0])
        try:
            run_research_script(prior.get("script", ""), {"prefixes": [[0] * 64, [0] * 64, [0] * 64]})
            return False
        except Exception as exc:
            diagnostic = (f"{type(exc).__name__}: {exc}; expected data['prefixes'][0..2][0..63] "
                          "integer arrays and result variable common_prefix")
        with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
            conn.execute("INSERT OR REPLACE INTO research_runs(task_id,sequence,role,model,input_json,response_text,parsed_json,artifact_paths_json,tests_json,decision,elapsed_ms,resource_json,error,created_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("AUTO_RESEARCH_BOOTSTRAP", 3, "code-diagnostic", "deterministic-test-runner",
                 json.dumps({"source_task": "AUTO_RESEARCH_BOOTSTRAP", "test": "sandbox_expected_data_contract"}),
                 str(previous[0])[:30000], json.dumps(prior, ensure_ascii=False), "[]",
                 json.dumps([{"name": "sandbox_expected_data_contract", "status": "FAIL", "diagnostic": diagnostic}], ensure_ascii=False),
                 "NEW_DIAGNOSTIC", 0, "{}", diagnostic, _utc()))
            conn.commit()
        _log_event("new_repair_diagnostic", {"task_id": "AUTO_RESEARCH_BOOTSTRAP", "diagnostic": diagnostic})
        return _create_task("AUTO_SCRIPT_REPAIR_001", "R1", "ollama-script-repair",
            "Repair the previous generated code using its independent test diagnostic and rerun it in the constrained runner.",
            {"mode": "repair", "source_task": "AUTO_RESEARCH_BOOTSTRAP", "target_suffix": "PDX",
             "depth": 0, "diagnostic": diagnostic, "attempt_limit": 1,
             "new_information": "after adding safe local-variable += support, the independent data-contract test exposed a key mismatch"},
            parent=None, priority=35)
    return _create_task("AUTO_RESEARCH_BOOTSTRAP", "R1", "ollama-research-code",
        "Generate one falsifiable EUZ/IZ/SCZ hypothesis and a constrained script to measure shared prefix bytes.",
        {"mode": "propose", "depth": 0, "max_depth": MAX_RESEARCH_DEPTH,
         "allowed_suffixes": sorted(ALLOWED_SUFFIXES), "source_root": "read-only original folders"},
        parent="F0_MODEL_BENCHMARK", priority=40)


def seed_independent_goal_task() -> dict[str, Any]:
    """Create one bounded F2 task when the current dependency graph is stuck.

    This is a deterministic scheduler decision over the F2 unknowns, not an
    LLM-generated task spec. The model still has to propose a falsifiable
    hypothesis and constrained script, which are tested independently.
    """
    ensure_runtime_schema()
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        assigned = _assigned_target_suffixes(conn)
    valid_sources = set(available_target_suffixes())
    assigned.intersection_update(valid_sources)
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        recorded = {str(row[0]).upper() for row in conn.execute(
            "SELECT target_suffix FROM research_experiments")
            if row[0] and str(row[0]).upper() in valid_sources}
    # A target is a bounded experiment whether its model output passed or
    # failed. Only a new diagnostic can create the one explicit repair task.
    recorded.update(assigned)
    if len(recorded) >= MAX_DYNAMIC_HYPOTHESES:
        return {"created": False, "reason": f"bounded F2 cap reached ({len(recorded)}/{MAX_DYNAMIC_HYPOTHESES} recorded experiments)",
                "used_suffixes": sorted(assigned)}
    for suffix in ("PDX", "FEA", "RL", "RT", "IL", "IOF", "MG1", "MG2", "MG3", "MP0",
                   "ABC", "RD", "STT", "AFF", "ASC", "CL", "CNY", "CT", "CTY", "PTI", "PTP", "TYP", "CFG"):
        if suffix not in valid_sources or suffix in assigned:
            continue
        records = _read_target(suffix)
        source_fingerprint = _source_fingerprint(suffix, records)
        task_id = f"AUTO_SCHEDULED_PROBE_{suffix}_{source_fingerprint[:12]}"
        if not _claim_target_suffix(suffix, task_id, "independent F2 scheduler"):
            assigned.add(suffix)
            continue
        added = _create_task(task_id, "F2", "ollama-research-code",
            f"Виконати нове незалежне 64-байтове порівняння EUZ/IZ/SCZ для {suffix}; встановлювати лише спостереження байтів, не семантику.",
            {"mode": "propose", "depth": 0, "max_depth": MAX_RESEARCH_DEPTH,
             "required_suffix": suffix, "exclude_suffixes": sorted(assigned),
             "source_fingerprint": source_fingerprint,
             "goal": "F2 semantic-record discovery; one reproducible regional prefix measurement"},
            parent=None, priority=34)
        if added:
            _log_event("goal_scheduler_task_created", {"task_id": task_id, "stage": "F2",
                "suffix": suffix, "source_fingerprint": source_fingerprint,
                "dependency": None, "cap": MAX_DYNAMIC_HYPOTHESES})
            return {"created": True, "task_id": task_id, "suffix": suffix,
                    "source_fingerprint": source_fingerprint, "reason": "new unused suffix with read-only source fingerprint and independent script test"}
        assigned.add(suffix)
    return {"created": False, "reason": "all available read-only F2 suffixes already have a task or experiment",
            "used_suffixes": sorted(assigned)}


def _prompt_for_proposal(task_id: str, excluded_suffixes: list[str] | None = None,
                         prior_verified_result: dict[str, Any] | None = None,
                         required_suffix: str | None = None,
                         prior_diagnostic: str | None = None) -> tuple[str, dict[str, Any]]:
    preview = _preview_candidates()
    available_suffixes = tuple(preview)
    excluded = sorted({str(value).upper() for value in (excluded_suffixes or [])})
    if required_suffix:
        required_suffix = str(required_suffix).upper().strip()
        if required_suffix not in available_suffixes or required_suffix in excluded:
            raise ValueError(f"required follow-up suffix is invalid or already verified: {required_suffix}")
    test_suffix = required_suffix or next((value for value in available_suffixes if value not in excluded), "")
    if not test_suffix:
        raise RuntimeError("no unused regional suffix has three present read-only inputs")
    data = {"prefixes": [row["prefix_bytes"] for row in preview[test_suffix]]}
    followup = ""
    if prior_verified_result:
        followup = (
            "\nЦЕ НОВИЙ ЕКСПЕРИМЕНТ, СТВОРЕНИЙ ПІСЛЯ ПЕРЕВІРЕНОГО РЕЗУЛЬТАТУ: "
            + json.dumps(prior_verified_result, ensure_ascii=False)[:4000]
            + "\nНе повторюй попередній target_suffix. Уже перевірені суфікси: "
            + ", ".join(excluded)
            + ". Обери інший кандидат і поясни, яке нове байтове спостереження тестуватиме сценарій."
        )
    visible_suffixes = [test_suffix] if required_suffix else list(preview)
    strict_rule = ""
    if required_suffix and prior_diagnostic:
        strict_rule = (
            "\n\nОБОВ'ЯЗКОВО: target_suffix має бути рівно " + test_suffix
            + ". Не повертай інший суфікс, не пропонуй DB/TXT чи інші файли. Ключ script обов'язковий і має містити виконуваний код обмеженого піднабору. "
            + "Діагностика попередньої відповіді: " + prior_diagnostic[:1200]
            + ". Виправ формат відповіді; не повторюй попереднє порушення.")
    elif required_suffix:
        strict_rule = (
            "\n\nОБОВ'ЯЗКОВО: target_suffix має бути рівно " + test_suffix
            + ". У відповіді не використовуй жодного іншого суфікса; ключ script обов'язковий і непорожній.")
    prompt = (
        "Завдання: проаналізуй короткі заголовки однакових розширень із трьох незалежних регіональних наборів Opel NCDx "
        "(EUZ/IZ/SCZ). Дані подані нижче як HEX та довжина. Це лише байтове порівняння; не приписуй семантику розширенням. "
        "Обери один target_suffix ТІЛЬКИ з " + ", ".join(available_suffixes) + ". "
        "Сформулюй перевірювану гіпотезу, очікувану ознаку й чіткий falsifier. "
        "Напиши script тільки в обмеженому Python-піднаборі: без import, def, while, атрибутів, файла/мережі; "
        "ВХІД СКРИПТУ ЗАВЖДИ data={'prefixes': [список_байтів_SW, список_байтів_Italy, список_байтів_Scandinavia]}. "
        "Preview з ключами розширень є лише для пояснення і НЕ є словником data. Ніколи не індексуй data назвою розширення; використовуй лише data['prefixes'][0], [1], [2]. "
        "Приклад валідного значення поля script:\\ncommon_prefix = 0\\nfor i in range(64):\\n    if data['prefixes'][0][i] == data['prefixes'][1][i] == data['prefixes'][2][i]:\\n        common_prefix += 1\\n    else:\\n        break\\n"
        "Скрипт має присвоїти ціле число змінній common_prefix. "
        "Поверни один JSON-об'єкт із непорожніми рядковими полями hypothesis, target_suffix, expected_observation, falsifier, script.\n\n"
        "Кандидати (лише префікс і довжина, це не декодування): "
        + json.dumps({suffix: [{"region": row["region"], "bytes": row["bytes"], "prefix_hex": row["prefix_hex"]} for row in preview[suffix]]
                     for suffix in visible_suffixes}, ensure_ascii=False)
        + followup
        + strict_rule)
    return prompt, data


def _source_fingerprint(suffix: str, records: list[dict[str, Any]]) -> str:
    short = [{"region": row["region"], "bytes": row["bytes"], "sha256": row["sha256"]} for row in records]
    return hashlib.sha256(json.dumps({"suffix": suffix, "sources": short}, sort_keys=True).encode()).hexdigest()


def _register_probe(parent_task: str, suffix: str, hypothesis: str, script_source: str,
                    depth: int, reason: str) -> tuple[bool, str]:
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"model proposed suffix outside allowlist: {suffix}")
    records = _read_target(suffix)
    source_fp = _source_fingerprint(suffix, records)
    fingerprint = hashlib.sha256(f"cross_region_prefix:{suffix}:{source_fp}".encode()).hexdigest()[:18]
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        total = conn.execute("SELECT count(*) FROM research_experiments").fetchone()[0]
        existing = conn.execute("SELECT status FROM research_experiments WHERE fingerprint=?", (fingerprint,)).fetchone()
        claim = conn.execute("SELECT task_id FROM research_target_claims WHERE target_suffix=?", (suffix,)).fetchone()
        # A failed-but-already-claimed probe may complete once after a
        # fingerprinted infrastructure diagnostic is fixed. This consumes
        # its reserved target; it cannot admit a new suffix or hypothesis.
        completing_reserved_probe = bool(claim and claim[0] == parent_task and not existing)
        if total >= MAX_DYNAMIC_HYPOTHESES and not completing_reserved_probe:
            _log_event("research_experiment_limit", {"limit": MAX_DYNAMIC_HYPOTHESES, "suffix": suffix,
                "reason": "bounded experiment chain reached its cap"})
            return False, "chain-limit"
        if existing:
            return False, fingerprint
        conn.execute("INSERT INTO research_experiments VALUES(?,?,?,?,?,?,?,?,?)",
            (fingerprint, "cross_region_prefix", suffix, hypothesis[:500], depth, parent_task,
             "PLANNED", source_fp, _utc()))
        conn.commit()
    verify_id = f"AUTO_VERIFY_{fingerprint}"
    added = _create_task(verify_id, "R1", "binary-probe",
        f"Independently compare the first 64 bytes of {suffix} across EUZ/IZ/SCZ; do not infer semantics.",
        {"mode": "cross_region_prefix", "suffix": suffix, "hypothesis": hypothesis,
         "script_source": script_source, "depth": int(depth), "fingerprint": fingerprint,
         "source_fingerprint": source_fp, "reason": reason},
        parent=parent_task, priority=45+depth)
    if not added:
        with closing(sqlite3.connect(STATE_DB)) as conn:
            conn.execute("UPDATE research_experiments SET status='ALREADY_QUEUED' WHERE fingerprint=?", (fingerprint,))
            conn.commit()
    _log_event("research_experiment_created", {"fingerprint": fingerprint, "target": suffix,
        "parent_task": parent_task, "depth": depth, "new_task": added, "reason": reason[:300]})
    return added, fingerprint


def _register_review(parent_task: str, result: dict[str, Any], depth: int) -> None:
    if depth >= MAX_RESEARCH_DEPTH:
        return
    parent_evidence = {"mode": "review", "depth": depth,
        "source_verification_task": parent_task, "expected_target": result.get("target_suffix"),
        "experiment_fingerprint": result.get("fingerprint")}
    task_id = f"AUTO_REVIEW_{str(result.get('fingerprint', parent_task))[:18]}"
    _create_task(task_id, "R1", "ollama-independent-review",
        "Independently assess the reproducible three-region byte-prefix result and choose at most one distinct next experiment.",
        parent_evidence, parent=parent_task, priority=50+depth)


def _queue_followup_proposal(review_task: dict[str, Any], review_result: dict[str, Any]) -> bool:
    """Boundedly turn a verified review into one new, distinct model experiment."""
    if str(review_result.get("next_target", "NONE")).upper() != "NONE":
        return False
    try:
        verified_id = json.loads(review_task.get("depends_on_json", "[]"))[0]
    except (IndexError, TypeError, json.JSONDecodeError):
        return False
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        experiment_count = conn.execute("SELECT count(*) FROM research_experiments").fetchone()[0]
        suffixes = _assigned_target_suffixes(conn)
        verified_row = conn.execute("SELECT result_json FROM tasks WHERE id=? AND status='DONE'", (verified_id,)).fetchone()
    if experiment_count >= MAX_DYNAMIC_HYPOTHESES or not verified_row:
        _log_event("followup_hypothesis_not_created", {"review_task": review_task.get("id"),
            "reason": "bounded experiment cap reached or verified result missing", "experiment_count": experiment_count})
        return False
    verified = json.loads(verified_row[0] or "{}")
    valid_sources = set(available_target_suffixes())
    available = [value for value in available_target_suffixes() if value in valid_sources and value not in suffixes]
    if not available:
        return False
    target_hint = available[0]
    task_id = f"AUTO_RESEARCH_FOLLOWUP_{str(review_result.get('parent_result', {}).get('fingerprint', verified_id))[:12]}"
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        if conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
            return False
    if not _claim_target_suffix(target_hint, task_id, "review follow-up proposal"):
        _log_event("followup_hypothesis_not_created", {"review_task": review_task.get("id"),
            "reason": f"target {target_hint} was claimed by another scheduler", "experiment_count": experiment_count})
        return False
    added = _create_task(task_id, "R2", "ollama-research-code",
        f"After verified {', '.join(sorted(suffixes))} comparison, propose and test a distinct {target_hint} regional byte hypothesis.",
        {"mode": "followup", "depth": 1, "exclude_suffixes": sorted(suffixes),
         "prior_verified_result": verified, "candidate_suffixes": available,
         "required_suffix": target_hint, "max_depth": MAX_RESEARCH_DEPTH,
         "reason": "next bounded experiment after independent review"},
        parent=str(review_task["id"]), priority=38)
    if added:
        _log_event("followup_hypothesis_created", {"task_id": task_id, "parent": review_task["id"],
            "verified_task": verified_id, "excluded_suffixes": sorted(suffixes), "candidate_suffixes": available})
    return added


def _queue_followup_repair(task: dict[str, Any], diagnostic: str) -> bool:
    """Create at most one fresh, tightly targeted task from a persisted failure diagnostic."""
    evidence = _parse_task_evidence(task)
    if evidence.get("mode") != "followup" or evidence.get("diagnostic_repair"):
        return False
    excluded = {str(value).upper() for value in evidence.get("exclude_suffixes", [])}
    candidates = [str(value).upper() for value in evidence.get("candidate_suffixes", [])]
    required = str(evidence.get("required_suffix") or next((x for x in candidates if x not in excluded), "")).upper()
    if required not in available_target_suffixes() or required in excluded:
        return False
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        row = conn.execute("SELECT depends_on_json FROM tasks WHERE id=?", (task["id"],)).fetchone()
        run = conn.execute("SELECT model,response_text,error FROM research_runs WHERE task_id=? AND role='code' ORDER BY sequence DESC LIMIT 1",
                           (task["id"],)).fetchone()
    if not row:
        return False
    parents = json.loads(row[0] or "[]")
    if not parents:
        return False
    response = str(run[1] if run else "")[:3000]
    reason = str(diagnostic or (run[2] if run else "no persisted diagnostic"))[:1600]
    fingerprint = hashlib.sha256((task["id"] + "\0" + reason + "\0" + response).encode("utf-8")).hexdigest()[:12]
    task_id = f"AUTO_FOLLOWUP_REPAIR_{fingerprint}"
    repair_evidence = dict(evidence) | {
        "mode": "followup", "required_suffix": required, "diagnostic_repair": True,
        "source_task": task["id"], "prior_diagnostic": reason,
        "failed_model": str(run[0] if run else "unknown"), "failed_response": response,
        "reason": "one bounded response-format repair from a new persisted test diagnostic",
    }
    added = _create_task(task_id, "R2", "ollama-research-code",
        f"Repair one failed follow-up using its new test diagnostic; test only the fixed, unused {required} suffix.",
        repair_evidence, parent=str(parents[0]), priority=37)
    if added:
        _log_event("followup_repair_created", {"task_id": task_id, "source_task": task["id"],
            "required_suffix": required, "diagnostic": reason, "attempt_limit": 1})
    return added


def _seed_followup_repairs() -> int:
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id,evidence_json,result_json FROM tasks WHERE status='BLOCKED' AND agent='ollama-research-code' ORDER BY updated_utc").fetchall()
    created = 0
    for row in rows:
        task = dict(row)
        task["evidence_json"] = row["evidence_json"]
        result = json.loads(row["result_json"] or "{}")
        created += int(_queue_followup_repair(task, str(result.get("error", ""))))
    return created


def _recover_verified_model_outputs() -> int:
    """Replay persisted, sandbox-verified model output after a coordinator validation bug.

    This does not call a model or trust the prior runner result by itself: the script
    is rerun against the original read-only target and must match the independent
    deterministic measurement before the blocked task can be completed.
    """
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.row_factory = sqlite3.Row
        candidates = conn.execute(
            """SELECT t.*, r.sequence, r.model, r.response_text, r.parsed_json
               FROM tasks t JOIN research_runs r ON r.task_id=t.id
               WHERE t.status='BLOCKED' AND t.agent='ollama-research-code'
                 AND r.role='code' AND r.decision='SCRIPT_VERIFIED' AND r.error IS NULL
                 AND r.sequence=(SELECT MAX(r2.sequence) FROM research_runs r2
                   WHERE r2.task_id=t.id AND r2.role='code')
               ORDER BY t.updated_utc""").fetchall()
    recovered = 0
    for row in candidates:
        task = dict(row)
        evidence = _parse_task_evidence(task)
        if evidence.get("mode") != "followup":
            continue
        try:
            parsed = json.loads(row["parsed_json"] or row["response_text"])
        except (TypeError, json.JSONDecodeError):
            continue
        # Older local model responses used `explanation` for the same plain-text
        # hypothesis field. Preserve the original wording and provenance.
        hypothesis = str(parsed.get("hypothesis") or parsed.get("explanation") or "").strip()
        script = str(parsed.get("script") or "")
        suffix = str(parsed.get("target_suffix") or "").upper().strip()
        required = str(evidence.get("required_suffix") or "").upper().strip()
        excluded = {str(value).upper() for value in evidence.get("exclude_suffixes", [])}
        if not hypothesis or len(hypothesis) > 500 or suffix not in ALLOWED_SUFFIXES:
            continue
        if required and suffix != required or suffix in excluded:
            continue
        try:
            records = _read_target(suffix)
            expected = _common_prefix_length(records)
            runner = run_research_script(script, {"prefixes": [item["prefix_bytes"] for item in records]})
            actual = runner.get("result", {}).get("common_prefix")
        except Exception as exc:
            _log_event("verified_model_recovery_rejected", {"task_id": task["id"],
                "diagnostic": f"{type(exc).__name__}: {exc}"})
            continue
        if type(actual) is not int or actual != expected:
            _log_event("verified_model_recovery_rejected", {"task_id": task["id"],
                "expected": expected, "actual": actual, "reason": "fresh isolated retest mismatch"})
            continue
        test = {"name": f"persisted_model_script_retested_on_{suffix}", "status": "PASS",
                "expected": expected, "actual": actual, "runner": runner}
        code_path = f"research/runs/coordinator/{task['id']}/model_generated_script.py"
        code_file = PROJECT_ROOT / code_path
        code_file.parent.mkdir(parents=True, exist_ok=True)
        code_file.write_text(script, encoding="utf-8")
        digest = hashlib.sha256(code_file.read_bytes()).hexdigest()
        with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
            conn.execute("INSERT OR REPLACE INTO artifacts(path,sha256,size_bytes,description,created_utc) VALUES(?,?,?,?,?)",
                (code_path, digest, code_file.stat().st_size,
                 "Persisted Qwen script, freshly retested in the constrained runner", _utc()))
            conn.commit()
        report_path = f"research/runs/coordinator/{task['id']}/model_output.json"
        report = _write_json(report_path, {"task_id": task["id"], "model": row["model"],
            "raw_response": row["response_text"], "parsed": parsed, "script_validation": [test],
            "selected_target": suffix, "source_preview": [
                {key: item[key] for key in ("region", "bytes", "prefix_hex")} for item in records],
            "script_path": code_path, "script_sha256": digest,
            "recovered_from_persisted_response": True,
            "warning": "Hypothesis is proposed; the comparison establishes bytes only, not format semantics."})
        result = {"mode": "followup", "model": row["model"], "hypothesis": hypothesis,
            "target_suffix": suffix, "expected_observation": str(parsed.get("expected_observation", ""))[:300],
            "falsifier": str(parsed.get("falsifier", ""))[:300], "script_source": script,
            "script_path": code_path, "script_sha256": digest, "artifact": report,
            "script_test": test, "source_preview": [{"region": item["region"], "bytes": item["bytes"],
                "prefix_hex": item["prefix_hex"]} for item in records],
            "claim_status": "PROPOSED_UNVERIFIED", "recovered_from_persisted_response": True}
        try:
            _update_llm_validation(task["id"], int(row["sequence"]), "code", [test], "SCRIPT_VERIFIED")
            created, fingerprint = _register_probe(task["id"], suffix, hypothesis, script,
                int(evidence.get("depth", 0)),
                "Replay of Qwen output already logged as SCRIPT_VERIFIED; hypothesis field normalized from explanation after fresh isolated retest")
            verify_id = f"AUTO_VERIFY_{fingerprint}"
            with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
                child = conn.execute("SELECT status FROM tasks WHERE id=?", (verify_id,)).fetchone()
                if not created and child is None:
                    continue
                result["verification_task"] = verify_id
                conn.execute("""UPDATE tasks SET status='DONE',verdict='PASS',next_action=?,result_json=?,
                    lease_owner=NULL,lease_until=NULL,updated_utc=? WHERE id=? AND status='BLOCKED'""",
                    ("Fresh independent binary verification is queued: " + verify_id,
                     json.dumps(result, ensure_ascii=False), _utc(), task["id"]))
                changed = conn.execute("SELECT changes()").fetchone()[0]
                conn.commit()
            if changed:
                state_store._sync_task_db(task["id"], "DONE", "PASS", int(task.get("attempts", 0)))
                recovered += 1
                _log_event("verified_model_output_recovered", {"task_id": task["id"],
                    "model": row["model"], "target_suffix": suffix, "expected": expected,
                    "actual": actual, "verification_task": verify_id, "new_task_created": created})
        except Exception as exc:
            _log_event("verified_model_recovery_error", {"task_id": task["id"],
                "diagnostic": f"{type(exc).__name__}: {exc}"})
    return recovered


def _recover_persisted_reviews() -> int:
    """Validate saved reviewer responses after interruption without another model call."""
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT t.*, r.sequence, r.model, r.response_text, r.parsed_json
               FROM tasks t JOIN research_runs r ON r.task_id=t.id
               WHERE t.status IN ('PENDING','BLOCKED') AND t.agent='ollama-independent-review'
                 AND r.role='independent-review' AND r.decision='RESPONSE_RECEIVED' AND r.error IS NULL
                 AND r.sequence=(SELECT MAX(r2.sequence) FROM research_runs r2
                   WHERE r2.task_id=t.id AND r2.role='independent-review')
               ORDER BY t.updated_utc""").fetchall()
    recovered = 0
    for row in rows:
        task = dict(row)
        evidence = _parse_task_evidence(task)
        if evidence.get("mode") != "review":
            continue
        try:
            parsed = json.loads(row["parsed_json"] or row["response_text"])
            parents = json.loads(task.get("depends_on_json") or "[]")
            if not parents:
                continue
            with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
                parent_row = conn.execute("SELECT status,result_json FROM tasks WHERE id=?", (parents[0],)).fetchone()
                existing_suffixes = {value[0] for value in conn.execute("SELECT target_suffix FROM research_experiments")}
            if not parent_row or parent_row[0] != "DONE":
                continue
            parent_result = json.loads(parent_row[1] or "{}")
        except (TypeError, json.JSONDecodeError, sqlite3.Error):
            continue
        assessment = str(parsed.get("assessment") or "").strip()
        target = str(parsed.get("next_target", "NONE")).upper().strip()
        if not assessment or target != "NONE" and target not in ALLOWED_SUFFIXES:
            diagnostic = "persisted independent review omitted assessment or named a target outside the allowlist"
            tests = [{"name": "review_response_schema_and_target", "status": "FAIL", "diagnostic": diagnostic}]
            _update_llm_validation(task["id"], int(row["sequence"]), "independent-review", tests,
                "REVIEW_REJECTED", diagnostic)
            with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
                conn.execute("UPDATE tasks SET status='BLOCKED',verdict='BLOCKED',result_json=?,next_action=?,updated_utc=? WHERE id=? AND status IN ('PENDING','BLOCKED')",
                    (json.dumps({"error": diagnostic}, ensure_ascii=False), "Review response rejected; wait for new evidence before any retry.", _utc(), task["id"]))
                changed = conn.execute("SELECT changes()").fetchone()[0]
                conn.commit()
            if changed:
                state_store._sync_task_db(task["id"], "BLOCKED", "BLOCKED", int(task.get("attempts", 0)))
            _log_event("persisted_review_rejected", {"task_id": task["id"], "diagnostic": diagnostic})
            continue
        rejected_target = None
        validation_reason = "target is new or reviewer requested no follow-up"
        if target != "NONE" and target in existing_suffixes:
            rejected_target = target
            target = "NONE"
            validation_reason = f"reviewer repeated previously tested {rejected_target}; suggestion discarded without rerunning that hypothesis"
        tests = [{"name": "review_target_is_not_a_duplicate", "status": "PASS",
                  "recommended_target": parsed.get("next_target"), "accepted_target": target,
                  "rejected_duplicate": rejected_target, "reason": validation_reason}]
        artifact = _write_json(f"research/runs/coordinator/{task['id']}/review.json", {
            "task_id": task["id"], "model": row["model"], "input_result": parent_result,
            "raw_response": row["response_text"], "parsed": parsed,
            "validation": tests, "rejected_duplicate_target": rejected_target,
            "claim_status": "REVIEW_OPINION_NOT_FORMAT_PROOF"})
        _update_llm_validation(task["id"], int(row["sequence"]), "independent-review", tests,
                               "REVIEW_VALIDATED")
        result = {"mode": "review", "model": row["model"], "assessment": assessment[:500],
            "next_target": target, "next_hypothesis": str(parsed.get("next_hypothesis", ""))[:500],
            "falsifier": str(parsed.get("falsifier", ""))[:300],
            "reason": (str(parsed.get("reason", "")) + ("; " + validation_reason if rejected_target else ""))[:500],
            "review_artifact": artifact, "depth": evidence.get("depth", 0),
            "parent_result": parent_result, "review_validation": tests}
        with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
            conn.execute("UPDATE tasks SET status='DONE',verdict='PASS',result_json=?,next_action=?,updated_utc=? WHERE id=? AND status IN ('PENDING','BLOCKED')",
                (json.dumps(result, ensure_ascii=False),
                 "Persisted Qwythos response validated; duplicate suffix rejected and no repeat queued." if rejected_target else "Persisted Qwythos response schema and target validated.",
                 _utc(), task["id"]))
            changed = conn.execute("SELECT changes()").fetchone()[0]
            conn.commit()
        if changed:
            state_store._sync_task_db(task["id"], "DONE", "PASS", int(task.get("attempts", 0)))
            recovered += 1
            _after_success(task, result)
            _log_event("persisted_review_recovered", {"task_id": task["id"],
                "model": row["model"], "accepted_target": target,
                "rejected_duplicate": rejected_target, "artifact": artifact})
    return recovered


def _seed_followups_from_completed_reviews() -> int:
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id,depends_on_json,result_json FROM tasks WHERE status='DONE' AND agent='ollama-independent-review' ORDER BY updated_utc").fetchall()
    created = 0
    for row in rows:
        result = json.loads(row["result_json"] or "{}")
        created += int(_queue_followup_proposal(dict(row), result))
        if created:
            break
    return created


def _do_model_task(task: dict[str, Any]) -> dict[str, Any]:
    evidence = _parse_task_evidence(task)
    mode = evidence.get("mode")
    task_id = task["id"]
    if mode in {"propose", "followup"}:
        prompt, data = _prompt_for_proposal(task_id,
            excluded_suffixes=evidence.get("exclude_suffixes", []),
            prior_verified_result=evidence.get("prior_verified_result"),
            required_suffix=evidence.get("required_suffix"),
            prior_diagnostic=(evidence.get("prior_diagnostic") + "\n" + evidence.get("failed_response", ""))
                if evidence.get("diagnostic_repair") else None)
        model, raw, parsed, script_run, tests = _prefix_script(prompt, data, task_id, role="code")
        hypothesis = str(parsed.get("hypothesis", "")).strip()
        suffix = str(parsed.get("target_suffix", "")).upper().strip()
        if suffix in {str(value).upper() for value in evidence.get("exclude_suffixes", [])}:
            raise ValueError(f"follow-up model repeated an already verified target: {suffix}")
        required_suffix = str(evidence.get("required_suffix", "")).upper()
        if required_suffix and suffix != required_suffix:
            raise ValueError(f"follow-up model selected {suffix}, but the tested candidate is fixed to {required_suffix}")
        if not hypothesis or len(hypothesis) > 500:
            raise ValueError("model hypothesis is missing or too long")
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError(f"model target_suffix is outside the explicit allowlist: {suffix!r}")
        full_records = _read_target(suffix)
        actual_prefixes = {"prefixes": [row["prefix_bytes"] for row in full_records]}
        independent_expected = _common_prefix_length(full_records)
        target_script_run = run_research_script(str(parsed["script"]), actual_prefixes)
        target_script_actual = target_script_run.get("result", {}).get("common_prefix")
        if type(target_script_actual) is not int or target_script_actual != independent_expected:
            raise RuntimeError(f"model code failed independent target test for {suffix}: expected {independent_expected}, received {target_script_actual!r}")
        target_test = {"name": f"sandbox_script_matches_independent_{suffix}_target", "status": "PASS",
                       "expected": independent_expected, "actual": target_script_actual,
                       "runner": target_script_run}
        tests = [*tests, target_test]
        with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
            row = conn.execute("SELECT MAX(sequence) FROM research_runs WHERE task_id=? AND role='code'", (task_id,)).fetchone()
        if row and row[0] is not None:
            _update_llm_validation(task_id, int(row[0]), "code", tests, "SCRIPT_VERIFIED")
        code_path = f"research/runs/coordinator/{task_id}/model_generated_script.py"
        code_file = (PROJECT_ROOT / code_path)
        code_file.parent.mkdir(parents=True, exist_ok=True)
        code_file.write_text(str(parsed["script"]), encoding="utf-8")
        code_sha = hashlib.sha256(code_file.read_bytes()).hexdigest()
        with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
            conn.execute("INSERT OR REPLACE INTO artifacts(path,sha256,size_bytes,description,created_utc) VALUES(?,?,?,?,?)",
                         (code_path, code_sha, code_file.stat().st_size, "LLM-authored script, executed only by constrained runner", _utc()))
            conn.commit()
        model_report_path = f"research/runs/coordinator/{task_id}/model_output.json"
        artifact_path = _write_json(model_report_path, {"task_id": task_id, "model": model, "raw_response": raw,
            "parsed": parsed, "script_validation": tests, "preview_test_expected": tests[0].get("expected"),
            "selected_target": suffix, "source_preview": [{k: row[k] for k in ("region", "bytes", "prefix_hex")} for row in full_records],
            "script_path": code_path, "script_sha256": code_sha,
            "warning": "Hypothesis is proposed, not a confirmed format fact."})
        _log_event("local_model_artifact_verified", {"task_id": task_id, "model": model,
            "script_path": code_path, "script_sha256": code_sha, "test": tests[0]})
        return {"mode": mode, "model": model, "hypothesis": hypothesis, "target_suffix": suffix,
            "expected_observation": str(parsed.get("expected_observation", ""))[:300],
            "falsifier": str(parsed.get("falsifier", ""))[:300], "script_source": str(parsed["script"]),
            "script_path": code_path, "script_sha256": code_sha, "artifact": artifact_path,
            "script_test": tests[0], "source_preview": [{"region": row["region"], "bytes": row["bytes"], "prefix_hex": row["prefix_hex"]} for row in full_records],
            "claim_status": "PROPOSED_UNVERIFIED"}
    if mode == "review":
        parent_id = json.loads(task["depends_on_json"] or "[]")[0]
        with closing(sqlite3.connect(STATE_DB)) as conn:
            row = conn.execute("SELECT result_json FROM tasks WHERE id=?", (parent_id,)).fetchone()
        if not row:
            raise RuntimeError("review parent result is missing from the persistent checkpoint")
        verified_result = json.loads(row[0] or "{}")
        available_suffixes = available_target_suffixes()
        prompt = (
            "Ти незалежний локальний рецензент NCDx дослідження. Оціни тільки наведені вимірювання, не приписуй байтам "
            "значення поля/індексу без доказів. Результат незалежного тесту: "
            + json.dumps(verified_result, ensure_ascii=False)[:9000]
            + "\nВибери щонайбільше один наступний target_suffix зі списку " + ", ".join(available_suffixes) + "; "
            "вибери NONE, якщо нового тесту не потрібно або його повторення неінформативне. "
            "Поверни JSON: assessment (коротко), next_target, next_hypothesis, falsifier, reason."
        )
        model, raw, parsed = _call_model(task_id, "independent-review", prompt)
        if not str(parsed.get("assessment", "")).strip():
            raise ValueError("independent model review omitted assessment")
        next_target = str(parsed.get("next_target", "NONE")).upper().strip()
        if next_target != "NONE" and next_target not in ALLOWED_SUFFIXES:
            raise ValueError(f"review model proposed suffix outside allowlist: {next_target}")
        with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
            prior_suffixes = {row[0] for row in conn.execute("SELECT target_suffix FROM research_experiments")}
        rejected_duplicate = None
        rejected_unavailable = None
        if next_target != "NONE" and next_target in prior_suffixes:
            rejected_duplicate = next_target
            next_target = "NONE"
        if next_target != "NONE" and next_target not in available_suffixes:
            rejected_unavailable = next_target
            next_target = "NONE"
        review_validation = {"name": "review_target_is_not_a_duplicate", "status": "PASS",
            "recommended_target": parsed.get("next_target", "NONE"), "accepted_target": next_target,
            "rejected_duplicate": rejected_duplicate, "rejected_unavailable": rejected_unavailable,
            "reason": (f"already-tested {rejected_duplicate} recommendation discarded" if rejected_duplicate else
                       f"missing regional inputs for {rejected_unavailable}; automatic planner will choose an available suffix" if rejected_unavailable else
                       "new target or no follow-up")}
        artifact = _write_json(f"research/runs/coordinator/{task_id}/review.json", {
            "task_id": task_id, "model": model, "input_result": verified_result,
            "raw_response": raw, "parsed": parsed,
            "validation": [review_validation],
            "claim_status": "REVIEW_OPINION_NOT_FORMAT_PROOF"})
        _log_event("independent_model_review_saved", {"task_id": task_id, "model": model,
            "next_target": next_target, "rejected_duplicate": rejected_duplicate, "artifact": artifact})
        return {"mode": mode, "model": model, "assessment": str(parsed["assessment"])[:500],
            "next_target": next_target, "next_hypothesis": str(parsed.get("next_hypothesis", ""))[:500],
            "falsifier": str(parsed.get("falsifier", ""))[:300], "reason": str(parsed.get("reason", ""))[:300],
            "review_artifact": artifact, "depth": evidence.get("depth", 0),
            "parent_result": verified_result, "review_validation": [review_validation],
            "rejected_duplicate_target": rejected_duplicate,
            "rejected_unavailable_target": rejected_unavailable}
    raise ValueError(f"unsupported Ollama research mode: {mode!r}")


def _do_script_repair(task: dict[str, Any]) -> dict[str, Any]:
    evidence = _parse_task_evidence(task)
    source_task = evidence.get("source_task")
    with closing(sqlite3.connect(STATE_DB)) as conn:
        row = conn.execute("SELECT response_text FROM research_runs WHERE task_id=? AND role='code' ORDER BY sequence DESC LIMIT 1",
                           (source_task,)).fetchone()
    if not row:
        raise RuntimeError("diagnostic repair has no persisted source model output")
    prior = json.loads(row[0])
    preview = _preview_candidates()["PDX"]
    data = {"prefixes": [item["prefix_bytes"] for item in preview]}
    prompt = (
        "Виправ код із конкретною новою діагностикою тесту. Попередній код: "
        + str(prior.get("script", ""))[:4000]
        + "\nДіагностика: " + str(evidence.get("diagnostic", ""))[:1200]
        + "\nТочний контракт: data — словник з ключем 'prefixes'; data['prefixes'] містить рівно три списки цілих байтів довжиною 64. "
        "Порівняй той самий індекс у трьох списках з i=0 до 63; зупинись при першій різниці; "
        "присвой кількість однакових початкових байтів цілій змінній common_prefix. "
        "Доступний тільки обмежений Python-піднабір: без імпортів, функцій, атрибутів, файлів, мережі та while; "
        "дозволено присвоєння, +=, for i in range(64), if/else, break, індексування списку та порівняння. "
        "Поверни тільки JSON з одним полем script.")
    model, raw, parsed, runner, tests = _prefix_script(prompt, data, task["id"], role="code")
    code = str(parsed["script"])
    records = _read_target("PDX")
    code_path = f"research/runs/coordinator/{task['id']}/model_generated_script.py"
    path = PROJECT_ROOT / code_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.execute("INSERT OR REPLACE INTO artifacts(path,sha256,size_bytes,description,created_utc) VALUES(?,?,?,?,?)",
                     (code_path, digest, path.stat().st_size, "LLM-authored script, constrained execution only", _utc()))
        conn.commit()
    artifact = _write_json(f"research/runs/coordinator/{task['id']}/model_output.json", {
        "task_id": task["id"], "repair_of": source_task, "diagnostic": evidence.get("diagnostic"),
        "model": model, "raw_response": raw, "parsed": parsed, "script_test": tests,
        "selected_target": "PDX", "script_path": code_path, "script_sha256": digest,
        "preview": [{k: item[k] for k in ("region", "bytes", "prefix_hex")} for item in records],
        "claim_status": "CODE_TESTED_NOT_A_DISK_WRITER"})
    return {"mode": "repair", "model": model,
        "hypothesis": "Compare the first 64 bytes of EUZ.PDX, IZ.PDX and SCZ.PDX without assigning field semantics.",
        "target_suffix": "PDX", "script_source": code, "script_path": code_path,
        "script_sha256": digest, "script_test": tests[0], "artifact": artifact,
        "source_preview": [{"region": item["region"], "bytes": item["bytes"], "prefix_hex": item["prefix_hex"]} for item in records],
        "claim_status": "PROPOSED_UNVERIFIED_AFTER_TESTED_REPAIR"}


def _do_probe_task(task: dict[str, Any]) -> dict[str, Any]:
    evidence = _parse_task_evidence(task)
    suffix = str(evidence.get("suffix", "")).upper()
    records = _read_target(suffix)
    expected_fingerprint = _source_fingerprint(suffix, records)
    if expected_fingerprint != evidence.get("source_fingerprint"):
        raise RuntimeError("source content changed since the experiment was scheduled; a new fingerprint is required")
    shared = _common_prefix_length(records)
    prefixes = {"prefixes": [row["prefix_bytes"] for row in records]}
    script_source = evidence.get("script_source", "")
    script_result = run_research_script(script_source, prefixes) if script_source else None
    script_value = script_result.get("result", {}).get("common_prefix") if script_result else None
    script_pass = type(script_value) is int and script_value == shared
    tests = [
        {"name": "three_regional_files_present", "status": "PASS", "regions": [row["region"] for row in records]},
        {"name": "read_only_sha256_and_size_captured", "status": "PASS", "files": len(records)},
        {"name": "shared_prefix_recomputed_independently", "status": "PASS", "common_prefix_bytes": shared},
        {"name": "model_script_retested_on_selected_originals", "status": "PASS" if script_pass else "FAIL",
         "expected": shared, "actual": script_value},
    ]
    artifact = _write_json(f"research/runs/coordinator/{task['id']}/verification.json", {
        "task_id": task["id"], "experiment_fingerprint": evidence.get("fingerprint"),
        "probe_type": "cross_region_prefix", "target_suffix": suffix,
        "hypothesis": evidence.get("hypothesis"), "records": records,
        "common_prefix_bytes": shared, "script_result": script_result, "tests": tests,
        "conclusion": "byte-level regional comparison only; no field or extension semantics inferred",
        "source_roots_read_only": True})
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.execute("UPDATE research_experiments SET status=? WHERE fingerprint=?",
                     ("VERIFIED" if script_pass else "TEST_FAILED", evidence["fingerprint"]))
        conn.commit()
    if not script_pass:
        raise RuntimeError(f"independent code artifact did not reproduce prefix count {shared}; received {script_value!r}")
    return {"mode": "cross_region_prefix", "fingerprint": evidence["fingerprint"],
        "target_suffix": suffix, "hypothesis": evidence.get("hypothesis"),
        "records": records, "common_prefix_bytes": shared, "script_result": script_result,
        "script_independent_test": tests[-1], "verification_tests": tests, "artifact": artifact,
        "claim_status": "BYTE_COMPARISON_VERIFIED_SEMANTICS_UNKNOWN",
        "depth": int(evidence.get("depth", 0)), "script_source": script_source}


def _resource_can_start(agent: str) -> tuple[bool, str]:
    snap = _host_resources()
    free = shutil.disk_usage(PROJECT_ROOT).free
    if free < 5 * 1024**3:
        return False, "less than 5 GiB disk free"
    available_ram = snap.get("ram", {}).get("available_bytes")
    if available_ram is not None and available_ram < 3 * 1024**3:
        return False, "less than 3 GiB RAM available"
    gpu = snap.get("gpu")
    if agent.startswith("ollama-") and gpu and gpu.get("memory_free_mib", 0) < 1500:
        return False, "less than 1.5 GiB VRAM free"
    return True, "resources within configured limits"


def _defer_task(task: dict[str, Any], reason: str) -> None:
    with closing(sqlite3.connect(STATE_DB, timeout=10)) as conn:
        conn.execute("UPDATE tasks SET status='PENDING',attempts=MAX(0,attempts-1),lease_owner=NULL,lease_until=NULL,updated_utc=? WHERE id=? AND status='LEASED'",
                     (_utc(), task["id"]))
        conn.execute("DELETE FROM leases WHERE task_id=? AND lease_id=?", (task["id"], task["lease_id"]))
        conn.commit()
    _log_event("task_deferred_resources", {"task_id": task["id"], "reason": reason})


def _after_success(task: dict[str, Any], result: dict[str, Any]) -> None:
    agent = task.get("agent")
    evidence = _parse_task_evidence(task)
    if agent in {"ollama-research-code", "ollama-script-repair"}:
        _register_probe(task["id"], result["target_suffix"], result["hypothesis"],
                        result["script_source"], int(evidence.get("depth", 0)),
                        "Qwen proposal; deterministic verifier queued as a dependent task")
    elif agent == "binary-probe":
        _register_review(task["id"], result, int(evidence.get("depth", 0)))
    elif agent == "ollama-independent-review":
        depth = int(evidence.get("depth", 0)) + 1
        target = result.get("next_target", "NONE")
        if target != "NONE" and depth <= MAX_RESEARCH_DEPTH:
            hypothesis = result.get("next_hypothesis") or f"Check whether the first 64 bytes of {target} repeat across EUZ/IZ/SCZ."
            parent_result = result.get("parent_result", {})
            script_source = parent_result.get("script_source", "")
            _register_probe(task["id"], target, hypothesis, script_source, depth,
                            "Qwythos recommendation after a verified byte comparison")
        else:
            _queue_followup_proposal(task, result)


def _record_completion_resource(task_id: str, resources: dict[str, Any], elapsed: float, status: str) -> None:
    _log_event("task_resource_checkpoint", {"task_id": task_id, "status": status,
        "elapsed_seconds": round(elapsed, 3), "resources": resources})


class _LeaseHeartbeat:
    def __init__(self, task_id: str, lease_id: str):
        self.task_id, self.lease_id = task_id, lease_id
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"lease-{task_id}", daemon=True)

    def _run(self) -> None:
        while not self.stop_event.wait(20):
            try:
                if not state_store.heartbeat(self.task_id, self.lease_id, lease_seconds=90):
                    _log_event("lease_lost", {"task_id": self.task_id})
                    return
            except Exception as exc:
                _log_event("lease_heartbeat_error", {"task_id": self.task_id, "error": f"{type(exc).__name__}: {exc}"})

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)


def _execute(task: dict[str, Any]) -> dict[str, Any]:
    if task.get("agent") == "ollama-research-code" or task.get("agent") == "ollama-independent-review":
        return _do_model_task(task)
    if task.get("agent") == "ollama-script-repair":
        return _do_script_repair(task)
    if task.get("agent") == "binary-probe":
        return _do_probe_task(task)
    # Deterministic allowlisted legacy tasks remain available from the restored checkpoint.
    from src.agent import coordinator as legacy
    handler = legacy.HANDLERS.get(task["id"])
    if handler is None:
        raise RuntimeError(f"No allowlisted executor for task {task['id']}")
    return handler()


def _checkpoint_sqlite() -> None:
    with closing(sqlite3.connect(STATE_DB, timeout=20)) as conn:
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"persistent project checkpoint failed integrity_check: {result}")


def run(max_tasks: int = 4, owner: str = "ncdr-autonomous", max_seconds: int = 300) -> dict[str, Any]:
    if not 1 <= max_tasks <= MAX_TASKS_PER_CYCLE:
        raise ValueError(f"max_tasks must be between 1 and {MAX_TASKS_PER_CYCLE}")
    if not 5 <= max_seconds <= 600:
        raise ValueError("max_seconds must be between 5 and 600")
    ensure_runtime_schema()
    seed_research_chain()
    _recover_verified_model_outputs()
    _recover_persisted_reviews()
    _seed_followups_from_completed_reviews()
    _seed_followup_repairs()
    from src.agent import coordinator as legacy
    legacy.update_gates()
    started = time.monotonic()
    completed: list[dict[str, Any]] = []
    for _ in range(max_tasks):
        if time.monotonic() - started >= max_seconds:
            break
        control = _control_row()
        if control["desired_state"] in {"PAUSED", "STOP_REQUESTED"}:
            break
        task = state_store.claim_next(owner, lease_seconds=90)
        if not task:
            break
        allowed, reason = _resource_can_start(task["agent"])
        if not allowed:
            _defer_task(task, reason)
            _set_worker_state("WAITING_FOR_RESOURCES", task["id"], reason)
            break
        _set_worker_state("RUNNING", task["id"], "Виконується обмежене дослідження")
        _log_event("task_execution_started", {"task_id": task["id"], "agent": task["agent"],
            "attempt": task["attempts"], "objective_tests": json.loads(task.get("objective_tests_json", "[]"))})
        before = _host_resources()
        task_start = time.monotonic()
        try:
            with _LeaseHeartbeat(task["id"], task["lease_id"]):
                result = _execute(task)
            _after_success(task, result)
            resources = {"before": before, "after": _host_resources()}
            result["task_elapsed_seconds"] = round(time.monotonic() - task_start, 3)
            result["resource_checkpoints"] = resources
            state_store.complete_task(task["id"], task["lease_id"], result)
            _checkpoint_sqlite()
            _record_completion_resource(task["id"], resources, time.monotonic()-task_start, "DONE")
            completed.append({"task_id": task["id"], "status": "DONE", "result": result})
            _set_worker_state("RUNNING", None, f"Завершено {task['id']}; наступна незалежна задача — з черги")
            legacy.update_gates()
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            try:
                status = state_store.fail_task(task["id"], task["lease_id"], reason)
            except RuntimeError:
                status = "LEASE_LOST"
            resources = {"before": before, "after": _host_resources()}
            _record_completion_resource(task["id"], resources, time.monotonic()-task_start, status)
            _log_event("task_diagnostic", {"task_id": task["id"], "status": status,
                "diagnostic": reason, "new_retry_created": False})
            completed.append({"task_id": task["id"], "status": status, "reason": reason})
            _set_worker_state("ERROR", task["id"], reason)
            legacy.update_gates()
            # A failed task is not retried in place. A repair task is created only
            # by a later explicit, fingerprinted diagnostic workflow.
            break
    final_status = state_store.status_summary()
    if completed and completed[-1]["status"] == "DONE":
        control = _control_row()
        if control["desired_state"] == "RUNNING":
            _set_worker_state("IDLE", None, "Цикл завершено; чергу перевірено")
    return {"completed_this_run": completed, "status": final_status,
            "elapsed_seconds": round(time.monotonic()-started, 3),
            "next_action": "Запусти наступний обмежений цикл або залиш фоновий сервіс чекати на команду Dashboard."}


def _model_telemetry(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return bounded, text-free model telemetry from the actual saved schema."""
    tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "research_runs" not in tables:
        return {"available": False, "reason": "research_runs table is absent", "periods": {}, "recent_runs": []}
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(research_runs)")}
    required = {"id", "task_id", "role", "model", "decision", "elapsed_ms", "created_utc", "error"}
    if not required <= columns:
        return {"available": False, "reason": "research_runs schema lacks required telemetry columns",
                "periods": {}, "recent_runs": []}
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now - timedelta(days=7)).isoformat()
    periods: dict[str, Any] = {}
    token_columns = "resource_json" in columns
    for name, cutoff in (("today", day_start), ("seven_days", week_start), ("all", None)):
        where = "COALESCE(role,'') NOT LIKE '%diagnostic%'"
        params: tuple[Any, ...] = ()
        if cutoff is not None:
            where += " AND created_utc>=?"
            params = (cutoff,)
        select = """SELECT COUNT(*) AS requests,
            SUM(CASE WHEN error IS NULL THEN 1 ELSE 0 END) AS successful,
            SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN decision!='API_ERROR' THEN 1 ELSE 0 END) AS responses,
            AVG(elapsed_ms) AS average_ms, MAX(elapsed_ms) AS maximum_ms"""
        if token_columns:
            select += ", SUM(CAST(json_extract(resource_json,'$.prompt_tokens') AS INTEGER)) AS input_tokens, " \
                      "SUM(CAST(json_extract(resource_json,'$.output_tokens') AS INTEGER)) AS output_tokens"
        row = conn.execute(f"{select} FROM research_runs WHERE {where}", params).fetchone()
        record = dict(row) if row else {}
        periods[name] = {"requests": int(record.get("requests") or 0),
            "responses": int(record.get("responses") or 0),
            "successful": int(record.get("successful") or 0),
            "failed": int(record.get("failed") or 0),
            "average_ms": round(float(record["average_ms"])) if record.get("average_ms") is not None else None,
            "maximum_ms": int(record["maximum_ms"]) if record.get("maximum_ms") is not None else None,
            "input_tokens": record.get("input_tokens"), "output_tokens": record.get("output_tokens")}
    select_recent = "id,task_id,role,model,decision,elapsed_ms,created_utc,error"
    if token_columns:
        select_recent += ",resource_json"
    text_columns = {"input_json", "response_text", "parsed_json"} <= columns
    if text_columns:
        select_recent += ",input_json,response_text,parsed_json"
    recent = []
    for row in conn.execute(f"SELECT {select_recent} FROM research_runs "
                            "WHERE COALESCE(role,'') NOT LIKE '%diagnostic%' ORDER BY id DESC LIMIT 300"):
        item = dict(row)
        resources: dict[str, Any] = {}
        if token_columns:
            try:
                resources = json.loads(item.pop("resource_json") or "{}")
            except (TypeError, json.JSONDecodeError):
                resources = {}
        text_available = False
        if text_columns:
            saved_input = item.pop("input_json", "")
            saved_response = item.pop("response_text", "")
            saved_parsed = item.pop("parsed_json", "")
            try:
                input_data = json.loads(saved_input or "{}")
            except (TypeError, json.JSONDecodeError):
                input_data = {}
            text_available = bool(resources.get("model_text_persisted") is True or
                (isinstance(input_data, dict) and input_data.get("prompt")) or
                saved_response or (saved_parsed and saved_parsed != "{}"))
        item["input_tokens"] = resources.get("prompt_tokens")
        item["output_tokens"] = resources.get("output_tokens")
        item["text_available"] = text_available
        item["status"] = "FAILED" if item.get("error") else (
            "INVALID" if item.get("decision") == "INVALID_JSON" else "OK")
        recent.append(item)
    models = [{"model": row[0], "role": row[1], "requests": row[2]}
        for row in conn.execute("""SELECT model,role,COUNT(*) FROM research_runs
            WHERE COALESCE(role,'') NOT LIKE '%diagnostic%' GROUP BY model,role
            ORDER BY COUNT(*) DESC,model,role LIMIT 30""")]
    return {"available": True, "source_table": "research_runs", "periods": periods,
        "models": models, "recent_runs": recent,
        "last_activity_utc": recent[0]["created_utc"] if recent else None,
        "full_text_available": any(row.get("text_available") for row in recent)}


def dashboard_state() -> dict[str, Any]:
    ensure_runtime_schema()
    with closing(sqlite3.connect(STATE_DB)) as conn:
        conn.row_factory = sqlite3.Row
        control = dict(conn.execute("SELECT * FROM coordinator_control WHERE id=1").fetchone())
        current = conn.execute("SELECT id,agent,stage,updated_utc,budget_json FROM tasks WHERE status='LEASED' ORDER BY updated_utc DESC LIMIT 20").fetchall()
        current = next((row for row in current if not project_scope.task_is_excluded(dict(row))), None)
        task_rows = [dict(row) for row in conn.execute("SELECT id,stage,status,agent,next_action,updated_utc,budget_json FROM tasks ORDER BY updated_utc DESC")]
        task_rows = [row for row in task_rows if not project_scope.task_is_excluded(row)]
        tasks = task_rows[:40]
        counts: dict[str, int] = {}
        for row in task_rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        model_telemetry = _model_telemetry(conn)
        model_rows = [row for row in model_telemetry.get("recent_runs", [])
                      if not project_scope.task_is_excluded(str(row.get("task_id") or ""))]
        latest_model = model_rows[0] if model_rows else None
        successful = conn.execute("SELECT task_id,decision,created_utc FROM research_runs WHERE decision IN ('SCRIPT_VERIFIED','RESPONSE_RECEIVED','REVIEW_VALIDATED') AND error IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        error = conn.execute("SELECT task_id,error,created_utc FROM research_runs WHERE error IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        runs = model_rows[:12]
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        artifact_rows: list[dict[str, Any]] = []
        if "autonomy_artifacts" in tables:
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(autonomy_artifacts)")}
            required = {"task_id", "path", "sha256", "size_bytes", "description", "created_utc"}
            if required <= columns:
                artifact_rows.extend(dict(row) for row in conn.execute(
                    "SELECT task_id,path,sha256,size_bytes,description,created_utc FROM autonomy_artifacts ORDER BY created_utc DESC LIMIT 200"))
        if "artifacts" in tables:
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(artifacts)")}
            required = {"path", "sha256", "size_bytes", "description", "created_utc"}
            if required <= columns:
                task_expr = "task_id" if "task_id" in columns else "NULL AS task_id"
                artifact_rows.extend(dict(row) for row in conn.execute(
                    f"SELECT {task_expr},path,sha256,size_bytes,description,created_utc FROM artifacts ORDER BY created_utc DESC LIMIT 200"))
        unique_artifacts: dict[str, dict[str, Any]] = {}
        for artifact in artifact_rows:
            path = str(artifact.get("path") or "")
            if not path or project_scope.task_is_excluded(f"{artifact.get('task_id') or ''} {path}"):
                continue
            unique_artifacts.setdefault(path, artifact)
        artifacts = sorted(unique_artifacts.values(), key=lambda row: str(row.get("created_utc") or ""), reverse=True)[:20]
        evidence_count = conn.execute("SELECT count(*) FROM evidence").fetchone()[0]
        db_integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    benchmark = _model_report()
    return {"updated_utc": _utc(), "control": control, "current_task": dict(current) if current else None,
        "current_codex": "Codex керує цією сесією; автоматичний виклик Codex поза сесією не налаштований",
        "last_model": dict(latest_model) if latest_model else None,
        "last_success": dict(successful) if successful else None,
        "last_error": dict(error) if error else None, "task_counts": counts, "tasks": tasks,
        "model_runs": runs, "model_telemetry": model_telemetry,
        "artifacts": artifacts, "evidence_count": evidence_count,
        "sqlite_integrity": db_integrity, "benchmark_recommended_model": benchmark.get("recommended_model"),
        "benchmark_models": [{k: row.get(k) for k in ("model","passed","task_count","verified_results_per_minute","peak_vram_used_mib")}
                             for row in benchmark.get("models", [])], "resources": _host_resources(),
        "system_readiness": _readiness()}


def _readiness() -> dict[str, Any]:
    acceptance_path = PROJECT_ROOT / "reports" / "product_acceptance.json"
    try:
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        acceptance = {"checks": {}}
    checks = acceptance.get("checks", {})
    passed = lambda name: checks.get(name, {}).get("pass") is True
    build = acceptance.get("build", {})
    map_path = str(build.get("osm_database") or "")
    map_db = (PROJECT_ROOT / map_path).resolve() if map_path else PROJECT_ROOT / "data" / "osm" / "missing.sqlite"
    if PROJECT_ROOT not in map_db.parents:
        map_db = PROJECT_ROOT / "data" / "osm" / "missing.sqlite"
    osm_ready = map_db.is_file() and all(passed(name) for name in
        ("map_database_integrity", "versioned_osm_provenance", "city_search_and_connected_route"))
    writer_tests = (PROJECT_ROOT / "research" / "writer" / "EUZ-noop-roundtrip.MP0").is_file() and \
                   (PROJECT_ROOT / "research" / "writer" / "EUZ-to-SC-header-experiment.MP0").is_file()
    writer_task = None
    try:
        with closing(sqlite3.connect(STATE_DB, timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            writer_task = conn.execute("SELECT status,result_json FROM tasks WHERE id=?",
                ("AUTO_F3_EXPERIMENTAL_MP0_ROUNDTRIP_001",)).fetchone()
    except sqlite3.Error:
        pass
    writer_task_result = json.loads(writer_task["result_json"] or "{}") if writer_task else {}
    writer_status = ("COPY_ONLY_ROUNDTRIP_PASS; DISK_WRITER_BLOCKED"
                     if writer_task and writer_task["status"] == "DONE" and writer_task_result.get("status") == "PASS_COPY_ONLY"
                     else "COPY_ONLY_ROUNDTRIP_QUEUED" if writer_task and writer_task["status"] in {"PENDING", "LEASED"}
                     else "HEADER_EXPERIMENTS_ONLY" if writer_tests else "RESEARCH")
    return {
        "OSM data preparation for disc": {"status": "DATA_READY_FOR_DISC_PIPELINE" if osm_ready else "IN_PROGRESS", "artifact": str(map_db.relative_to(PROJECT_ROOT)) if map_db.is_file() else "OSM database not verified", "tests": "saved database integrity, dated source provenance, Ukrainian street search and connected road route; preparation only, no NCDx export claimed"},
        "NCDx Reader/Writer": {"status": writer_status, "artifact": "src/readers/ncdx_mp0_header.py; src/writers/research_writer.py; reports/autonomous_writer_roundtrip.json", "tests": "three regional no-op copies plus one-field experiment on a copy; payload semantics and device compatibility unknown"},
        "Disc image": {"status": "NOT_BUILT", "artifact": "none", "tests": "no confirmed NCDx export layout or independent image verification"},
        "Original media": {"status": "READ_ONLY", "artifact": "prior SHA-256 manifest; no full rescan", "tests": "source opens read-only and exact per-probe SHA captured"},
        "Physical compatibility": {"status": "NOT_TESTED", "artifact": "none", "tests": "not tested in a compatible Opel vehicle"},
    }


def _page_with_live_controls(token: str) -> bytes:
    from src.agent.build_dashboard import build_html
    base = build_html()
    controls = '''<section id="live-coordinator" class="panel"><h1>Живий координатор</h1>
      <div class="metrics"><article><span>Координатор / Qwen</span><b id="live-worker">—</b><small id="live-model">Модель ще не запускалася</small></article>
      <article><span>Поточна задача</span><b id="live-current">—</b><small id="live-codex">—</small></article>
      <article><span>Остання перевірка</span><b id="live-success">—</b><small id="live-error">Помилок моделі не зафіксовано</small></article>
      <article><span>Ресурси</span><b id="live-resources">—</b><small id="live-db">—</small></article></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="tab" onclick="controlNcdr('RUNNING')">▶ Запустити</button>
      <button class="tab" onclick="controlNcdr('PAUSED')">Ⅱ Пауза після поточної задачі</button>
      <button class="tab" onclick="controlNcdr('STOP_REQUESTED')">■ Коректно зупинити</button>
      <span id="live-updated" class="muted"></span></div>
      <h2>Приймальні критерії продукту</h2><div class="table-wrap"><table><thead><tr><th>Напрям</th><th>Готовність</th><th>Перевірюваний стан</th></tr></thead><tbody id="live-readiness"><tr><td colspan="3">Завантаження…</td></tr></tbody></table></div>
      <h2>Журнал останніх модельних рішень і тестів</h2><div class="table-wrap"><table><thead><tr><th>Час / задача</th><th>Модель</th><th>Рішення / діагностика</th></tr></thead><tbody id="live-runs"><tr><td colspan="3">Завантаження…</td></tr></tbody></table></div>
      <h2>Робочі артефакти</h2><ul id="live-artifacts"><li>Завантаження…</li></ul></section>'''
    token_script = f'''<script>
const NCDR_TOKEN={json.dumps(token)};
const escNcdr=x=>String(x??'').replace(/[&<>"']/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}}[c]));
async function refreshNcdr(){{try{{const s=await(await fetch('/api/state',{{cache:'no-store'}})).json();
document.getElementById('live-worker').textContent=s.control.worker_state+' · '+s.control.desired_state;
document.getElementById('live-current').textContent=s.current_task?s.current_task.id:'Черга очікує';
document.getElementById('live-codex').textContent=s.current_codex;
document.getElementById('live-model').textContent=s.last_model?s.last_model.model+' · '+s.last_model.role:'Локальна модель ще не запускалася';
document.getElementById('live-success').textContent=s.last_success?s.last_success.task_id+' · '+s.last_success.decision:'Ще немає перевіреної відповіді';
document.getElementById('live-error').textContent=s.last_error?('Остання помилка: '+s.last_error.error):'Остання помилка: відсутня';
const r=s.resources||{{}}, ram=r.ram||{{}}, gpu=r.gpu||{{}};
document.getElementById('live-resources').textContent='RAM '+(ram.available_bytes?Math.round(ram.available_bytes/1048576)+' MiB':'—')+' · VRAM '+(gpu.memory_free_mib||'—')+' MiB · CPU '+(r.cpu_percent??'—')+'%';
document.getElementById('live-db').textContent='Диск вільний '+(r.disk_free_bytes?Math.round(r.disk_free_bytes/1073741824)+' GiB':'—')+' · SQLite '+s.sqlite_integrity+' · докази '+s.evidence_count;
document.getElementById('live-updated').textContent='Оновлено '+s.updated_utc;
document.getElementById('live-readiness').innerHTML=Object.entries(s.system_readiness||{{}}).map(([n,x])=>'<tr><td>'+escNcdr(n)+'</td><td>'+escNcdr(x.status)+'</td><td>'+escNcdr(x.tests)+'<br><code>'+escNcdr(x.artifact)+'</code></td></tr>').join('')||'<tr><td colspan="3">Критерії ще не записані.</td></tr>';
document.getElementById('live-runs').innerHTML=(s.model_runs||[]).map(x=>'<tr><td>'+escNcdr(x.created_utc)+'<br><code>'+escNcdr(x.task_id)+'</code></td><td>'+escNcdr(x.model)+'<br>'+escNcdr(x.role)+'</td><td>'+escNcdr(x.decision)+(x.error?'<br>'+escNcdr(x.error):'')+' · '+escNcdr(x.elapsed_ms)+' ms</td></tr>').join('')||'<tr><td colspan="3">Запусків ще немає.</td></tr>';
document.getElementById('live-artifacts').innerHTML=(s.artifacts||[]).map(x=>'<li><code>'+escNcdr(x.path)+'</code> · '+escNcdr(x.size_bytes)+' B · '+escNcdr(String(x.sha256).slice(0,16))+'</li>').join('')||'<li>Артефактів ще немає.</li>';
}}catch(e){{document.getElementById('live-updated').textContent='Dashboard API недоступний: відкрий через start_dashboard.ps1';}}}}
async function controlNcdr(state){{await fetch('/api/control',{{method:'POST',headers:{{'Content-Type':'application/json','X-NCDR-Control':NCDR_TOKEN}},body:JSON.stringify({{state}})}});await refreshNcdr();}}
refreshNcdr();setInterval(refreshNcdr,3000);
</script>'''
    html_doc = base.replace("<main>", "<main>" + controls, 1).replace("</main>", token_script + "</main>", 1)
    return html_doc.encode("utf-8")


def serve_dashboard(port: int = 8765) -> tuple[ThreadingHTTPServer, threading.Thread]:
    token = secrets.token_urlsafe(32)
    page = _page_with_live_controls(token)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:
            return
        def _json(self, status: int, value: dict[str, Any]) -> None:
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self) -> None:
            if self.path == "/api/state":
                self._json(200, dashboard_state())
            elif self.path in {"/", "/index.html"}:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            else:
                self._json(404, {"error": "not found"})
        def do_POST(self) -> None:
            if self.path != "/api/control" or self.headers.get("X-NCDR-Control") != token:
                self._json(403, {"error": "forbidden"})
                return
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
                self._json(403, {"error": "origin rejected"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 1000:
                    raise ValueError("invalid request size")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                set_control(payload.get("state", ""), "dashboard button")
                self._json(200, {"ok": True, "state": payload["state"]})
            except Exception as exc:
                self._json(400, {"error": f"{type(exc).__name__}: {exc}"})
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, name="ncdr-dashboard-http", daemon=True)
    thread.start()
    _log_event("dashboard_server_started", {"host": "127.0.0.1", "port": port})
    return server, thread


def service(port: int = 8765, max_tasks: int = 4, max_seconds: int = 300, resume: bool = False) -> int:
    ensure_runtime_schema()
    seed_research_chain()
    if resume:
        set_control("RUNNING", "service resume on user logon")
    server, _server_thread = serve_dashboard(port)
    _set_worker_state("RUNNING" if _control_row()["desired_state"] == "RUNNING" else "PAUSED", None,
                      f"Живий Dashboard: http://127.0.0.1:{port}/")
    _log_event("coordinator_service_started", {"port": port, "resume": resume,
        "max_tasks_per_cycle": max_tasks, "max_seconds_per_cycle": max_seconds})
    idle_rounds = 0
    try:
        while True:
            control = _control_row()
            desired = control["desired_state"]
            if desired == "STOP_REQUESTED":
                break
            if desired in {"PAUSED", "STOPPED"}:
                _set_worker_state("PAUSED", None, "Пауза; ресурси не витрачаються")
                time.sleep(1)
                continue
            result = run(max_tasks=max_tasks, owner="ncdr-windows-service", max_seconds=max_seconds)
            if result["completed_this_run"]:
                idle_rounds = 0
                time.sleep(0.2)
                continue
            idle_rounds += 1
            _set_worker_state("IDLE", None, "Немає доступної задачі; очікування без виклику моделі")
            time.sleep(min(30, max(2, idle_rounds * 2)))
    except KeyboardInterrupt:
        _log_event("coordinator_service_interrupted", {"reason": "keyboard interrupt"})
    finally:
        _set_worker_state("STOPPING", None, "Завершення після поточної задачі")
        server.shutdown()
        server.server_close()
        _mark_service_stopped("Зупинено коректно; checkpoint і цілісність SQLite підтверджені")
        _checkpoint_sqlite()
        _log_event("coordinator_service_stopped", {"checkpoint_integrity": "ok"})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NCDR persistent local research coordinator")
    parser.add_argument("--max-tasks", type=int, default=4, help="maximum tasks in one bounded cycle (1..10)")
    parser.add_argument("--max-seconds", type=int, default=300, help="cycle wall-time limit in seconds (5..600)")
    parser.add_argument("--owner", default="ncdr-coordinator")
    parser.add_argument("--service", action="store_true", help="run background worker with a live dashboard API")
    parser.add_argument("--resume", action="store_true", help="resume pending work when the service starts")
    parser.add_argument("--dashboard-port", type=int, default=8765)
    parser.add_argument("--set-control", choices=("RUNNING", "PAUSED", "STOP_REQUESTED"))
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    ensure_runtime_schema()
    if args.status:
        print(json.dumps(dashboard_state(), ensure_ascii=True, indent=2))
        return 0
    if args.set_control:
        set_control(args.set_control, "command line")
        return 0
    if args.service:
        return service(args.dashboard_port, args.max_tasks, args.max_seconds, args.resume)
    result = run(args.max_tasks, args.owner, args.max_seconds)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if all(row.get("status") == "DONE" for row in result["completed_this_run"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())


