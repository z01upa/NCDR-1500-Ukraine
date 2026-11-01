# NCDR 1500 research — start here

This repository is a research record, not a firmware or map distribution package. Use the [repository rules](../AGENTS.md), [full research index](../docs/RESEARCH_INDEX.md), and [known unknowns](../docs/KNOWN_UNKNOWNS.md) before changing analysis code.

## Current bounded findings

1. The v47 offline replay confirms a local selected-bit filter: the `0x0308C1F0` result can skip the current packed candidate in its traced caller path. It does not establish a route-wide prohibition, direction rule, or cost. Start with [sanitized evidence](geometry_breakthrough/cover_routing_v47/EVIDENCE.md) and [result forward slice](geometry_breakthrough/cover_routing_v47/RESULT_FORWARD_SLICE.md).
2. The static consumer XREF list and separate `0x030AC04C` path are in the [consumer call graph](geometry_breakthrough/cover_routing_v47/CONSUMER_CALL_GRAPH.md) and [routing XREF index](geometry_breakthrough/cover_routing_v47/ROUTING_XREF_INDEX.md).
3. The `context+0x3C`, `context+0x40`, and `context+0x4C` relationships are distinct from the replayed `SP+0x40` stack buffer; see [callback targets](geometry_breakthrough/cover_routing_v47/CALLBACK_TARGETS.md).
4. A short function listing, explicit CFG/T/delay-slot notes, and a read-only pypcode check cover `0x030AC72C–0x030AC79E`: [assembly](geometry_breakthrough/cover_routing_v47/FUNC_030AC72C_ASM.md), [control flow](geometry_breakthrough/cover_routing_v47/CFG_T_AND_DELAY_SLOTS.md).
5. Section 7/8 wrapper evidence leaves table requirements unresolved; see [consumer status](geometry_breakthrough/cover_routing_v47/SECTION789_CONSUMERS.md) and the already published [Astra-021](geometry_breakthrough/consumer_trace_v21/EVIDENCE.md) / [Astra-022](geometry_breakthrough/consumer_trace_v22/EVIDENCE.md).

## Publication boundary

Original maps, firmware, recovered section images, raw instruction dumps, and full replay traces remain local. The published call graph is a metadata projection with only function/call-site/target relationships; see its [schema and coverage](geometry_breakthrough/cover_routing_v47/CALL_GRAPH_INDEX.md) and [withheld-materials list](geometry_breakthrough/cover_routing_v47/MISSING_BINARY_EVIDENCE.md).

No Writer, MP0, firmware, or hardware state was changed or tested by this evidence update.
