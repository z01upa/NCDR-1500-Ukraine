"""Deterministic failure classification used by the autonomous worker."""

from __future__ import annotations

import json
import re
from typing import Any


FAILURE_CLASSES = {
    "OOM", "TIMEOUT", "DATA", "TOOL_MISSING", "TEST_FAILURE",
    "EXTERNAL_DEPENDENCY", "CODEX_RATE_LIMIT", "CODE_DEFECT", "UNKNOWN", "WAITING_EXTERNAL",
}


_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("TEST_FAILURE", ("scriptrejected", "script field rejected", "script-field rejected",
                      "script field is missing or too large")),
    ("CODE_DEFECT", ("nameerror", "keyerror")),
    ("CODEX_RATE_LIMIT", ("rate limit", "quota exceeded", "usage limit", "too many requests", "429")),
    ("OOM", ("out of memory", "memoryerror", "cannot allocate memory", "not enough memory", "oom")),
    ("TIMEOUT", ("timed out", "timeout", "time limit", "перевищила ліміт", "перевищено ліміт")),
    ("TOOL_MISSING", ("no module named", "command not found", "not recognized as an internal", "tool_missing", "unrecognized handler", "no allowlisted handler")),
    ("TEST_FAILURE", ("assertionerror", "test failed", "tests failed", "verification failed", "acceptance test")),
    ("EXTERNAL_DEPENDENCY", ("hardware unavailable", "device not connected", "vehicle acceptance", "waiting_external", "physical compatibility")),
    ("DATA", ("parseerror", "badgzipfile", "invalid data", "corrupt input", "unexpected eof", "malformed")),
)


def classify_failure(error: str, *, hint: str | None = None,
                     next_action: str = "", dependencies: list[str] | None = None,
                     dependency_statuses: dict[str, str | None] | None = None,
                     task_id: str | None = None) -> dict[str, Any]:
    """Classify a saved failure by deterministic rules, preserving its source text."""
    text = str(error or "")[:20_000]
    normalized = text.casefold()
    if not normalized.strip():
        category, matched = "WAITING_EXTERNAL", ["blank saved diagnostics"]
    elif ("osm" in normalized and "stale" in normalized
          and any(marker in normalized for marker in ("continuation", "checkpoint"))):
        category, matched = "DATA", ["stale OSM continuation/checkpoint"]
    elif (re.search(r"script[\s_-]+field", normalized)
          and any(marker in normalized for marker in ("rejected", "missing", "too large"))):
        category, matched = "TEST_FAILURE", ["rejected script field payload"]
    elif hint and hint in FAILURE_CLASSES:
        category, matched = hint, ["explicit deterministic hint"]
    else:
        category, matched = "UNKNOWN", []
        for candidate, markers in _RULES:
            found = [marker for marker in markers if marker in normalized]
            if found:
                category, matched = candidate, found
                break
    action = {
        "OOM": "reduce peak-memory path or stream data; resume only from a verified checkpoint",
        "TIMEOUT": "inspect the timed operation and checkpoint; split only if the operation is resumable",
        "DATA": "verify source provenance and parser diagnostics before changing or retrying data work",
        "TOOL_MISSING": "create a scoped capability request; do not substitute an unverified tool",
        "TEST_FAILURE": "preserve the failing result, create a repair task, and rerun independent acceptance",
        "EXTERNAL_DEPENDENCY": "set WAITING_EXTERNAL and continue independent software work",
        "CODEX_RATE_LIMIT": "set WAITING_CODEX_QUOTA, persist the rate-limit cooldown, and continue independent local work without retries",
        "CODE_DEFECT": "create a bounded repair task with the saved reproducer and acceptance test",
        "UNKNOWN": "preserve evidence and request deterministic diagnosis before retry",
        "WAITING_EXTERNAL": "obtain logs or saved diagnostic evidence; continue independent software work",
    }[category]
    evidence = None
    if not normalized.strip():
        action_text = str(next_action or "")
        action_normalized = action_text.casefold()
        statuses = dependency_statuses or {}
        deps = dependencies or []
        unresolved = [dep for dep in deps if statuses.get(dep) not in (None, "DONE")]
        physical = bool(re.search(
            r"(?:obtain|require[sd]?|test only|wait(?:ing)? for).*"
            r"(?:matching hardware|head[- ]unit|faceplate|vehicle|physical .*evidence)",
            action_normalized))
        prerequisite = action_normalized.startswith("resume after ") and any(
            re.search(r"\b" + re.escape(dep.split("_")[0].casefold()) + r"\b", action_normalized)
            or ("proven writer target" in action_normalized and "WRITER" in dep.upper())
            for dep in unresolved)
        if physical or prerequisite:
            category = "EXTERNAL_DEPENDENCY"
            matched = ["saved next_action: physical evidence required" if physical
                       else "saved next_action: unresolved prerequisite"]
            action = "set WAITING_EXTERNAL and continue independent software work"
            evidence = {"source": "tasks", "task_id": task_id,
                "next_action": action_text, "dependencies": deps,
                "dependency_statuses": {dep: statuses.get(dep) for dep in deps},
                "unresolved_dependencies": unresolved,
                "source_fields": ["tasks.next_action", "tasks.depends_on_json", "tasks.status"]}
    result = {"class": category, "matched_rules": matched, "recommended_action": action,
            "error_excerpt": text[:2000], "retry_requires_new_evidence": True}
    if not normalized.strip() or category == "EXTERNAL_DEPENDENCY":
        result["status"] = "WAITING_EXTERNAL"
    if evidence is not None:
        result["classification_evidence"] = evidence
    return result


def classify_blocked_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a compact diagnostic view for blocked runtime tasks."""
    result = []
    statuses = {row.get("id"): row.get("status") for row in rows}
    for row in rows:
        saved = row.get("result", {})
        if "result_json" in row:
            try:
                saved = json.loads(row["result_json"] or "{}")
            except (TypeError, ValueError):
                saved = {}
        error = row.get("error") or (saved.get("error", "") if isinstance(saved, dict) else "")
        dependencies = row.get("depends_on", [])
        if "depends_on_json" in row:
            try:
                dependencies = json.loads(row["depends_on_json"] or "[]")
            except (TypeError, ValueError):
                dependencies = []
        if not isinstance(dependencies, list) or not all(isinstance(dep, str) for dep in dependencies):
            dependencies = []
        failure = classify_failure(str(error or ""), next_action=row.get("next_action", ""),
            dependencies=dependencies, dependency_statuses=row.get("dependency_statuses", statuses),
            task_id=row.get("id"))
        result.append({"task_id": row.get("id"), "failure": failure,
                       "status": failure.get("status", row.get("status", "BLOCKED"))})
    return result
