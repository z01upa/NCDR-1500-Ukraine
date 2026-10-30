# Test of `N` as a node-local half-edge selector

## Scope and method

This test uses only the authoritative post-fix road corpus. It does not scan
the database or inspect a new raw32 field. The 95,119 owned objects were
ordered by `(road_id, road_object_index)` and collapsed into runs only for the
purpose of locating node changes; every descriptor in a repeated-node run was
retained.

The corpus contains 24,419 node-change transitions and 1,002 distinct
undirected physical-node pairs. For every transition, the evidence table
preserves the last object at the departing node and the first object at the
arriving node.

## Sequence alignment

`(node,N)` mappings were evaluated without `road_id` or direction. Alignment
A uses every retained descriptor in the current node run against the next
node. Alignment B uses it against the previous node. C uses only the last
descriptor at the previous node against the current node. D uses only the
first descriptor at the next node against the current node.

| Alignment | mappings | one neighbor | conflicts | precision | physical-edge coverage | 1 neighbor | 2 neighbors | 3+ neighbors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 70 | 38 | 32 | 54.29% | 18/1,002 (1.80%) | 38 | 2 | 30 |
| B | 62 | 31 | 31 | 50.00% | 19/1,002 (1.90%) | 31 | 1 | 30 |
| C | 59 | 28 | 31 | 47.46% | 16/1,002 (1.60%) | 28 | 1 | 30 |
| D | 38 | 8 | 30 | 21.05% | 7/1,002 (0.70%) | 8 | 0 | 30 |

A is the best alignment by one-neighbor precision, but 54.29% is not a
deterministic selector and its graph coverage is only 1.80%. B covers one more
edge, but with lower mapping precision.

## Reverse direction and half-edge pairs

For the 26 physical edges observed in both directions with readable endpoint
descriptors, the modal/canonical endpoint `N` is stable at both endpoints:
52/52 endpoint comparisons and 26/26 physical edges. This reproduces the
previous canonical endpoint result. A stricter comparison of the complete
observed value sets succeeds for only 43/52 endpoints and 18/26 edges because
minority descriptor variants occur on eight edges.

Across all 1,002 physical edges, complete readable endpoint pairs are sparse:

| Pair status | edges |
|---|---:|
| exactly one stable `(N_U,N_V)` pair | 41 |
| multiple conflicting pairs | 10 |
| no observation readable at both endpoints | 951 |

Thus reverse-direction stability is real for the canonical value, but it does
not make `N` a globally usable local port identifier.

## Conflict analysis

Alignment A has 32 conflicting `(node,N)` keys. All 32 span different roads,
different object positions, and include observations from consecutive
duplicate-node runs. Only 2/32 are composed entirely of duplicate-run
observations. Different `ptr`, K, and P values occur in 31/32 conflicts; none
is attributable to an unreadable selector endpoint. The complete evidence is
in `halfedge_conflicts.csv`.

## `ptr` and minimal composite signatures

Among readable descriptors, all 2,886 `(node,ptr)` keys map to exactly one N;
none maps to multiple N values. In the reverse relation, 75 `(node,N)` keys
map to one `ptr` and 35 map to multiple `ptr` values. At the observed-pair
level this is 75 one-to-one pairs and 2,811 cases where a single N is reused
by multiple pointers. `ptr` therefore identifies descriptor storage much more
finely than N; it is not a reusable endpoint port.

| Signature | mappings | one-neighbor mappings | precision | physical-edge coverage |
|---|---:|---:|---:|---:|
| N | 63 | 30 | 47.62% | 16/1,002 (1.60%) |
| N,K | 231 | 90 | 38.96% | 58/1,002 (5.79%) |
| N,P | 1,186 | 952 | 80.27% | 149/1,002 (14.87%) |
| N,K,P | 1,269 | 1,072 | 84.48% | 164/1,002 (16.37%) |
| ptr | 7,267 | 6,348 | 87.35% | 903/1,002 (90.12%) |

N,K,P is the best tested N-based signature, but it remains
non-deterministic and low-coverage. `ptr` has much greater coverage because it
is a high-cardinality storage location; its 87.35% one-neighbor rate and prior
34.75% repeated-edge stability reject it as a stable node-local half-edge ID.

## Internal-node and degree tests

There are 12,125 internal node runs. Comparing the first arrival descriptor
with the last departure descriptor gives 44 distinct-N runs, 2,291 same-N
runs, and 9,790 unresolved runs. Among the 2,335 resolved runs, only 1.88%
use different incoming and outgoing N values. The corresponding pointer test
is 5,435 distinct, 6,690 same, and 0 unresolved.

No physical node has `N_count == graph_degree`: 0/334 (0.00%). No node has
`ptr_count == graph_degree` either. The exact difference values are retained
in `node_degree_comparison.csv`; `N_count - graph_degree` is negative for 332
nodes and positive for two, with no zero values. This is incompatible with N
enumerating local graph ports.

## Descriptor-only reconstruction and decision

Using only nonconflicting alignment-A `(node,N)->neighbor` mappings reconstructs
18 true physical edges, 0 false edges, and misses 984 of the authoritative
1,002 edges: 100.00% precision and 1.80% recall. The precision is a consequence
of retaining only already-observed nonconflicting mappings; the decisive
result is the very low recall.

**Decision D: the descriptor requires road-sequence context and has no
standalone port ID.** N is context-stable on frequently observed edges but is
too reused, too sparse at transition boundaries, and unrelated to graph
degree to be a node-local half-edge selector. Neither `ptr` nor N,K,P is a
validated replacement.

The next exact structure is the ordered predecessor/current/successor caller
24-byte object triple, testing caller fields A/B/C/D/F for the missing
sequence selector while preserving the established road direction.
