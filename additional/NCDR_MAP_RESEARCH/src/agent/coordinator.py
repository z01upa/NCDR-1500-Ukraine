"""Bounded, resumable coordinator for deterministic NCDR research tasks."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import state_store
from src.agent.resource_probe import resource_snapshot


def _run(command: list[str], timeout: int = 180) -> dict[str, Any]:
    result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout)
    return {"returncode": result.returncode, "stdout": result.stdout[-8000:], "stderr": result.stderr[-8000:]}


def _runner_entrypoint() -> dict[str, Any]:
    powershell = "powershell.exe"
    command = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PROJECT_ROOT / "tests" / "integration" / "test_entrypoint.ps1")]
    test_result = _run(command, timeout=60)
    if test_result["returncode"]:
        raise RuntimeError(f"entrypoint test failed: {test_result['stderr'] or test_result['stdout']}")
    resources = resource_snapshot()
    with sqlite3.connect(state_store.STATE_DB) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"project state database integrity_check={integrity!r}")
    return {"entrypoint_test": test_result, "resource_snapshot": resources, "state_integrity": integrity}


def _model_benchmark() -> dict[str, Any]:
    report_path = PROJECT_ROOT / "reports" / "model_benchmark.json"
    report: dict[str, Any] | None = None
    if report_path.exists():
        candidate = json.loads(report_path.read_text(encoding="utf-8"))
        if candidate.get("benchmark_version") == 2 and candidate.get("status") == "COMPLETE" and len(candidate.get("models", [])) >= 3 and all(
            row.get("status") == "COMPLETE" and row.get("task_count") == 18 for row in candidate["models"]
        ):
            report = candidate
    if report is None:
        from src.agent.benchmark_runner import run_benchmark

        report = run_benchmark()
    state_store.record_model_runs(report)
    if report.get("status") != "COMPLETE" or not report.get("recommended_model"):
        raise RuntimeError("model benchmark did not complete for every installed candidate; inspect reports/model_benchmark.json")
    return {
        "benchmark_status": report["status"],
        "recommended_model": report["recommended_model"],
        "models": [{key: row.get(key) for key in ("model", "status", "passed", "task_count", "duration_seconds", "verified_results_per_minute", "peak_vram_used_mib")} for row in report["models"]],
        "report": str(report_path.relative_to(PROJECT_ROOT)),
    }


def _mp0_tests() -> dict[str, Any]:
    result = _run([sys.executable, "-m", "unittest", "discover", "-s", "tests/unit", "-p", "test_*.py", "-v"], timeout=180)
    if result["returncode"]:
        raise RuntimeError(f"unit tests failed: {result['stderr'] or result['stdout']}")
    return {"unit_tests": result, "golden_files": ["EUZ.MP0", "IZ.MP0", "SCZ.MP0"]}


def _regional_diff() -> dict[str, Any]:
    path = PROJECT_ROOT / "inventory" / "region_cross_diff.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    expected = {"matched_normalized_paths": 113, "same_sha256_count": 78, "different_sha256_count": 35}
    observed = {key: result.get(key) for key in expected}
    if observed != expected or result.get("italy_only_count") != 0 or result.get("scandinavia_only_count") != 0:
        raise RuntimeError(f"regional inventory totals changed: {observed}")
    return {"regional_comparison": observed, "italy_only": 0, "scandinavia_only": 0, "claim_scope": "path/hash difference only; no semantic equivalence inferred"}


HANDLERS: dict[str, Callable[[], dict[str, Any]]] = {
    "F0_RUNNER_ENTRYPOINT": _runner_entrypoint,
    "F0_MODEL_BENCHMARK": _model_benchmark,
    "F2_MP0_HEADER_READER": _mp0_tests,
    "F2_REGIONAL_DIFF": _regional_diff,
}


def update_gates() -> None:
    summary = state_store.status_summary()
    counts = summary["task_counts"]
    done = lambda task_id: _task_status(task_id) == "DONE"
    inventory = json.loads((PROJECT_ROOT / "inventory" / "hash_verification.json").read_text(encoding="utf-8"))
    benchmark = PROJECT_ROOT / "reports" / "model_benchmark.json"
    bench_complete = False
    if benchmark.exists():
        report = json.loads(benchmark.read_text(encoding="utf-8"))
        bench_complete = report.get("status") == "COMPLETE" and bool(report.get("recommended_model"))
    f0 = {
        "hash_manifest": bool(inventory.get("complete") and inventory.get("files_expected") == 5600 and inventory.get("files_failed") == 0),
        "previous_results_review": (PROJECT_ROOT / "reports" / "COMPATIBILITY_MATRIX.md").exists() and (PROJECT_ROOT / "reports" / "AUDIT_REPORT.md").exists(),
        "local_model_check": bench_complete,
        "portable_entrypoint": done("F0_RUNNER_ENTRYPOINT"),
        "runnable_healthcheck": done("F0_RUNNER_ENTRYPOINT"),
    }
    state_store.update_stage_gate("F0", "COMPLETE" if all(f0.values()) else "IN_PROGRESS", {"criteria_pass": f0, "task_counts": counts})

    f2 = {
        "header_reader": done("F2_MP0_HEADER_READER"),
        "independent_disc_golden_tests": done("F2_MP0_HEADER_READER"),
        "unknowns_documented": (PROJECT_ROOT / "reports" / "FORMAT_UNKNOWN.md").exists(),
        "corruption_detection": done("F2_MP0_HEADER_READER"),
        "semantic_records": False,
    }
    state_store.update_stage_gate("F2", "IN_PROGRESS", {"criteria_pass": f2, "note": "MP0 payload records are still undecoded."})


def _task_status(task_id: str) -> str | None:
    with sqlite3.connect(state_store.STATE_DB) as conn:
        row = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
    return row[0] if row else None


def run(max_tasks: int = 4, owner: str = "ncdr-coordinator") -> dict[str, Any]:
    if not 1 <= max_tasks <= 10:
        raise ValueError("max_tasks must be between 1 and 10")
    update_gates()
    completed: list[dict[str, Any]] = []
    for _ in range(max_tasks):
        task = state_store.claim_next(owner, lease_seconds=1800)
        if not task:
            break
        task_id = task["id"]
        handler = HANDLERS.get(task_id)
        if handler is None:
            reason = f"No allowlisted handler for task {task_id}"
            state_store.fail_task(task_id, task["lease_id"], reason)
            completed.append({"task_id": task_id, "status": "BLOCKED", "reason": reason})
            break
        try:
            result = handler()
            state_store.complete_task(task_id, task["lease_id"], result)
            completed.append({"task_id": task_id, "status": "DONE", "result": result})
            update_gates()
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            status = state_store.fail_task(task_id, task["lease_id"], reason)
            completed.append({"task_id": task_id, "status": status, "reason": reason})
            update_gates()
            break
    final_status = state_store.status_summary()
    return {"completed_this_run": completed, "status": final_status, "next_action": _next_action(final_status)}


def _next_action(summary: dict[str, Any]) -> str:
    counts = summary.get("task_counts", {})
    if counts.get("PENDING", 0):
        return "Resume the bounded queue with python -m src.agent.coordinator --max-tasks 4."
    if counts.get("BLOCKED", 0):
        return "Resolve an explicitly documented blocker, then requeue only the affected task."
    return "No currently eligible automated task remains; inspect the F1 hardware gate before disc work."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a bounded slice of the resumable local NCDR task queue.")
    parser.add_argument("--max-tasks", type=int, default=4, help="maximum eligible tasks for this run (1..10)")
    parser.add_argument("--owner", default="ncdr-coordinator", help="lease owner label")
    args = parser.parse_args(argv)
    print(json.dumps(run(args.max_tasks, args.owner), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
