# Routing owner assessment

## Conclusion

**The module that actually reads EUZ.MP0, decodes Section 5 and routes is not yet confirmed.** The evidence does identify a concrete highest-priority in-image candidate: **`NavigationRem.dll`**, with **`nmicore_ce.dll`** as the next candidate. They are embedded-name hits in the NK.BIN region containing 74 module-looking names, at `0x009FA304` and `0x009FB1C8`. This supports investigating them as navigation components by name and image location; it does **not** prove either one owns MP0 parsing or route calculation.

## What the available code proves

1. `MMIDISLOADER.CFG` auto-starts both `NaviMain.exe` and `mmidis.exe`.
2. `NAVIMAIN.EXE` is a small SH4 bootstrap/communication process. Its bounded `.pdata` CFG scan covered 45 roots and 1,339 reachable instruction observations with zero decoder failures. It calls `MI_CF_RemoteComManager` and `MI_CF_CommunicationBroker`. At `0x116E4`, it requests a manager-created instance using GUIDs `e3187b20-abd6-11d3-a83a-00105a6b0576` and `e3187b1f-abd6-11d3-a83a-00105a6b0576`, with `r6 = NULL`, `r7 = 0x15`, and a local output pointer. GUID names/roles are unresolved. No reached Section 5 reader or MP0 path was found.
3. `MMIDIS.EXE` is also SH4 and auto-started. Its bounded scan covered 20 `.pdata` roots and 541 reachable instruction observations with zero decoder failures. It calls `mtl.dll!MTLCoCreateInstance` at `0x11168` with GUIDs `c19f8c92-cffd-11d3-ad06-0060085eab3c` and `c19f8c91-cffd-11d3-ad06-0060085eab3c`. The human-readable service name and object's role are unknown. There are no literal EUZ.MP0/RT/RL strings in the scanned app.
4. `MTL.dll`, `MP_Service.dll`, `Main.exe`, `NavigationRem.dll`, `nmicore_ce.dll` and `nmihmi_ce.dll` appear as filename strings in NK.BIN. `MTL.dll` is consistent with MMIDIS's unresolved standalone import. No module code was reconstructed from these names.
5. The four updater DLLs in the MMIDIS/KERNEL packages were scanned as control candidates. Their filenames, update-package paths and imports do not make them routing-owner candidates. The broad `.pdata` scans are bounded static evidence; indirect runtime targets were not followed beyond what the existing scanner resolves.

## Candidate ranking (not a finding of ownership)

| Priority | Module | Why it remains a candidate | Missing proof |
|---:|---|---|---|
| 1 | `NavigationRem.dll` | Explicit navigation-named module entry in NK.BIN's candidate filename cluster | No extracted SH4 code, imports, file-open call or Section 4/5 access |
| 2 | `nmicore_ce.dll` | Core-named module entry adjacent in the same cluster | No extracted code or independent link to MP0/routing |
| 3 | `MP_Service.dll` / `Main.exe` | Platform service/executable names in the same image region | No evidence tying either to maps rather than other services |
| 4 | `MMIDIS.EXE` | Installed auto-start app; performs MTL COM activation | The scanned code does not show map I/O or route graph work |
| 5 | `NAVIMAIN.EXE` | Installed auto-start app; MI_CF component creation and trace loading | Reached code is bootstrap/communication; no Section 5 consumer found |

`NaviTrace.dll` is requested dynamically by NAVIMAIN through `coredll.dll` ordinals 528 and 530, followed by an indirect `Initialize` call. It was not found as a standalone file or literal NK module name. Its name and call path indicate tracing/bootstrap behavior, not a routing engine.

## Exact blocker

The system ROM image is present, but its Siemens/Windows CE wrapper and module table are not decoded. The prior xref scan found the `CE00FF` marker at `0x400`, an `ECEC` marker at `0x9CEAD3`, no structurally valid embedded PE, and no validated ROMHDR/XIP table. A new bounded scan found a 74-name candidate region but could not validate the neighboring address, size, compression and section records. Consequently no executable bytes can yet be attributed to `NavigationRem.dll` or `nmicore_ce.dll`, and their SH4 code cannot be checked for an MP0 open, 10-byte node handling, 14-byte edge handling, or the topology_v6 continuation rule.

The unresolved MI_CF/MTL GUIDs also have no module/service name mapping. Even if a module is extracted, connect the two evidence chains: **caller GUID/service registration → loaded module → observed map-file and edge/node routines**. A filename alone is insufficient to declare a routing owner.

Microsoft's Windows CE tool documentation confirms that NK.BIN is a run-time image that can include binaries and XIP regions, which supports the location hypothesis but does not decode this specific file ([Romimage documentation](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms938650(v=msdn.10))).

## Safety and result

All input access was read-only. No MP0, disc image, SQLite, Manager, GUI or source module was written. Fresh final SHA-256 checks for the six analyzed standalone SH4 modules match their inventory hashes; NK.BIN also matches xref_v4's pinned hash. No physical compatibility claim is made.
