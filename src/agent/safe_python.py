"""Run a tiny, data-only Python subset for research experiments.

LLM-authored code never gets filesystem, import, subprocess, socket, or process
APIs. The parser rejects every syntax form outside the documented subset, and
the child process has a hard timeout plus a Windows Job Object memory/CPU cap.
This is a constrained experiment runner, not a general-purpose Python sandbox.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any


MAX_SOURCE_BYTES = 32_000
MAX_INPUT_BYTES = 1_000_000
MAX_OUTPUT_BYTES = 64_000
DEFAULT_TIMEOUT_SECONDS = 4.0
DEFAULT_MEMORY_BYTES = 256 * 1024 * 1024

BOOTSTRAP = r'''import ast, json, sys
raw = sys.stdin.buffer.read(1_100_001)
if len(raw) > 1_000_000: raise SystemExit("input limit exceeded")
payload = json.loads(raw.decode("utf-8"))
# -I deliberately ignores PYTHON* environment variables, including
# PYTHONIOENCODING. Set the isolated child's output codec explicitly so the
# final JSON can contain Ukrainian text on Windows code pages such as cp1252.
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
source = payload["source"]
tree = ast.parse(source, mode="exec")
allowed = (ast.Module, ast.Assign, ast.Expr, ast.Name, ast.Load, ast.Store,
 ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript, ast.Slice,
 ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.If, ast.For, ast.Call,
 ast.keyword, ast.Break, ast.Continue, ast.AugAssign, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
 ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt,
 ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot)
calls = {"abs", "all", "any", "bool", "dict", "enumerate", "float", "int",
 "len", "list", "max", "min", "range", "round", "set", "sorted", "str",
 "sum", "tuple", "zip", "print"}
for node in ast.walk(tree):
    if not isinstance(node, allowed): raise SystemExit("syntax rejected: " + type(node).__name__)
    if isinstance(node, ast.Name) and (node.id.startswith("_") or node.id == "__builtins__"):
        raise SystemExit("private names are not allowed")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in calls or node.keywords:
            raise SystemExit("call rejected")
        if node.func.id == "range":
            if not 1 <= len(node.args) <= 3 or not all(isinstance(a, ast.Constant) and type(a.value) is int for a in node.args):
                raise SystemExit("range must use one to three integer constants")
            values = [a.value for a in node.args]
            count = len(range(*values))
            if count > 10000: raise SystemExit("range limit exceeded")
    if isinstance(node, (ast.Assign,)):
        if not all(isinstance(t, ast.Name) for t in node.targets): raise SystemExit("assignment target rejected")
    if isinstance(node, ast.AugAssign):
        if not isinstance(node.target, ast.Name) or type(node.op) not in {ast.Add, ast.Sub, ast.Mult}:
            raise SystemExit("augmented assignment rejected")
    if isinstance(node, ast.For):
        if not isinstance(node.target, ast.Name) or not isinstance(node.iter, ast.Call) or not isinstance(node.iter.func, ast.Name) or node.iter.func.id != "range":
            raise SystemExit("loops must be for-name in range(constant)")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        # Literal sequence repetition is permitted only with a small constant.
        if isinstance(node.left, (ast.List, ast.Tuple, ast.Constant)) and isinstance(node.right, ast.Constant) and type(node.right.value) is int and node.right.value > 10000:
            raise SystemExit("sequence repetition limit exceeded")
        if isinstance(node.right, (ast.List, ast.Tuple, ast.Constant)) and isinstance(node.left, ast.Constant) and type(node.left.value) is int and node.left.value > 10000:
            raise SystemExit("sequence repetition limit exceeded")

def limited_range(*values): return range(*values)
chunks = []
total = 0
def safe_print(*values):
    global total
    line = " ".join(str(v) for v in values) + "\n"
    total += len(line.encode("utf-8"))
    if total > 32000: raise SystemExit("printed output limit exceeded")
    chunks.append(line)
safe = {"abs":abs,"all":all,"any":any,"bool":bool,"dict":dict,"enumerate":enumerate,
 "float":float,"int":int,"len":len,"list":list,"max":max,"min":min,"range":limited_range,
 "round":round,"set":set,"sorted":sorted,"str":str,"sum":sum,"tuple":tuple,"zip":zip,"print":safe_print}
env = {"__builtins__":safe, "data":payload.get("data")}
exec(compile(tree, "<bounded-research-script>", "exec"), env, env)
result = {k:v for k,v in env.items() if k not in {"__builtins__","data"} and not k.startswith("_")}
encoded = json.dumps({"result":result,"stdout":"".join(chunks)}, ensure_ascii=False, separators=(",",":"))
if len(encoded.encode("utf-8")) > 64000: raise SystemExit("result limit exceeded")
sys.stdout.write(encoded)
'''


class ScriptRejected(ValueError):
    pass


def _static_validate(source: str) -> None:
    if not isinstance(source, str) or not source.strip():
        raise ScriptRejected("script is empty")
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ScriptRejected("script exceeds the source-size limit")
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise ScriptRejected(f"invalid Python syntax: {exc}") from exc
    # Use the same AST and call rules as the isolated child before starting it.
    allowed_names = {"abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len", "list", "max", "min", "range", "round", "set", "sorted", "str", "sum", "tuple", "zip", "print"}
    allowed_types = {
        ast.Module, ast.Assign, ast.Expr, ast.Name, ast.Load, ast.Store, ast.Constant,
        ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Subscript, ast.Slice, ast.BinOp,
        ast.UnaryOp, ast.BoolOp, ast.Compare, ast.If, ast.For, ast.Call, ast.keyword,
        ast.Break, ast.Continue, ast.AugAssign, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.UAdd, ast.USub,
        ast.Not, ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
        ast.In, ast.NotIn, ast.Is, ast.IsNot,
    }
    for node in ast.walk(tree):
        if type(node) not in allowed_types:
            raise ScriptRejected(f"syntax rejected: {type(node).__name__}")
        if isinstance(node, ast.Name) and (node.id.startswith("_") or node.id == "__builtins__"):
            raise ScriptRejected("private names are not allowed")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in allowed_names or node.keywords:
                raise ScriptRejected("only allowlisted built-in calls without keywords are permitted")
            if node.func.id == "range":
                if not 1 <= len(node.args) <= 3 or not all(isinstance(a, ast.Constant) and type(a.value) is int for a in node.args):
                    raise ScriptRejected("range must use one to three integer constants")
                if len(range(*(a.value for a in node.args))) > 10_000:
                    raise ScriptRejected("range limit exceeded")
        if isinstance(node, ast.Assign) and not all(isinstance(t, ast.Name) for t in node.targets):
            raise ScriptRejected("assignment target rejected")
        if isinstance(node, ast.AugAssign) and (not isinstance(node.target, ast.Name) or type(node.op) not in {ast.Add, ast.Sub, ast.Mult}):
            raise ScriptRejected("augmented assignment rejected")
        if isinstance(node, ast.For) and (not isinstance(node.target, ast.Name) or not isinstance(node.iter, ast.Call) or not isinstance(node.iter.func, ast.Name) or node.iter.func.id != "range"):
            raise ScriptRejected("loops must be for-name in range(constant)")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            for sequence, count in ((node.left, node.right), (node.right, node.left)):
                if isinstance(sequence, (ast.List, ast.Tuple, ast.Constant)) and isinstance(count, ast.Constant) and type(count.value) is int and count.value > 10_000:
                    raise ScriptRejected("sequence repetition limit exceeded")


def _windows_job(process: subprocess.Popen[bytes], memory_bytes: int, cpu_seconds: int):
    """Assign a process memory/CPU budget before sending it the script."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    info = ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = 0x00000100 | 0x00000002 | 0x00002000
    info.BasicLimitInformation.PerProcessUserTimeLimit = cpu_seconds * 10_000_000
    info.ProcessMemoryLimit = memory_bytes
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise OSError(error, "SetInformationJobObject failed")
    if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise OSError(error, "AssignProcessToJobObject failed; script was not started")
    return job


