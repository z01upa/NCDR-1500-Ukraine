# NK.BIN header and container analysis (v10)

## Input and method

Read-only input: LK841 `NK.BIN`, 11,021,915 bytes, SHA-256 `d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847`. The probe in `scripts/nk_structure_probe.py` scans every byte offset for ROMHDR candidates, tests TOC mappings at file origins 0 and `0x400`, recognizes B000FF framing only when its signature and bounded records validate, and never extracts data. It does not alter v9.

## v9 assumptions audited

- **Alignment:** v9's ROMHDR search stepped by four bytes. v10 scans byte-by-byte. It finds one coarse candidate at file offset `0x9FEA2D` (offset mod 4 = 1), so the alignment restriction could miss candidates in general. This candidate is not a valid ROMHDR/TOC on this input.
- **VA to file offset:** `origin + (VA - base)` is only a flat-image hypothesis. v10 also implements sparse B000FF segment mapping independent of physical segment order and rejects overlapping/ambiguous ranges. The real LK841 file has no B000FF signature, so neither that format nor a sparse mapping is established for it.
- **`nk.exe` TOC position:** v10 imposes no fixed slot requirement. A synthetic control with an unaligned ROMHDR and a coherent one-entry `route.dll` TOC (no `nk.exe`) is accepted. The control validates scanner behavior only, not the LK841 format.
- **Positive control availability:** no independent, genuine Windows CE ROM/BIN fixture was present in the local project inventory. Therefore standard B000FF/ROMHDR handling has synthetic unit coverage but no real-image positive-control result.

## LK841 observations

- The first 4 KiB have entropy 5.83570 bits/byte, 7.373% zero bytes and 24.561% `FF` bytes. `LK-01-05` occurs once. `CE00FF\n` occurs at `0x400`; its following bytes begin `0B 00 00 1F 8C 24 BE 10`.
- Full image: no `B000FF\n` and no ASCII `ROMHDR`; one `ECEC`, 15 `MZ` byte pairs and one `PE\0\0` signature. These isolated signatures do not establish a ROM container or executable module.
- Across 169 64-KiB chunks, entropy ranges 6.98413–7.61427 (median 7.26852). zlib level 1 yields 9,321,907 bytes (0.845761 ratio). These measurements show compressibility only; they do not identify an encoding or segmentation scheme.
- A bytewise scan yields one coarse ROMHDR-like structure at `0x9FEA2D`: 257 proposed modules and 40,544 files, but 0/257 readable names and 0/257 mapped e32/o32 records under both tested flat origins. It fails structural TOC validation and is rejected. The earlier v9 aligned hit at `0x9D7794` also fails: its `physfirst=0xCC640096` is outside the Windows CE kernel VA range used by the validator.
- Raw `ECEC` is at `0x9CEAD3` (unaligned). Its `ptoc` value is `0x8D2F66CC`; the following offset-like word is `0x025A4543`, outside the file as a raw offset. Neither value yields a validated ROMHDR under the tested raw-offset formula.

Conclusion: the first-page marker and raw `ECEC` are real byte observations, but the physical LK841 NK container, ROMHDR location, and VA-to-file mapping remain unresolved.
