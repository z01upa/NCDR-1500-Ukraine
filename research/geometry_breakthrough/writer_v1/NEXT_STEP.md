# Next step before adding a new road edge

Writer v1 proves a full-file rewrite for one existing shape-bearing edge. Adding a new edge still requires recovering and independently validating these structures:

1. **Node/adjacency section 4:** the meaning of each 10-byte node record, complete adjacency references, degree greater than two, node insertion order, and every index that must be shifted when adding a node.
2. **Edge section 5:** semantics of `attributes` and `unresolved`, all endpoint-table combinations, edge identity, and the supported way to create reciprocal/directed records. The `0x3000` XOR observation is not evidence of a reverse-edge operation.
3. **Coordinate tables 0 and 2:** primary/secondary membership rules, deduplication, endpoint index allocation, and changes required across block borders.
4. **Shape tail section 10:** per-edge shape-span ownership, all offset/count update cases, and capacity behavior when the tail or decompressed block exceeds u16 limits.
5. **Block index/container:** how to allocate a new block, choose its bbox, grow the 24-byte entry table and opaque `4*N` pre-payload region, preserve physical stream ordering, and update all absolute pointers.
6. **Names and routing metadata:** section 6 text record ownership/encoding, route class and access semantics, and the verified firmware lookup path that links names and edge records.
7. **Length semantics:** trace the feet conversion and rounding rule in firmware, and classify all known exceptional edges before any bulk recalculation.

The critical blocker is safe topology insertion: without section 4 adjacency semantics and section 5 edge identity/direction semantics, a new road could decode but remain unroutable or corrupt neighboring topology. The next experiment should use copies only and target one synthetic node/edge insertion after those fields are resolved. Physical Opel acceptance remains a separate later test.