def run_research_script(source: str, data: Any = None, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                        memory_bytes: int = DEFAULT_MEMORY_BYTES) -> dict[str, Any]:
    """Run only the data-only subset in a fresh, bounded child process."""
    _static_validate(source)
    payload = json.dumps({"source": source, "data": data}, ensure_ascii=False, separators=(",", ":"))
    if len(payload.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ScriptRejected("input exceeds the size limit")
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ncdr-script-", dir=Path(__file__).resolve().parents[2]) as sandbox:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen([sys.executable, "-I", "-S", "-c", BOOTSTRAP], cwd=sandbox,
                                   env={"PYTHONIOENCODING": "utf-8"}, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        job = None
        try:
            job = _windows_job(process, memory_bytes, max(1, int(timeout_seconds) + 1))
            stdout, stderr = process.communicate(payload.encode("utf-8"), timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            raise TimeoutError(f"bounded research script exceeded {timeout_seconds:.1f}s")
        finally:
            if job is not None:
                import ctypes
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
                kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
                kernel32.CloseHandle(job)
        if len(stdout) > MAX_OUTPUT_BYTES:
            raise RuntimeError("bounded runner returned too much output")
        if process.returncode:
            message = stderr.decode("utf-8", "replace")[-2000:] or stdout.decode("utf-8", "replace")[-2000:]
            raise ScriptRejected(message.strip())
        try:
            result = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("bounded runner returned invalid JSON") from exc
        result["elapsed_seconds"] = round(time.monotonic() - start, 4)
        result["memory_limit_bytes"] = memory_bytes
        result["timeout_seconds"] = timeout_seconds
        return result

