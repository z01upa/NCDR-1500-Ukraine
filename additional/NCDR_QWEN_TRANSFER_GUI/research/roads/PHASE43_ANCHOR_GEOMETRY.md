# Phase 43 — 24-byte object anchors

Analysis used the persisted Moscow 0x0E ownership list: 185 roads and 483 ordered objects, with 114 roads having at least two objects and 298 consecutive transitions. No database object rescan was performed.

The ordered anchor sequences are not generally usable road polylines. The median consecutive distance is 0 m because repeated anchors are common; p90 is 2,218.17 m and maximum is 6,004.36 m. The broad jumps and repeated coordinates support routing/control nodes or duplicated directional records, not detailed geometry. A random-control comparison was not persisted in the prior dataset and is therefore not claimed as a completed quantitative result.

The known `1 iy mikrorayon` road has one object at 37.20529056, 56.00748080, so it has no consecutive geometry test.

There are 70 shared `(target,ptr)` slots among these roads. Where the Phase 41 class is available, shared slots are Z=4 and NZ=0; 66 shared slots are outside the 23-target Phase 41 lattice and cannot support a Z/NZ rate. Shared slots have identical anchor coordinates by construction of the persisted per-slot invariant. A/B/C/D show no proven adjacency grammar: the strongest equality is C[N]==C[N+1] at 105/298 (35.2%), followed by D[N]==D[N+1] at 94/298 (31.5%).

Conclusion: anchors are best classified as sparse routing/control nodes or duplicated edge records; detailed road shape, if present, is elsewhere. Shared-slot node semantics and the complete type-0x00 consumer remain unresolved.
