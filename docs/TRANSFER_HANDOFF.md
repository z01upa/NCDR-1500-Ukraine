# NCDR UKRAINE — handoff to Codex Astra 6

Archive prepared: 2026-10-29. Open this file first, then inspect the linked documents under `research/geometry_breakthrough/`. The project tree is a source-and-evidence snapshot; `.git` and SQLite files were deliberately excluded.

> Publication note: this handoff describes an earlier research package. Original map/firmware binaries and local databases are not distributed in this repository; paths such as `originals/NCDR/...` below are provenance references only.

## Goal and safety line

Create a modern Ukraine map for the original Opel Siemens NCDR 1500. Preserve original-device compatibility as a hard final requirement: no experimental MP0 or inferred format is certified until tested in a compatible physical unit. Keep the original map and firmware files read-only; all edits belong in new experimental files.

## Confirmed EUZ.MP0 structure

The pinned original is `originals/NCDR/SW/DB/EUZ.MP0` (SHA-256 `73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e`). `topology_v6` independently parsed all 2,956 blocks: 956,071 physical Section 4 records, 954,116 logical node heads, 1,955 continuation records, and 1,090,323 Section 5 edge records. It reconciled endpoint adjacency with zero unexplained membership errors. Node identity includes block/table/index; equal coordinates are not sufficient to merge nodes. This proves adjacency, not route direction, cost, road class semantics, or safe new-edge insertion.

`writer_v1` creates a full experimental MP0 with one controlled geometry edit and independent readback; its acceptance reports 16/16 tests passing. It is not hardware-compatible evidence. `writer_v2` correctly refuses insertion of a new road edge: high-degree/continuation storage, unknown Section 5 routing attributes and possible sidecar dependencies remain unresolved. No new edge is confirmed.

## Firmware research

`NAVIMAIN.EXE` is a small SH4 PE/bootstrap-communication process. The bounded CFG scan covered 45 roots / 1,339 reachable instruction observations; it showed MI_CF component creation, but no reached Section 4/5 reader or route calculation. Its GUID/service identities remain unknown. `MMIDIS.EXE` is another SH4 startup component; its scanned code likewise did not establish map routing ownership.

`NK.BIN` is the LK841 image (`originals/NCDR/SW/LK841/.../NK.BIN`, pinned SHA-256 `d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847`). `routing_owner_v8` identified `NavigationRem.dll` and `nmicore_ce.dll` as names in an unresolved module cluster, not extracted binaries. The latest `nk_structure_v10` bytewise audit found a repeated 16-byte `CE`-associated record pattern for 48/74 names; the `+4` words are aligned kernel-VA-range candidates and independently recur in the held-out sample. Their field meanings and VA-to-file mapping are unproven. No module was extracted; NK.BIN has no validated ROMHDR/TOC or B000FF mapping.

## Latest completed task and next step

Latest: `NCDR-NK-STRUCTURE-010`, output in `research/geometry_breakthrough/nk_structure_v10/`. The parser's synthetic tests passed 4/4 and a separate direct-byte verifier passed 8/8 checks on the pinned original. It did not recover a physical address map or executable module.

Next: obtain a genuine Windows CE ROM positive-control image and, preferably, an uncompressed/documented LK841 XIP/ROM dump or OEM container specification. Use that map to resolve the 48 candidate record addresses, verify actual module byte ranges, and inspect `NavigationRem.dll` / `nmicore_ce.dll` code before assigning routing ownership. Continue with `sh4_routing_v7`, `routing_owner_v8`, `xip_extract_v9`, and `nk_structure_v10` evidence; do not repeat the completed topology/geometry passes.

## Transfer limitations

SQLite databases, queue state, `.git`, caches, build output, temporary directories, and credentials/private-key files were excluded by request. JSON task/results, evidence, research logs, source code, tests, non-SQLite checkpoints and compressed OSM sources are included. The SQLite-backed autonomous queue is therefore not resumable from this ZIP alone; treat the saved reports and JSON as evidence, not a live queue. Ollama model weights and Codex account credentials are not included.

Original map inputs include the complete `SW/DB` set plus Italy and Scandinavia DB comparison sets. Firmware inputs include the LK841 source tree. All packaged files are listed and SHA-256 pinned in `MANIFEST.json`. The source package verifier is not copied into this curated repository; the root SHA-256 manifest covers the published text and code files.
