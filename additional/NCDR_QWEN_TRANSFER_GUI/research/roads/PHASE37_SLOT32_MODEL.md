# Phase 37 — fixed 32-byte type-0x00 slot model

For every one of the 23 readable targets, let `base` be the minimum distinct referenced pointer for that target. Every known pointer satisfies `(ptr-base) % 32 == 0`. This is exact across all 2,458 unique target/pointer pairs; the base is target-specific, not global. Thus ptr selects a fixed 32-byte slot lattice within each target block.

The first inspected slots are 32-byte records with repeated internal structure. Larger pointer gaps are consistent with skipped/unreferenced slot positions, but intermediate slots were not exhaustively classified as valid records in every target. Slot extraction is therefore structurally valid for known pointers; unreferenced-slot semantics remain open.

The strongest field pattern in the sample is a repeated 32-byte descriptor-like record, not an obvious coordinate payload. No aligned BE16/BE24/BE32 field achieved sufficient cross-target evidence as a secondary local pointer to claim a two-level geometry structure. Same-slot anchors require full saturated caller grouping for geographic interpretation; no geometry decoder is claimed.

F remains mostly invariant by `(target,slot)` (97.1%) but has 71 exception groups. Those exceptions are not explained by slot bytes alone in the current evidence and may be caller-side semantics or false-positive layout hits.
