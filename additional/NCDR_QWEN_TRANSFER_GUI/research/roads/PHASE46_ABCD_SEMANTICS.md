# Phase 46 — A/B/C/D semantics

The 10,615 persisted road references do not support A/B/C/D as ordinary bounding-box corners. `C-A` ranges from -32766 to 32765 and is nonnegative in 57.44%; `D-B` ranges from -32766 to 32765 and is nonnegative in 59.69%. Exact `C=A` and `D=B` each occur 22.25%; `C=A+1` and `D=B+1` occur only 6.07% and 6.14%.

The fields are strongly structured as even-valued local/index-like quantities: B-A is always nonnegative (0..122), and D-C is always nonnegative (0..84), with zero in 58.24% and 60.83% respectively. This is not enough to assign a coordinate-grid meaning.

At the 102 exact raw physical nodes, A/B/C/D are constant across all descriptors only at 34.3%, 32.4%, 37.3%, and 34.3% respectively; the fields therefore vary substantially by descriptor/caller. At identical `(target,ptr)` groups, no stronger node identity was established.

The apparent count coincidence is structurally exact in this sample: 102 physical nodes map to 102 type-0x00 targets, with every target associated with exactly one physical node and every physical node with one target. This is a 1:1 mapping in the recovered Moscow data, not evidence that A/B/C/D encode coordinates.

Aligned BE16 searches in the selected raw32 slots are rare: A 29/10,615, B 43/10,615, C 44/10,615, D 55/10,615. No exact contiguous A/B/C/D pair rule is established. On 114 collapsed physical-node edges, the strongest equality is D(P)==D(Q), 69/114 (60.5%), followed by C(P)==C(Q), 62/114 (54.4%); these are not unique enough to identify topology.

Conclusion: A/B/C/D are most consistent with caller-local index/range or topology metadata, not proven coordinate/grid fields. Detailed geometry and exact field semantics remain unresolved.
