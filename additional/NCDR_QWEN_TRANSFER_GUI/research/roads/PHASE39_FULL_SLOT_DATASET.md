# Phase 39 — full road-reference dataset and slot boundaries

The targeted reverse search was rerun across all 861 type-0x0E blocks using the 23 readable type-0x00 BL_ADDRs and the confirmed 24-byte object validation rules. The complete row-level dataset contains 10,615 validated references, 2,458 unique `(target_sector,ptr)` slots, and all 23 readable targets, exactly reproducing Phase 36.

For each target, all known pointers occupy one target-specific residue class modulo 32 and have delta gcd 32. The global minimum-pointer base is not a valid shared table base; each target has its own phase. Across 8,299 intermediate 32-byte positions inside known gaps, 4,880 (58.8%) match the dominant referenced-slot zero-mask signature. The remainder are structurally different or uncertain. This supports a 32-byte lattice with skipped/nonuniform content, but does not prove true table start/end boundaries.

The persisted unique-slot field census shows offset `+0x10` is zero in 93.53% of known slots; other fields have broad value ranges and no exact caller-field equality was established. No semantic node/edge/coordinate field or internal pointer is confirmed. F is invariant for 2,387/2,458 groups (97.1%); 71 groups vary and are listed in `phase39_f_exceptions.csv`.

Same-road rows are persisted in `phase39_same_road_sequences.csv`. Road names are unavailable for the expanded reverse hits, so geographic anchor clustering is based on coordinates rather than recovered names. No polyline or geometry decoder is attempted.

Next exact unresolved item: determine whether the 41.2% nonconforming intermediate slots are padding/other records or a second descriptor grammar, then prove table boundaries.
