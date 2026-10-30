"""Bounded header, marker, dependency-string and GUID checks for NK.BIN."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
import os

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
NK = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3])) / 'SW' / 'LK841' / 'HU_HARDWARE_LOC_0000000001' / 'HU_KERNEL_LOC_0101000870' / 'NK.BIN'
EXPECTED_SHA256 = "d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847"
XREF = PROJECT / "research" / "geometry_breakthrough" / "xref_v4" / "evidence" / "firmware_xref.json"
TERMS = ("NaviTrace.dll", "mtl.dll", "traceable.dll", "commgr.dll",
         "MMIDIS.EXE", "NAVIMAIN.EXE", "EUZ.MP0", "EUZ.RT", "EUZ.RL",
         "ROMHDR", "XIP")
GUIDS = {
    "NAVIMAIN_second_GUID_candidate": "1f7b18e3d6abd311a83a00105a6b0576",
    "MMIDIS_class_GUID_candidate": "c19f8c92cffdd311ad060060085eab3c",
    "MMIDIS_interface_GUID_candidate": "c19f8c91cffdd311ad060060085eab3c",
}


def find_all(data: bytes, needle: bytes) -> list[int]:
    out, start = [], 0
    while True:
        at = data.find(needle, start)
        if at < 0:
            return out
        out.append(at)
        start = at + 1


def main() -> None:
    data = NK.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(f"NK.BIN SHA changed: {digest}")
    xref = json.loads(XREF.read_text(encoding="utf-8"))
    old_nk = xref["sources"]["NK.BIN"]
    names = []
    wanted = {"navitrace.dll", "mtl.dll", "traceable.dll", "commgr.dll"}
    physical_jsonl = HERE / "evidence" / "physical_files.jsonl"
    for line in physical_jsonl.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        base = row["path"].replace("/", "\\").rsplit("\\", 1)[-1].casefold()
        if base in wanted:
            names.append(row["path"])
    markers = {"CE00FF": find_all(data, b"CE00FF"),
               "ECEC": find_all(data, b"ECEC"),
               "ROMHDR_ascii": find_all(data, b"ROMHDR"),
               "ROMHDR_utf16le": find_all(data, b"R\x00O\x00M\x00H\x00D\x00R\x00")}
    strings = {}
    for term in TERMS:
        ascii_term = term.encode("ascii")
        wide_term = b"".join(bytes((b, 0)) for b in ascii_term)
        strings[term] = {"ascii": find_all(data.lower(), ascii_term.lower()),
                         "utf16le": find_all(data.lower(), wide_term.lower())}
    guid_hits = {name: find_all(data, bytes.fromhex(value))
                 for name, value in GUIDS.items()}
    module_name_region = []
    for match in re.finditer(rb"(?i)[A-Z0-9_.$-]{1,80}\.(?:DLL|EXE|CPL|SYS|DAT|BIN)\x00", data):
        if 0x9D0000 <= match.start() < 0xA10000:
            module_name_region.append({"offset": match.start(),
                                       "name": match.group()[:-1].decode("ascii")})
    def context(at: int, before: int = 24, after: int = 80) -> dict:
        lo, hi = max(0, at - before), min(len(data), at + after)
        return {"offset": at, "context_start": lo, "context_hex": data[lo:hi].hex(" ")}
    report = {
        "path": str(NK), "size_bytes": len(data), "sha256": digest,
        "expected_sha256_from_xref_v4": EXPECTED_SHA256,
        "prefix_ascii": data[:32].split(b"\x00", 1)[0].decode("ascii", errors="replace"),
        "header_window_0x3e0_0x480": data[0x3E0:0x480].hex(" "),
        "existing_xref_v4_bounds": {k: old_nk.get(k) for k in (
            "first_non_ff_after_byte_32", "ce00ff_marker_offsets", "ecec_marker_offsets",
            "mz_marker_count", "mz_marker_offsets", "raw_pe_signature_count",
            "raw_pe_signature_candidates", "embedded_pe_scan", "image_format",
            "node_reader_code")},
        "marker_contexts": {"CE00FF": [context(x) for x in markers["CE00FF"]],
                            "ECEC": [context(x) for x in markers["ECEC"]]},
        "module_basename_matches_in_inventory": names,
        "module_name_cluster_candidate": {
            "range_start": "0x009d0000", "range_end_exclusive": "0x00a10000",
            "filename_count": len(module_name_region),
            "entries": module_name_region,
            "interpretation": "A bounded cluster of NUL-terminated module-looking filenames. This is useful for locating candidate names but is not claimed to be a decoded XIP table without validating record boundaries and address fields.",
        },
        "target_candidate_name_contexts": {
            row["name"]: context(row["offset"], 32, 96)
            for row in module_name_region
            if row["name"].casefold() in {"mtl.dll", "mmidis.exe", "main.exe",
                                           "mp_service.dll", "navigationrem.dll",
                                           "nmicore_ce.dll", "nmihmi_ce.dll"}
        },
        "module_and_map_strings_in_NK": strings,
        "candidate_GUID_byte_hits_in_NK": guid_hits,
        "assessment": {
            "XIP_ROMHDR_module_table": "NOT_DECODED: existing bounded scan records CE00FF and ECEC markers but no validated ROMHDR/XIP table layout or address mapping; raw PE signatures do not form valid PE modules.",
            "runtime_component_location": "The statically imported mtl.dll, traceable.dll and commgr.dll were not found as standalone files by the physical-file inventory; their possible presence in NK.BIN is not established by the bounded markers or target strings.",
            "disassembly_performed": False,
        },
        "read_only": True,
    }
    evidence = HERE / "evidence"
    (evidence / "nk_targeted_inspection.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"size": len(data), "sha256": digest,
                      "markers": markers, "strings": strings,
                      "guid_hits": guid_hits, "module_file_matches": names,
                      "valid_embedded_pe_count": old_nk["embedded_pe_scan"]["valid_pe_image_count"]},
                     indent=2))


if __name__ == "__main__":
    main()
