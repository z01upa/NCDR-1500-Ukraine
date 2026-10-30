# Type-0x00 +0x74 table analysis

- Blocks: 79. Candidate structure: word0 header, then three 4-byte descriptors `(metadata, local_offset)`.
- Three valid roots at word positions 2, 4, 6: 79/79. Strictly increasing: 5/79.
- Root pointer encoding: big-endian uint16 local offsets from BL_HEAD; root fields are raw +0x78, +0x7C, +0x80.
- Object boundary rule: each root starts an object; boundaries are the next higher root, with the final extent requiring the next enclosing pointer/section boundary.
- Descriptor metadata words at raw +0x76, +0x7A, +0x7E vary by block and are not yet semantically decoded.
- Next exact structure: parse the three root objects at each root offset, then identify the terminal boundary for root 3 from the next table/list pointer.
