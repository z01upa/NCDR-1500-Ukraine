"""Evidence-based progress scoring for the active physical-disc scope."""

from __future__ import annotations

import json
from typing import Any

from src.agent import project_scope


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _passed(checks: dict[str, Any], name: str) -> bool:
    return _object(checks.get(name)).get("pass") is True


def calculate_readiness(stage_gates: list[dict[str, Any]], *, product: dict[str, Any] | None = None,
                        writer: dict[str, Any] | None = None) -> dict[str, Any]:
    """Score only allowlisted acceptance evidence; task volume never enters the calculation."""
    scope = project_scope.load_scope()
    policy = scope["readiness_policy"]
    allowed: dict[str, list[str]] = policy["progress_criteria"]
    product = product or {}
    writer = writer or {}
    checks = _object(product.get("checks"))

    # Evidence overlays are deliberately narrow and require real saved artifacts.
    regional = writer.get("regional_roundtrips")
    writer_safe = (writer.get("status") == "PASS_COPY_ONLY" and writer.get("source_write_count") == 0
                   and writer.get("original_media_protection") == "PASS" and isinstance(regional, list)
                   and len(regional) >= 3
                   and all(_object(item.get("no_op")).get("no_op_roundtrip_pass") is True for item in regional))
    controlled = _object(writer.get("controlled_header_change"))
    source_unchanged = controlled.get("source_sha256_before") == controlled.get("source_sha256_after")
    independent = _object(writer.get("independent_readback"))
    independent_writer_readback = (
        writer_safe and independent.get("status") == "PASS"
        and independent.get("regional_source_count") == 3
        and independent.get("no_op_copies_match_manifest_sources") is True
        and independent.get("controlled_change_field_limited") is True
        and independent.get("separate_parser") is True
        and independent.get("original_media_write_count") == 0
    )
    overlays = {
        "F3": {
            "no_op_roundtrip": writer_safe,
            "controlled_change": writer_safe and controlled.get("controlled_change_pass") is True and source_unchanged,
            "independent_readback": independent_writer_readback,
        },
        "F4": {
            "dated_osm_source": _passed(checks, "versioned_osm_provenance"),
            "road_graph_tests": _passed(checks, "map_database_integrity") and
                _passed(checks, "city_search_and_connected_route"),
        },
        "F5": {"ukrainian_names_test": _passed(checks, "city_search_and_connected_route")},
    }
    rows = {str(row.get("stage")): row for row in stage_gates}
    gate_scores: dict[str, dict[str, int]] = {}
    for stage, keys in allowed.items():
        row = rows.get(stage, {})
        criteria = _object(row.get("criteria_json", row.get("criteria", {})))
        proof = _object(row.get("proof_json", row.get("proof", {})))
        proved = _object(proof.get("criteria_pass"))
        stage_earned = stage_total = 0
        for key in keys:
            weight = int(criteria.get(key, 0))
            if weight <= 0:
                continue
            stage_total += weight
            is_proved = proved.get(key) is True or overlays.get(stage, {}).get(key) is True
            if is_proved:
                stage_earned += weight
        gate_scores[stage] = {"earned": stage_earned, "total": stage_total}

    earned = sum(row["earned"] for row in gate_scores.values())
    total = sum(row["total"] for row in gate_scores.values())
    components: dict[str, dict[str, int]] = {}
    for name, refs in policy["progress_components"].items():
        component_earned = component_total = 0
        for ref in refs:
            stage, _, criterion = ref.partition(":")
            criterion_weight = int(_object(rows.get(stage, {}).get("criteria_json",
                rows.get(stage, {}).get("criteria", {}))).get(criterion, 0))
            # Components contain only the same allowlisted criteria as the overall score.
            if criterion not in allowed.get(stage, []):
                continue
            component_total += criterion_weight
            row = rows.get(stage, {})
            proof = _object(_object(row.get("proof_json", row.get("proof", {}))).get("criteria_pass"))
            is_proved = proof.get(criterion) is True or overlays.get(stage, {}).get(criterion) is True
            if is_proved:
                component_earned += criterion_weight
        components[name] = {"earned": component_earned, "total": component_total,
            "percent": int(100 * component_earned / component_total + 0.5) if component_total else 0}

    f1 = gate_scores.get("F1", {}).get("total", 0)
    f9_criteria = _object(rows.get("F9", {}).get("criteria_json", rows.get("F9", {}).get("criteria", {})))
    unverified_hardware = f1 + int(f9_criteria.get("hardware_acceptance", 0))
    return {"earned": earned, "total": total,
        "percent": int(100 * earned / total + 0.5) if total else 0,
        "gates": gate_scores, "components": components,
        "hardware_unverified_points": unverified_hardware,
        "physical_compatibility": "NOT_TESTED"}
