# Phase 26 — 0x06 cell/origin model

## Confirmed table

One contiguous structurally identified 28-byte sequence is in type-`0x06` sector `0x7749B`, beginning at logical offset `0x0C66` and ending at `0x3F7A` (exclusive): 467 entries, 13,076 bytes (`0x3314`). The preceding and following 64-byte windows are preserved in `phase26_tables.csv`. No second complete table was proven from the available material.

## META16

Across the 467 candidate entries, `META16=0x001C` occurs 7 times (1.499%). Values vary broadly; the most common is `0x0030` (48), occurring 260 times. Since every candidate entry is still spaced at 28 bytes, alternate META16 values do not imply alternate entry sizes. META16 is not established as a length field.

## Origin/cell test

The seven controlled points all give exactly `originX=0x59763F`, `originY=0x48A93F`. No independent displayed-coordinate identities are available for the other table entries, so no additional origin pair can be proven and no origin clustering can be claimed. The candidate cell width is 65,536 Q units per axis, equal to `65,536*64/5,555,555 = 0.755914°` per axis.

No literal origin was found in the tested table windows as BE/LE 16-, 24-, or 32-bit values, nor as the obvious shifted MULCOORD forms. The origin storage location is therefore unresolved; it may be in a parent/index structure outside the examined local table.

## Entry fields and transitions

`+0x00..+0x05` are X16/Y16/META16. In the candidate table, `+0x06..+0x09`, `+0x0E..+0x17` are usually zero in the inserted entry but are not globally constant. `+0x0A..+0x0D` has recurring `0x3B87`-family prefixes and changing words; `+0x16..+0x1B` contains recurring pointer/index-like values. These are classifications only, not decoded semantics.

Three descending X16 transitions occur in the candidate sequence (at entries 463, 464, and 466), but no origin transition can be proven without displayed coordinates. META16 changes at many ordinary consecutive entries, so it is not by itself a demonstrated cell-origin marker.

## Encoder/decoder and overflow

The controlled-output candidate remains: `Qlon=floor((lon+30)M)>>6`, `Qlat=floor(lat*M)>>6`; `X16=Qlon-0x59763F`, `Y16=Qlat-0x48A93F`; store BE16 X16, BE16 Y16, and META16. Decode by adding the same origins and applying the inverse scale. This is not database-wide validated. Overflow behavior, parent cell headers, and origin transitions remain unresolved.
