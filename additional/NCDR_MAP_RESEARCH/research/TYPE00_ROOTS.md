# Type-0x00 root descriptors

- Confirmed blocks: 79; root rows: 237.
- Grammar at +0x74: `word74` header/count-like field; then three 4-byte descriptors `(metadata, pointer)` at +0x76/+0x78, +0x7A/+0x7C, +0x7E/+0x80; +0x82 begins the enclosing structure.
- All blocks have three valid root targets; distinct-root count is three in 5/79 blocks.
- Pointer encoding: BE uint16 local offset from BL_HEAD. CSV includes the first 32 BE words at every root target.
- Root extents: start at each sorted distinct target and end at the next distinct target; the final root uses the first later confirmed in-block pointer candidate from the enclosing structure.
- Terminal boundary is not yet reliable: the enclosing pointer candidate is observed but its grammar is unconfirmed.
- Next unresolved field: identify and validate the +0x82 enclosing structure so the final-root terminal boundary becomes exact.
