from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any

try:
    from .resource_probe import resource_snapshot
except ImportError:  # allow direct execution as a script
    from resource_probe import resource_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TASKS_PATH = PROJECT_ROOT / "src" / "agent" / "benchmark_tasks.json"
REPORT_PATH = PROJECT_ROOT / "reports" / "model_benchmark.json"
API_BASE = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
MODELS = (
    "qwen3.5:4b",
    "qwen2.5-coder:7b",
    "qwen3.5:9b",
    "hf.co/empero-ai/Qwythos-9B-v2-GGUF:Q4_K_M",
)
BENCHMARK_VERSION = 3
SAFE_AST_NODES = {
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.If,
    ast.Compare, ast.NotEq, ast.Eq, ast.Lt, ast.Gt, ast.Call, ast.Name, ast.Load, ast.Constant,
    ast.Raise, ast.Attribute, ast.Subscript, ast.Slice, ast.BinOp, ast.Add,
}


def api_json(path: str, payload: dict[str, Any] | None = None, timeout: int = 120) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        API_BASE + path,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def gpu_line() -> dict[str, Any] | None:
    return resource_snapshot().get("gpu")


class ResourceSampler:
    def __init__(self, interval_s: float = 1.0) -> None:
        self.interval_s = interval_s
        self.samples: list[dict[str, Any]] = []
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self.stop_event.is_set():
            snap = resource_snapshot()
            snap["sampled_monotonic"] = time.monotonic()
            self.samples.append(snap)
            self.stop_event.wait(self.interval_s)

    def __enter__(self) -> "ResourceSampler":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)


def _normalized(value: Any) -> str:
    return " ".join(str(value).casefold().split())


def _safe_generated_function(code: str, function_name: str, test_inputs: list[bytes], expected: list[Any]) -> bool:
    if len(code) > 4000:
        return False
    cleaned = code.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        tree = ast.parse(cleaned, mode="exec")
    except SyntaxError:
        return False
    if len(list(ast.walk(tree))) > 160 or not tree.body or any(type(node) not in SAFE_AST_NODES for node in ast.walk(tree)):
        return False
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(functions) != 1 or functions[0].name != function_name:
        return False
    allowed_names = {function_name, "data", "len", "ValueError", "int", "bytes"}
    if any(isinstance(node, ast.Name) and node.id not in allowed_names for node in ast.walk(tree)):
        return False
    allowed_attributes = {"from_bytes", "split", "decode"}
    if any(isinstance(node, ast.Attribute) and node.attr not in allowed_attributes for node in ast.walk(tree)):
        return False
    namespace = {"__builtins__": {"len": len, "ValueError": ValueError, "int": int, "bytes": bytes}}
    try:
        exec(compile(tree, "<bounded-model-code>", "exec"), namespace, namespace)
        func = namespace[function_name]
        for sample, answer in zip(test_inputs, expected):
            actual = func(sample)
            if isinstance(answer, tuple) and answer[0] == "raises":
                if not isinstance(actual, Exception):
                    return False
            elif actual != answer:
                return False
    except ValueError:
        return False
    except Exception:
        # A direct ValueError test is performed separately below, so normal inputs must not throw.
        return False
    return True


def _code_u24_pass(value: dict[str, Any]) -> bool:
    code = value.get("code", "")
    if not _safe_generated_function("\n".join([code]), "read_u24_be", [b"\x00\x00\x02", b"\xff\xff\xff"], [2, 16_777_215]):
        return False
    cleaned = code.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    namespace = {"__builtins__": {"len": len, "ValueError": ValueError, "int": int, "bytes": bytes}}
    exec(compile(ast.parse(cleaned), "<bounded-model-code>", "exec"), namespace, namespace)
    try:
        namespace["read_u24_be"](b"\x00\x02")
    except ValueError:
        return True
    except Exception:
        return False
    return False


