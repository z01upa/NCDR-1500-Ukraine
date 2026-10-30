# CONSUMER EVIDENCE

## Static def-use evidence

Producer instructions and consumer/caller chain are listed with exact VAs in `COVER_ALIAS_GRAPH.md`. Key behavior:

- `0x02FFB9BE` loads the first u32 edge word; shift at `0x02FFB9C4` by -13, `and #1` at `0x02FFB9CA`, compare at `0x02FFB9CC`; `bt/s 0x02FFBA06` at `0x02FFB9D4`. Its delay instruction at `0x02FFB9D6` still writes edge+4 to output+0x10. The edge+5 store at `0x02FFB9D0` precedes this test.
- consumer `0x0308C1F0`: converter call at `0x0308C200` with delay slot `0x0308C202`; byte read at `0x0308C208`; selected mask constructed by `shad` at `0x0308C210`; `tst` at `0x0308C212`; `bt/s` at `0x0308C214` with `mov #-1,r0` delay at `0x0308C216`; returns `-1` if selected bit is set, `0` otherwise.
- caller `0x0306F484` calls the producer at `0x0306F536`, then consumer at `0x0306F54C`; `tst` `0x0306F550` and `bf/s` `0x0306F552` (delay `mov #-1,r0` at `0x0306F554`) return `-1` when consumer returns -1, otherwise set return to 0 at `0x0306F556`.

The static chain proves output alias and an observable caller result, not that these attribute bits encode a universal navigation rule or identify their real-world meaning.

## Reproduction

The replay matrix, exact per-run values, execution boundary, and commands are in `DIFFERENTIAL_REPLAY.md`; key outputs and caller register snapshots are in `replay_summary.json`; full local traces are in `replay_results.json`.
