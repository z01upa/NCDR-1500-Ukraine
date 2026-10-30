# Caller object as ordered topology link

## Scope

This analysis uses only the authoritative global road corpus: 95,119 owned
objects, 33,381 roads, 61,738 same-road adjacent object pairs, 24,419
distinct-node adjacent pairs, and 10,455 ordered `P -> C -> Q` triples. No
database rescan, geometry analysis, or new raw32 field was used.

The complete ordered object table is in `caller_sequences.csv`; repeated
physical nodes are retained. `FIRST`, `MIDDLE`, and `LAST` are road-object
positions; `ONLY` is used for one-object roads.

## Adjacent equality matrix

The 5x5 matrix in `caller_adjacent_matrix.csv` reports real equality and a
deterministic control matched by position class and same/distinct physical-node
status. The strongest distinct-node relation is `B_i == A_j`: 34.95% real
versus 18.20% control (16.75 percentage points). The strongest raw same-field
relation is `C_i == C_j`: 40.05% real versus 21.70% control.

The strongest distinct-node relations are:

| Relation | Real | Control | Lift |
|---|---:|---:|---:|
| B_i == B_j | 37.12% | 18.08% | 19.03 pp |
| D_i == D_j | 38.92% | 20.41% | 18.51 pp |
| C_i == C_j | 40.05% | 21.70% | 18.35 pp |
| A_i == A_j | 37.67% | 19.94% | 17.74 pp |
| B_i == A_j | 34.95% | 18.20% | 16.75 pp |

These are broad value-copying effects, not a one-to-one topology reference.

## +/-1 and 32-bit tests

For the strongest exact relations, all tested non-wrapping `+1` and `-1`
relations have zero matches. There is no adjacent increment/decrement chain.

The strongest 32-bit relation is `AC_i == AC_j`: 23.59% real versus 5.43%
control. The requested cross relations are weak: `AB_i == CD_j` is 21.83%
versus 17.86% control and `CD_i == AB_j` is 21.47% versus 17.94% control.
Neither pair relation supplies an endpoint ID.

## Predecessor/current/successor triples

The strongest equality against the predecessor is `C_C == C_P`, 4,265/10,455
(40.79%). The strongest equality against the successor is `D_C == C_Q`,
4,112/10,455 (39.33%). These high rates are compatible with repeated/default
caller values and do not distinguish the two neighboring nodes.

The best signatures in triple context are:

| Signature | PREV precision / covered pairs | NEXT precision / covered pairs |
|---|---:|---:|
| ABCD | 92.02% / 626 | 92.07% / 640 |
| ABCDFE | 94.59% / 761 | 94.59% / 766 |
| ptr | 98.91% / 819 | 99.05% / 819 |

The `ptr` result is storage-location specificity, not proof that caller
fields encode the neighbor. It is included as the downstream descriptor
selector required by the task.

## Caller-to-ptr selection

Within each physical node, no caller-only signature uniquely selects `ptr`.
The best tested non-tautological signature is `A+B+C+D+F+E_flags` at
11,859/12,713 = 93.28%; `ABCD` reaches 9,816/10,780 = 91.06%. The exact
mapping table is in `caller_ptr_mapping.csv`.

## Directed-edge and opposite-direction tests

Among the requested caller signatures, `C` is the most stable departure value
on directed physical edges: 777/1,444 = 53.81%. `D` is 53.67%, `CD` 53.46%,
and `ptr` 44.53%. `E_flags` alone is 74.79%, but it is a coarse flag value and
does not identify a neighbor.

Opposite-direction modal cross-field matches do not produce a global
field-to-field relation above the ordinary repeated-value baseline. The
opposite-direction summary is retained in `caller_topology_summary.json`.

## Road-chain and repeated-node runs

The three tested chain relations have identical aggregate behavior:
`D_i == A_{i+1}`, `C_i == B_{i+1}`, and `CD_i == AB_{i+1}` each match
12,396/61,738 = 20.08%, break 49,342 times, reach a longest continuous chain
of 181 objects, and are 100%-consistent on 2,478 of 21,112 multi-object roads.
The chains therefore do not define a universal linked-list numbering rule.

Repeated-node runs do explain the boundary ambiguity. For a node run followed
by a different node, `(node,ptr)` maps to the next node as follows:

| Selected run object(s) | one-neighbor precision | covered physical pairs |
|---|---:|---:|
| first only | 4,620/4,715 = 97.99% | 965/1,002 |
| last only | 4,326/4,405 = 98.21% | 974/1,002 |
| all objects | 7,353/7,558 = 97.29% | 970/1,002 |

The last object is the strongest departure carrier. This is a run-position
rule, not a caller-field topology ID.

## Structural decision

**D. Repeated-node object runs provide the missing topology structure.**

A/B/C/D/F show real adjacency correlations, but none gives a deterministic
predecessor/successor ID, paired incoming/outgoing IDs, or a universal chain.
The selected descriptor pointer is most informative when taken from the last
object in the repeated-node run before departure.

The next exact structure to follow is the run-boundary record that owns that
last-object `E -> ptr` selection, including the surrounding selected raw32
descriptor and its parent structural table. Do not infer a new caller-field
encoding from the equality matrix.
