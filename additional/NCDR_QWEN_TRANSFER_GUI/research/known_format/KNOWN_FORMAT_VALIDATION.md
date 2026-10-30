# Validation

## Confirmed

- The eight-byte published `BL_HEAD` maps directly to this DB variant:
  `uint24_be address`, `uint8 physical span`, `uint8 alignment`, `uint8 type`,
  `uint8 compression`, `uint8 size field`.
- `compression=0x02` is zlib: all 16,371 such records decompressed
  successfully, while no `0x00` or `0x01` record did.
- For every successful zlib record, decompressed length equals
  `size_field × 512 − 8`. Thus byte 7 is a **total physical record size in
  512-byte sectors**, including the eight-byte header, in this compiler variant.
- `0x0A` exists once and decompresses to country names including `rossiya`,
  `france`, `polska`, and `united kingdom`. `0x0C` exists 213 times and contains
  administrative/city names including `moskva`.
- `0x10` exists 542 times. Its payloads contain large populations of valid
  published MULCOORD coordinate pairs, including Moscow-area points around
  37.62E, 55.75N. This validates the published POI interpretation for this DB.

## Strongly supported

- `MULCOORD=5,555,555`, BE `hlon, hlat`, with longitude offset −30, decodes
  plausible Russian data in multiple types. Type `0x10` is particularly dense
  in such pairs. The broad geographic filter yields many overlapping candidates;
  it is evidence of the representation, not a one-to-one POI parser.
- This file uses a 512-byte physical variant of BL_ADDR: sector ID × 512 gives
  every validated record address. The 0x800 page unit described in the article
  cannot be applied directly.

## Not established

- The exact variant layout for BRIF, MORE_INFO, PSTR and FAR_LIST has not yet
  been parsed from every 0x10 payload. The current coordinate scan does not
  connect an individual Moscow coordinate to a specific multilingual name.
- No logical 0x800 address layer was found, and index links still need
  type-aware parsing rather than generic BL_ADDR-shaped scans.
