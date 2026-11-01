# NCDR-CODEX-ROUTING-061 — sanitized evidence summary

## Confirmed within the offline replay

- The producer forwards Section 5 edge bytes +4 and +5 into cover bytes +0x10 and +0x11. The consumer chooses one byte from endpoint comparison, then tests the selected bit using the caller-provided selector.
- For the selected bit, the consumer returns `0xFFFFFFFF` when set and `0` when clear. In the caller chain, nonzero skips the current packed block/edge candidate. This is a local candidate filter, not evidence of a global road prohibition or a route-cost rule.
- The v47 matrix ran 240 cases: three sampled real records, two independent attribute bytes, five test values, four selector values, and two endpoint-match conditions. The consumer/caller returned `-1` in 63 cases and `0` in 177 cases. The three bit-13-only cases returned `-1` once and `0` twice.
- Bit 13 changes the producer's cover `+0x18` status in this replay; its higher-level meaning remains unknown.
- The raw replay is retained locally. This published summary omits record identifiers, source-derived record values, memory snapshots, instruction bytes, and trace data.

## Limits

- Offline pypcode replay only; external calls are explicitly modeled where documented.
- The forward slice injects the returned status at the first caller boundary because the upstream context setup is not fully reconstructed.
- No complete route search, physical device, map acceptance, direction semantics, or Writer behavior was tested. Writer, MP0, and firmware were not changed.
