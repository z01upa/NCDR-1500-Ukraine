# Routing XREF index — bounded evidence

| Source | Target | Transfer | Evidence | Status |
|---|---|---|---|---|
| `0x030AB4D0` at `0x030AB552` | `0x030AC04C` | direct `bsr` | [consumer call graph](CONSUMER_CALL_GRAPH.md) | Confirmed; separate `0x58`-stride table path |
| `0x0301F984` | callback pointer at context `+0x3C` | indirect | [callback targets](CALLBACK_TARGETS.md) | Call site confirmed; target body/meaning unknown |
| `0x0301F984` | callback pointer at context `+0x40` | indirect | [callback targets](CALLBACK_TARGETS.md) | Distinct call site; target body/meaning unknown |
| `0x01000E2C` at `0x01000E34` | `0x01000E50` | direct `bsr` | [Section 7/8 consumers](SECTION789_CONSUMERS.md) | Wrapper call confirmed; upper caller not identified in bounded search |
| `0x01000E40` at `0x01000E44` | `0x01000E50` | direct `bsr` | [Section 7/8 consumers](SECTION789_CONSUMERS.md) | Wrapper call confirmed; wrapper was not executed in paired test |
| 11 listed call sites | `0x0308C1F0` | indirect `jsr @r0`, target resolved from literal pool | [consumer call graph](CONSUMER_CALL_GRAPH.md) | Bounded static resolution; callers and result handling listed there |

The two `0x0301F984` callbacks are not the `SP+0x40` cover buffer passed through the `0x0306F484` path. No verified call-graph path links `0x030AC04C` to the `0x0308C1F0` return path.

The Astra-022 search did not identify an upper caller of `0x01000E2C` in the recovered call/literal indexes or bounded aligned `BRA`/`BSR` range. This is not proof of unreachability: computed pointers, indirect tables, other modules, and runtime dispatch remain unresolved. See [Astra-022 evidence](../consumer_trace_v22/EVIDENCE.md).
