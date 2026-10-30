# Phase 47 — node-to-node edge links

The 102 physical-node/type-0x00 1:1 mapping is retained. Phase 45 supplies 114 collapsed transitions, representing 74 unique directed physical-node pairs. The selected Phase 41 raw32 dataset contains both endpoint slots for only 9/114 transitions; this limits descriptor-byte tests and is recorded explicitly.

No selected P raw32 contains the Q target sector, full BL_ADDR, low16 sector, or the tested target ordinal forms. No reciprocal block reference was proven. The best raw byte/BE16 equality across endpoint descriptors is only 9/114 (7.9%) and is driven by the limited readable subset; no repeatable shared edge ID is established.

Coordinate-delta tests likewise show no stable encoding: the best tested two-byte shifted match is 32/558 field comparisons (5.7%), with no common scale/offset rule. No reciprocal ptr/slot relation or secondary geometry pointer was identified.

The 74 unique physical edges are therefore graph transitions inferred from ordered road ownership, not decoded type-0x00 links. Descriptor-per-neighbor behavior, D(P)==D(Q) semantics, and detailed geometry remain unresolved.
