# S4/S5 loader conclusions (stage C, first pass)

## Confirmed (machine code + block886 bytes)
1. The runtime loads S4 by raw 10-byte copy (0x0304D848). Therefore the meaning of byte0 high nibble, byte1 and slot +8 is NOT decided at load time; it is decided by consumers that read the RAM array.
2. S5 is converted at load time (0x0304D8A0). File layout (14 B): u32 @0 | u8 @4 | u8 @5 | u16 @6 | u16 @8 | u32 @10. +4 and +5 are two independent bytes, not a u16. The u32 @0 is loaded as one 32-bit value, so bits 16..31 of the first word exist in RAM next to the known u16 flags.
3. S1/S3 are patch tables (u16 index, u8 value) writing a u16 at +8 of 12-byte records indexed by that u16 (0x0304D7E4). The 12-byte arrays come from the S0/S2 loader (0x0304D6F0, not yet analysed).
4. S10 is carried by the dispatcher as a byte blob: length = header word +44.

## Candidate consumers (HYPOTHESIS, not traced)
- `db\db_intersection.c`: 0x03002960 (two `mov #10`), 0x03002F2C (`add #14`). First targets for byte0 mask and slot access.
- `rg\rm_db.c@0x03064848`: extracts bits 3..6 of a word at struct offset +20 (`shlr; shlr2; and #15`). Different structure; relation to S4 not shown.
- Scan table: runtime_readsites.tsv (score is a heuristic, status HYPOTHESIS for every row).

## Not yet answered
C1..C9 from the mission (high nibble, degree rule, byte1, slot +8, degree 3->4). Next step: trace the RAM array pointer stored by the dispatcher (r8 struct) into db_intersection.c readers.
