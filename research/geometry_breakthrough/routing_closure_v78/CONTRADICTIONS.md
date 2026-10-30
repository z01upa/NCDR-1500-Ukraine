# Evidence reconciliation

## Local artifacts present / absent

Present and read: `mask_producer_v48`, `route_closure_066`, `closure_v41`, `payload_consumers_v21`, `caller_v40`, `sh4_audit_051`. Absent at the requested paths: `cover_routing_v47`, `routing_engine_v77`, `route_closure_066` is present, `cover_xref_v46`, `consumer_trace_v22`, `qwen_redteam_063`. No claims from an absent report are treated as evidence.

## Conflict matrix

| Claim | Verdict | Direct check |
|---|---|---|
| `r8 == 0` calls `010AC72C` | REFUTED | `010AC160 TST; 162 MOVT; 164 TST; 166 BT/S 188`; exact test cases in `R8_REPLAY.json`. |
| `r8 != 0` calls `010AC72C` | CONFIRMED | `BT/S` takes only for nonzero r8 after the second `TST`; delay `010AC168` executes both ways. |
| Section 5 `+4/+5` become candidate exclusion bits | CONFIRMED, local scope | Original copy opcodes at `01068874/7C/7E/80`, consumer at `010AC75A–768`, caller seed `010AC192`, local skip at `010AC200–202`; differential replay. |
| Route-state writers for `+0x38/+0x3A/+0x3C/+0x44` were entirely unknown | NARROWED | `010AC5D8` writes `+0x38`; `010AC6C8` writes selected ordinal to `+0x3A`; `010AC6DA` writes the selected bit to `+0x3C`; `010AC6F2` replaces bits 12–14 in `+0x44`. Their semantic origin before this producer chain and actual request inputs remain UNKNOWN. |
| `cover+0x10/+0x11` and adjacency `+0x10/+0x11` are the same structure | REFUTED as a proven identity | Independent producer pointers and consumers; no alias/dataflow proof. Similar offsets are insufficient. |
| `caller_v40/COVER_CONSUMERS.md`: no consumer of cover `+0x10/+0x11` found | REFUTED as a complete inventory; ROUTING ROLE UNKNOWN | `0308C1F0` directly loads the selected cover byte at `0108C208`; its 11 callers are outside the demonstrated AC04C path. |
| C1F0 result reaches AC04C's R11 | UNKNOWN | 11 caller sites are outside AC04C; no direct call or result def-use into R11 found. |
| Section 5 mask changes final route availability | UNKNOWN | Local candidate skip is proven; full request state and final route result are not replayed. |
| No Section 7–9 record is needed for a new routable edge | UNKNOWN | The examined mask chain does not prove completeness of all route inputs. |

`DIFFERENTIAL_REPLAY.json` directly tests the requested fields. The tests only interpret the original SH4 slices and controlled in-memory state; they do not promote local branch effects into map-wide semantics.
