# Acceptance — routing owner v8

**Research milestone status: partial.** The inventory, call-ABI reconstruction and candidate narrowing passed; the actual module that consumes MP0 Section 5 and routes was **not confirmed**. `NavigationRem.dll` is a concrete next extraction candidate, not a proven routing owner.

## Verification results

`python validate_evidence.py` completed with **12 PASS, 0 FAIL**. Its machine-readable results are in `evidence/acceptance_evidence.json`.

| Check | Result | Evidence |
|---|---|---|
| Physical file inventory | PASS — 5,635 files / 11,086,850,742 bytes | `module_inventory.json`, `physical_files.jsonl` |
| Prior manifest reconciliation | PASS — 5,600 path+size matches, 35 new paths, no size changes/missing paths | `module_inventory.json` |
| Inventory read/scan errors | PASS — 0 | `module_inventory.json` |
| Unique PE candidate count | PASS — 18 | `module_inventory.json` |
| Installed startup configuration | PASS — NaviMain and MMIDIS both AutoStart=1 | original `MMIDISLOADER.CFG`; check in `acceptance_evidence.json` |
| NAVIMAIN/MMIDIS PE hashes | PASS — before/after hashes match | `candidate_sh4_scan.json` plus final rehash |
| SH4 decoder controls | PASS — all controls; 0 failures on NAVIMAIN and MMIDIS | `candidate_sh4_scan.json` |
| `CreateInstance` signature/arguments | PASS — decorated signature demangled; `r4–r7` and two stack arguments recovered; both GUID byte arrays valid | `component_call_trace.json` |
| MMIDIS MTL activation | PASS — two GUID arguments recovered from the actual call site | `component_call_trace.json` |
| NK hash and candidate names | PASS — pinned NK hash and six named candidates verified | `nk_targeted_inspection.json` |
| NK PE / MP0 literal check | PASS — no valid embedded PE in reused bounded scan; no literal EUZ.MP0 in NK | xref_v4 and `nk_targeted_inspection.json` |
| Original analyzed module hashes | PASS — all six standalone SH4 files match fresh inventory SHA-256 | `acceptance_evidence.json` |

The constrained pypcode scan covered 1,880 reachable instruction observations in NAVIMAIN and MMIDIS combined, with zero decode failures. The four updater-DLL scans add 43,057 observations; `MMIDISUPDATE.DLL` has one CFG decode failure, and the other three updater scans have zero. Counts per module are recorded in `candidate_sh4_scan.json`. No direct `EUZ.MP0`, `EUZ.RT` or `EUZ.RL` strings were found in any of the six scanned PE images. These negative string/pattern observations do not prove that a reader is absent: file names may be constructed dynamically and code may live in NK.BIN.

## Not accepted / not proven

- Routing owner identification: **FAIL TO ESTABLISH / BLOCKED**.
- MP0 open/read procedure: **not located**.
- Section 4 10-byte node consumer in executable code: **not located**.
- Section 5 14-byte edge consumer or routing-field use: **not located**.
- Topology_v6 continuation logic in a runtime module: **not located**.
- NAVIMAIN GUID-to-service/module mapping: **unknown**.
- MTL GUID-to-service/module mapping: **unknown**.
- NK.BIN ROMHDR/XIP/table-of-modules layout: **not validated or decoded**.
- Physical hardware compatibility: **not tested**.

The data does support a concrete next module candidate: `NavigationRem.dll` at NK file offset `0x009FA304`, followed by `nmicore_ce.dll` at `0x009FB1C8`. Their code was not extracted. It would be false to call either one the MP0 reader now.

All new files are under `routing_owner_v8/`. Source modules and the NK image were read-only; MP0, SQLite, GUI and Manager files were not opened for writing or modified.
