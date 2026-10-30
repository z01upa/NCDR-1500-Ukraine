#!/usr/bin/env python3
"""Verify preserved NK.BIN probe evidence and original-image integrity."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_NK_SHA256 = "d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(nk: Path, root: Path) -> dict:
    probe_path = root / "evidence" / "nk_format_probe.json"
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    current_hash = sha256(nk)
    structural = probe["checks"]["ce1_ecec_free_structural_romhdr"]
    ecec = probe["checks"]["raw_ecec_candidates"]
    findings = []

    def record(name: str, ok: bool, detail: str) -> None:
        findings.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})

    record("original_sha256_unchanged", current_hash == EXPECTED_NK_SHA256,
           f"current={current_hash}; expected={EXPECTED_NK_SHA256}")
    record("probe_sha256_matches_original", probe["sha256"] == current_hash,
           f"probe={probe['sha256']}; current={current_hash}")
    record("no_validated_standard_romhdr_toc", not structural["validated_candidates"],
           f"bounded candidates={structural['bounded_header_candidates']}; validated={len(structural['validated_candidates'])}")
    resolved_ecec = any(
        (c.get("romhdr") or {}).get("bounds_valid")
        and c.get("toc", {}).get("all_first_names_printable")
        and c.get("toc", {}).get("nk_exe_seen_in_first_32")
        for e in ecec for c in e.get("romhdr_candidates", [])
    )
    record("ecec_addresses_do_not_resolve", bool(ecec) and not resolved_ecec,
           f"raw ECEC count={len(ecec)}; no candidate has a validated module TOC")
    targets = {item["name"]: item["hits"] for item in probe["target_name_strings"]}
    record("target_names_are_only_string_hits", all(len(targets.get(n, [])) == 1 for n in
           ("NavigationRem.dll", "nmicore_ce.dll")),
           "one literal hit per target; no validated TOC row or module bytes")

    outputs = []
    for name in ("extractor_parse_only", "extractor_parse_only_no_override"):
        outdir = root / "evidence" / name
        files = [str(p.relative_to(root)) for p in outdir.rglob("*") if p.is_file()] if outdir.exists() else []
        outputs.append({"directory": name, "files": files})
    record("extractor_emitted_no_module_files", all(not o["files"] for o in outputs),
           json.dumps(outputs, separators=(",", ":")))

    logs = []
    for name in ("extractor_parse_only.log", "extractor_parse_only_no_override.log"):
        path = root / "evidence" / name
        logs.append(path.read_text(encoding="utf-8", errors="replace") if path.exists() else "")
    record("parser_attempt_logs_preserved", all("EXIT_CODE=0" in s for s in logs),
           "both bounded tool invocations completed; exit code is not extraction success")
    return {
        "status": "PASS" if all(x["status"] == "PASS" for x in findings) else "FAIL",
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "original_path": str(nk.resolve()),
        "original_size": nk.stat().st_size,
        "original_sha256": current_hash,
        "checks": findings,
        "product_acceptance": {
            "nk_format_confirmed": False,
            "NavigationRem_dll_extracted": False,
            "nmicore_ce_dll_extracted": False,
            "navigation_or_routing_role_proven": False,
            "blocker": "No internally consistent ROMHDR+TOC/XIP region; filename literals are not a module table.",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("nk", type=Path)
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    result = verify(args.nk, args.root)
    out = args.root / "evidence" / "acceptance_verification.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
