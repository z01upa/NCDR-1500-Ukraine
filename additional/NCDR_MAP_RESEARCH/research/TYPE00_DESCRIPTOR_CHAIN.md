# Type-0x00 descriptor chain

- Scope: 79 confirmed road-referenced blocks; continuation starts at raw +0x82.
- Pair layout: `(metadata, BE uint16 local pointer)`; metadata is not yet semantically decoded.
- Chain length distribution: 5 pairs: 77, 6 pairs: 2.
- Termination rule: stop at the first pair whose pointer is invalid or decreases below the preceding pointer; no zero/count exhaustion was needed.
- Success: monotonic descriptor chain found in 79/79 blocks; first transition observed in all blocks.
- First structure after chain: the transition pair is small metadata plus a pointer-like/non-pointer word; its grammar is unresolved and analysis stops there.
- Next unresolved field: decode the transition pair and determine whether it is a count/section header or the next descriptor family.
