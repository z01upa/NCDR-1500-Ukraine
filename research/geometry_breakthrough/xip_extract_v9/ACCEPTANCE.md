# Acceptance

## Evidence checks: PASS

`scripts/verify_results.py` completed **7/7 checks PASS** in `evidence/acceptance_verification.json`:

1. original NK.BIN SHA-256 still matches the existing `xref_v4` and `routing_owner_v8` value;
2. current hash matches the probe's input hash;
3. no structurally validated standard ROMHDR/TOC was found;
4. no ECEC candidate resolves to a validated module table;
5. each target has only a raw filename hit, not a validated module entry;
6. both extractor output directories contain zero files;
7. both bounded parser logs are preserved and end with exit code 0.

The single coarse ROMHDR-shaped candidate at `0x009D7794` is rejected: zero of its first 32 TOC names are printable and no `nk.exe` entry is present.

## Product criteria: BLOCKED / NOT MET

| Required result | Status | Evidence |
|---|---|---|
| NK.BIN format and internal address mapping established | **FAIL** | No standard container or validated ROMHDR/TOC; see `NK_FORMAT.md` |
| `NavigationRem.dll` extracted and executable code validated | **FAIL** | No module bytes emitted |
| `nmicore_ce.dll` extracted and executable code validated | **FAIL** | No module bytes emitted |
| At least one target linked to routing/map processing | **NOT TESTED** | Extraction prerequisite not met; see `ROUTING_CANDIDATES.md` |

No module is presented as successfully extracted. The `PASS` checks validate the repeatable blocker and preservation of the original, not the requested extraction outcome.
