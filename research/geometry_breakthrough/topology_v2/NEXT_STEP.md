# Next step toward a new edge

Do not extend Writer yet. The insertion gate found an eligible test pair in block 886, but a correct MP0 edge cannot be specified safely.

1. Trace the firmware reader for Section 4 records, beginning with a degree-5 record and its same-coordinate neighbor (block 1 nodes 283–284). Recover byte `+1`, the high nibble, duplicate-coordinate identity, and the overflow/continuation structure.
2. Trace Section 5 consumers for `attributes @+2`, `unresolved @+4`, and flag bits other than `0x1000`, `0x2000`, and `0x8000`. Establish routing direction/access from controlled firmware behavior or independently labeled routes; do not infer it from XORs or duplicate geometry.
3. Identify what Sections 7, 8, and 9 index and whether any rows point to Section 5 edge IDs. Their observed record widths are 7, 11, and 13 bytes respectively when populated, but their semantics are unknown.
4. Revisit the block 886 pair (nodes 412 and 414) only after the above is known. Their current +8/+9 words are 518 and 271. Across all 281,608 records with degree nibble 3, that word is nonzero in 280,356 cases and matches a local incident edge ID in 2,650; prove its read/update semantics before replacing either.
5. Then mutate a copy, add exactly one edge, update all proven dependencies, and run both the topology validator and an independent Reader. The experiment must still be labeled non-routable until its edge attributes and firmware behavior are confirmed.
