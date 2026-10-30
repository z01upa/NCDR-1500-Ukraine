# NCDR-ASTRA-022 — 2026-10-30
Result: UNKNOWN; no upper caller of 0x01000E2C was identified within this bounded investigation. Stop condition reached; no further scan undertaken.

## Reused baseline
Read consumer_trace_v21/EVIDENCE.md. Its ID0/ID593 test was not rerun. Known call 0x01000E34 `bsr 0x01000E50` and return 0x01000E3C `rts` belong to the wrapper itself; they do not identify who calls the wrapper.
All addresses below are original link VAs; saved instruction evidence adds runtime delta 0x02000000.

## Narrow searches and one reproducible verification
1. Queried the existing NavigationRem sh4_analysis.json call/literal index for target runtime 0x03000E2C: zero direct calls and zero normalized literal loads. No new full-DLL disassembly.
2. Exact address-byte lookup in the five already recovered target-module sections found one occurrence only: 0x01152B30, Section3/.pdata, start word of an 8-byte function entry. Metadata is not a caller.
3. As part of that bounded reference check, inspected raw aligned BRA/BSR encodings only within ±4100 bytes of the target (their possible PC-relative reach): no instruction encoding targets 0x01000E2C. This avoids depending solely on CFG completeness for nearby direct branches.
The verification script rechecks the saved section hashes, index results, relative branch calculation, and the PDATA classification. It passed.
Run from this directory: `python3 verify_references.py` (Windows: `python verify_references.py`). Standard library only, no external calls or stubs.

## What is and is not established
- No direct upper caller was identified in these sources; this is not proof that the function is dead or never invoked.
- Computed pointers, indirect function tables, callers in other modules and runtime loader modifications remain outside the check.
- v21's wrappers leave their incoming r4 value unchanged before the lookup. Without its producer, the entity type of that value is still UNKNOWN.
- The upper caller's response to r0=0 is UNKNOWN; no instruction address can honestly be supplied for an unidentified caller.
- No new dynamic caller-behavior test was possible. The reproducible result here is a bounded negative reference check, not successful execution or acceptance of an edge without auxiliary records.
- Omitting Sections7/8 for edge706 remains UNKNOWN; no Writer instruction follows from this result.

Next single required evidence: an actual callsite or runtime trace entering 0x01000E2C (saved PR/caller address and r4). This would permit a bounded producer/return-branch trace without another broad static search.
Inputs: ../module_recovery_v13/modules/NavigationRem.dll/{module.json,sh4_analysis.json,section_0.bin..section_4.bin}; ../consumer_trace_v21/EVIDENCE.md.
Only consumer_trace_v22 was written. MP0, NK.BIN, originals, Writer and previous evidence remain unchanged.
