# `0x030AC04C` decision notes

This is a focused correction record, not a publication of the full function disassembly.

## `r11` mask and branch at `0x030AC076–0x030AC07C`

- `0x030AC076 cmp/eq r1,r4` writes T.
- `0x030AC078 mov #1,r11` is the `bf/s` delay instruction.
- `0x030AC07A bf/s 0x030AC108` reads the T value from the compare.
- `0x030AC07C and r11,r8` executes as the delay slot on either branch outcome and masks `r8` with the constant one.

The branch decision is therefore based on the compare, not on the value produced by the `and` delay slot. The input data producer and higher-level meaning of the masked `r8` value are not resolved.

## `sett` / `shlr2` / `bf/s` correction

At `0x030AC3E0`, `sett` sets T=1. `0x030AC3E2 shlr2 r6` shifts `r6` and does not change T. `0x030AC3E4 bf/s 0x030AC40C` reads T and is not taken; the delay instruction at `0x030AC3E6 and r1,r6` still executes before fall-through. It is incorrect to describe `sett` as making this `bf/s` target branch taken.

## Separate structures and unresolved producers

- `0x0308F1C0` advances a candidate array with `0x34` stride.
- `0x030AC04C` indexes a distinct table with `0x58` stride; `0x030AB4D0` calls it at `0x030AB552`.
- The recovered call/result chain for `0x0308C1F0` does not establish that either structure is required alongside the other, or that either is the same as Sections 7/8.
- The producers, ownership, record semantics, and connection of the `0x58` table to MP0 edge attributes remain `UNKNOWN`. No `REQUIRED`/`OPTIONAL` conclusion is supported for Sections 7/8.
