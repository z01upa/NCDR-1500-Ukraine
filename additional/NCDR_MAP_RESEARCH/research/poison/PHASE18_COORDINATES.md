# Phase 18 — isolate POISoN coordinate encoding

## Result

OUTPUT_A and OUTPUT_D have identical record chains and point counts. Their only DB_0 difference is one byte in type `0x06`, sector `0x76CE2`, physical span `0x11`, logical payload size 8,696: logical offset `0x0837`, `D8→D9`.

The edited display longitude is 20.27098→20.27099, a delta of 0.00001 degree. The one-byte stored delta is +1, giving a directly observed scale of 100,000 stored units per degree. This is consistent with a direct decimal fixed-point longitude byte field only at this location; the surrounding structure and full coordinate representation are not yet decoded.

OUTPUT_A and OUTPUT_E are byte-for-byte identical, including DB_0 SHA256 (`538a3fbee97b1abab6fb10bfa31ff37fa83ab1a64f762301e8eca5d2d8fd3dfd`). No latitude-specific persisted offset, field, index change, checksum change, or regenerated type-0x06 noise is observable. The latitude edit may not have been committed or may have been rejected/rounded by the writer.

## Structure

The smallest confirmed primary change is the single byte at `0x76CE2:0x0837` in the logical type-0x06 payload. An exact editable-point item boundary cannot be proven from this single-byte mutation; no fixed-width item or neighboring coordinate pair is established. No Morton, tile-origin, split high/low, varint, or lookup-reference encoding is confirmed. The changed byte is therefore recorded as a longitude candidate, not as a complete coordinate decoder.

## Conclusion

This experiment separates true point data from index regeneration noise: longitude produces one persisted primary byte; latitude produces none. The next experiment must repeat the latitude edit and verify that the application visibly accepts and saves it, ideally with two distinct non-rounding latitude increments.
