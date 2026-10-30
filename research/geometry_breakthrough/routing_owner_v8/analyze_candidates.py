"""Targeted SH4 scans that reuse the project's existing pypcode CFG scanner."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
import os

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
SCAN_DIR = PROJECT / "research" / "geometry_breakthrough" / "sh4_routing_v7"
VENDOR = SCAN_DIR / "vendor"
sys.path[:0] = [str(VENDOR), str(PROJECT), str(SCAN_DIR),
                str(PROJECT / "research" / "geometry_breakthrough" / "xref_v4")]
import pypcode  # noqa: E402
import sh4_scan as existing  # noqa: E402
from src.readers.ncdx_binary_headers import inspect_pe_headers  # noqa: E402
from src.readers.ncdx_pe_imports import parse_imports  # noqa: E402

NCDR = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3]))
ROOT = NCDR / "SW" / "LK841" / "HU_HARDWARE_LOC_0000000001"
MMI = ROOT / "HU_MMIDIS_LOC_0130170000"
KERNEL = ROOT / "HU_KERNEL_LOC_0101000870"
CANDIDATES = [
    MMI / "WINDOWS" / "NAVIMAIN.EXE",
    MMI / "WINDOWS" / "MMIDIS.EXE",
    MMI / "MMIDISUPDATE.DLL",
    MMI / "MMIDISUPDATE01.DLL",
    KERNEL / "KERNELUPDATE.DLL",
    KERNEL / "KERNELUPDATE01.DLL",
]
LANGUAGE = existing.LANGUAGE
KEYS = (b"EUZ.MP0", b"EUZ.RT", b"EUZ.RL", b"NaviTrace.dll",
        b"mtl.dll", b"traceable.dll", b"route", b"routing", b"navigation")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_offsets(data: bytes, needle: bytes) -> list[int]:
    found, pos = [], 0
    while True:
        pos = data.lower().find(needle.lower(), pos)
        if pos < 0:
            return found
        found.append(pos)
        pos += 1


def analyze(path: Path) -> dict:
    data = path.read_bytes()
    headers = inspect_pe_headers(data)
    if headers["architecture"] != "SH4":
        return {"path": str(path), "sha256": sha(data), "size": len(data),
                "architecture": headers["architecture"], "scan": "NOT_SH4"}
    pe = int(headers["pe_offset"])
    image = int.from_bytes(data[pe + 24 + 28:pe + 24 + 32], "little")
    entry = int.from_bytes(data[pe + 24 + 16:pe + 24 + 20], "little")
    sections = headers["sections"]
    text_sec = next(s for s in sections if s["name"] == ".text")
    pdata_sec = next(s for s in sections if s["name"] == ".pdata")
    text_va = image + int(text_sec["virtual_address"])
    text_end = text_va + int(text_sec["virtual_size"])
    text = data[int(text_sec["raw_pointer"]):int(text_sec["raw_pointer"])
                + int(text_sec["virtual_size"])]
    roots = existing._pdata_roots(data, pdata_sec, image, text_va, text_end)
    controls = []
    ctx = pypcode.Context(LANGUAGE)
    for code, expected in existing.EXPECTED_CONTROL:
        ins = ctx.disassemble(code, 0x1000, max_instructions=1).instructions[0]
        controls.append({"bytes": code.hex(), "expected": expected,
                         "actual": ins.mnem.lower(), "pass": ins.mnem.lower() == expected})
    functions = []
    for i, root in enumerate(roots):
        end = roots[i + 1]["va"] if i + 1 < len(roots) else text_end
        functions.append(existing._walk_root(ctx, text, text_va, root["va"], end))
    imports = parse_imports(data)
    xrefs = existing._import_call_xrefs(functions, data, image, sections, imports)
    call_rows = []
    for call in xrefs:
        insns = next(f["instructions"] for f in functions if f["root_va"] == call["root_va"])
        at = next(i for i, row in enumerate(insns) if row["va"] == call["call_va"])
        call_rows.append({**call, "context": insns[max(0, at - 14):min(len(insns), at + 3)]})
    # Names are captured without assuming that a text match is executable logic.
    ascii_strings = []
    for m in re.finditer(rb"[\x20-\x7e]{5,}", data):
        s = m.group().decode("ascii", errors="replace")
        if re.search(r"(?i)(navi|route|road|euz|mp0|\.rt\b|\.rl\b|service|registry)", s):
            ascii_strings.append({"offset": m.start(), "text": s[:180]})
    wide_strings = []
    for m in re.finditer(rb"(?:[\x20-\x7e]\x00){5,}", data):
        s = m.group().decode("utf-16le", errors="replace")
        if re.search(r"(?i)(navi|route|road|euz|mp0|\.rt\b|\.rl\b|service|registry)", s):
            wide_strings.append({"offset": m.start(), "text": s[:180]})
    hits = {key.decode("ascii"): file_offsets(data, key)[:80] for key in KEYS}
    imports_compact = []
    for mod in imports.get("modules", []):
        named = [i["name"] for i in mod["imports"] if i.get("name")]
        ords = [i["ordinal"] for i in mod["imports"] if i.get("ordinal") is not None]
        imports_compact.append({"module": mod["module"], "named": named,
                                "ordinal_count": len(ords), "ordinal_sample": ords[:20]})
    return {
        "path": str(path), "sha256": sha(data), "size": len(data),
        "architecture": headers["architecture"], "image_base": image,
        "entry_rva": entry, "entry_va": image + entry,
        "sections": [{"name": s["name"], "va": image + int(s["virtual_address"]),
                      "virtual_size": int(s["virtual_size"]),
                      "raw_size": int(s["raw_size"])} for s in sections],
        "pdata_roots": len(roots), "reachable_instruction_observations":
            sum(f["reachable_instruction_count"] for f in functions),
        "decode_failures": sum(len(f["decode_failures"]) for f in functions),
        "controls": controls, "import_call_xrefs": call_rows,
        "imports": imports_compact, "raw_term_offsets": hits,
        "strings_ascii": ascii_strings[:200], "strings_utf16le": wide_strings[:200],
        "source_sha256_after": sha(path.read_bytes()),
    }


def main() -> None:
    out = {"language": LANGUAGE, "existing_scanner": str(SCAN_DIR / "sh4_scan.py"),
           "candidates": [analyze(path) for path in CANDIDATES]}
    evidence = HERE / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "candidate_sh4_scan.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = []
    for row in out["candidates"]:
        summary.append({"name": Path(row["path"]).name, "sha256": row["sha256"],
                        "roots": row.get("pdata_roots"), "reachable":
                        row.get("reachable_instruction_observations"),
                        "decode_failures": row.get("decode_failures"),
                        "named_calls": sorted({f"{c['import']['module']}!{c['import']['symbol']}"
                                                for c in row.get("import_call_xrefs", [])})})
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
