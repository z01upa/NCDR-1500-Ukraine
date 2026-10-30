# Roads phase

## Confirmed

- compression=0x02: 16371/16371 payloads exactly satisfy `len(payload)+8 = byte7 × 512`.
- type 0x0E blocks: 861; type 0x0F blocks: 106.
- exact 0x0F→0x0E BL_ADDR-shaped fields: 431632.

## Not established

Moscow city text is present, but `ch_roads` has not yet been parsed from its MORE_INFO structure. Therefore no individual Moscow road name or end-to-end road trace is asserted.

## Phase 7–8 update

Moscow's `ch_roads` is now parsed through CH_IDX to a type-0x0E list. A CH_IDX
LIST locates 185 consecutive eight-byte road entries at logical offset `0xF20`
in sector `0x31A0`. Each entry has a valid PSTR name and in-bounds extended-info
PTR. The first entry is `1 iy mikrorayon`; its extended-info target remains
unparsed, so it has no confirmed type-0x00 ownership yet.

## Outgoing references from 0x0E

Counter({'0x00': 790824, '0x1c': 1845, '0x0e': 1824, '0x0c': 391, '0x16': 361, '0x13': 310, '0x06': 222, '0x02': 171, '0x04': 150, '0x09': 149, '0x15': 93, '0x01': 41, '0x0f': 14, '0x03': 10, '0x0d': 5, '0x17': 3})

## Phase 11: 24-byte object and type 0x00 target

The 185 Moscow road entries own 483 objects of width 24. The object begins
with a confirmed MULCOORD pair, has four uint16 fields A/B/C/D at `+0x08`, a
validated BL_ADDR to a type `0x00` block at `+0x10`, then E/F at `+0x14`.
F is a count of consecutive owned objects/list items. E is best decoded as
`flags = E >> 14`, `pointer = E & 0x3fff`: this gives `0x4df8 → 0x0df8`,
flags `1`, F `31` for `1 iy mikrorayon`.

All 483 masked pointers fit the logical extents advertised by their target
headers. Only 462 fit the currently available stored/decompressed view for the
`0x3fff` mask; the remaining records use type-0x00 compression `0x01`, whose
logical tail is not decoded yet. There are 102 unique type-0x00 target blocks.

A/B/C/D are ordered pair-like values, but their semantics are not confirmed;
global coordinate correlations are weak and only 260/483 objects satisfy both
`C >= A` and `D >= B`. The 31 bytes at the example pointer have not yielded a
validated fixed-width element schema or a geographic polyline. The next exact
unresolved field is the compression-`0x01` decoder and the resulting type-0x00
element boundaries.
