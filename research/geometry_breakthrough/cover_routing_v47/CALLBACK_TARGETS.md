# Callback targets and context objects

## `0x0301F984` callback pair

The function invokes two distinct indirect callback pointers stored at `context+0x3C` and `context+0x40`. It passes the output object produced by `0x0301FCD8` at `context+0x4C` into these callbacks.

| Context slot | Relationship | Established | Unknown |
|---|---|---|---|
| `+0x3C` | First indirect callback invoked from `0x0301F984` | Call site and pointer slot | Runtime target, callback body, whether it reads output `+0x10/+0x11` |
| `+0x40` | Second indirect callback invoked from `0x0301F984` | Distinct call site and pointer slot | Runtime target, callback body, whether it reads output `+0x10/+0x11` |
| `+0x4C` | Output object produced by `0x0301FCD8` | Producer-to-object relationship | Full consumer chain and semantics |

## Keep stack and context objects separate

`SP+0x40` is a separate stack buffer in the `0x0306F484` call path. The producer at `0x02FFB92C` fills it and `0x0308C1F0` consumes it. It is not either callback pointer at `context+0x3C/+0x40`, and it is not the context output object at `context+0x4C`.

No callback-body behavior or field meaning is inferred from the matching offsets. See the [v46 alias evidence](../cover_xref_v46/COVER_ALIAS_GRAPH.md) and [bounded routing XREF index](ROUTING_XREF_INDEX.md).
