# Next technical step

Resolve the write dependencies for **one existing degree-3 node becoming
degree 4**, then return to adding an edge. The best frozen test case is block
886, nodes 412 and 414: each has three proven active links, they are not
already joined by a local primary edge, and their next u16 values (+8/+9) are
nonzero (518 and 271).

1. In `NAVIMAIN.EXE` and the relevant NK.BIN code paths, locate the consumer
   that reads a 10-byte Section 4 node. Confirm whether it reads beyond the
   degree-selected references and decode the high-degree/overflow encoding.
2. Trace Section 5 field consumers to establish a valid ordinary edge record:
   flags beyond coordinate selectors/shape bit, attributes, unresolved word,
   and direction/access/routing behavior. Use read-only code/data evidence and
   independent known-road examples; do not infer values from frequency alone.
3. Identify Section 6 ownership and trace Sections 7/8/9 edge-index-shaped
   keys to their consumers. Determine which records must be inserted, shifted,
   or re-keyed when one edge ID is appended.
4. Decode `EUZ.RT` type 22 and establish whether it carries routing state or is
   unrelated metadata. Do not infer that relationship from its filename.
5. Once these rules are independently confirmed, extend the insertion gate to
   a single copied block. Preserve opaque fields and use Writer v1 only for
   final container assembly. Require independent full-container readback and
   unchanged-byte proofs before retaining an experimental MP0.

Until those items are proven, the specific blocker is safe adjacency growth:
the degree-3 node records have nonzero fourth words, and the new Section 5
record needs unassigned routing fields. No output MP0 with a new edge should
be emitted yet.
