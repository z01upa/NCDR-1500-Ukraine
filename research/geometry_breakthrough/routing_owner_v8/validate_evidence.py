"""Cross-check the produced routing-owner evidence against pinned originals."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
EVIDENCE = HERE / "evidence"
NCDR = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3])) / 'SW' / 'LK841' / 'HU_HARDWARE_LOC_0000000001'


def load(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    inventory = load("module_inventory.json")
    sh4 = load("candidate_sh4_scan.json")
    calls = load("component_call_trace.json")
    nk = load("nk_targeted_inspection.json")
    checks = []

    def check(name: str, condition: bool, detail: str) -> None:
        checks.append({"name": name, "status": "PASS" if condition else "FAIL",
                       "detail": detail})
        if not condition:
            raise AssertionError(f"{name}: {detail}")

    check("physical_inventory_counts",
          inventory["physical_file_count"] == 5635 and
          inventory["physical_total_bytes"] == 11086850742,
          f"{inventory['physical_file_count']} files, {inventory['physical_total_bytes']} bytes")
    old = inventory["old_manifest"]
    check("prior_manifest_reconciliation",
          old["entries"] == 5600 and old["same_path_and_size"] == 5600 and
          old["new_current_paths"] == 35 and not old["changed_size_paths"] and
          old["missing_old_paths"] == 0,
          "5600 prior paths+sizes match; 35 added paths; no size changes or missing old paths")
    loader_cfg = (NCDR / "HU_MMIDIS_LOC_0130170000" / "MMIDISLOADER.CFG").read_text(
        encoding="utf-16")
    autostart_names = []
    for block in loader_cfg.split("# File Information Block"):
        name = next((line.split("=", 1)[1].strip() for line in block.splitlines()
                     if line.strip().lower().startswith("name =")), None)
        auto = next((line.split("=", 1)[1].strip() for line in block.splitlines()
                     if line.strip().lower().startswith("autostart =")), None)
        if name and auto == "1":
            autostart_names.append(name.casefold())
    check("installed_navigation_autostart_config",
          "navimain.exe" in autostart_names and "mmidis.exe" in autostart_names,
          "MMIDISLOADER.CFG marks NaviMain.exe and mmidis.exe AutoStart=1")
    check("inventory_complete_without_io_errors",
          not inventory["unreadable_or_bounded_skips"],
          "0 unreadable paths and 0 bounded candidate skips")
    check("pe_candidate_count", inventory["pe_module_unique_content_count"] == 18,
          "18 unique executable contents")
    nav_hash = "8bbeb2a919a4b5e470dd1eaaf47dd029dd2ccf12586b1a4ebb0ea9729087fb07"
    mmidis_hash = "4eeaa86bb01c4fd74aad2b5c73746a963d8d5546a743e5b6e644cb4b4211d744"
    scanned = {Path(row["path"]).name.casefold(): row for row in sh4["candidates"]}
    check("core_executable_hashes",
          scanned["navimain.exe"]["sha256"] == nav_hash and
          scanned["mmidis.exe"]["sha256"] == mmidis_hash and
          scanned["navimain.exe"]["source_sha256_after"] == nav_hash and
          scanned["mmidis.exe"]["source_sha256_after"] == mmidis_hash,
          "NAVIMAIN.EXE and MMIDIS.EXE hash before/after targeted scan match")
    check("core_sh4_decode",
          all(c["pass"] for row in sh4["candidates"] for c in row.get("controls", [])) and
          scanned["navimain.exe"]["decode_failures"] == 0 and
          scanned["mmidis.exe"]["decode_failures"] == 0,
          "SH4 byte-order controls pass; 0 CFG decode failures in NAVIMAIN and MMIDIS")
    check("navimain_call_signature_and_guids",
          calls["navimain_createinstance"]["dbghelp_demangled"].startswith(
              "public: long __cdecl MI_CF_RemoteComManager::CreateInstance") and
          calls["navimain_createinstance"]["arguments_by_signature_and_observed_setup"][1]["guid_bytes_le"] ==
              "e3187b20-abd6-11d3-a83a-00105a6b0576" and
          calls["navimain_createinstance"]["arguments_by_signature_and_observed_setup"][4]["guid_bytes_le"] ==
              "e3187b1f-abd6-11d3-a83a-00105a6b0576",
          "decorated signature and both 16-byte GUID arguments independently recovered")
    check("mmidis_mtl_activation",
          calls["mmidis_mtl_activation"]["arguments_observed"]["r4_guid1_guid_bytes_le"] ==
              "c19f8c92-cffd-11d3-ad06-0060085eab3c" and
          calls["mmidis_mtl_activation"]["arguments_observed"]["r7_guid2_guid_bytes_le"] ==
              "c19f8c91-cffd-11d3-ad06-0060085eab3c",
          "MMIDIS MTL call has two valid GUID-shaped arguments; service names unresolved")
    entries = nk["module_name_cluster_candidate"]["entries"]
    name_offsets = {row["name"].casefold(): row["offset"] for row in entries}
    check("NK_candidate_module_names_and_source_hash",
          nk["sha256"] == "d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847" and
          all(name in name_offsets for name in ("mtl.dll", "mmidis.exe", "navigationrem.dll",
                                                 "nmicore_ce.dll", "mp_service.dll", "main.exe")),
          "NK hash matches xref_v4; candidate module-looking names found at recorded offsets")
    check("no_validated_NK_PE_or_map_reader",
          nk["existing_xref_v4_bounds"]["embedded_pe_scan"]["valid_pe_image_count"] == 0 and
          nk["module_and_map_strings_in_NK"]["EUZ.MP0"]["ascii"] == [] and
          nk["module_and_map_strings_in_NK"]["EUZ.MP0"]["utf16le"] == [],
          "no valid embedded PE or literal EUZ.MP0 string; XIP layout remains unparsed")

    # Rehash the six originals that received code/ROM analysis; all are read-only.
    expected = {
        "NAVIMAIN.EXE": nav_hash,
        "MMIDIS.EXE": mmidis_hash,
        "MMIDISUPDATE.DLL": "82ef6cd5084b706e228ec9a39ad1fed35e4ba1b7257df9edd3601d9d5aef35c1",
        "MMIDISUPDATE01.DLL": "832551e7e3dc74ae1cff7d18b4dfc18f10525fc9110825569586466803ba3c29",
        "KERNELUPDATE.DLL": "a12c349447064b99de916ea2fe2888615afb54648a163e77d7b6460de8a6f545",
        "KERNELUPDATE01.DLL": "86ea43f7a5154be4bf7cd121202f7dabb93b5c64122e6b569a2ba17518bbd66b",
    }
    actual = {}
    for name in expected:
        if name in {"NAVIMAIN.EXE", "MMIDIS.EXE"}:
            path = NCDR / "HU_MMIDIS_LOC_0130170000" / "WINDOWS" / name
        elif name.startswith("MMIDISUPDATE"):
            path = NCDR / "HU_MMIDIS_LOC_0130170000" / name
        else:
            path = NCDR / "HU_KERNEL_LOC_0101000870" / name
        actual[name] = digest(path)
    check("original_module_hashes_unchanged",
          actual == expected,
          "6 directly analyzed original PE modules still match inventory SHA-256")

    result = {
        "status": "PASS_WITH_ROUTING_OWNER_UNRESOLVED",
        "checks_passed": sum(row["status"] == "PASS" for row in checks),
        "checks_failed": sum(row["status"] == "FAIL" for row in checks),
        "checks": checks,
        "routing_owner": "NOT_CONFIRMED",
        "best_module_candidates": [
            {"name": "NavigationRem.dll", "evidence": "NK filename-cluster candidate at file offset 0x009fa304; code not extracted or decoded"},
            {"name": "nmicore_ce.dll", "evidence": "NK filename-cluster candidate at file offset 0x009fb1c8; code not extracted or decoded"},
            {"name": "MMIDIS.EXE", "evidence": "SH4 auto-start app in MMIDISLOADER.CFG; activates an MTL object, but no MP0/Section5 read path found"},
        ],
        "blocker": "The original NK.BIN wrapper/XIP module table and per-module address/compression records are not decoded; no executable code from NavigationRem.dll or nmicore_ce.dll is available for SH4 call/data-flow analysis.",
        "read_only": True,
    }
    (EVIDENCE / "acceptance_evidence.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "passed": result["checks_passed"],
                      "failed": result["checks_failed"],
                      "routing_owner": result["routing_owner"]}, indent=2))


if __name__ == "__main__":
    main()
