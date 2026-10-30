# Agent errata

## `sett` before `bf/s`

At `0x030AC3E0` the instruction is `sett`; `0x030AC3E2` is `shlr2 r6`; `0x030AC3E4` is `bf/s 0x030AC40C`. Pypcode's instruction semantics show that SETT writes T=1, SHLR2 does not write T, and BF/S reads T. Therefore the target branch is not taken here; the fall-through path is deterministic. SETT does not make the BF/S target unconditionally taken. The branch delay slot begins at `0x030AC3E6`.

## `0x34`, `0x58`, Sections 7/8

`0x0308F1C0` uses a `0x34`-stride candidate array at `0x0308F1FE`–`0x0308F210`. `0x030AC04C` uses a separate `0x58`-stride table at `0x030AC08A`–`0x030AC096`. No machine-code link from this cover consumer requires both structures to be rewritten for each MP0 edge. Whether either table or Sections 7/8 are required by some other load/route path remains UNKNOWN.

## Alleged direct write at `+0x40`

At `0x0306F532` the caller loads immediate `0x40` into r5; `0x0306F536` calls the producer; delay `0x0306F538 add r15,r5` forms a stack pointer `SP+0x40`. The same buffer base is passed as consumer r4 at `0x0306F542`–`0x0306F54E`. The producer writes at that buffer's +0x10/+0x11. This path does not show a field write at `cover+0x40`.

## Corrections to v46 replay scope

The old `replay.py` chose the candidate node fixture using the selector value, so endpoint-slot choice and mask-selector tests were coupled. It also tested fewer attribute values. v47 varies both dimensions independently over 240 cases. v46's PASS label established only the local bit predicate and caller return; it did not prove route selection. v47 reports the bounded offline result without a route-level PASS claim.

The v46 alias note places the second producer's bit-13 branch at `0x02FFBB82`. Direct re-disassembly shows `0x02FFBB82` is `ldc r8,GBR`; the actual `bt/s 0x02FFBBBA` is at `0x02FFBB88`, with the output+0x10 store in delay slot `0x02FFBB8A`. The `-2` store is at `0x02FFBBC0`.
