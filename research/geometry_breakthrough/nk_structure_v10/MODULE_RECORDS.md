# 74 module-name records

## Inventory

The v8 manifest's 74 names all match exact NUL-terminated strings at their recorded offsets in the current LK841 `NK.BIN` (74/74). Their offsets are not uniformly aligned: 23 mod 4 = 0, 19 = 1, 19 = 2, 13 = 3. The scan retains 64 bytes before and after every name in `evidence/nk_structure.json`.

## Repeated CE-associated 16-byte pattern

For 48 of 74 names, the first byte pair `43 45` (`CE`) occurs 0–14 bytes after the NUL. At that marker, the following 16 bytes consistently parse as:

| Relative bytes | Reproducible observation | Semantic status |
|---|---|---|
| `+0..+1` | literal `CE` | observed marker; purpose unknown |
| `+2..+3` | little-endian 16-bit value | observed; meaning unknown |
| `+4..+7` | little-endian 32-bit value | 48/48 distinct, aligned values in `0x80000000..0xBFFFFFFF`, strictly increasing in manifest order (47/47 transitions) |
| `+8..+11` | little-endian 32-bit value | observed; meaning unknown |
| `+12..+15` | little-endian 32-bit value | observed; meaning unknown |

This is a **confirmed recurring byte-record family associated with a subset of the names**, not a confirmed Windows CE TOC or executable record. The `+4` word is a strong address/pointer candidate: every value is aligned and within the CE kernel VA range, and 46/48 values occur exactly once more elsewhere in the file. The remaining two have no second exact byte occurrence. No consumer/dereference has been proven, so the field is not called a module load address as a fact.

To reduce overfitting, indexes 0–36 and 37–73 were evaluated separately. The first subset contains 22 candidates; all 22 `+4` values are unique, aligned and in range, strictly increasing across its 21 transitions, with 20 secondary occurrences. The held-out second subset contains 26 candidates; all 26 satisfy the same value/range/alignment conditions, are strictly increasing across 25 transitions, and have one secondary occurrence each.

### Target examples

- `NavigationRem.dll`: name at `0x9FA304`, marker at `0x9FA318`, 2 bytes after NUL. Record: `43 45 27 03 64 51 59 8C 94 0E 00 00 3B AB 05 00`. Candidate `+4` word `0x8C595164`; secondary exact occurrence at `0xA1AC1F`.
- `nmicore_ce.dll`: name at `0x9FB1C8`, marker at `0x9FB1D7`, immediately after NUL. Record: `43 45 10 04 44 C5 59 8C BC 0A 00 00 8A CF 03 00`. Candidate `+4` word `0x8C59C544`; secondary exact occurrence at `0xA1B14C`.

The observed secondary copies do **not** supply a flat VA-to-file formula: the 46 `VA - secondary_file_offset` values are all different (range `0x8B82BEED`–`0x8BCF5AC9`). The locations are not a fixed-stride table. Fields `+2`, `+8`, `+12`, padding before `CE`, record boundaries, and the meaning of the secondary copies remain unknown. Accordingly neither target module is extracted or treated as executable code.

The remaining 26 names do not have this pattern within the tested 16-byte window; that difference is retained rather than forced into the model. No common fixed-width row/table covering all 74 names was established.
