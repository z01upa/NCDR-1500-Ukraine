# CFG, inputs, T flag, and delay slots for `0x030AC72C`

## Inputs and result boundary

The visible caller at `0x030AC18A–0x030AC190` passes the current `r10` value in `r4`, a literal-pool pointer in `r5` (the `0x030AC190` delay slot), and a caller-stack value loaded into `r6`. The callee copies `r6` to `r8` as the loop bound, uses `r4` to establish `GBR`, and advances the `r5` record pointer by `0x34` per iteration. These are data-flow descriptions only; the higher-level meaning of the context, bound, and table is unknown. The result mask is returned in `r0`.

## Control-flow outline

```text
entry/setup
   -> initialize index and accumulated mask
   -> loop head 0x030AC74A
       ├─ index >= bound (T=0): 0x030AC74C -> exit 0x030AC794
       └─ process current 0x34-stride record
           ├─ first selected-bit path -> merge at 0x030AC790
           ├─ alternate attribute path -> optional mask-bit set
           └─ increment index and return to 0x030AC746
   -> return accumulated mask in r0
```

## T flag and branches

| T writer | T consumer | Meaning in this local CFG | Delay slot |
|---|---|---|---|
| `0x030AC74A cmp/gt r6,r8` | `0x030AC74C bf 0x030AC794` | Loop-bound check | None; plain `bf` |
| `0x030AC766 tst r3,r1` | `0x030AC768 bt 0x030AC774` | Selects the first local mask path | None; plain `bt` |
| `0x030AC784 tst r2,r0` | `0x030AC786 bf 0x030AC746` | Repeats while the tested local condition is false | None; plain `bf` |

Delayed transfers in this function:

- `0x030AC742 bra 0x030AC74A`: delay `0x030AC744 extu.w r0,r9`.
- `0x030AC770 bra 0x030AC790`: delay `0x030AC772 or r1,r4`.
- `0x030AC790 bra 0x030AC746`: delay `0x030AC792 nop`.
- `0x030AC79A rts`: delay `0x030AC79C mov.l @r15+,r8`.

The `bf`/`bt` branches listed above are not delayed forms. This function's local `r4` accumulator and `r5` `0x34`-stride records should not be conflated with the separate `0x030AC04C` `0x58`-stride table.
