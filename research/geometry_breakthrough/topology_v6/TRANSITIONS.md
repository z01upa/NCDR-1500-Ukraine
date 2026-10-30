# Degree-transition contract — no unsafe writes

##3->4
CONFIRMED adjacency-layout changes:
1. Change only byte0 low nibble from3 to4.
2. Keep existing ordered references at+2,+4,+6.
3. Fourth edge ID would occupy+8/+9.

BLOCKER: existing+8/+9 are UNKNOWN semantic data, often nonzero. They are not demonstrated free space. High nibble and byte1 may also depend on degree/order/turn constraints. `transition_plan()` returns allowed=false, lists the affected fields and preserves the bytes. An attempted degree-only change through the lossless serializer fails opaque-span validation.

##4->5
CONFIRMED adjacency-layout changes, preserving old link order:
1. Degree nibble4->5.
2. Representation expands10->20bytes. Insert an immediately following10-byte continuation.
3. Old refs e0,e1,e2 move from+2/+4/+6 to+4/+6/+8.
4. Old e3 moves from head+8 to continuation+0; new e4 would be continuation+2.
5. Head+2/+3 becomes UNKNOWN; continuation+4..9 also needs UNKNOWN initialization.
6. Existing corpus aligns continuation physical slots with duplicated primary coordinates. Physical node/coordinate count increases by1. Later physical IDs shift, requiring all dependent endpoint indices to be revised. A future Writer must prove all consumers, not just the known Section5 primary fields.

BLOCKER: no justified initialization for unknown bytes or routing/header masks; cross-section/sidecar dependencies unresolved. No20-byte record is fabricated and no MP0 is written.

## In-memory experiments actually performed
- Degree5 active-edge permutation: swap two known u16 link fields only; serialized byte differences remain within those active slots, opaque prefix/suffix are identical, unordered incidence remains identical, and reversing the swap restores original bytes.
- This is ONLY an abstract adjacency preservation test. It does not claim turn permissions or runtime routes survive a link-order permutation.
- Replace one degree6 link with a different in-range edge: the independent Section5 endpoint oracle detects incorrect adjacency.
- Attempt3->4 or4->5 while retaining existing opaque spans: serializer rejects the invalid representation; original Section4 remains byte-identical.
- Unsupported degree0 head and missing continuation are rejected.

Modified buffers exist only in test memory. Saved fixture files contain unmodified original decoded blocks. No new MP0, geometry edit, edge insertion or production-module change occurred.
