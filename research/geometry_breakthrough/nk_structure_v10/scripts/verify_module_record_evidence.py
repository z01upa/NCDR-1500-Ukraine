#!/usr/bin/env python3
"""Independent assertions over the real LK841 module-name byte evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def all_offsets(data: bytes, needle: bytes) -> list[int]:
    result = []
    pos = 0
    while True:
        pos = data.find(needle, pos)
        if pos < 0:
            return result
        result.append(pos)
        pos += 1


def verify(nk_path: Path, manifest_path: Path) -> dict:
    data = nk_path.read_bytes()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest["module_name_cluster_candidate"]["entries"]
    sha = hashlib.sha256(data).hexdigest()
    rows, failures = [], []

    for index, entry in enumerate(entries):
        name = entry["name"].encode("ascii")
        off = entry["offset"]
        if data[off:off + len(name) + 1] != name + b"\0":
            failures.append(f"name mismatch at manifest index {index}")
            continue
        after_nul = off + len(name) + 1
        marker = data.find(b"CE", after_nul, min(len(data), after_nul + 17))
        if marker < 0 or marker + 16 > len(data):
            continue
        number = struct.unpack_from("<H", data, marker + 2)[0]
        address, word8, word12 = struct.unpack_from("<III", data, marker + 4)
        occurrences = all_offsets(data, struct.pack("<I", address))
        external = [p for p in occurrences if p != marker + 4]
        rows.append({"index": index, "name": entry["name"], "name_offset": off,
                     "marker_offset": marker, "marker_distance_after_nul": marker - after_nul,
                     "record_hex": data[marker:marker + 16].hex(" "),
                     "u16_plus_2": number, "u32_plus_4": address,
                     "u32_plus_8": word8, "u32_plus_12": word12,
                     "secondary_offsets": external})

    values = [r["u32_plus_4"] for r in rows]
    dist = Counter(len(r["secondary_offsets"]) for r in rows)
    checks = {
        "74_of_74_names_match": len(entries) == 74 and not failures,
        "48_CE_record_candidates": len(rows) == 48,
        "all_48_plus4_aligned_kernel_VAs": len(values) == 48 and all(
            (v & 3) == 0 and 0x80000000 <= v < 0xC0000000 for v in values),
        "plus4_values_unique": len(set(values)) == len(values),
        "strictly_increasing_all_47_transitions": len(values) == 48 and all(
            a < b for a, b in zip(values, values[1:])),
        "46_one_secondary_and_2_no_secondary": dist == Counter({1: 46, 0: 2}),
        "heldout_indexes_37_73_validate_26_of_26": len([r for r in rows if r["index"] >= 37]) == 26
            and all(0x80000000 <= r["u32_plus_4"] < 0xC0000000
                    and (r["u32_plus_4"] & 3) == 0
                    and len(r["secondary_offsets"]) == 1
                    for r in rows if r["index"] >= 37)
            and all(a["u32_plus_4"] < b["u32_plus_4"] for a, b in zip(
                [r for r in rows if r["index"] >= 37],
                [r for r in rows if r["index"] >= 38])),
        "both_target_names_present": {"NavigationRem.dll", "nmicore_ce.dll"}.issubset(
            {r["name"] for r in rows}),
    }
    for key, passed in checks.items():
        if not passed:
            failures.append(key)
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(nk_path.resolve()), "size": len(data), "sha256": sha,
        "manifest": str(manifest_path.resolve()), "manifest_count": len(entries),
        "candidate_count": len(rows), "secondary_reference_distribution": dict(dist),
        "checks": {k: bool(v) for k, v in checks.items()},
        "status": "PASS" if not failures else "FAIL", "failures": failures,
        "rows": rows,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[4]
    parser = argparse.ArgumentParser()
    parser.add_argument("nk", type=Path)
    parser.add_argument("--manifest", type=Path, default=root /
                        "research/geometry_breakthrough/routing_owner_v8/evidence/nk_targeted_inspection.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.nk, args.manifest)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "status", "sha256", "manifest_count", "candidate_count",
        "secondary_reference_distribution", "checks", "failures")}, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
