# Known facts (verified in this session, 2026-11-01)

Evidence classes: CMC = CONFIRMED_BY_MACHINE_CODE, CBD = CONFIRMED_BY_BINARY_DATA.
All reproducible with `python3 -I research/deep_re/tests/run_tests.py` (12 PASS, 1 BLOCKED).

| # | Fact | Class | Evidence |
|---|------|-------|----------|
| 1 | `block886.bin` = 30061 bytes, SHA-256 c4fd9570...d983a6; header = 23 LE u16 words (46 bytes) | CBD | tests T01, T12 |
| 2 | NavigationRem.dll section_0 runtime base 0x02FD1000, section_1 0x030B4000 | CBD | module.json + section SHA, T02/T03 |
| 3 | Link VA -> runtime VA delta is 0x02000000 for all 5 sections; code literals (e.g. 0x010B38B4) are link-time VAs | CBD + CMC | section_mapping.json; literals in verified_instructions.tsv |
| 4 | Old base 0x2FEA0000 cannot map the code (entry offset outside section) | CBD | T04 |
| 5 | 58 consecutive SH4 instructions decoded at 0x030B3830..0x030B38A2, bytes == file, 7 branch targets and 5 literal loads recomputed independently, Capstone and pypcode(SLEIGH) agree 58/58; function ends with rts + delay slot, then literal pool | CMC | 01_disassembler/*, T07 |
| 6 | Dispatcher `db_upack.c@0x0304DBE8` loads header words (pairs at +0..+38, then +40 and +44) and calls one loader per section | CMC | s4_code_evidence.asm, header_pairs_crosscheck.json |
| 7 | S4 header pair is (+16 offset=3270, +18 count=664); loader 0x0304D848 copies records of exactly 10 bytes raw (`mov #10,r6`, both pointers `add #10`), no field conversion | CMC + CBD | T09, T10 |
| 8 | S5 loader 0x0304D8A0: file record 14 bytes = u32@+0, u8@+4, u8@+5, u16@+6, u16@+8, u32@+10; RAM struct is 16 bytes (u32,u8,u8,u16,u16,pad2,u32) | CMC | T08 |
| 9 | S1/S3 loader 0x0304D7E4: 3-byte records (u16 LE index, u8 value) -> `dst[index*12+8] = value` (u16 store) | CMC | s4_code_evidence.asm |
| 10 | S10 length comes from header word +44 (3120 bytes); 26941+3120 = 30061 = file size. Dispatcher has no direct displacement load of +42 (369) | CMC + CBD | header_pairs_crosscheck.json |
| 11 | Section chain is contiguous: S4 end == S5 start (3270+664*10=9910), S5 end == S6 start (9910+706*14=19794) | CBD | T12 |
| 12 | NavigationRem.dll contains the whole Siemens DB/routing stack (db_*.c, idb_*.c, rg_*.c, dbutils, mnvr), not only COM glue | CBD | string_xrefs.tsv, source_file_to_functions.json |
