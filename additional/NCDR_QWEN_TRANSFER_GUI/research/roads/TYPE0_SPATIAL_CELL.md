# Type-0 spatial-cell and local-coordinate test

## Anchor inventory

The analysis uses the authoritative road corpus and calls the raw
`BE32 hlon || BE32 hlat` pair an **ANCHOR**. It does not treat the 354 values
as proven intersections. The inventory is in `type0_anchors.csv`.

There are 354 anchors and 354 type-0 targets with the previously confirmed
one-to-one mapping. The anchor bounding box is 28.62335..43.48692 E by
51.88461..64.76637 N. The nearest-anchor distance is 2,222 m median,
19,186 m p90, and 265,427 m maximum.

The raw coordinate components are strongly quantized: 106 unique raw
longitude values and 89 unique raw latitude values occur among 354 anchors;
positive sorted deltas have GCD 49,152 for longitude and 24,576 for latitude.
The most common deltas are 49,152 and 98,304 units. This is evidence for
quantized anchor placement or cell origins, but the wide nearest-neighbor
tail and irregular occupancy do not prove one regular global grid.

## Density and road traversal

Roads per anchor are sparse but uneven: median 1, p90 3, maximum 124. Thus
most anchors are not shared by dozens of unrelated roads, although a small
number are highly reused. The per-anchor object, run, road, and pointer
counts are retained in `type0_anchors.csv`.

The 33,381 roads use anchors as follows:

| distinct anchors in road | roads |
|---:|---:|
| 1 | 21,087 |
| 2 | 7,272 |
| 3 or more | 5,022 |

The maximum is 124 anchors per road. Consecutive distinct-anchor spans have
median 2,211 m and p90 4,088 m, consistent with traversal through local
spatial regions, but not sufficient to establish that the anchors are road
intersections.

## Pointer selection inside runs

There are 57,800 consecutive-anchor runs and 24,419 run transitions. The
run-length equals the number of distinct ptr values in 57,724/57,800 runs
(99.87%); 76 runs are exceptions. The last object remains the authoritative
outgoing descriptor carrier for this phase.

## Raw32 local-coordinate candidates

All eight aligned BE16 pairs, signed and unsigned interpretations, and shifts
1, 2, 4, 8, 16, 32, and 64 were evaluated on 5,102 selected readable raw32
descriptors. The full results are in `local_coordinate_candidates.csv`.

The smallest displacement from the anchor is produced by pair `(+18,+1A)`
with signed scale 1: median 13.81 m and p90 24.22 m. This is not sufficient
evidence of coordinates: the values are small and similarly close to every
anchor by construction. The best ordered-run continuity score is also
`(+18,+1A)`, signed scale 8, with ordered median 9.61 m versus 12.81 m for
the deterministic random ordering; p90 is 130.37 m versus 132.90 m. The
improvement is weak and does not survive the boundary test.

For anchor-boundary transitions, the best real/control comparison is
`(+00,+02)` unsigned scale 8: real median 1,965 m versus control 1,992 m,
with real p90 3,415 m versus control 3,467 m. Other candidates are similarly
close to control. `anchor_boundary_continuity.csv` contains all pair/scale
comparisons.

The explicit W08/W0A pair `(+08,+0A)` has anchor displacement median 578 m
(signed scale 1) or 740 m unsigned, but boundary median 1,981 m versus
1,988 m control. It is not a validated local XY pair. The `(+14,+16)` pair,
including N at `+0x16`, is likewise not spatially discriminative; N remains
classified as a topology/descriptor attribute rather than a coordinate.

## Bounded selected-ptr neighborhood test

Only the bounded windows `ptr-64 .. ptr+128` around selected descriptors were
read from the owning type-0 blocks. Among 5,102 selected readable windows,
all had at least one nearby int16 pair within 10 km of the anchor; this is not
selective evidence because the window contains many candidate pairs and the
anchor threshold is broad. No repeated coordinate-list framing, validated
P/Q endpoint geometry, or stronger ordered path was found.

The example long and short paths are saved in `example_local_paths.csv`; they
are diagnostic candidate paths, not recovered road geometry.

## Decision

**ANCHOR MODEL: B — possible, but not strongly proven.** Quantization,
one-to-one type-0 ownership, anchor reuse, and multi-anchor road traversal
support a cell/origin interpretation. The nearest-anchor distribution and
sparse occupancy do not prove a regular spatial-cell grid.

**GEOMETRY: C — raw32 appears to contain attributes or metadata; no local
geometry was identified.** The best aligned pair gives small local offsets,
but ordered continuity is only marginally better than random and
cross-anchor continuity is indistinguishable from control. No local XY
encoding is recovered.

The exact next target is the selected type-0 descriptor's non-coordinate
attribute grammar, preserving `(anchor, run position, outgoing ptr)` context;
do not promote any raw32 pair to geometry without a new spatially validated
endpoint test.
