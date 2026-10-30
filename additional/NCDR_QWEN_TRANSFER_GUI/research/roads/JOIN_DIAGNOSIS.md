# Phase39 ownership-join diagnosis

The zero join was an offset-label bug, not a sector-identity or road-parser
failure. `phase39_all_road_references.csv` stores the location of the matched
type-0x00 BL_ADDR field, which is `object_start + 0x10`, in its
`object_offset` column.

Subtracting `0x10` matches 10,608/10,615 rows to confirmed MORE_INFO-owned
24-byte objects in the same type-0x0E sector. The remaining seven rows are
structural false positives. No row matches without correction, and adding
`0x10` matches none.

The nearest-owned-start delta is `+8` for all 10,615 rows. This is expected:
from `object_start + 0x10`, the next object in a 24-byte array starts eight
bytes later, while the actual owning object starts sixteen bytes earlier.

All 101 original readable Moscow controls match confirmed ownership and occur
under the same `+0x10` Phase39 representation. Sector IDs are identical in
both datasets.

The repaired Phase39 corpus contains 10,608 confirmed rows. Claims based only
on the seven false-positive rows must be discarded; aggregate Phase39–42
counts should be recomputed from the repaired corpus. The authoritative
95,119 owned-object occurrence corpus contains 20,156 readable objects whose
selected 32-byte window is in bounds.
