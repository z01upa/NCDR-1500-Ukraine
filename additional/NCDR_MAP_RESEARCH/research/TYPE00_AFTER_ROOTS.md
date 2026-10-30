# Type-0x00 after-root structure

- Scope: 79 confirmed road-referenced type-0x00 blocks; bytes raw +0x82..+0xA0 only.
- +0x82 does not form a constant LIST header. It begins a continuation of variable BE word pairs; values and pointer candidates vary by block.
- The first reliably repeated field pattern is at +0x96: a small metadata/count-like BE word (typically 0x0330..0x0334 / 0x033x), followed by a variable word at +0x98; +0x9A/+0x9C are small aligned metadata values. This is not yet a confirmed boundary marker.
- No field in +0x82..+0xA0 validates as a unique post-root terminator in all 79 blocks; final-root termination success: 0/79.
- Final-root boundary remains unresolved; do not use the first apparent pointer candidate as an extent without decoding the continuation grammar.
- Next exact structure: parse the continuation beginning at +0x82 as linked/paired descriptors and validate its first enclosing count/length against the root targets.
