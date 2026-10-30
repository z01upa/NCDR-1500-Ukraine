# Next technical step

## Decode only enough of NK.BIN to extract the relevant modules

1. **Validate the CE image wrapper.** Begin from the observed `CE00FF` marker at `0x400` and `ECEC` marker at `0x9CEAD3`. Test the header, address ranges and candidate module-name region against internal size/count/pointer constraints. Do not label a marker as ROMHDR or a filename cluster as a TOC until those checks agree.
2. **Recover module records for a small set only.** Start with `MTL.dll` (`0x009ED19B`), `NavigationRem.dll` (`0x009FA304`), `nmicore_ce.dll` (`0x009FB1C8`), `MP_Service.dll` (`0x009F9029`) and `Main.exe` (`0x009F9041`). Resolve record boundaries, load addresses, code/data ranges and compression from the image's own checked fields. Do not full-disassemble NK.BIN.
3. **Reconstruct PE-like views without rewriting the source.** Save extracted candidates under a separate evidence subdirectory with source/output hashes and exact source byte ranges. Require internally consistent SH4 machine/type, entry point and section mapping before disassembly.
4. **Reuse the current pypcode scanner.** Run a bounded scan only on the validated `NavigationRem.dll` and `nmicore_ce.dll` code ranges. Follow candidate imports/calls for file opens/reads, `EUZ.MP0` path formation, 10-byte node traversal, 14-byte edge access and the topology_v6 high-degree continuation rule. Keep every negative result scoped to reached instructions.
5. **Resolve activation IDs.** Locate the registry/service table or class-registration records for GUIDs `e3187b20-abd6-11d3-a83a-00105a6b0576`, `e3187b1f-abd6-11d3-a83a-00105a6b0576`, `c19f8c92-cffd-11d3-ad06-0060085eab3c` and `c19f8c91-cffd-11d3-ad06-0060085eab3c`. Bind an activation to a module only if an image record or call path independently supports it.
6. **Name the routing owner only after the chain closes:** NAVIMAIN/MMIDIS activation → validated module → code that opens a map source → Section 4/5 traversal → route consumer. Otherwise report which link remains missing.

## Expected decision point

If no parser validates the NK wrapper and module-record addresses, stop before interpreting compressed payload bytes. The current exact blocker is the proprietary/variant NK layout: it has CE/ECEC-like markers and embedded module names, but no validated ROMHDR/XIP record parser or extracted module code. Do not spend time on another MP0 topology census or updater DLLs unless new call evidence points there.
