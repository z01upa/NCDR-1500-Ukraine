# Acceptance — NK structure v10

**Status: PARTIAL STRUCTURAL RESULT; MODULE EXTRACTION / ADDRESS MAPPING BLOCKED.**

## Verified

- Read-only analysis of the original 11,021,915-byte LK841 `NK.BIN`; SHA-256 `d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847`.
- Bytewise ROMHDR candidate scan and no fixed `nk.exe` TOC slot assumption.
- A recurring CE-associated 16-byte byte-record family across 48/74 names; `+4` observations independently satisfy aligned kernel-VA-range and monotonicity checks on the held-out 26 records, and all held-out records have a second exact occurrence.
- Target records for `NavigationRem.dll` and `nmicore_ce.dll` preserved with exact offsets and bytes in `evidence/nk_structure.json`.
- Sparse B000FF mapping behavior and unaligned-ROMHDR behavior covered by synthetic tests.
- Automated tests: **4/4 PASS** (`python -m unittest discover -s research/geometry_breakthrough/nk_structure_v10/tests -v`).
- Independent direct-byte verifier: **8/8 checks PASS** on the original image (`scripts/verify_module_record_evidence.py`); full output is saved in `evidence/module_record_validation.json`.

## Not verified / blocked

- No real Windows CE ROM/BIN positive-control fixture is available in the local inventory.
- LK841 `NK.BIN` is not recognized as B000FF; no internally coherent ROMHDR/TOC candidate or physical VA-to-file mapping was found.
- Semantics of fields `CE+2`, `CE+4`, `CE+8`, and `CE+12` are not confirmed by executable code or an independent image.
- `NavigationRem.dll` and `nmicore_ce.dll` have **not** been extracted. No executable code or routing role is claimed.

## Safety

The probe opens inputs read-only and writes only its report under `nk_structure_v10/evidence/`. No MP0, original disk, SQLite, or v9 file was modified. `evidence/nk_structure.json` records the input path/hash and all 74 name contexts.
