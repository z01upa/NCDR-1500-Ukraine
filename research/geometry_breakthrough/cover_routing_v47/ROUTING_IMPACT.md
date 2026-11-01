# Routing impact

## Confirmed local effect

Across three real block 886 records, overwriting only edge+4 or edge+5 with `00`, `01`, `02`, `03`, or `FF` changed the selected-bit predicate exactly as `byte & (1 << selector)`. The converter's endpoint-match result and the mask selector were varied independently. A set bit returned -1; the traced `0x0303D670` caller loop then skipped that current packed edge candidate and advanced its loop index.

This confirms an effect on candidate filtering in this caller. The tested consumer itself does not calculate path cost or choose a next graph node. The code path is not sufficient to identify which real-world condition the bit represents.

## Relation to other verified routines

- `0x02FFBA84` calls `0x0301B428` from the producer path. Replay stubs this helper's return to 100; this can affect other cover fields and limits conclusions to the tested attribute and mask decision.
- `0x0301FCD8` independently copies edge+5/+4 into its own output+0x11/+0x10. The caller chain uses a separate context temporary and callbacks; no alias to the `SP+0x40` output was proven.
- `0x030AB4D0` calls `0x030AC04C` at `0x030AB552`. That separate function iterates a `0x58`-stride table at `0x030AC08A`–`0x030AC096`. No recovered call graph path connects it to the `0x0308C1F0` result path.
- Other `0x0308C1F0` callers use `0x34`-stride arrays (for example `0x0308F1C0` at `0x0308F1FE`–`0x0308F206`). Those structures are not shown to be the `0x58` table or MP0 Sections 7/8.

## Verdict

Changing edge+4/+5 changes which candidate passes this local filter. Whether that changes a selected route, route cost, user-visible path, or physical navigation is UNKNOWN. Section 7/8 and RT/RL requirements for writing a new MP0 edge are not proved by this analysis. Do not encode one-way or two-way movement in Writer from this predicate alone.
