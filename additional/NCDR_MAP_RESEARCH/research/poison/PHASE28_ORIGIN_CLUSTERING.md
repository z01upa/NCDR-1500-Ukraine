# Phase 28 — origin clustering

The search was constrained to the already identified valid table in `OUTPUT_B`, type-`0x06` sector `0x7749B`, logical `0x0C66..0x3F7A`, 467 entries at 28-byte spacing. This avoids a new broad DB scan. The complete type-0x06 population contains 5,433 records, so no claim is made about unexamined tables.

Exactly one supplied displayed point matched a valid raw entry: B (`37.65431,55.12344`) at `0x7749B:0x0C82`, payload prefix `26425A3D`. It gives `originX=0x59763F`, `originY=0x48A93F`. None of the other 16 supplied predicted X16/Y16 pairs occurred at a valid boundary in this table.

Therefore there is one convincing origin cluster of size one, no additional origin pairs, and no evidence from this constrained search that the visible POISoN list is or is not a merge of multiple underlying tables. Order preservation and parent/header comparison are likewise unavailable for unmatched points.

No origin value was found in the local 64-byte table header window as an obvious BE/LE 16-, 24-, or 32-bit representation. Origin inheritance through a parent BL_ADDR/LIST/index remains unresolved. The next exact step is to identify the owning tables for the 16 unmatched displayed points, then repeat exact-boundary matching only within those structures.
