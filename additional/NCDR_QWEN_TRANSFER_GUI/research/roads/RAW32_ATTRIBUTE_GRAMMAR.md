# Selected raw32 attribute grammar

## Corpus and selection

The primary corpus contains 24,419 selected outgoing occurrences, defined as
the last object of every consecutive-anchor run with a known next anchor. Of
these, 5,102 have readable 32-byte raw32 descriptors. All tables in this
phase use only those selected readable descriptors unless explicitly labelled
as an all-object run-position comparison.

The complete selected rows and W00..W1E words are in
`selected_raw32_attributes.csv`.

## Field cardinality

| Group | Fields | Evidence |
|---|---|---|
| highest-cardinality/index-like candidates | W00, W02, W04, W06, W08, W0C, W0E, W12, W14 | 262–759 distinct values |
| medium-cardinality candidates | W0A, W10, W16, W18, W1A, W1C, W1E | 25–144 distinct values |
| lowest nonconstant field | W18 | 25 distinct values; 92.43% zero |

W02 has the highest observed cardinality, 759 distinct values. The exact
cardinality, range, zero rate, and top frequencies are in
`raw32_field_cardinality.csv`. These classifications are structural only;
the high-cardinality words are not declared coordinates or pointers.

## Road and directed-edge stability

For 899 roads with at least two selected readable descriptors, W18 is constant
on 744 roads (82.76%), the strongest road-wide stability. W10 is constant on
323 roads (35.93%), W16 on 298 (33.15%), and W1E on 206 (22.91%).

For repeated directed P->Q groups, W16 is the strongest edge-stable word:
574/596 same-road groups (96.31%) and 169/184 cross-road groups (91.85%) are
constant. W18 is next at 85.40% same-road and 79.35% cross-road. W16 is
therefore edge-associated, while W18 is primarily road/record-class stable.

The exact same-road and cross-road tables are in
`raw32_edge_stability.csv`; road-wide results are in
`raw32_road_stability.csv`.

## Reverse-direction relations

Twenty-six bidirectional physical edges have readable selected descriptors in
both directions. The strongest same-word modal relation is W10(P->Q) =
W10(Q->P): 15/26 versus 5/26 random controls. Its high-byte relation is
17/26 versus 5/26. W1C=W1C is 8/26 versus 4/26, but its high-byte equality is
common and not selective.

The strongest cross-word relation is W08(P->Q) = W18(Q->P), including
byte-swapped equality, 10/26 versus 6/26 controls. This is weak and is not
accepted as a directional field mapping. The full 16x16 equality, high-byte,
low-byte, and byte-swapped matrix is in `raw32_reverse_matrix.csv`.

## Run position and run length

Across all readable raw32 objects, W06 is the clearest position discriminator
by zero rate: FIRST 1.41%, MIDDLE 6.25%, LAST 10.15%. W08 is less separated
(6.30%, 6.25%, 5.26%). The position table is in `raw32_run_position.csv`.

The largest simple run-length relation is W18 high-byte equality at 93.71%,
but this is a trivial consequence of W18 usually being a small/zero-valued
word. No exact W18=run_length relation exists. W18 equals the ptr ordinal in
60.51% of readable objects, but this is not stable enough to assign an
ordinal meaning. No field provides a validated run-length or slot-count
encoding.

Within multi-object anchor runs, ptr order is ascending in 14,761 runs,
descending in 5,529, and mixed in 4,776. Common positive ptr deltas are 32
(597 occurrences), 64 (319), 192 (304), and 128 (275). The order is therefore
mostly increasing but not a universal sequence rule.

## Caller-field relations

The strongest exact caller relation is W18 = E_flags at 69.05%; this is
consistent with W18 being a low-cardinality flag/class field. The strongest
high-byte coincidence is W0C with F/E_flags at 93.06%, but it is a broad
high-byte effect rather than an exact copy. No caller field is proven to be an
index into the high-cardinality raw32 words.

## Minimal attribute partition

The strongest evidence-supported partition is:

- **road-stable/class-like:** W18, with 82.76% road constancy and low
  cardinality; W1C and W1E are weaker class-like candidates;
- **directed-edge/endpoint-associated:** W16, with 96.31% same-road and
  91.85% cross-road repeated-edge stability;
- **run-position-sensitive:** W06, with a clear FIRST/MIDDLE/LAST zero-rate
  gradient; W08 is weaker;
- **high-cardinality/index-like unresolved:** W00, W02, W04, W0C, W0E, W12,
  W14, and parts of W06/W08;
- **unresolved:** W0A, W10, W1A, and W1E beyond their measured stability
  patterns.

No field is assigned a speed, access, turn, neighbor, geometry, or pointer
semantic. The selected raw32 is demonstrably not a homogeneous record: at
least road-stable/class-like, edge-stable, and run-position-sensitive groups
coexist.

## Decision

The current semantic model is a mixed attribute record: W16 carries the
strongest repeated directed-edge association, W18 carries the strongest
road-wide low-cardinality association, and W06/W08 vary with run position.
The remaining words are unresolved index/attribute candidates. No standalone
neighbor ID or geometry interpretation was searched for or inferred.

The exact next target is the W16/W18/W06 field grammar across repeated edge,
road, and run-position contexts, using the existing selected-descriptor
corpus only.
