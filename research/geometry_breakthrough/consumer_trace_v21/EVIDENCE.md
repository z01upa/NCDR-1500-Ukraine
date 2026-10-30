# NCDR-ASTRA-021 — 2026-10-30
Verdict for edge706: UNKNOWN. Bounded count-query behavior is demonstrated; route acceptance is not.
Read EDGE_DEPENDENCIES.md (019). No distinct Astra-020 result was found in the available research files. Two local lookups identified callers and inspected only them/the known callee; no new DLL disassembly or topology/mask/NK analysis.

## Direct callers (link VAs; saved runtime VAs add 0x02000000)
- 0x01000E2C: `mov r6,r7` at +2; `mov r5,r6` at +4; `bsr 0x01000E50` at 0x01000E34, delay slot sets the filter argument. After return, stack/PR restore then `rts` at 0x01000E3C; r0 is neither tested nor changed.
- 0x01000E40: `bsr 0x01000E50` at 0x01000E44; delay slot `mov #1,r7`. Returns at 0x01000E4C without testing/changing r0. This wrapper was inspected statically, not executed in the paired test.
These wrappers do not locally reject a zero result. Their own callers and routing policy remain untraced.

## Actual absence behavior in the callee
At 0x01000EF8 `cmp/gt r11,r4`, 0x01000EFA `bf 0x01000F46`: Section7 exhaustion advances to Section8.
0x01000EFC loads record key, 0x01000F02 compares it; mismatch branches at 0x01000F04 to the next Section7 record.
0x01000F58/0x01000F5A similarly advance from Section8 to Section9.
The count accumulator is initialized to zero (`mov #0,r9`, 0x01000E76), incremented for matches, and returned by `mov r9,r0` at 0x010010E4.
Thus missing Section7 alone is not a local error: searching continues through other tables. A zero-total path has no additional rejection in these wrappers, but is not a demonstrated acceptable routing outcome.

## One controlled paired test, PASS with explicit models
Original block886 decoded SHA256: c4fd95701be3301b999d7e8886d08a6d2e8a3461e9f6caa973a5128959d983a6.
Key0: Section7=1, Section8=0, Section9=0; wrapper 0x01000E2C returns1 (8579 interpreted instruction translations).
Key593: Section7=0, Section8=2, Section9=0; same wrapper returns2 (8799 translations).
All 706 existing edge-index values have a key in Section7 OR Section8. There is no real zero-total counterpart in this block; therefore a paired full-absence test on two real existing IDs cannot be supplied.
Reproduction executes recovered instructions using the existing v13 restricted p-code interpreter, with output capacity0. It executes the internal converter 0x010002E8 as actual code.
Modeled calls: 0x0101213C/0x0101217C lock/unlock no-op; 0x0100D19C returns the real unpacked block886 tables and success, bypassing file loading and ID decoding; 0x00FFFB48 returns NULL only when the output-record count argument is zero (asserted). Its actual body is not verified.
The last stub controls merge behavior for key593; the return2 result is conditional on that explicit empty-output model. No claim of materialized output, device execution or full emulator behavior.
During setup, harness-only issues were corrected (scope binding, direct-CALL PR semantics, missing INT_NEGATE support). Final run verifies both callee return and caller RTS; earlier failed runs are not counted as successful evidence.

## Identity and edge706 gate
Record keys equal the low12 bits of the supplied ID (literal 0xFFF and AND at 0x01000EBA..0x01000EBE). The wrappers preserve r4, but do not establish its entity type.
Using real edge IDs0/593 as keys and their complete combined coverage supports, but does not prove, edge identity. The loader stub specifically prevents this test from proving it. Do not treat ID coincidence as resolved provenance.
No evidence permits omitting BOTH auxiliary tables for edge706. Nor does this establish that both tables require a new record.
Next single dependency to resolve: caller provenance of r4 into 0x01000E2C, including the loader's interpretation and the upper caller's handling of a zero-total result.

Run from project root: research/geometry_breakthrough/module_recovery_v13/.venv/bin/python research/geometry_breakthrough/consumer_trace_v21/reproduce.py
Sources: module_recovery_v13/modules/NavigationRem.dll/{module.json,section_*.bin,sh4_analysis.json,reachable.jsonl.gz}; original EUZ.MP0; existing verify_graph_readers.py. Only this new research directory was written; Writer and originals untouched.