def _code_mp0_pass(value: dict[str, Any]) -> bool:
    code = value.get("code", "")
    # Only simple bytes slicing, NUL splitting and ASCII decoding are allowed by the AST gate.
    sample = bytearray(80)
    sample[48:64] = b"EU44420940.82\0\0\0"
    it_sample = bytearray(80)
    it_sample[48:64] = b"I44431940.82\0\0\0\0"
    if not _safe_generated_function(code, "parse_mp0_dataset_code", [bytes(sample), bytes(it_sample)], ["EU44420940.82", "I44431940.82"]):
        return False
    cleaned = code.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    namespace = {"__builtins__": {"len": len, "ValueError": ValueError, "int": int, "bytes": bytes}}
    exec(compile(ast.parse(cleaned), "<bounded-model-code>", "exec"), namespace, namespace)
    try:
        namespace["parse_mp0_dataset_code"](b"short")
    except ValueError:
        return True
    except Exception:
        return False
    return False


def score_task(task: dict[str, Any], value: dict[str, Any]) -> tuple[bool, str]:
    kind = task["kind"]
    if kind == "exact":
        return _normalized(value.get(task.get("field", "answer"), "")) == _normalized(task["expected"]), "exact answer"
    if kind == "contains":
        candidate = _normalized(value.get(task.get("field", "answer"), ""))
        missing = [term for term in task["must_contain"] if _normalized(term) not in candidate]
        return not missing, "missing: " + ", ".join(missing)
    if kind == "fields":
        actual = {key: value.get(key) for key in task["fields"]}
        return actual == task["fields"], f"expected {task['fields']}; got {actual}"
    if kind == "code_u24":
        passed = _code_u24_pass(value)
        return passed, "code passed or failed bounded byte tests"
    if kind == "code_mp0":
        passed = _code_mp0_pass(value)
        return passed, "code passed or failed bounded header tests"
    if kind == "hypothesis":
        required = ("hypothesis", "file_offset", "test", "falsifier")
        valid = all(isinstance(value.get(key), str) and value[key].strip() for key in required)
        valid = valid and value.get("file_offset") in {"0x00", "0x30"}
        return valid, "complete falsifiable hypothesis structure required"
    raise ValueError(f"unknown task kind: {kind}")


def _model_metadata(tags: dict[str, Any]) -> list[dict[str, Any]]:
    by_name = {row.get("name", row.get("model")): row for row in tags.get("models", [])}
    return [by_name[name] for name in MODELS if name in by_name]


def _unload(model: str) -> str:
    try:
        api_json("/api/generate", {"model": model, "prompt": "", "stream": False, "keep_alive": 0, "options": {"num_predict": 1}}, timeout=30)
    except Exception as exc:
        return f"unload request failed: {type(exc).__name__}: {exc}"
    return "unload requested"


