# Confirmed on the complete LK841 image
Input: 11,021,915 bytes. SHA-256 `d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847`.

- The LK wrapper occupies the first 0x400 bytes. Signature `CE00FF\n` starts at 0x400; byte +7 is 0x0B, meaning unresolved (not a verified checksum).
- Global LE32 +8 = image base 0x8C1F0000; LE32 +12 = span 0x110BE24.
- Packet stream begins at 0x410. Header is 16 bytes: ASCII CE at +0; LE16 header sum at +2; LE32 destination VA at +4; LE32 decoded byte count at +8; LE32 decoded additive checksum at +12.
- Header sum equals sum of its 12 bytes at +4..+15. This holds for every decoded packet and the terminal header.
- A token below 0x80 copies that many following literal bytes.
- Token 0x80..0xBF: length = token & 0x3F, then an unsigned 8-bit backward distance.
- Token 0xC0..0xFF: length = token & 0x3F, then an unsigned 16-bit little-endian backward distance.
- Match copying is byte-by-byte and permits overlap. Dictionary starts empty for each packet. No length or distance bias is added.
- Decoding stops exactly at the declared output length. The consumed-input cursor is the next packet boundary; compressed length is not guessed from CE string hits.
- Packet checksum is sum(decoded bytes) modulo 2^32. All 1065 packet sizes and checksums passed. Zero literal/zero-length match/zero distance were not encountered and are rejected rather than assigned speculative semantics.
- Zero-address header at 0xA82E4B ends the stream exactly at EOF. Its +8 value is 0x8C1F0004 (entry-point interpretation still unverified); +12 is zero. It has no data payload.
- Decoded destination ranges do not overlap. 17,845,716 bytes mapped across 0x8C1F0000..0x8D2FBE24 (end exclusive); 28,752 bytes are unrepresented gaps, tracked explicitly.
- Recovered image contains ROM signature ECEC and a ROMHDR/TOC candidate at 0x8D2F66CC: 154 complete TOC rows, all names resolve through recovered address coverage. The candidate CPU field is zero: this does not establish SH4 code validity. Target module e32/o32/load pointers are preserved in modules.csv; DLL code has not been extracted or validated.

Provenance: the transferred v10 report explicitly left CE+2 semantics unresolved. This run established the packet rules through exact whole-image consumption, decoded lengths and all additive checksums. No prior algorithm implementation was available in that transfer. No claim is made that this format applies to every Windows CE image.
