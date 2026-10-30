# Type-0x00 motif to next descriptor

- First descriptor-like pair after the 16-byte region: found in 78/79; D distribution: 20:14, 18:10, 28:7, 36:4, 26:4, 16:4, 24:2, 1354:1, 3178:1, 1310:1, 2378:1, 1674:1.
- Tested byte and adjacent-BE-word multiples (1,2,4,8; uint16×1,2,4); no single field predicts D across the 79 blocks.
- `b4=0x03` occurs in 76/79, but does not uniquely determine D or a fixed three-group extent.
- No self-length, next-section offset, or fixed 3-entry substructure rule is confirmed.
- Success: 0/79.
- Next unresolved field: identify the descriptor-family marker for the first post-window pair, including blocks with no candidate within the bounded scan.