def run_benchmark() -> dict[str, Any]:
    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    tags = api_json("/api/tags", timeout=10)
    model_metadata = _model_metadata(tags)
    installed = {row.get("name", row.get("model")) for row in model_metadata}
    missing = [model for model in MODELS if model not in installed]
    results: list[dict[str, Any]] = []
    for model in MODELS:
        if model not in installed:
            results.append({"model": model, "status": "NOT_INSTALLED", "tasks": []})
            continue
        task_results: list[dict[str, Any]] = []
        model_started = time.monotonic()
        baseline = resource_snapshot()
        sampler = ResourceSampler(interval_s=1.0)
        sampler.__enter__()
        ps_before = ""
        ps_after = ""
        try:
            try:
                ps_before = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10).stdout
            except Exception:
                ps_before = "unavailable"
            for task in tasks:
                if time.monotonic() - model_started > 360:
                    task_results.append({"task_id": task["id"], "status": "SKIPPED_BUDGET", "pass": False})
                    continue
                prompt = task["prompt"] + "\nReturn exactly one JSON object and no prose."
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a local NCDR binary-format analysis worker. Use only evidence supplied in the task. Do not invent format semantics. Return valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "format": "json",
                    "think": False,
                    "stream": False,
                    "keep_alive": "30s",
                    "options": {"num_ctx": 4096, "num_predict": 192, "temperature": 0, "top_p": 1},
                }
                started = time.monotonic()
                try:
                    response = api_json("/api/chat", payload, timeout=90)
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    content = response.get("message", {}).get("content", "")
                    value = json.loads(content)
                    passed, score_detail = score_task(task, value)
                    tokens = int(response.get("eval_count") or 0)
                    eval_ns = int(response.get("eval_duration") or 0)
                    task_results.append({
                        "task_id": task["id"], "status": "PASS" if passed else "FAIL", "pass": passed,
                        "score_detail": score_detail, "wall_ms": elapsed_ms,
                        "prompt_tokens": response.get("prompt_eval_count"), "output_tokens": tokens,
                        "tokens_per_second": tokens / (eval_ns / 1e9) if eval_ns else None,
                        "load_duration_ns": response.get("load_duration"), "total_duration_ns": response.get("total_duration"),
                        "result": value,
                    })
                except Exception as exc:
                    elapsed_ms = int((time.monotonic() - started) * 1000)
                    task_results.append({"task_id": task["id"], "status": "ERROR", "pass": False, "wall_ms": elapsed_ms,
                                         "error": f"{type(exc).__name__}: {exc}"})
            try:
                ps_after = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10).stdout
            except Exception:
                ps_after = "unavailable"
        finally:
            sampler.__exit__()
            unload_message = _unload(model)
        duration_s = time.monotonic() - model_started
        passed_count = sum(bool(row.get("pass")) for row in task_results)
        gpu_samples = [sample["gpu"] for sample in sampler.samples if sample.get("gpu")]
        ram_samples = [sample["ram"] for sample in sampler.samples if sample.get("ram")]
        peak_vram_mib = max([row["memory_used_mib"] for row in gpu_samples], default=None)
        peak_ram_used_bytes = max([row["used_bytes"] for row in ram_samples], default=None)
        results.append({
            "model": model, "status": "COMPLETE" if len(task_results) == len(tasks) else "PARTIAL",
            "task_count": len(tasks), "passed": passed_count, "failed_or_error": len(tasks) - passed_count,
            "useful_artifacts": passed_count, "duration_seconds": round(duration_s, 3),
            "verified_results_per_minute": round(passed_count / (duration_s / 60), 4) if duration_s else 0,
            "baseline_resources": baseline, "peak_vram_used_mib": peak_vram_mib,
            "peak_host_ram_used_bytes": peak_ram_used_bytes, "ollama_ps_before": ps_before,
            "ollama_ps_during_or_after_load": ps_after, "unload": unload_message,
            "tasks": task_results,
        })
    complete = [row for row in results if row.get("status") == "COMPLETE"]
    winner = max(complete, key=lambda row: (row.get("verified_results_per_minute", 0), row.get("passed", 0))) if complete else None
    report = {
        "benchmark_version": BENCHMARK_VERSION,
        "status": "COMPLETE" if len(complete) == len([m for m in MODELS if m in installed]) else "PARTIAL",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "api_base": API_BASE,
        "context_tokens": 4096,
        "models_in_order": list(MODELS),
        "model_metadata": model_metadata,
        "missing_models": missing,
        "task_set_count": len(tasks),
        "selection_rule": "Maximize automatically verified NCDR tasks per minute; report incomplete runs separately.",
        "recommended_model": winner["model"] if winner else None,
        "models": results,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run_benchmark()
    print(json.dumps({
        "status": report["status"],
        "recommended_model": report["recommended_model"],
        "models": [{key: row.get(key) for key in ("model", "status", "task_count", "passed", "failed_or_error", "duration_seconds", "verified_results_per_minute", "peak_vram_used_mib")} for row in report["models"]],
        "report": str(REPORT_PATH),
    }, indent=2, ensure_ascii=False))
