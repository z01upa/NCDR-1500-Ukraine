# raw32 `+0x10` topology-key test

`K = BE16(raw32 + 0x10)` was evaluated only on the authoritative corpus.
There are 2,886 unique readable slots and 74 distinct K values. Twelve slots
have K=0 and 2,874 are nonzero.

K cardinality rejects a physical-edge-ID interpretation. Fifty-seven values
occur in exactly one physical node, two values occur in exactly two nodes, and
15 occur in three or more nodes. Neither of the two two-node values connects
an actual physical edge (0/2 precision). Common values are reused across
22–30 nodes with geographic spans up to 27.3 km.

Only 51 of the 1,002 unique physical edges have readable descriptor coverage
at both nodes. All 51 share at least one node-wide K, but all equally-sized
random unrelated node pairs also share K. Thus node-wide shared-K recall is
100% with zero discriminative precision. Of 2,200 RR occurrences, selected
descriptors already share K in 1,593; all remaining 607 are rescued by another
descriptor at the endpoint nodes, and none lacks a node-wide shared K.

Descriptor choice is not one outgoing edge. Of 2,886 readable descriptors,
1,059 map to exactly one recovered neighbor, 226 map to multiple neighbors,
and 1,601 have no recovered readable transition context. Among descriptors
with context, 82.41% map to one neighbor; over all descriptors the rate is
36.69%. At node scope, K maps to one ptr in only 97/306 `(node,K)` groups and
to multiple ptrs in 209 groups.

For 26 RR physical edges observed in both directions, 23 reuse at least one
canonical endpoint-K pair and three use different pairs; 25 additional edges
are observed in one direction only. This weak directional difference does not
support a directed-edge ID.

K has no exact equality with caller A/B/C/D/F/E-flags in any of 20,156
readable object occurrences. Adjacent BE16 fields at `+0x0E` and `+0x12`
remain undecoded.

## Decision

K is a reused road/topology class or target-local index, not a physical or
directed edge ID. The next bounded target is the adjacent triple
`(+0x0E,+0x10,+0x12)` to determine whether K is a class byte plus flags/range.
