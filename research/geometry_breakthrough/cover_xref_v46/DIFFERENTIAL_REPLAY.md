# DIFFERENTIAL REPLAY

`replay.py` replays actual recovered SH4 instructions through the existing pypcode-based minimal interpreter. Input edge index 0 is read from original block 886; the test creates in-memory copies and changes exactly one byte/bit per case. Assertions check the routine path, output bytes, dependent fields, real converter/consumer result, and caller return path. The original MP0 is read-only.

| Case | Change from original | `cover+0x10/+0x11` | `cover+0x14` | `cover+0x18` | consumer / caller result, selector 0 then 1 |
|---|---|---|---|---|---|
| Baseline | none | `00 / 00` | `0x0037628A` | `0x0037628B` | `0/0` |
| A | `edge+4 XOR 1` | `01 / 00` | unchanged | unchanged | `-1/0` |
| B | `edge+5 XOR 2` | `00 / 02` | unchanged | unchanged | `0/-1` |
| C | first u32 bit13 XOR | `00 / 00` | unchanged | `0xFFFFFFFE` | `0/0` |

Both `0x02FFB92C` and `0x02FFBB00` show the same A/B forwarding effect and C's `cover+0x18` effect. A/B retain baseline producer branch traces. C follows the alternate branch at `0x02FFB9D4` / `0x02FFBB82`; delay slots `0x02FFB9D6` / `0x02FFBB8A` still store `edge+4` to `cover+0x10`.

The real caller path starts at its stack lookup `0x0306F52A`, with a one-item stack array containing the packed block/edge identifier. This executes caller callsite `0x0306F536`, the producer, caller callsite `0x0306F54C`, `0x0301EFE4`, `0x0308C1F0`, and the return branch through `0x0306F556`. The public `replay_summary.json` snapshots show producer-entry `r4=0x00376000`, `r5=SP+0x40`, and consumer-entry `r4=SP+0x40`, `r5=SP+0xA8`, `r6=selector`. This proves same-buffer alias in replay.

Run from the project root:

```sh
research/geometry_breakthrough/module_recovery_v13/.venv/bin/python research/geometry_breakthrough/cover_xref_v46/scan_xrefs.py
research/geometry_breakthrough/module_recovery_v13/.venv/bin/python research/geometry_breakthrough/cover_xref_v46/replay.py
```

`replay_summary.json` preserves the per-case outcomes and key register snapshots. `replay_results.json` keeps the full local instruction traces and source-derived buffers for exact reproduction; it is not part of the GitHub upload. The test stubs lock/unlock, block load, a length helper, and a division helper; see `UNKNOWN_BLOCKERS.md`. The actual converter and selected-bit consumer are executed without stubs. This is offline isolated execution, not complete navigation or physical-device validation.
