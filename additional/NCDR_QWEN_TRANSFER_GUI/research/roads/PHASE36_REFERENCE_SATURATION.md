# Phase 36 — road-reference saturation

The 23 readable target BL_ADDRs from Phase 33 were searched across all 861 type-0x0E logical blocks. Hits were accepted only when the target BL_ADDR occurred at object+0x10, the preceding bytes decoded to a plausible MULCOORD anchor, E/F were present, E&0x3FFF was in-bounds and 4-byte aligned, and the location was inside a type-0x0E payload.

Result: 10,615 accepted road-object-layout hits, 2,458 unique `(target,ptr)` pairs, across all 23 targets. This is a large expansion from the Phase 35 sample of 101 objects and 74 distinct-pointer deltas. The reverse search is structurally broader than the named Moscow road list, so road-name recovery is unavailable for most hits.

Across sorted unique pointers, there are 2,435 adjacent deltas, range 32..2,592 bytes, gcd 32. The most common deltas are 32 (652), 64 (445), 96 (332), 128 (238), 160 (184), 192 (130), and 224 (99). This establishes a strong 32-byte pointer lattice in the saturated reference set, but does not by itself prove record width.

For each unique `(target,ptr)`, F is identical across references in 97.1% of groups; 2.9% have multiple F values. Thus F is strongly associated with the pointed region but is not proven to be an intrinsic record length/count. Same-target road continuity is retained in the raw reference CSV only as object order where available.

The strongest new fact is the 32-byte pointer lattice. A universal descriptor signature or additional local subpointer was not proven, so geometry decoding remains deferred.
