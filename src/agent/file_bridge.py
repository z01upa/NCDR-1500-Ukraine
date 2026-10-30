"""Bounded JSON task/result files backed by a durable SQLite intent journal.

Only complete, fsynced files become visible. Journal commits precede publication,
so reopening the bridge repairs an interrupted publication without overwriting
another writer's record.
"""

from contextlib import closing
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile


MAX_BYTES = 64 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def _safe_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value) or value.upper() in _RESERVED:
        raise ValueError("unsafe task ID")
    return value


def _safe_path(value):
    path = Path(os.path.abspath(value))
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("bridge paths must not contain links or junctions")
    return path


def _tree(value, depth=0):
    if depth > 12:
        raise ValueError("JSON nesting exceeds limit")
    if value is None or type(value) in (bool, int):
        if type(value) is int and value.bit_length() > 63:
            raise ValueError("integer exceeds limit")
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite number")
    elif type(value) is str:
        if len(value) > 8192:
            raise ValueError("string exceeds limit")
    elif type(value) in (dict, list):
        if len(value) > 256:
            raise ValueError("container exceeds limit")
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str or not key or len(key) > 128:
                    raise ValueError("invalid JSON key")
                _tree(item, depth + 1)
        else:
            for item in value:
                _tree(item, depth + 1)
    else:
        raise ValueError("unsupported JSON value")


def _encode(kind, value):
    key = "id" if kind == "TASKS" else "task_id"
    fields = {key, "schema_version", "payload", "objective" if kind == "TASKS" else "status"}
    if type(value) is not dict or set(value) != fields:
        raise ValueError("invalid bridge schema fields")
    _safe_id(value[key])
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("unsupported schema version")
    if type(value["payload"]) is not dict:
        raise ValueError("payload must be an object")
    if kind == "TASKS":
        objective = value["objective"]
        if type(objective) is not str or not objective.strip() or len(objective) > 4096:
            raise ValueError("invalid objective")
    elif type(value["status"]) is not str or value["status"] not in {"PASS", "FAIL", "ERROR", "BLOCKED"}:
        raise ValueError("invalid result status")
    _tree(value)
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid JSON encoding") from exc
    if len(data) > MAX_BYTES:
        raise ValueError("record exceeds byte limit")
    return value[key], data


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _decode(kind, data):
    if len(data) > MAX_BYTES:
        raise ValueError("record exceeds byte limit")
    try:
        value = json.loads(data, object_pairs_hook=_pairs)
        _encode(kind, value)
        return value
    except (UnicodeError, RecursionError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid bridge JSON") from exc


def _sync_directory(directory):
    if os.name != "nt":
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class FileTaskBridge:
    def __init__(self, root, db_path):
        self.root = _safe_path(root)
        self.db_path = _safe_path(db_path)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        for kind in ("TASKS", "RESULTS"):
            _safe_path(self.root / kind).mkdir(exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("CREATE TABLE IF NOT EXISTS bridge_journal ("
                         "kind TEXT NOT NULL, id TEXT COLLATE NOCASE NOT NULL, document BLOB NOT NULL, "
                         "PRIMARY KEY(kind,id))")
        self.recover()

    def _connect(self):
        _safe_path(self.db_path)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _path(self, kind, identifier):
        return _safe_path(self.root / kind / (_safe_id(identifier) + ".json"))

    def _read(self, kind, identifier):
        target = self._path(kind, identifier)
        try:
            with target.open("rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("record must be a regular file")
                value = _decode(kind, stream.read(MAX_BYTES + 1))
        except FileNotFoundError:
            return None
        if value["id" if kind == "TASKS" else "task_id"] != identifier:
            raise ValueError("record ID does not match its path")
        return value

    def _publish(self, kind, identifier, data):
        target = self._path(kind, identifier)
        fd, name = tempfile.mkstemp(prefix=".bridge-", suffix=".tmp", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                if os.name == "nt":
                    # Windows rename is atomic and fails if the destination exists.
                    # Unlike os.link, it needs no hard-link support or privilege.
                    os.rename(temporary, target)
                else:
                    # POSIX rename overwrites. link provides atomic no-clobber creation.
                    os.link(temporary, target)
            except OSError:
                existing = self._read(kind, identifier)
                if existing is None:
                    raise
                if _encode(kind, existing)[1] != data:
                    raise ValueError("conflicting published record")
            _sync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _put(self, kind, value):
        identifier, data = _encode(kind, value)
        self._path(kind, identifier)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT id,document FROM bridge_journal WHERE kind=? AND id=?",
                               (kind, identifier)).fetchone()
            if row and (row[0] != identifier or bytes(row[1]) != data):
                raise ValueError("conflicting journal record")
            existing = self._read(kind, identifier)
            if existing is not None and _encode(kind, existing)[1] != data:
                raise ValueError("conflicting published record")
            if not row:
                conn.execute("INSERT INTO bridge_journal VALUES (?,?,?)", (kind, identifier, data))
            created = row is None and existing is None
        self._publish(kind, identifier, data)
        return created

    def recover(self):
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT kind,id,document FROM bridge_journal ORDER BY kind,id").fetchall()
        for kind, identifier, data in rows:
            if kind not in {"TASKS", "RESULTS"}:
                raise ValueError("invalid journal kind")
            value = _decode(kind, bytes(data))
            if _encode(kind, value) != (identifier, bytes(data)):
                raise ValueError("invalid journal record")
            self._publish(kind, identifier, bytes(data))
        return len(rows)

    def enqueue_task(self, task):
        return self._put("TASKS", task)

    def publish_result(self, result):
        return self._put("RESULTS", result)

    def read_task(self, task_id):
        return self._read("TASKS", task_id)

    def read_result(self, task_id):
        return self._read("RESULTS", task_id)

    def _count(self, kind):
        with closing(self._connect()) as conn:
            return conn.execute("SELECT count(*) FROM bridge_journal WHERE kind=?", (kind,)).fetchone()[0]

    def outbox_count(self):
        return self._count("TASKS")

    def inbox_count(self):
        return self._count("RESULTS")
