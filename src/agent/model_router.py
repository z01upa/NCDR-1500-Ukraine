"""Bounded local JSON inference, with durable quotas and immutable evidence."""
from __future__ import annotations

from contextlib import contextmanager, closing
from datetime import datetime, timezone
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _validate(value, schema):
    """Validate a strict JSON Schema subset without optional dependencies."""
    def json_value(v):
        if v is None or type(v) in (str, bool, int):
            return
        if type(v) is float and math.isfinite(v):
            return
        if type(v) is list:
            for item in v:
                json_value(item)
            return
        if type(v) is dict and all(type(k) is str for k in v):
            for item in v.values():
                json_value(item)
            return
        raise ValueError("non-JSON value")

    def equal(a, b):
        if type(a) in (int, float) and type(b) in (int, float):
            return a == b
        if type(a) is not type(b):
            return False
        if isinstance(a, dict):
            return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
        if isinstance(a, list):
            return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
        return a == b

    def check_schema(s):
        if type(s) is bool:
            return
        supported = {"type", "properties", "required", "additionalProperties", "items", "enum", "const",
                     "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems",
                     "title", "description", "$schema"}
        if type(s) is not dict or set(s) - supported:
            raise ValueError("unsupported schema keyword or schema type")
        for key in ("title", "description", "$schema"):
            if key in s and type(s[key]) is not str:
                raise ValueError("schema annotation must be a string")
        if "$schema" in s and s["$schema"] not in {
                "http://json-schema.org/draft-07/schema#",
                "https://json-schema.org/draft/2019-09/schema",
                "https://json-schema.org/draft/2020-12/schema"}:
            raise ValueError("unsupported schema dialect")
        if "type" in s:
            names = s["type"] if type(s["type"]) is list else [s["type"]]
            allowed = {"object", "array", "string", "boolean", "null", "integer", "number"}
            if (not names or any(type(n) is not str or n not in allowed for n in names)
                    or len(set(names)) != len(names)):
                raise ValueError("invalid schema type")
        if "properties" in s:
            if type(s["properties"]) is not dict:
                raise ValueError("schema properties must be an object")
            for key, child in s["properties"].items():
                if type(key) is not str:
                    raise ValueError("schema property names must be strings")
                check_schema(child)
        if "required" in s:
            required = s["required"]
            if (type(required) is not list or any(type(k) is not str for k in required)
                    or len(set(required)) != len(required)):
                raise ValueError("invalid schema required list")
        for key in ("additionalProperties", "items"):
            if key in s:
                check_schema(s[key])
        for key in ("minimum", "maximum"):
            if key in s and (type(s[key]) not in (int, float)
                             or (type(s[key]) is float and not math.isfinite(s[key]))):
                raise ValueError("invalid numeric schema bound")
        for key in ("minLength", "maxLength", "minItems", "maxItems"):
            if key in s and (type(s[key]) is not int or s[key] < 0):
                raise ValueError("invalid schema size bound")
        if "enum" in s:
            choices = s["enum"]
            if type(choices) is not list or not choices:
                raise ValueError("schema enum must be a nonempty array")
            for i, choice in enumerate(choices):
                json_value(choice)
                if any(equal(choice, previous) for previous in choices[:i]):
                    raise ValueError("duplicate schema enum value")
        if "const" in s:
            json_value(s["const"])

    def check(v, s):
        if isinstance(s, bool):
            if not s:
                raise ValueError("schema rejects value")
            return
        supported = {"type", "properties", "required", "additionalProperties", "items", "enum", "const",
                     "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems",
                     "title", "description", "$schema"}
        if not isinstance(s, dict) or set(s) - supported:
            raise ValueError("unsupported schema keyword")
        types = {"object": isinstance(v, dict), "array": isinstance(v, list),
                 "string": isinstance(v, str), "boolean": isinstance(v, bool), "null": v is None,
                 "integer": type(v) is int or (type(v) is float and v.is_integer()),
                 "number": type(v) in (int, float)}
        if "type" in s:
            names = s["type"] if isinstance(s["type"], list) else [s["type"]]
            if not any(types.get(n, False) for n in names):
                raise ValueError("schema type mismatch")
        if "enum" in s and not any(equal(v, x) for x in s["enum"]):
            raise ValueError("schema enum mismatch")
        if "const" in s and not equal(v, s["const"]):
            raise ValueError("schema const mismatch")
        if isinstance(v, dict):
            if any(k not in v for k in s.get("required", [])):
                raise ValueError("missing required property")
            for k, item in v.items():
                if k in s.get("properties", {}):
                    check(item, s["properties"][k])
                else:
                    check(item, s.get("additionalProperties", True))
        if isinstance(v, list):
            for item in v:
                check(item, s.get("items", True))
        for low, high, size in (("minLength", "maxLength", len(v) if isinstance(v, str) else None),
                                ("minItems", "maxItems", len(v) if isinstance(v, list) else None),
                                ("minimum", "maximum", v if type(v) in (int, float) else None)):
            if size is not None and ((low in s and size < s[low]) or (high in s and size > s[high])):
                raise ValueError("schema bound mismatch")
    check_schema(schema)
    json_value(value)
    check(value, schema)


