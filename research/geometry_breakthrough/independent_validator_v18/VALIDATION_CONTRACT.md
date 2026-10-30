# MAC-018 contract
Accept original MP0 and candidate MP0. No output map is produced. Existing node, edge and block IDs must retain identity; only appended IDs are supported. Reindexing is outside this contract and cannot pass by matching coordinates alone.

Each JSON rule has PASS/FAIL/UNKNOWN, observation/failure/unknown counts and up to 12 example failures. Exit 0 means all comparative local rules PASS; 1 means at least one FAIL; 2 means UNKNOWN without FAIL. Hardware compatibility is always UNKNOWN. A successful original/original comparison is a control, not evidence of insertion safety.

Checks reuse topology_v6/topology_decoder.py and independent_verify.py without modification or any Writer import: container stream coverage, zlib and indexed sizes, section bounds, node continuation rules, physical endpoint IDs, adjacency incidence, orientation by ordered adjacency slot, 12-bit local-ID capacity, shape offsets, coordinates and old edge geometry. Existing non-mask edge fields, old opaque bytes still inactive, byte1 at low degree, high-degree upper nibble, unknown sections and the opaque file index region must be preserved. Section 7/8/9 counts must fit 7/11/13-byte stored records respectively.

Any degree change remains UNKNOWN for newly consumed opaque storage. Every old edge incident on changed adjacency gets transition_mask_reindex=UNKNOWN, even if its mask bytes are unchanged. Unaffected edges must preserve +4/+5 exactly. Every appended edge gets new_transition_masks=UNKNOWN until the bit-to-turn binding and endpoint orientation proof from Lenovo is supplied. No arbitrary mask value can earn PASS merely because it fits one byte.

Sections 1/3/6/7/8/9 must remain byte/count identical under this conservative contract. A change FAILs preservation; unchanged sections still leave their semantic insertion dependencies UNKNOWN whenever an edge is added. RT/RL and new cross-block identity remain UNKNOWN. Border two-copy multiplicity and existing signatures are checked, but do not prove remote identity for a new edge.

Lenovo handoff: send original MP0, the modified MP0, and the MAC-017/transition-mask evidence including instruction addresses and before/after node ordering. Run this validator first. Do not treat UNKNOWN as permission to release a map. An explicit old-to-new identity mapping and an extended proof are required before supporting reindexing.
