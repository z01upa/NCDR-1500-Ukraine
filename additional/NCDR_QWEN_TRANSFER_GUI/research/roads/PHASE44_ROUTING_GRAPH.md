# Phase 44 — routing node/edge semantics

Using the persisted Phase 43 ownership table, there are 413 unique candidate nodes `(target_sector,ptr)`, 70 used by multiple roads, and 298 consecutive transitions between different node IDs. The undirected graph has 102 connected components; its largest component has 16 nodes. Degree is 204 nodes of degree 1 and 142 of degree 2 in the connected graph.

All 184 consecutive transitions with identical decoded coordinates nevertheless have different node IDs. Thus equal anchors do not prove a shared routing node; they are compatible with separate edge/direction/variant records at one coordinate. Exact original MULCOORD-byte identity was not available in the persisted export, so only decoded-coordinate equality is claimed.

The 4x4 A/B/C/D adjacency test has no exact field grammar. The strongest relation is C[N]==C[N+1], 105/298 (35.2%); D[N]==D[N+1] is 94/298 (31.5%). Searching the 101 available Phase 41 raw32 slots found none of A/B/C/D at aligned BE16 offsets. F and E flags remain nonsemantic under these tests.

Shared-node class coverage is incomplete: of 70 multi-road nodes, only four are in the Phase 41 lattice and all four are Z; 66 are outside that persisted 23-target subset. Therefore no reliable Z/NZ graph-role difference is established. The candidate node hypothesis remains plausible as an indexing model, but routing-node semantics are not proven.
