# Phase 25 — X16/Y16 local-coordinate validation

Parsing bytes 0..1 as BE X16 and bytes 2..3 as BE Y16 gives one constant origin across all seven controls:

`originX = Qlon - X16 = 5,862,975 = 0x59763F`  
`originY = Qlat - Y16 = 4,761,919 = 0x48A93F`

The trailing field is `META16=0x001C` in all controlled entries. Twenty adjacent 28-byte entries were extracted from B; their payloads and candidate coordinates are in `phase25_neighbor_validation.csv`. Entry 2 matches the displayed B coordinate within about 0.000005 degrees per axis. The other 19 neighboring display identities are not recorded in the supplied artifacts, so they are raw-only validation, not independent POISoN-coordinate validation.

Neighbor META16 values include `0x000C`, `0x0024`, `0x0025`, `0x002D`, `0x002F`, and `0x0030`; therefore META16 is not a table-wide constant size. `0x001C` is compatible with the 28-byte entry width but its semantic role—cell/tile, flags, group, index, or other metadata—is unresolved. No literal origin words were found in the tested entries.

Candidate encoder: `Qlon=floor((lon+30)*5555555)>>6`, `Qlat=floor(lat*5555555)>>6`; `X16=Qlon-0x59763F`, `Y16=Qlat-0x48A93F`; store `X16_BE || Y16_BE || META16`.

Candidate decoder: `Qlon=0x59763F+be16(payload[0:2])`, `Qlat=0x48A93F+be16(payload[2:4])`; `lon=Qlon*64/5555555-30`, `lat=Qlat*64/5555555`. This is confirmed for the seven controls, not yet database-wide. Candidate local range is 0..65535 per axis; overflow behavior is unresolved.
