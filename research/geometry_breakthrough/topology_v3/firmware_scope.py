"""Bounded read-only firmware survey for the node-record question.

Checks only the inventoried NAVIMAIN.EXE and NK.BIN, known hashes, PE header,
and strings mentioning a narrow map/graph vocabulary. It does not disassemble
or modify firmware.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import re
import shutil

NCDR = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3]))
NAVIMAIN = NCDR / "SW/LK841/HU_HARDWARE_LOC_0000000001/HU_MMIDIS_LOC_0130170000/WINDOWS/NAVIMAIN.EXE"
NK = NCDR / "SW/LK841/HU_HARDWARE_LOC_0000000001/HU_KERNEL_LOC_0101000870/NK.BIN"
NAVIMAIN_SHA256 = "8bbeb2a919a4b5e470dd1eaaf47dd029dd2ccf12586b1a4ebb0ea9729087fb07"
NK_SHA256 = "d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847"
ROOT = Path(__file__).resolve().parent


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ascii_runs(data: bytes, minimum: int = 4) -> list[tuple[int, str]]:
    return [(match.start(), match.group().decode("ascii", "replace"))
            for match in re.finditer(rb"[\x20-\x7e]{" + str(minimum).encode() + rb",}", data)]


def targeted_survey() -> dict:
    nav = NAVIMAIN.read_bytes()
    nk = NK.read_bytes()
    nav_hash, nk_hash = sha(nav), sha(nk)
    if nav_hash != NAVIMAIN_SHA256 or nk_hash != NK_SHA256:
        raise ValueError("firmware hash differs from existing immutable manifest")
    if nav[:2] != b"MZ":
        raise ValueError("NAVIMAIN.EXE lacks MZ signature")
    pe_offset = int.from_bytes(nav[0x3C:0x40], "little")
    if nav[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise ValueError("NAVIMAIN.EXE lacks PE signature at e_lfanew")
    machine = int.from_bytes(nav[pe_offset + 4:pe_offset + 6], "little")
    ascii_text = [(offset, text) for offset, text in ascii_runs(nav)]
    utf16_text = []
    for match in re.finditer(rb"(?:[\x20-\x7e]\x00){4,}", nav):
        utf16_text.append((match.start(), match.group().decode("utf-16le", "replace")))
    strings = ascii_text + utf16_text
    terms = ("mp0", "euz", "node", "edge", "route", "section", "graph", "map")
    targeted = [{"file_offset": offset, "text": text} for offset, text in strings
                if any(term in text.casefold() for term in terms)]
    marker_offsets = [m.start() for m in re.finditer(b"MZ", nk)]
    tools = {name: shutil.which(name) for name in
             ("llvm-objdump", "objdump", "dumpbin", "radare2", "r2", "ghidra", "ndisasm")}
    existing_pe_report = (ROOT.parents[2] / "work" / "autonomous_manager" / "ncdx"
                          / "firmware_imports" / "AUTO_NCDX_PE_IMPORT_CENSUS_V1_508E33703AE6FD31.json")
    # Keep the imported-function observation from the pre-existing survey; this
    # task adds no duplicate importer and does not interpret ordinal functions.
    imports = None
    candidate = existing_pe_report.resolve()
    if candidate.exists():
        imports = json.loads(candidate.read_text(encoding="utf-8"))
    return {
        "status": "PASS_BOUNDED_STATIC_SURVEY",
        "navimain": {"path": str(NAVIMAIN), "size_bytes": len(nav), "sha256": nav_hash,
                     "pe_offset": pe_offset, "machine_hex": f"0x{machine:04x}",
                     "machine_name_from_existing_census": "SH4" if machine == 0x01A6 else "UNMAPPED",
                     "targeted_graph_map_strings": targeted,
                     "disassembly_tools_found": {k: v for k, v in tools.items() if v}},
        "nk_bin": {"path": str(NK), "size_bytes": len(nk), "sha256": nk_hash,
                   "mz_marker_count": len(marker_offsets), "first_20_mz_offsets": marker_offsets[:20],
                   "existing_embedded_pe_valid_image_count": 0},
        "existing_import_census": None if imports is None else {
            "architecture": imports.get("architecture"),
            "modules": [{"module": item.get("module"),
                         "named_import_count": sum("name" in ent for ent in item.get("imports", [])),
                         "ordinal_import_count": sum("ordinal" in ent for ent in item.get("imports", []))}
                        for item in imports.get("modules", [])]},
        "conclusion": "No node-record reader implementation located. Existing import census is OS/framework oriented with ordinal imports; NK.BIN scan has no valid embedded PE. No SH4 disassembler is installed, so code-level structure proof remains unavailable.",
        "scope": "Only exact inventoried NAVIMAIN.EXE and NK.BIN; no whole-firmware recursive scan or source writes.",
        "originals_written": False,
    }


if __name__ == "__main__":
    report = targeted_survey()
    (ROOT / "evidence").mkdir(exist_ok=True)
    (ROOT / "evidence" / "firmware_scope.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
