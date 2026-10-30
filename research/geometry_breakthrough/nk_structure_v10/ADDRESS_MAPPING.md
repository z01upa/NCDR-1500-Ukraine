# Address-mapping audit

## Result

No validated `NK.BIN` VA-to-file mapping was recovered. The input is not B000FF-framed (`B000FF\n` absent). The only coarse ROMHDR-like candidate is unaligned at `0x9FEA2D`, but its putative 257-entry TOC produces no readable names and no mapped e32/o32 structures under flat origins 0 or `0x400`. The raw `ECEC` fields also fail the tested direct file-offset interpretation.

The repeated module-name pattern yields 48 aligned values in the CE kernel VA interval, `0x8C2194C0` through `0x8C7111C4`. Forty-six reoccur once as exact little-endian byte sequences elsewhere in the file. Those occurrences confirm correlation, not address dereference or mapping. Across the 46 observations, `VA - file_offset` has 46 distinct values; a single-base linear map is therefore rejected for these locations.

## Mapping implementation and limits

`scripts/nk_structure_probe.py` contains a sparse address map for validated B000FF segments. It handles noncontiguous regions in physical record order, rejects overlapping VA ranges, and can read across adjacent segments. Synthetic tests verify these mechanics, but the absence of an independent real CE image means the framing parser lacks a positive-control validation in this workspace. The code does not extract modules.

The `MZ`/`PE\0\0` byte counts are not evidence of a mapped executable: no module record was linked to a bounded PE, consistent section table, or independently disassembled SH4 code.
