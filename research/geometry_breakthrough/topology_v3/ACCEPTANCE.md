# NCDR MP0 node-link investigation v3 — acceptance

Date: 2026-10-29  
Outcome: **PARTIAL NODE-LINK RULES CONFIRMED; SAFE TOPOLOGY MUTATION NOT ACCEPTED.**  
New/modified MP0: **No.** Edge permutation: **No.** New edge: **No.**

## Integrity and scope

- Source read-only: `${NCDR_SOURCE_ROOT}\SW\DB\EUZ.MP0`.
- SHA-256 before and after: `73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e`.
- Independent v3 pass: all **2,956/2,956** compressed streams inflated; all block section extents parsed; **956,071** Section 4 rows and **1,090,323** Section 5 records; **0** Section 5 endpoint indexes out of range.
- Original MP0, CD media, SQLite, GUI, Worker, and Director were not written by this work.
- Evidence: `evidence/node_link_validation.json`, `evidence/block_layout_summary.json`, `evidence/firmware_scope.json`.

## What the bytes support

### Section 4, bytes +0 through +9

**Supported for the exact-identity low-degree cohort:** byte `+0` low nibble values 0–4 select that many inline little-endian u16 edge candidates, beginning at `+2`. The candidates match the multiset of local Section 5 edges whose primary endpoint index is that exact Section 4 record in **952,280/952,791** rows. Per-degree counts are:

| Low nibble | Rows | Exact node-index matches |
|---:|---:|---:|
| 0 | 119 | 119 |
| 1 | 110,359 | 110,228 |
| 2 | 527,686 | 527,552 |
| 3 | 281,608 | 281,489 |
| 4 | 33,019 | 32,892 |

The remaining **511** rows all have repeated coordinates with another node ID. Their edge lists do not match by node index. Coordinates were not used to merge them. All 511 mismatch records, both node IDs for their equal-coordinate groups, raw ten-byte values, active candidate edge IDs, and Section 5 incidence IDs are preserved in the JSON.

For exact degree-4 rows, `+8/+9` is the fourth inline edge ID in **32,892** records. The other 127 degree-4 records are among the identity mismatches and are not treated as confirmed.

For low-nibble values 0–3, `+8/+9` is **not a free slot**. Among degree-3 rows, the word is nonzero in **280,356/281,608**, lies numerically within the local edge-ID range in **234,204**, but equals a local incident edge in only **2,650**; all 2,650 values equal one of the already active inline IDs. Cross-tabulating by the high nibble does not reveal a type class where `+8` consistently adds a fourth edge. Looking up that number as a Section 7/8/9 row index also does not yield a general continuation rule. Its meaning remains unknown and it must be preserved. The complete high/low-nibble split is in `word_at_plus8_by_high_and_low_nibble`.

More generally, the first inactive u16 after the low-degree inline list is nonzero in **119/119** degree-0 rows, **110,076/110,359** degree-1 rows, **526,442/527,686** degree-2 rows, and **280,356/281,608** degree-3 rows. Thus increasing a node's nibble and writing into the next apparent slot would overwrite real, presently opaque bytes in most records.

**Partial high-degree observation, not a complete decoder:** there are **3,280** rows with low nibble greater than 4. Of these, 1,712 have low nibble 5 and exactly five local primary incidences, 222 have 6 and exactly six, and 21 have 7 and exactly seven. In those **1,955** records, the three u16 words at `+4/+6/+8` are distinct local incident edge IDs; the word at `+2` is not one of those edges. This pattern also appears in the preselected holdout blocks: 405/428 low-5, 59/87 low-6, and 6/38 low-7 rows have those same three tail words as incident-edge subsets; the other rows include cases with no local primary incidence. The other **1,325** high-nibble rows have no local primary endpoint incidence (including every low nibble 8–15). The missing high-degree links and the purpose of `+2` are not decoded. Coordinate-only incidence counts often equal a stored nibble, but duplicate coordinates and secondary-coordinate endpoints make that only a candidate relation, not node identity.

Byte `+1` has 137 observed values; the complete histogram and bit counts are included in the evidence. Its semantics are **unknown**. The high nibble of byte `+0` also varies across records; its meaning as type, flags, or a reference is **unknown**. No byte in an unresolved record is writable by this tool.

### Sections 7, 8, and 9

The existing record strides were rechecked: Section 7 is 7 bytes in 2,956 blocks; Section 8 is 11 bytes in 1,903 populated blocks; Section 9 is 13 bytes in 26 populated blocks. For each section’s first little-endian u16:

| Section | Rows | Populated blocks | All keys below local edge count | Nondecreasing in all populated blocks | Keys valid as edge IDs but above node-count in their block |
|---:|---:|---:|---:|---:|---:|
| 7 | 1,471,866 | 2,956 | 2,956 | 2,956 | 177,977 |
| 8 | 126,436 | 1,903 | 1,903 | 1,903 | 15,140 |
| 9 | 51 | 26 | 26 | 26 | 5 |

The same range and ordering checks pass on the preselected holdout blocks: 592 Section 7 blocks, 379 Section 8 blocks, and 4 Section 9 blocks. There are no first-field values that are node-only under the local node/edge counts. This is strong evidence that the first field is an **edge-index-shaped key**, and rules out treating it as a local Section 4 node index for those edge-only values. It does not alone prove ownership or meaning of every row. Row counts do not equal edge counts, keys repeat, and many edges have no row in Sections 8/9. Aligned payload words were compared against the keyed Section 5 endpoints; matches are sparse (Section 7: 5,413 endpoint-number coincidences across the tested aligned fields and 1,471,866 rows; Section 8: 397 across 126,436; Section 9: 0 across 51). Payload semantics are unresolved.

Coverage of first-field keys for edges incident to high-nibble-greater-than-4 nodes was measured separately and is in the evidence JSON. It does not establish a different layout or semantics for high-degree records. No controlled rekey experiment was safe to perform.

## Firmware scope

The bounded survey rechecked the exact inventoried `NAVIMAIN.EXE` and `NK.BIN` hashes. `NAVIMAIN.EXE` is a 9,798-byte SH4 PE; the targeted strings `MP0`, `EUZ`, `node`, `edge`, `route`, `section`, `graph`, and `map` were not found. The existing import census is OS/framework-oriented and includes ordinal imports. The existing bounded `NK.BIN` scan found 15 MZ markers and zero valid embedded PE images. No SH4 disassembler was available in the current environment. Therefore no executable code path reading Section 4 was established.

## Edit safety and tests

`topology_editor.py` supports byte-identical no-op only. It refuses permutations and topology writes because Section 6 ownership, Sections 7–9 edge-key payload meaning, high-degree continuation, the 511 node-identity anomalies, and Section 5 routing fields are unresolved. No MP0 candidate was written.

| Test suite | Result |
|---|---:|
| topology_v3 real-data tests | **8 passed, 0 failed** |
| Writer v1 regression suite | **16 passed, 0 failed** |
| topology_v2 regression suite | **10 passed, 0 failed** |

The 34 passing tests do not imply that a new edge was written or that the format is routable. Source hash verification and byte-identical no-op checks passed; there is no topology mutation result to claim.

## Exact remaining blocker

The unresolved mechanism is how high-degree adjacency beyond three confirmed inline edge IDs is represented, especially the meaning of the first u16 at `+2`, and which records in Section 6/Sections 7–9 must be updated when Section 5 edge IDs or endpoints change. Until the Section 4 continuation and all edge-key consumers are independently identified, even swapping two existing edge IDs could silently break references. Section 5 direction/access/routing meaning also remains unknown, so no new edge could yet be claimed routeable.
