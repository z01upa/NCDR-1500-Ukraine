# Module inventory — routing owner v8

## Scope and result

The one-pass inventory covered `%USERPROFILE%\Desktop\crz\NCDR` on 2026-10-29. It recorded file paths, sizes and 16-byte headers for all physical files; it parsed bounded PE headers/imports/exports for executable candidates, searched selected software/config text, and inspected executable members in ZIP archives. It did not hash or reread every byte of the 11 GB tree.

- Physical files: **5,635**; total reported size: **11,086,850,742 bytes**.
- Existing manifest reconciliation: **5,600/5,600** prior paths match by path and size; **35** current paths are new; **0** prior paths are missing; **0** sizes changed.
- Read or bounded-scan errors: **0**.
- Unique PE contents: **18** — 16 SH4 and two x86. The SH4 set contains the two installed navigation executables and 14 update DLLs. The x86 programs are `patch.exe` and `poison.exe` under `tools/POISoN`.
- The archive's 16 executable members duplicate the corresponding `SW` modules by SHA-256; they do not add a distinct navigation executable.

## Unique executable contents

The complete header/import/export report and duplicate paths are in [module_inventory.json](evidence/module_inventory.json). The SHA-256 values below are fresh hashes of each candidate's bytes during this analysis.

| Module | Architecture | Bytes | SHA-256 prefix | Classification from location/name/import evidence |
|---|---:|---:|---|---|
| NAVIMAIN.EXE | SH4 | 9,798 | `8bbeb2a919a4` | Installed auto-start navigation process; MI_CF communication/bootstrap calls |
| MMIDIS.EXE | SH4 | 6,724 | `4eeaa86bb01c` | Installed auto-start MMIDIS process; MTL component activation |
| KERNELUPDATE.DLL | SH4 | 19,968 | `a12c34944706` | Kernel update package module |
| KERNELUPDATE01.DLL | SH4 | 45,644 | `86ea43f7a515` | Kernel update package module |
| MMIDISUPDATE.DLL | SH4 | 50,688 | `82ef6cd5084b` | MMIDIS update package module |
| MMIDISUPDATE01.DLL | SH4 | 84,556 | `832551e7e3dc` | MMIDIS update package module |
| A20UPDATE.DLL | SH4 | 20,992 | `8c182b29cb4f` | A20 update package module |
| A20UPDATE01.DLL | SH4 | 45,129 | `e1c5724e0f88` | A20 update package module |
| AUDIOUPDATE.DLL | SH4 | 23,040 | `82bea46e85ed` | Audio update package module |
| AUDIOUPDATE01.DLL | SH4 | 48,203 | `7fe9dc178eda` | Audio update package module |
| C161APPLUPDATE.DLL | SH4 | 22,016 | `d4584197b1bf` | C161 application update package module |
| C161APPLUPDATE01.DLL | SH4 | 46,670 | `2651263e6251` | C161 application update package module |
| LANGUAGEUPDATE.DLL | SH4 | 50,688 | `fc3e76b1225f` | Language update package module |
| LANGUAGEUPDATE01.DLL | SH4 | 83,534 | `1cd2b4b0299b` | Language update package module |
| TMCUPDATE.DLL | SH4 | 69,703 | `b5fa74e9e721` | TMC update package module |
| TMCUPDATE01.DLL | SH4 | 73,289 | `f5fc79d18b2f` | TMC update package module |
| patch.exe | x86 | 16,896 | `459ac4587f6b` | PC-side utility, not a SH4 navigation candidate |
| poison.exe | x86 | 411,136 | `5c19ea123d11` | PC-side utility, not a SH4 navigation candidate |

Direct `SW` paths for each of these modules are recorded in `module_inventory.json`. Duplicate copies in prior research snapshots and the ZIP package are listed separately there.

## Boot and component evidence

`SW\LK841\HU_HARDWARE_LOC_0000000001\HU_MMIDIS_LOC_0130170000\MMIDISLOADER.CFG` sets `AutoStart = 1` for both `NaviMain.exe` and `mmidis.exe`. This establishes that both participate in the installed navigation startup path, not that either is the road-graph reader.

`NAVIMAIN.EXE` imports named `MI_CF_RemoteComManager` and `MI_CF_CommunicationBroker` methods from `commgr.dll`. It also obtains `NaviTrace.dll` through two dynamically resolved `coredll.dll` ordinals and resolves `Initialize`; the exact `NaviTrace.dll` basename is absent from physical filenames and the NK literal search. This is trace/bootstrap evidence, not evidence that NaviTrace routes.

`MMIDIS.EXE` imports `MTLCoCreateInstance` from `mtl.dll` and tracing helpers from `traceable.dll`. No standalone `mtl.dll`, `traceable.dll`, or `commgr.dll` exists in the physical-file inventory. `MTL.dll` does appear in the NK.BIN filename cluster described below; the other two names were not found there as literal basenames.

## NK.BIN candidate-name region

The original `NK.BIN` is 11,021,915 bytes, SHA-256 `d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847`. The reused xref_v4 scan found no structurally valid embedded PE image, one invalid raw `PE` signature candidate, and the markers `CE00FF` at `0x400` and `ECEC` at `0x9CEAD3`. This task did not full-disassemble NK.BIN.

A bounded, case-insensitive scan found **74 NUL-terminated module-looking filenames** in the range `0x009D0000–0x00A10000`. The exact strings include:

| Name | File offset | Assessment |
|---|---:|---|
| `MTL.dll` | `0x009ED19B` | Strong lead for the imported `mtl.dll`; module bytes not extracted |
| `mmidis.exe` | `0x009F7F8F` | Embedded name; matches installed app basename |
| `MP_Service.dll` | `0x009F9029` | Candidate platform service; role unknown |
| `Main.exe` | `0x009F9041` | Candidate platform executable; role unknown |
| `NavigationRem.dll` | `0x009FA304` | Highest-priority route-owner extraction candidate by name only |
| `nmicore_ce.dll` | `0x009FB1C8` | Additional navigation-core candidate by name only |
| `nmihmi_ce.dll` | `0x009FC438` | HMI-named candidate; not treated as the route owner |

These are raw filename hits in the image, not a validated XIP TOC parse. The adjacent `CE` bytes and following fields have not been shown to be a particular module-header layout. The 74 names and their contexts are in [nk_targeted_inspection.json](evidence/nk_targeted_inspection.json).

Microsoft's Windows CE documentation describes NK.BIN as a runtime image assembled from modules/files and supports XIP regions; that makes NK a justified place to search for runtime modules, but does not identify the semantics of this particular Siemens image. See [Microsoft Romimage documentation](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms938650(v=msdn.10)).

## Evidence files

- `evidence/physical_files.jsonl` — one metadata/header record per physical file.
- `evidence/module_inventory.json` — bounded PE imports, exports, sections, hashes, duplicate paths, ZIP members and targeted text hits.
- `evidence/candidate_sh4_scan.json` — reuse of the installed pypcode CFG scanner on NAVIMAIN, MMIDIS and four update DLLs.
- `evidence/component_call_trace.json` — demangled signature and argument/GUID derivations.
- `evidence/nk_targeted_inspection.json` — NK markers, module-name candidates, address contexts and targeted string/GUID searches.
- `evidence/acceptance_evidence.json` — 11 reproducibility/integrity checks.
