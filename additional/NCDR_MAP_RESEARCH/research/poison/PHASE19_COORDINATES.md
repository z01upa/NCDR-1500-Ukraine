# Phase 19 — confirm latitude encoding

All four databases have identical size, chain count, and 1,935-point population. Logical type-0x06 record identity is stable at sector `0x76CE2`, payload size 8,696 bytes.

Longitude edit A→D changes only logical offset `0x0837`: `D8→D9` (+1). Inspecting the required neighborhood gives bytes `D8 B4 D9`; treating all three as a BE 24-bit integer would give a +0x100000 change, but the observed one-byte mutation does not prove that interpretation.

Latitude edit A→F changes only offset `0x0839`: `D9→E1` (+8). A→G changes offsets `0x0838..0x0839`: `B4 D9→B5 2F`, which is +0x0456 = 1,110 as a BE uint16. The F delta multiplied by ten is 80, not 1,110. Therefore no consistent direct 100,000-units/degree latitude integer is confirmed.

The three-byte neighborhood changes as a whole from `D8 B4 D9` to `D8 B4 E1` (F) and `D8 B5 2F` (G), so the representation exhibits quantization/carry or a non-coordinate table field. No exact editable-point item boundary is identifiable from these isolated mutations, and no complete lon/lat formula is confirmed.

The strongest confirmed fact is that the writer persists coordinate edits as one or two byte mutations in the same type-0x06 logical record, with no broad index/checksum regeneration. Further experiments must use several small latitude increments and inspect whether the displayed value is actually accepted/rounded before save.
