# Phase 31 — type-0x08 to type-0x09 bridge

The target type-0x09 header is `07 63 07 01 00 09 00 00`, so its exact BL_ADDR is `07630701` (sector `0x76307`, span `0x01`).

The direct incoming structural reference is in type-0x08 sector `0x75F47`, span `0x30`, at logical offset `0x2BC8`: bytes `07 63 07 01`. This type-0x08 block is in the same contiguous primary/type-0x08 record run as the log-reported `0x075EB7` block. The specific `0x075EB7` block itself contains no occurrence of `07630701` in its inspected logical payload, so the bridge is indirect through the primary-block family, not a direct `0x075EB7 -> 0x76307` edge.

Type-0x07 sector `0x000003` contains `075EB730` at local offset `0x30`, proving the root-to-primary edge. The proven structural path is therefore `0x07:0x000003 -> 0x08:0x075EB7` (root-selected primary block family), and independently `0x08:0x075F47 -> 0x09:0x76307 -> 0x06:0x7749B`. A single semantic root-to-leaf path through exactly `0x075EB7` is not proven.

The 0x09 block begins with a compact offset/range header, then six valid child BL_ADDRs at logical offsets `0x2C, 0x30, 0x34, 0x38, 0x3C, 0x40`: `07743F03`, `07744B29`, `07747427`, `07744209`, `07749B20`, `0774BB2B`. It therefore behaves as a flat bucket/list for these children, not a recursively proven tree. Only six children exist in this block, so the requested ten-child minimum is not met by the actual block.

The 0x07, 0x08, and 0x09 records involved are byte-identical between A and B. The strongest child-selection evidence is the compact range/offset header preceding the six BL_ADDRs; its exact key semantics remain unresolved.
