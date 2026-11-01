# Result forward slice

## First complete caller decision

For the `0x0306F484` caller path:

1. `0x0308C1F0` returns `0xFFFFFFFF` if the selected bit is set; otherwise it returns 0.
2. `0x0306F550 tst r0,r0`; `0x0306F552 bf/s 0x0306F558`. The delay instruction `0x0306F554 mov #-1,r0` makes a nonzero consumer result return -1. A zero result falls through to `0x0306F556 mov #0,r0`.
3. `0x0303DCCC` calls `0x0306F484`. At `0x0303DCD0 tst r0,r0`, nonzero branches to `0x0303DD94 mov #-1,r0` and returns -1. Zero falls through to subsequent checks at `0x0303DCD4`.
4. `0x0303D670` calls `0x0303DCB0` once per list index (`r13`). At `0x0303D6FA tst r0,r0`, nonzero takes `0x0303D6FC bf/s 0x0303D7D0`; delay `0x0303D6FE mov r0,r12` runs, and `0x0303D7D0` branches back to `0x0303D6BC`. Its delay `0x0303D7D2 add #1,r13` advances to the next candidate. Thus -1 skips the current packed block/edge item in this procedure. Zero continues with that item's later processing.

The first step's mask predicate is confirmed; the third and fourth steps establish its local caller effect. The local effect is candidate filtering, not proof that every navigation subsystem globally forbids that road edge.

## Reproducible result-boundary replay

The actual `0x0306F484` replay produced both statuses from original edge records. The script then injected each value at the first caller instruction after return, because the preceding runtime object setup for `0x0303DCB0` is not fully reconstructed:

- `-1`: `0x0303DCD0` → `0x0303DCD2` → `0x0303DD94`, returns -1. At the `0x0303D670` boundary, `0x0303D6FC` → `0x0303D7D0`; the delayed increment leaves `r13=1` before the loop recheck.
- `0`: `0x0303DCD0` → `0x0303DCD2` falls through to the next validations.

This isolated boundary replay does not claim a full invocation of `0x0303D670` or an end-to-end route search. The exact inputs, traces, and limitations are recorded in `DIFFERENTIAL_REPLAY.json`.
