# DB_0: phase 1 and phase 2 observations

Input examined read-only: `../DB_0` (252,521,472 bytes; 493,206 physical
512-byte sectors). The scanner is `db0_scan.py`; reproducible output is
`record_index.csv`, `compression.csv`, and `scan_statistics.txt`.

## Record-start rule — confirmed for this image

At every physical sector boundary, the scanner decoded bytes 0–2 as an unsigned
24-bit big-endian integer and compared it with the sector number. It found
54,011 matches. Of these, 54,009 have a non-zero byte 3 and point to another
matching header at `sector + byte_3`.

The two exceptions are sector `0x000000` (byte 3 is zero) and the final sector
`0x078695` (span one; the next sector is exactly EOF). The remaining 54,010
headers form one consecutive forward chain beginning at sector `0x000002` and
ending at `0x078695`. Its covered region is sectors `0x000002` through
`0x078695`, with the last record ending at EOF.

This supports the following observed layout for this DB_0 only:

```
bytes 0..2  uint24 big-endian sector identifier
byte 3       sector span
record byte offset = sector identifier × 512
next record sector = sector identifier + sector span
```

Evidence can be independently checked in `record_index.csv`: for each row,
`sector`, `span`, `next_sector`, and `next_valid` contain the inputs and result.
The records at sectors `0x00f12a`, `0x00f12f`, `0x07158f`, and `0x0769ff`
match the supplied examples.

## Compression — confirmed for individual records

The scanner inspected the first 64 bytes after the four-byte record prefix of
every validated record for zlib CMF/FLG pairs `78 01`, `78 5e`, `78 9c`, and
`78 da`. It attempted decompression only within that record's declared span.

It found 16,593 candidate zlib prefixes. 16,371 streams reached a zlib end
marker within their own record boundary. Together, those streams use
106,531,975 compressed bytes and produce 255,262,824 decompressed bytes.
The first success is sector `0x000002`, span 1, zlib offset 8: 330 compressed
bytes expand to 1,016 bytes.

Therefore, a zlib stream at the reported offset is confirmed only when its
`success` field is `True` in `compression.csv`. The other bytes before or after
the stream are deliberately not assigned a meaning here.

## Not established

No rule has yet been established for the semantic meaning of bytes 4–7, for
the uncompressed record types, for any pointer encoding, or for the contents
of a decompressed payload. The supplied absolute-pointer and 1024-byte-page
reference observations remain hypotheses pending separate statistical tests.

## Phase 3–4 update

Classification produced 54,009 validated-record rows in `record_classes.csv`.
The most frequent class signatures are documented in `record_class_statistics.txt`.
They remain signatures only, not proven types. Every successful zlib record in
this image began at record-local offset 8 and had one successful stream.

`strings.csv` provides a capped conservative sample of null-terminated text in
raw and decompressed data. It includes independently recognizable values such
as `moskva`, `renault`, and `russneft'` in decompressed records. The present
pointer/key candidate scan does not satisfy the independent, low-accident
probability evidence needed to confirm a string reference scheme or a B-tree.
See `FORMAT.md` for the complete separation of confirmed facts and hypotheses.

## Phase 5 update

The five selected `000402xx` signatures yielded 1,601 zlib payloads. Their
records have a common zlib boundary at local offset 8, but the tested widths
from 2 through 32 bytes did not yield a layout that repeats across the family.
Exact integer matches to record-sector values are too frequent to establish a
link scheme without a null model and independent structural constraints.
No tested coordinate encoding matched even three independent cities.

## Published CARiN study validation

The external format study resolved the prior blind-analysis ambiguity. In this
DB, bytes 4–7 are `alignment`, `type`, `compression`, and logical-size field.
Byte 6 `0x02` is zlib; byte 7 gives logical uncompressed size as `byte7 × 512`,
whose payload length is therefore `byte7 × 512 − 8`; byte 3 remains the
physical stored span. The published MULCOORD formula
decodes Moscow-area coordinates and a dense type-0x10 coordinate population.

## Roads correction

Type `0x16` is UNKNOWN. Phase 6 validates byte-7 size globally and finds many
exact `0x0F → 0x0E` BL_ADDR links. Moscow's `ch_roads` substructure has not yet
been type-aware parsed, so no specific Moscow road is claimed.

## Phase 9 update

The `0x0E` container header has LISTs at `0x30/663` and `0x14E8/642`; the
Moscow CH_IDX selects a separate sublist at `0x0F20/185`. Its 185 BRIF records
all validate with the same 8-byte layout. Their `extended_info` pointers are
unique and form a six-byte sequence from `0x1F9E` through `0x23EE`.

The isolated `1 iy mikrorayon` record is `54b401010000`. No external BL_ADDR,
LIST, or FAR_LIST is confirmed in this record, so no type-0x00 ownership or
geometry claim is made. The BRIF parser generalizes to ten control `0x0E`
blocks; the six-byte MORE_INFO interpretation still requires validation.

## Phase 11 update

Phase 11 resolves that MORE_INFO field 0 as a pointer into a 24-byte object
array. Across 483 objects, the first eight bytes are confirmed MULCOORD, the
four uint16 values A/B/C/D remain unresolved ordered pair-like fields, and the
BL_ADDR at `+0x10` points to a type-`0x00` target. E/F is best represented as
`E & 0x3fff` plus upper-bit flags, with F as the count. This decodes the
example `0x4df8` to `0x0df8`, flag `1`, count `31`.

The 483 references cover 102 unique type-`0x00` blocks. The header logical
extents accept all references, while the available bytes accept 462 masked
`0x3fff` pointers; the remaining 21 are in compression-`0x01` logical tails.
The 31 example items remain raw candidate data: no fixed element width,
element semantics, or geographic polyline has been proven. The next concrete
target is the compression-`0x01` decoder and the resulting type-`0x00` list
boundaries.