@contextmanager
def _gpu_mutex(name, timeout=120):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateMutexW(None, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        acquired = False
        try:
            result = kernel.WaitForSingleObject(handle, int(timeout * 1000))
            if result not in (0, 0x80):
                raise TimeoutError("GPU mutex unavailable")
            acquired = True
            yield
        finally:
            if acquired:
                kernel.ReleaseMutex(handle)
            kernel.CloseHandle(handle)
    else:
        import fcntl
        lock_path = Path(tempfile.gettempdir()) / ("ncdr-gpu-" + hashlib.sha256(name.encode()).hexdigest())
        with lock_path.open("a+b") as lock:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("GPU mutex unavailable")
                    time.sleep(.02)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


class ModelRouter:
    def __init__(self, db_path, quota_per_model=None, mutex_name="Local\\NCDR-Ollama-GPU"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.quotas = dict(quota_per_model or {})
        self.mutex_name = mutex_name
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS model_daily_quota(day TEXT, model TEXT, used INTEGER NOT NULL, PRIMARY KEY(day,model))")
            conn.execute("CREATE TABLE IF NOT EXISTS model_router_requests(task_id TEXT PRIMARY KEY, request_json TEXT NOT NULL, result_json TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS model_router_attempts(id INTEGER PRIMARY KEY, task_id TEXT, attempt_json TEXT NOT NULL)")

    def _reserve(self, model):
        day = datetime.now(timezone.utc).date().isoformat()
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT used FROM model_daily_quota WHERE day=? AND model=?", (day, model)).fetchone()
            used = row[0] if row else 0
            limit = int(self.quotas.get(model, 100))
            if used >= limit:
                return None
            conn.execute("INSERT INTO model_daily_quota VALUES(?,?,?) ON CONFLICT(day,model) DO UPDATE SET used=excluded.used", (day, model, used + 1))
            return {"day": day, "reservation": used + 1, "daily_limit": limit}

    def generate_json(self, task_id, prompt, schema, models, invoke, *, original_evidence=None, retry_limit=1):
        evidence = copy.deepcopy(original_evidence)
        evidence_hash = _hash(evidence)
        schema = copy.deepcopy(schema)
        models = list(dict.fromkeys(models))
        request = {"task_id": task_id, "prompt": prompt, "schema": schema, "models": models,
                   "original_evidence": evidence, "original_evidence_sha256": evidence_hash}
        result = {**copy.deepcopy(request), "status": "WAITING_MODEL", "schema_sha256": _hash(schema),
                  "attempts": [], "resumable": True}
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
            previous = conn.execute("SELECT request_json FROM model_router_requests WHERE task_id=?", (task_id,)).fetchone()
        if previous:
            saved_request = json.loads(previous[0])
            if saved_request.get("original_evidence_sha256") != evidence_hash:
                return {**saved_request, "status": "WAITING_MODEL", "resumable": True,
                        "attempts": [], "reason": "Evidence changed; use a new task id to preserve the original request"}
        def save():
            with closing(sqlite3.connect(self.db_path, timeout=30)) as conn, conn:
                conn.execute("INSERT OR REPLACE INTO model_router_requests VALUES(?,?,?)", (task_id, _json(request), _json(result)))
        save()
        for model in models:
            for retry in range(min(max(int(retry_limit), 0), 3) + 1):
                attempt = {"model": model, "retry": retry, "original_evidence_sha256": evidence_hash,
                           "schema_sha256": result["schema_sha256"], "started_utc": datetime.now(timezone.utc).isoformat()}
                started = time.monotonic()
                try:
                    with _gpu_mutex(self.mutex_name):
                        if _hash(original_evidence) != evidence_hash:
                            raise ValueError("original evidence changed")
                        reservation = self._reserve(model)
                        if reservation is None:
                            attempt["status"] = "QUOTA_EXHAUSTED"
                        else:
                            attempt["resource"] = {**reservation, "mutex": self.mutex_name, "pid": os.getpid()}
                            raw = invoke(model, prompt, copy.deepcopy(schema))
                            attempt["response_sha256"] = _hash(raw)
                            if _hash(original_evidence) != evidence_hash:
                                raise ValueError("original evidence changed during inference")
                            value = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x))) if isinstance(raw, str) else copy.deepcopy(raw)
                            _validate(value, schema)
                            attempt["status"] = "PASS"
                            result.update(status="PASS", value=value, model=model, resumable=False)
                except Exception as exc:
                    attempt.update(status="REJECTED", error=f"{type(exc).__name__}: {exc}")
                attempt["elapsed_seconds"] = time.monotonic() - started
                attempt["evidence_after_sha256"] = _hash(original_evidence)
                result["attempts"].append(attempt)
                with closing(sqlite3.connect(self.db_path, timeout=30)) as conn, conn:
                    conn.execute("INSERT INTO model_router_attempts(task_id,attempt_json) VALUES(?,?)", (task_id, _json(attempt)))
                save()
                if result["status"] == "PASS":
                    return result
                if attempt["evidence_after_sha256"] != evidence_hash:
                    result["reason"] = "Original evidence changed; new evidence required before resuming"
                    save()
                    return result
                if attempt["status"] == "QUOTA_EXHAUSTED":
                    break
        result["reason"] = "No local model produced schema-valid JSON within quota and retry bounds"
        save()
        return result
