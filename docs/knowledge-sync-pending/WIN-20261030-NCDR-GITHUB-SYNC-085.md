# WIN-20261030-NCDR-GITHUB-SYNC-085

Status: PARTIAL. The v78 evidence branch is confirmed on GitHub; the requested 079/080/084 source packages and commit objects are absent from the inspected local repositories and advertised remote branches.

Evidence: `research/github_sync_085/AUDIT_REPORT.json` and `audit_repo.py`; local-only hashes and absolute file locations are in `research/github_sync_085/local_only/LOCAL_SOURCE_MANIFEST.json` in the workstation research checkout, not in this public repository. The public v78 branch points to `df645355eabab875cc57277d1c03ffb3a810b0f8`; `main` was `cee807cbea0563f489a54c3583bc3e050b659e4f` at audit time.

Changed: this sync audit package and source-access instructions. No original `NK.BIN`, `EUZ.MP0`, `EUZ.RT`, `EUZ.RL`, `NavigationRem.dll`, database, Writer, or full firmware dump is included.

Checks: source-file size/SHA-256 reconciliation, scoped JSON/link/path/secret/binary audit, Git `cat-file` checks for the three requested commit IDs, and remote-ref verification. Existing v78 replay logs remain the evidence for its 9 offline tests; no hardware compatibility claim is made.

Limits: exact candidate directories `research/github_complete_sources_084`, `research/routing_closure_v78`, `research/index_producer_080`, and `research/index_forensics_079` are not present. The available v78 directory is `research/geometry_breakthrough/routing_closure_v78`. Full module disassembly and functions `0x01000E2C`, `0x01000E40`, and `0x01000E50` remain unavailable locally.

Reuse: source originals stay read-only and local; use `NCDR_SOURCE_ROOT` and `NCDR_RESEARCH_ROOT` with the local manifest. Do not infer missing research from commit IDs or publish proprietary binaries without rights confirmation.
