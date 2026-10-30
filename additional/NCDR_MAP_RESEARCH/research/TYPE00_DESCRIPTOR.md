# Type-0x00 descriptor test

- Blocks analyzed: 79; first pair exactly LIST(ptr=0x0074,count=3): 79/79.
- The pointer is a valid in-block address under the project convention. At raw record offset +0x74 (payload-array offset +0x6C), all 79 blocks contain non-random, pointer-like BE word sequences; the alternate payload-relative +0x74 view is also retained.
- Three repeated items are not proven by byte equality: the target bytes vary per block and do not form identical fixed-width records at widths 4, 6, 8, or 12 bytes.
- Pre-0x74 pairs are predominantly small even offsets/count-like values, but no additional pair has enough evidence for a confirmed section descriptor.
- Exact next structure to parse: resolve the 0x74 table entry grammar from the raw +0x74 view, then follow its internal pointers and determine the item stride/count before interpreting later pairs.
