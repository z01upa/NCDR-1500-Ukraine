#!/usr/bin/env python3
"""Export only static call-edge metadata; never copy instruction/literal records."""
import argparse
import gzip
import json
import re
from pathlib import Path

MODULES = ("NavigationRem.dll", "nmicore_ce.dll")


def rows(module_dir, module):
    with gzip.open(module_dir / "reachable.jsonl.gz", "rt", encoding="utf-8") as source:
        for line in source:
            function = json.loads(line)
            for call in function.get("calls", []):
                body = call.get("body", "")
                target = call.get("target")
                if re.fullmatch(r"0x[0-9a-fA-F]+", body):
                    if not isinstance(target, int):
                        raise ValueError("direct target is missing")
                    kind, resolution = "direct", "static_target"
                    target_va, register = "0x%08X" % target, None
                else:
                    match = re.fullmatch(r"@r(\d+)", body or "")
                    if not match or target is not None:
                        raise ValueError("unexpected call form; refusing non-metadata export")
                    kind, resolution = "indirect", "unresolved_indirect"
                    target_va, register = None, "r" + match.group(1)
                yield {
                    "module": module,
                    "source_function_va": "0x%08X" % function["va"],
                    "source_function_end_va": "0x%08X" % function["end"],
                    "callsite_va": "0x%08X" % call["va"],
                    "call_kind": kind,
                    "resolution": resolution,
                    "target_va": target_va,
                    "target_register": register,
                }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modules-root", type=Path, required=True,
                        help="Directory containing the two recovered module directories")
    parser.add_argument("--output", type=Path, required=True,
                        help="Explicit destination for the metadata-only gzip JSONL")
    args = parser.parse_args()
    counts = {name: 0 for name in MODULES}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0, compresslevel=9) as out:
            for module in MODULES:
                module_dir = args.modules_root / module
                for row in rows(module_dir, module):
                    out.write((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode())
                    counts[module] += 1
    print(json.dumps({"metadata_edges": counts, "total": sum(counts.values())}, sort_keys=True))


if __name__ == "__main__":
    main()
