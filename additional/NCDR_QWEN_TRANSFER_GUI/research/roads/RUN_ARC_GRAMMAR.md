# Run-level arc grammar

## Canonical runs

This phase uses only the authoritative post-fix road corpus. Consecutive
objects are grouped only when their raw `hlon || hlat` pair is identical;
every original MORE_INFO object remains in its run.

There are 57,800 runs: 32,734 single-object runs and 25,066 multi-object
runs. The run-length distribution is:

| length | runs |
|---:|---:|
| 1 | 32,734 |
| 2 | 17,038 |
| 3 | 5,342 |
| 4 | 1,792 |
| 5 | 525 |
| 6 | 195 |
| 7 | 124 |
| 8 | 22 |
| 9 | 15 |
| 10 | 2 |
| 11 | 11 |

The full run table is `road_node_runs.csv`.

## Outgoing and incoming arc carriers

There are 24,419 run transitions, 1,444 unique directed physical edges, and
1,002 undirected physical pairs.

For the last object of each current run, `(current_node, last_ptr)` has:

- 4,405 unique keys;
- 4,326 one-next-node keys;
- 98.21% one-next precision;
- 974/1,002 = 97.21% physical-pair coverage.

For the first object of the next run, `(next_node, first_ptr)` has 4,386
keys, 4,295 one-previous-node keys, 97.93% precision, and 978/1,002 =
97.60% physical-pair coverage. The last-current and first-next descriptors
are therefore paired endpoint carriers, but their pointers are generally
different endpoint-local values.

`outgoing_arc_descriptors.csv` contains all 24,419 selected outgoing
occurrences. Only 5,102 have a readable raw32 descriptor; the remaining
selected objects still have a valid `E & 0x3FFF` pointer but no readable raw32
payload in the authoritative corpus.

## Endpoint ARC_PAIRs and reverse direction

`arc_endpoint_pairs.csv` records `(P, P_out_ptr) <-> (Q, Q_in_ptr)` for all
1,444 directed edges. There are 4,567 distinct observed ARC_PAIR values. A
single ARC_PAIR is stable on 638/1,444 = 44.18% of directed edges. Restricting
to directed edges with repeated occurrences, stability is 487/1,293 = 37.66%.

Among 442 physical pairs observed in both directions, modal endpoint-local
pointer equality is:

| endpoint comparison | equal |
|---|---:|
| P outgoing vs P incoming in reverse traversal | 52/442 = 11.76% |
| Q outgoing vs Q incoming in reverse traversal | 77/442 = 17.42% |

Incoming and outgoing descriptors are therefore not one shared descriptor per
undirected endpoint. The pair is directional/contextual.

## The 28 failures

All 28 previously uncovered physical pairs are explicitly listed in
`run_rule_failures.csv`. Every failure has a missing reverse road direction
and a pointer collision involving more than one next neighbor. Twenty-one
also span multiple roads sharing the same physical pair; two have different
pointer values for the same neighbor. No failure requires a geometry or
parser-data explanation, and none is a self-loop. The failures are therefore
direction/road-coverage and pointer-collision cases, not evidence against the
run boundary rule.

## Run-length semantics

The strongest exact relation is:

`run_length == number_of_distinct_ptrs`: 57,724/57,800 = 99.87%.

The corresponding equality counts are only 884/57,800 for graph degree,
1,823/57,800 for previous-neighbor count, and 1,951/57,800 for
next-neighbor count. A run enumerates distinct descriptor/variant entries at a
node; it is not a degree list. The last entry is the most reliable departure
carrier.

## Selected versus unselected raw32

The selected/unselected word statistics are retained in `run_arc_summary.json`
and the candidate-reference rates in `selected_descriptor_refs.csv`. The strongest distribution difference is
word `W08` (BE16): zero appears in 14.27% of selected readable descriptors
versus 3.24% of unselected descriptors, a +11.03 percentage-point difference.
This is a selection-associated field distribution, not yet a decoded pointer.

The strongest in-bounds candidate is also `W08 * 32`: 16.13% selected versus
4.67% unselected. Targeted dereferencing of the 823 selected hits shows that
most values are zero and therefore point to logical offset 0, the owning type0
block header. The nonzero hits do not form a validated shared local structure
or reverse-related target. In-bounds enrichment alone is consequently
insufficient, and `W08 * 32` is rejected as a local arc reference.

No selected raw32 candidate produced a validated geometry sequence, coordinate
delta list, or variable-length point array. The selected raw32 remains an
arc-attribute/metadata candidate; its exact field semantics are unresolved.

## Decision

**C. Both define paired endpoint descriptors.** The last object of the current
run is the outgoing carrier and the first object of the next run is the
incoming carrier. Their high precision is a run-boundary property, while the
endpoint pointers are direction-specific and do not form a stable undirected
edge ID.

No direct local reference or geometry target was identified. The next exact
structure to decode is the selected raw32 attribute grammar, beginning with
the selection-associated W08/W16 words, while retaining the run-boundary
direction and endpoint pairing.
