# Phase 45 — physical MULCOORD nodes and descriptor collapse

Targeted recovery from the Moscow type-0x0E logical payload recovered all 483 original 24-byte objects. The anchor is exactly 8 bytes: BE32 `hlon` followed by BE32 `hlat`; the decoder is `lon=hlon/5555555-30`, `lat=hlat/5555555`.

There are 102 unique raw 8-byte physical nodes. Grouping collapses 483 objects into 102 nodes; 79 nodes have multiple object records and 67 are used by multiple roads. The raw grouping reproduces the repeated decoded-coordinate groups with no observed coordinate/raw-byte exception. Physical nodes can carry up to 22 distinct `(target,ptr)` descriptors.

After collapsing consecutive duplicate physical nodes, the graph has 114 edges, 22 connected components, and a largest component of 11 nodes. This is smaller and more coherent than the Phase 44 descriptor graph (298 edges, 102 components, largest 16), but it is not a proof of road-network completeness.

The descriptor variants at a physical node are not explained by one exact A/B/C/D relation. Across 114 collapsed transitions the strongest equality is D(P)==D(Q), 56/114 (49.1%); C(P)==C(Q) is 51/114 (44.7%). No selected raw32 field match was established. F, E flags, and Z/NZ do not yet yield a repeatable topology rule; Phase 41 class coverage is incomplete for most descriptors.

The `1 iy mikrorayon` control remains a one-object road and maps to one physical node/descriptor. No detailed-geometry link was identified. The strongest confirmed result is that raw MULCOORD is a much better physical-node key than `(target,ptr)`; descriptor semantics remain unresolved.
