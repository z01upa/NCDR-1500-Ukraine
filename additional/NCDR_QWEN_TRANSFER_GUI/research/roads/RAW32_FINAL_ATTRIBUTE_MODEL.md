# Final focused raw32 attribute model

## Scope

This phase uses only the authoritative selected outgoing corpus: 24,419
selected occurrences and 5,102 readable raw32 descriptors. It tests only
W0C/F, W18/E_flags, W16, and W06. No new raw32 fields, geometry, neighbor
search, or database scan was used.

## W0C and caller F

The exact byte relations over 5,102 selected descriptors are:

| Relation | Matches | Rate |
|---|---:|---:|
| F_hi == W0C_hi | 4,748 | 93.06% |
| F_hi == W0C_lo | 21 | 0.41% |
| F_lo == W0C_hi | 58 | 1.14% |
| F_lo == W0C_lo | 18 | 0.35% |

W0C_hi has 23 distinct values, with zero in 4,748/5,102 descriptors. W0C_lo
has 208 distinct values. The high byte is constant on 3,352 road groups and
the low byte on 2,590 groups. Thus W0C_hi is a strongly caller-linked copied
or shared byte, but 93.06% is below the 95% proof threshold.

The 354 mismatches are structurally distributed: 188 are FIRST-position
objects and 166 LAST-position objects; none are MIDDLE in the selected corpus.
They span 332 roads, 19 anchors, 66 ptr values, and both E_flags classes
(184 with flag 1, 170 with flag 0). They are not a single deterministic
exception class. Full mismatch rows are in `raw32_w0c_f.csv`.

## W18 and E_flags

The direct relation W18 == E_flags holds for 3,523/5,102 = 69.05%. Testing
the requested 2-bit projections gives the strongest relation at
`((W18 >> 2) & 3) == E_flags`: 3,709/5,102 = 72.70%. Low-two-bit equality is
72.52%; high-two-bit equality is 72.46%. W18 is therefore correlated with the
two-bit E_flags class, not a deterministic copy or masked encoding.

Across all readable road groups, 8,300/9,305 = 89.20% have exactly one W18,
898 have two, and 107 have three or more. W18 is road/class-linked, but the
road-stable value is not fully determined by E_flags or by the caller alone.
The detailed rows are in `raw32_w18_eflags.csv`.

## W16 edge behavior

Among 195 directed edges with readable selected W16, 180 have exactly one
W16, 9 have two, 2 have three, 2 have four, and 2 have five values. On
repeated same-road P->Q groups W16 is stable in 574/596 = 96.31%; across
repeated cross-road groups it is stable in 169/184 = 91.85%.

For the 26 bidirectional readable physical pairs, W16 is equal in 0/26
reverse comparisons; every direction uses a different modal value. No
forward/reverse W16 pair pattern repeats across those 26 pairs. W16 is thus a
strong same-road directed-edge attribute, but not a universal undirected
edge ID or a deterministic global edge field. Details are in
`raw32_w16_edges.csv`.

## W06 boundary test

The best individual W06 bit by FIRST/MIDDLE/LAST rate separation is bit 4:
48.48% / 52.85% / 43.18%, only a 9.67-point spread. The best single-bit
LAST predictor is bit 8, with precision 24.55% and recall 48.97%.

Therefore W06 has a position correlation but no proven boundary flag. The
complete bit rates and precision/recall tests are in
`raw32_w06_boundaries.csv`.

## Joint model and decision

Applying all four proposed relations simultaneously explains 14.62% of the
selected readable descriptors. The measured partition is:

- W0C: correlated caller-linked high byte, not proven at 95%;
- W18: correlated road/class field, not a deterministic E_flags encoding;
- W16: proven stable only within repeated same-road directed-edge groups,
  not globally deterministic;
- W06: correlated with run position, not a boundary flag.

No new relation reaches the required deterministic threshold. The stop
condition is met: raw32 correlation work stops here. Raw32 is a mixed
routing/attribute structure whose complete semantics cannot be recovered from
these correlations alone.

The exact next target is the separate road geometry structure referenced by
the road/object or selected-descriptor tables, not another raw32 field.
