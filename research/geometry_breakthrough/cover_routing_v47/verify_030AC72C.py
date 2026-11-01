#!/usr/bin/env python3
"""Read-only independent decode check for the bounded 0x030AC72C function."""
import argparse
import hashlib
import json
from pathlib import Path

import pypcode

START = 0x030AC72C
END = 0x030AC79E


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--module-dir", type=Path, required=True,
                        help="Local recovered NavigationRem module directory")
    args = parser.parse_args()
    meta = json.loads((args.module_dir / "module.json").read_text())
    section = next(s for s in meta["sections"] if s["index"] == 0)
    data = (args.module_dir / "section_0.bin").read_bytes()
    actual_sha = hashlib.sha256(data).hexdigest()
    if actual_sha != section["sha256"]:
        raise SystemExit("FAIL: section_0.bin SHA256 does not match module metadata")
    offset = START - section["runtime_va"]
    if offset < 0 or offset + (END - START) > len(data):
        raise SystemExit("FAIL: requested function range is outside section_0.bin")
    ctx = pypcode.Context("SuperH4:LE:32:default")
    result = ctx.disassemble(data[offset:offset + END - START], START)
    ins = result.instructions
    total = sum(i.length for i in ins)
    final = ins[-1].addr.offset + ins[-1].length if ins else None
    if len(ins) != 57 or total != END - START or final != END:
        raise SystemExit("FAIL: decoded instruction count or range differs")
    print("PASS: pypcode decoded 57 instructions across 114 bytes; end=0x%08X" % final)


if __name__ == "__main__":
    main()
