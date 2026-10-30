# Phase 17 — deep diff of the POISoN editable-point format

## Confirmed result

The principal +1-point change is type `0x06`, sector `0x7749B`, physical span `0x20`, compression `0x00`, with a 16,376-byte logical payload. A→B changes 4,259 logical payload bytes. The first visible change is logical offset `0x03`, `0x3D`→`0x3E`; the remainder is a broad sparse/table rewrite extending through the payload. This is not evidence for a fixed-size inserted POI item.

OUTPUT_C has a one-sector insertion/allocation before the homologous region: the corresponding type-0x06 header occurs at `0x7749C`. Therefore A/B/C type-0x06 records must be matched by logical/index identity, not raw sector number. A direct A→C comparison at equal sector is invalid.

## Encoding tests

The changed-field scan found no confirmed BE/LE 16/24/32-bit field whose B→C delta equals the +0.10000/+0.10000 coordinate delta under the requested decimal, MULCOORD, signed-fixed-point, lon+30, tile-origin, or simple delta interpretations. The requested coordinates also do not occur as confirmed raw/decompressed MULCOORD pairs. Coordinate encoding remains unresolved.

## New records and growth

The records appended at C sectors `0x7868B..0x78697` are all type `0x06`, span 1, compression `0x00`; there are no newly appended type-0x08 or type-0x09 records. The earlier claim that C added one 0x08 and one 0x09 record was a positional-alignment artifact. Consequently the 1,024-byte growth is confirmed as two additional 512-byte type-0x06 chain records, but its semantic trigger is not yet distinguished between count threshold, spatial allocation, and index split.

## Current interpretation

Type `0x06` is a large regenerated POISoN editable-point/index family containing tables or bitmaps, not a simple array of self-contained coordinate items. Point 1 changes a broad table/index region. Point 2 cannot yet be isolated at field level because C adds a sector and shifts physical record addresses. No item size, coordinate scale/origin, or BL_ADDR rewrite is confirmed.
