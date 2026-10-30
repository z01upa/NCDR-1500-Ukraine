# Type-0 road-target structure inventory

## Scope

This report uses the authoritative post-fix road corpus and the 354 unique
type-0 targets referenced by its confirmed MORE_INFO ownership. No DB bytes
were modified and no raw32 field semantics are assigned here.

## Inventory

| target compression | blocks | owned object occurrences |
|---:|---:|---:|
| 0x00 | 0 | 0 |
| 0x01 | 324 | 74,963 |
| 0x02 | 30 | 20,156 |

The readable road-target subset is therefore 30 compression-0x02 blocks. The
remaining 324 blocks are compression-0x01 and cannot be structurally inspected
until its decoder exists.

## Confirmed descriptor occupancy

For each readable block, the confirmed referenced raw32 ranges `[ptr,ptr+32)`
were merged. All readable target pointers share one residue modulo 32 per
block. The evidence-backed descriptor lattice is the interval from the first
known slot through the last known slot; gaps were not extrapolated as geometry.

Across the 30 readable blocks:

- logical bytes: 1,148,416
- bytes occupied by referenced descriptor ranges: 92,352
- bytes in the evidence-backed descriptor lattice: 442,144
- bytes outside that lattice: 706,272

The non-descriptor space is mostly a large trailing region after the last
known lattice slot, plus a variable prefix. This establishes the search space,
not its semantics.

## Non-descriptor regions and candidate tables

The 30 readable blocks do not share one fixed prefix length or one fixed tail
length. Prefixes and tails recur only as layout positions, not as a common
fixed-size table. Correlation of outside-lattice length with local owned-object
count is weak (Pearson r about 0.17), and with distinct descriptor count is
near zero (about 0.06).

The tested fixed strides were 2, 4, 6, 8, 10, 12, and 16. No count-plus-array
relationship reproduced across independent blocks with a structurally proven
count and exact region length. Consequently no candidate table is promoted
to a geometry table, and raw32 W02/W14/W18/W1A/W1C/W1E values were not treated
as indices into an unsupported table.

## Geometry tests

No structurally identified candidate table was available, so no absolute
BE32 coordinate, signed BE16 delta, local BE16 coordinate, road-order, or
endpoint candidate was accepted. This avoids accidental-coordinate matches in
untyped bytes.

## Compression decision

Compression 0x01 is the blocker. It covers 324/354 target blocks and 74,963 /
95,119 owned object occurrences (78.81%). The readable 0x00/0x02 subset
cannot establish that the geometry-bearing region is absent from those blocks.

`COMPRESSION_01_DECODER_REQUIRED = YES`

Next exact target: recover and validate the type-0x01 logical decoder, then
rerun this same structural inventory on the newly readable type-0x01 blocks.
