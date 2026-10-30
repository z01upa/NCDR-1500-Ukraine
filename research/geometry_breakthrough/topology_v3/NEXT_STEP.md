# Next technical step

Trace the actual SH4 code that reads Section 4 and its overflow/link consumer before enabling any topology edit.

1. Use the existing NCDR inventory to identify the map/navigation executable or DLL that is larger or more likely to own EUZ.MP0 parsing; `NAVIMAIN.EXE` is only 9,798 bytes and exposes no targeted map/graph strings. Keep this a bounded inventory lookup.
2. Run a real SH4 disassembler on that exact module and trace the 10-byte stride, low nibble, offsets `+2/+4/+6/+8`, plus its Section 7/8/9 and Section 6 accesses. Record instructions and file offsets, not decompiler guesses.
3. Decode the first word at `+2` for high-degree records and test whether it identifies a continuation table, a per-node overflow run, or a type-dependent payload. Validate on blocks outside the discovery set and preserve the 511 repeated-coordinate identities.
4. Establish the precise Section 7/8/9 row ownership and every edge-index consumer. Use a copied-block experiment with two existing edges only after a dependency map accounts for every changed key and payload.
5. Separately establish Section 5 routing/direction fields. Then implement a full-container copied-file permutation test with an independent reader; attempt one new edge only after this test and the overflow update both pass.

Current edit gate: **closed**. No original or experimental MP0 was changed in topology_v3.
