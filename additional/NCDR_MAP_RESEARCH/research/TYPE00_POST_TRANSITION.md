# Type-0x00 post-transition windows

- Windows: 79 total; +0x96: 77; +0x9A: 2. Exact 16-byte pattern clusters: 79 (largest cluster 1).
- Position stats (index: unique, zero-rate, min..max): 0: 34, 0.013, 0x0000..0x0600; 1: 64, 0.000, 0x001E..0xFD17; 2: 10, 0.342, 0x0000..0x1800; 3: 15, 0.215, 0x0000..0x6C0E; 4: 29, 0.013, 0x0000..0x0C00; 5: 66, 0.000, 0x001E..0xFD2C; 6: 12, 0.190, 0x0000..0x1800; 7: 12, 0.215, 0x0000..0x380E.
- Dominant layout: four repeated-looking `(metadata, value)` word pairs; metadata words are small/highly structured, while value words vary. No identical 16-byte binary pattern dominates.
- The transition is not proven to be a boundary: second word is a valid local PTR in 21/79 windows, so a non-monotonic descriptor remains possible.
- No confirmed pointer relation to all three roots or to the previous pointer; relative differences are block-specific.
- The +0x9A cases have the same pair layout but begin two bytes later because their descriptor chain has one additional monotonic pair; no distinct section signature is confirmed.
- Next exact experiment: compare the transition value as another descriptor pointer against the complete ordered target set, still limited to this 16-byte window.
