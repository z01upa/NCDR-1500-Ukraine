# v78 compact evidence index

- Original NavigationRem.dll SHA-256: `4555a95f5bdd7d0479a39dcf8ab10a1d0dbe6e40d560d550df2461fee350ffcd`; `.text`: `91d33ac02d82dc109e65d83c87e44a00cba02887fb14e6e5b136eb16db0a35a9`.
- Original EUZ.MP0 SHA-256 before/after: `73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e` / `73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e`.
- pypcode SH4 little-endian listing and mapping: `ORIGINAL_DISASSEMBLY.md`, `BINARY_MAPPING.json`.
- Rebuilt reachable CFGs with delay slots: `CFG.json`.
- R8 condition replay: `R8_REPLAY.json` (5 test values).
- Section 5 bit replay: `DIFFERENTIAL_REPLAY.json` (60 cases; three original edges).
- Cover consumer trace/callers: `CONSUMER_TRACE.json`.
- Producer/source chains: `MEMORY_LINEAGE.json`, `MASK_PRODUCERS.json`.
- Static higher-level status-call chain `0109904A -> 01071960 -> 0106D2C4 -> 0107AC98`: `MEMORY_LINEAGE.json`, `CFG.json`, and `ORIGINAL_DISASSEMBLY.md`; status flow is not classified as route success/failure.
- Executable assertions and captured output: `reproduce.py`, `tests/test_artifacts.py`, `tests/stdout.txt`, `tests/stderr.txt`.
- Interpretation and blockers: `ROUTING_GATE.md`, `BLOCKERS.md`, `CONTRADICTIONS.md`.

Only the local candidate exclusion is confirmed. End-to-end route selection remains UNKNOWN.
