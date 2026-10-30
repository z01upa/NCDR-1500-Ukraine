# Phase 27 — displayed POI to raw X16/Y16 cell matching

Search scope was restricted to the previously identified valid 28-byte sequence in `OUTPUT_B`, sector `0x7749B`, logical `0x0C66..0x3F7A`, 467 entries at `0x1C` spacing. No broad DB scan was performed.

Of the 17 supplied displayed points, exactly one predicted X16/Y16 pair matched a valid entry: B at logical offset `0x0C82`:

`26 42 5A 3D 00 1C 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 C6 F2 21 15 F0`

Recomputation for B gives `Qlon=0x599C81`, `Qlat=0x49037C`, `originX=0x59763F`, and `originY=0x48A93F`. The other 16 predicted pairs had no exact match at a valid entry boundary. Consequently no additional origin cluster, longitude-order validation, or field correlation by Ycell is established.

The confirmed B entry has `META16=0x001C`; no entries for Ycell `-13`, `-1`, or `+1` were found by the exact-pair search. Cell identity is therefore not localized to a proven per-entry field. It may be table/block-owned, but that remains unresolved. The supplied predicted cell indices are not independently confirmed except Ycell=0 for B.

The next required step is to identify the correct owning tables/groups for the 16 unmatched displayed points, then repeat the exact-boundary search within those already identified structures.
