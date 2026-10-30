# Consumer call graph

## Confirmed path to the real candidate loop

```text
Section 5 record
  -> 0x02FFB92C producer
  -> stack cover at SP+0x40
  -> 0x0308C1F0 -> 0x0301EFE4 endpoint comparator
  -> 0x0306F484 returns -1 or 0
  -> 0x0303DCB0 tests that result
  -> 0x0303D670 skips or continues the current packed-ID candidate
```

The first call to `0x0308C1F0` from this path is at `0x0306F54C`. The parent `0x0303D670` calls `0x0303DCB0` at `0x0303D6F6`; the latter calls `0x0306F484` at `0x0303DCCC`.

## All resolved literal-pool call sites to `0x0308C1F0`

The 11 rows below were re-resolved from the Section 0 literal-pool bytes. Each call is an indirect `jsr @r0`; `r6` is the selector input at the call.

| Caller function | Call address | `r6` source visible at call | First result handling |
|---|---:|---|---|
| `0x03068D38` | `0x03068D7E` | `r10` | `r0` copied to `r4` in delay slot `0x03068D86`; `tst r4,r4` at `0x03068D8C`, then maps nonzero to -1 and zero to 0. |
| `0x0306F11C` | `0x0306F218` | `r11` | `0x0306F21C tst r0,r0`; `bf/s 0x0306F224`, delay sets -1, else sets 0. |
| `0x0306F484` | `0x0306F54C` | `r11` (original function `r5`) | `0x0306F550` / `0x0306F552`; nonzero returns -1, zero returns 0. |
| `0x0308C9BC` | `0x0308CA8C` | `r8` | `0x0308CA90 tst`; nonzero branches to `0x0308CA98`. |
| `0x0308D924` | `0x0308DAC2` | `r8` | `0x0308DAC6 tst`; nonzero branches to `0x0308DADE`. |
| `0x0308D924` | `0x0308DAD2` | `r13` | `0x0308DAD6 tst`; nonzero branches to `0x0308DADE`. |
| `0x0308F1C0` | `0x0308F20E` | `r11` | `0x0308F212 tst`; nonzero branches to `0x0308F21A`, zero branches away to `0x0308F286`. |
| `0x030904AC` | `0x03090552` | `r9` | `0x03090556 tst`; zero branches to `0x0309058A`, nonzero continues to another call. |
| `0x03090C00` | `0x03090CBE` | `r13` | `0x03090CC2 tst`; nonzero branches to `0x03090CE6`. |
| `0x03091914` | `0x030919A0` | `r9` | `0x030919A4 tst`; nonzero branches to `0x030919DE`. |
| `0x03094DF8` | `0x03094EE8` | `r13` | `0x03094EEC tst`; nonzero branches to `0x03094EBA`. |

This is the complete set of literal-pool references found in reachable PDATA functions in the recovered module. Calls through unresolved computed pointers or code outside the recovered module are not excluded.

The comparison path to `0x030AC04C` is separate: `0x030AB4D0` calls it with `bsr` at `0x030AB552`. No verified call edge links the `0x0306F484`/`0x0308C1F0` result path to that function. The separate output producer `0x0301FCD8` is called from `0x0301F984`; its output alias is the context temporary described in v46, not the replayed `SP+0x40` buffer.
