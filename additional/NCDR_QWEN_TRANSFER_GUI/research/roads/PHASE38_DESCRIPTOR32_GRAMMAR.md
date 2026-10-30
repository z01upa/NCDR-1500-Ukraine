# Phase 38 — type-0x00 32-byte descriptor grammar

The confirmed result remains the per-target slot lattice from Phase 37: for all 23 readable targets, known pointers satisfy `ptr = base_target + 32*slot_index`, with `base_target` equal to the minimum known pointer for that target. This is not a global table base and does not establish the physical table start/end.

The current workspace contains the original 101-object reference CSV, while the 10,615 saturated references were summarized but not saved as a row-level dataset. Therefore a complete 2,458-slot field census, intermediate-slot classification, and geographic spread computation cannot be reproduced from the saved artifacts without rerunning the targeted saturation pass.

No deterministic boundary transition, semantic BE16/BE32 field, internal pointer, coordinate component, or F relation is proven. The 32-byte records remain descriptor-like. The 71 F-exception groups from Phase 37 remain unexplained; no geometry interpretation is claimed.

Next exact step: persist the full 10,615-row saturation output, then compute field statistics and boundary scans from that complete set.
