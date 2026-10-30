# DB_0 reverse-engineering project state

This file records confirmed facts required for continuation. `DB_0` is read-only.

## Physical framing

- `DB_0` size: 252,521,472 bytes = 493,206 physical sectors of 512 bytes.
- A record header starts at a physical sector boundary.
- Bytes `0..2`: big-endian uint24 record sector number.
- Byte `3`: physical record span in 512-byte sectors.
- Next record sector is `sector + byte3`.
- The validated main chain runs from sector `0x000002` through `0x078695`.

## BL_HEAD fields

- `+0x00..0x02`: sector identifier (uint24 BE).
- `+0x03`: physical span (uint8, sectors).
- `+0x04`: alignment/header field.
- `+0x05`: block type.
- `+0x06`: compression code.
- `+0x07`: logical-size units; logical extent is `byte7 * 512` bytes.
- Physical span and logical extent are separate values.

## Compression

- For every validated `compression=0x02` record, zlib begins at local byte `8`.
- For those records, `len(decompressed_payload) + 8 == byte7 * 512`.
- The zlib stream is bounded by the physical record span.
- Type-`0x00` targets with `compression=0x01` are present; their logical extent
  is known from byte 7, but the compression decoder is unresolved.

## Confirmed block types

- `0x0A`: country text records.
- `0x0C`: city/administrative text and MORE_INFO records.
- `0x0E`: road container / road object ownership.
- `0x0F`: CH_IDX records selecting lists in `0x0E`.
- `0x00`: targets referenced by the confirmed 24-byte road objects.
- `0x10`: dense MULCOORD coordinate records.

## PTR, LIST, FAR_LIST

- Local PTR fields are big-endian uint16 logical offsets within the current block.
- LIST is a big-endian uint16 pointer followed by a big-endian uint16 count.
- A BL_ADDR/FAR_LIST address is three BE bytes of target sector followed by
  one byte of physical span; the target header must match both values.
- The target block type is read from target header byte `+0x05`.

## MULCOORD

- A coordinate pair is two BE uint32 values `hlon`, `hlat`.
- `longitude = hlon / 5,555,555 - 30`.
- `latitude  = hlat / 5,555,555`.

## Confirmed `0x0C -> 0x0F -> 0x0E` chain

- Moscow city record: sector `0x0899`, physical span `0x2C` (44).
- Moscow BRIF is at logical offset `0x07E8`; its MORE_INFO pointer is `0x21F0`.
- The `ch_roads` FAR_LIST bytes are `00 1B 19 24`: target sector `0x1B19`,
  span `0x24`, target type `0x0F`.
- In type `0x0F` sector `0x1B19`, CH_IDX starts at logical offset `0x4A10`:
  `0031a01f31010f2000b90000`.
- It selects type `0x0E` sector `0x31A0`, span `0x1F`, and a list at
  logical offset `0x0F20` with count `185`.

## Confirmed type-`0x0E` BRIF layout

- Width: 8 bytes.
- `+0x00`: name PTR (uint16 BE).
- `+0x02`: place/bitmask byte.
- `+0x03`: language byte.
- `+0x04`: region PTR (uint16 BE).
- `+0x06`: extended-info PTR (uint16 BE).
- All 185 Moscow entries at `0x31A0:0x0F20` parse with this layout.

## Confirmed six-byte road MORE_INFO

- Each Moscow road MORE_INFO record is exactly 6 bytes: three uint16 BE values.
- `field0`: pointer into the 24-byte object array.
- `field1 >> 8`: number of owned 24-byte objects.
- `field1 & 0xFF`: one-byte flag field.
- `field2`: zero in all 185 Moscow records.
- MORE_INFO pointers run from `0x1F9E` through `0x23EE` in 6-byte steps.
- The `0x31A0` object-array LIST is at logical `0x23F4`, count `933`.

## Confirmed 24-byte road object

- `+0x00`: `hlon` uint32 BE; `+0x04`: `hlat` uint32 BE.
- `+0x08`, `+0x0A`, `+0x0C`, `+0x0E`: uint16 BE fields A, B, C, D.
- `+0x10`: BL_ADDR (target sector uint24 BE + span byte).
- `+0x14`: uint16 BE field E; `+0x16`: uint16 BE field F.
- Width is 24 bytes. All 483 analyzed objects have valid coordinates and
  BL_ADDRs to type `0x00` targets.
- Current strongest E interpretation: `pointer = E & 0x3FFF`, `flags = E >> 14`.
- F behaves as the referenced-list/object count. Flag semantics and element
  width remain unresolved.

## Current unresolved fields A-F

- A, B, C, D: exact meaning is unresolved; index/range behavior is only a
  working description, not a decoded schema.
- E: the `0x3FFF` pointer mask is the strongest tested interpretation; the
  semantics of bits 15..14 and the exact target-list encoding remain unresolved.
- F: behaves as a count, but the element width and element structure are unresolved.

## Example: `1 iy mikrorayon`

- BRIF logical offset: `0x0F20`; name: `1 iy mikrorayon`.
- MORE_INFO pointer: `0x1F9E`; raw bytes: `54b401010000`.
- `field0=0x54B4`, `field1=0x0101` (count 1, flag 1), `field2=0`.
- Object at `0x54B4`: `16411000128bd000006400a6006500a7035329214df8001f`.
- Coordinate: `37.205291 E, 56.007481 N`.
- A/B/C/D: `100, 166, 101, 167`.
- BL_ADDR: sector `0x35329`, span `0x21`, target type `0x00`.
- E/F: `E=0x4DF8`, `F=31`; masked pointer is `0x0DF8`.
- Target header: sector `0x35329`, raw header `035329210000014a`, compression `0x01`,
  advertised logical size `0x4A * 512`, physical span `0x21`.

## Latest result files

- `research/roads/OBJECT24_FORMAT.md`
- `research/roads/object24_pointer_encoding.csv`
- `research/roads/type00_list_references.csv`
- `research/roads/type00_element_layout.csv`
- `research/roads/type00_targets.csv`
- `research/roads/type00_35329_0DF8.txt`
- `research/roads/1iy_type00_items.csv`
- `research/roads/ROAD_FORMAT.md`
- `research/FORMAT.md`
- `research/FINDINGS.md`

## Phase 12 checkpoint

- Rebuilt 483 road-owned type-0x00 references across 413 unique target-block pointers; duplicate owners and all F values are retained in `research/roads/phase12_road_refs.csv`.
- Known next-pointer extents were measured for 413 pointers. No fixed element width or uniform pointer-table grammar is confirmed across F>1 lists.
- The 1 iy mikrorayon region is preserved as raw bytes and remains unresolved; no speculative geometry was emitted.

## Phase 13 checkpoint

- Mapped 483 unique road-owned pointers to 457 provisional root/descriptor ranges across 79 type-0x00 blocks.
- No new section-relative or E-flag semantics are confirmed; terminal section framing and compression=0x01 grammar remain unresolved.

## Phase 13 checkpoint

- Mapped 413 unique road-owned pointers (483 owner rows) to 457 provisional root/descriptor ranges across 79 type-0x00 blocks.
- No new section-relative or E-flag semantics are confirmed; terminal section framing and compression=0x01 grammar remain unresolved.

## Phase 14 checkpoint

- Built readable type-0x00 logical views for 3232 blocks (196 compression=0x00 and 3036 compression=0x02).
- Exported prefix validation, provisional section maps, structural matches, and conservative road-pointer classifications; no new semantic decoder is confirmed.

## Phase 15 checkpoint

- Static PE metadata, imports, strings, and auxiliary file snapshots were extracted for POISoN and patch; neither executable was run.
- No compression-0x01 decoder, coordinate routine, database writer strategy, or relocation behavior is confirmed yet.

## Phase 43 checkpoint

- Persisted Moscow ownership data contains 185 roads and 483 ordered 24-byte objects; 114 roads have at least two objects, producing 298 consecutive transitions.
- Ordered absolute MULCOORD anchors are not sufficient as detailed road geometry: median consecutive distance is 0 m, p90 is 2,218.17 m, and maximum is 6,004.36 m.
- The known `1 iy mikrorayon` road has one object, so it provides no within-road continuity test.
- Seventy `(target,ptr)` slots are shared by multiple roads; all callers of a shared slot have the same anchor. Phase 41 class coverage is incomplete, so Z/NZ conditional rates are not established.
- No exact A/B/C/D adjacency grammar is confirmed; the strongest tested equality is C[N]==C[N+1] (105/298).
- Anchors are provisionally routing/control nodes or duplicated edge records; detailed geometry remains unresolved.

## Phase 44 checkpoint

- Persisted object ownership yields 413 unique `(target,ptr)` candidate nodes, 70 multi-road nodes, and 298 transitions between different node IDs; the undirected candidate graph has 102 components and largest component size 16.
- There are 184 consecutive equal-coordinate transitions, and every one uses different node IDs. Equal anchors therefore do not prove shared-node identity.
- No exact A/B/C/D adjacency grammar is confirmed; the strongest equality remains C[N]==C[N+1] at 105/298. A/B/C/D were not found at aligned BE16 positions in the 101 available raw32 slots.
- Only four multi-road nodes overlap the persisted Phase 41 lattice, all Z; Z/NZ graph-role rates are not established.
- Routing-node/edge semantics, exact MULCOORD-byte identity, and detailed geometry remain unresolved.

## Phase 45 checkpoint

- Targeted recovery confirms the 24-byte anchor layout: BE32 `hlon` at `+0x00` and BE32 `hlat` at `+0x04`; all 483 Moscow objects were recovered.
- Exact raw 8-byte MULCOORD grouping yields 102 physical nodes; 79 have multiple object records and 67 are used by multiple roads. A physical node can carry up to 22 distinct `(target,ptr)` descriptors.
- Collapsing consecutive duplicate physical nodes yields 114 edges, 22 components, and largest component 11; this is more compact than the descriptor graph but not complete-network proof.
- No exact descriptor A/B/C/D, F, E-flag, raw32, or Z/NZ topology rule is confirmed. The strongest collapsed-edge equality is D(P)==D(Q), 56/114.
- Raw MULCOORD is confirmed as the strongest physical-node key; descriptor semantics and detailed geometry remain unresolved.

## Phase 46 checkpoint

- Across 10,615 references, `C-A` ranges -32766..32765 and is nonnegative in 57.44%; `D-B` ranges -32766..32765 and is nonnegative in 59.69%. A/B/C/D are not confirmed bbox corners.
- `B-A` is always nonnegative (0..122) and `D-C` always nonnegative (0..84), but this does not establish coordinate semantics.
- Across 102 physical nodes, A/B/C/D constancy is only 34.3%, 32.4%, 37.3%, and 34.3%; fields vary by descriptor/caller.
- The 102 recovered physical nodes and 102 type-0x00 targets form an exact 1:1 mapping in the Moscow sample.
- Raw32 aligned BE16 hit rates are low: A 29, B 43, C 44, D 55 of 10,615. A/B/C/D remain unresolved caller-local index/range or topology metadata; detailed geometry remains unresolved.

## Phase 47 checkpoint

- The 102 physical-node/type-0x00 target 1:1 mapping remains confirmed for the Moscow sample. Phase 45 provides 114 collapsed transitions and 74 unique directed physical-node pairs.
- No direct neighbor target-sector, BL_ADDR, ordinal, reciprocal pointer, or coordinate-delta encoding was found in the selected raw32 records.
- Only 9/114 transitions have both endpoint raw32 records in the persisted Phase 41 subset; the best endpoint byte equality is 9/114 and is not semantic evidence.
- No shared edge ID or secondary geometry pointer is confirmed. Graph transitions remain ownership-derived, and descriptor/geometry semantics are unresolved.

## Phase 48 checkpoint

- Full type-0x00 header inventory confirms 3,232 readable records: 196 compression-0 and 3,036 compression-2.
- The persisted Phase 39 corpus contains 10,615 validated reverse-reference rows, all to 23 readable compression-2 targets; it does not retain complete MORE_INFO road ownership and ordered object-array boundaries.
- Therefore no global road transition, RR edge corpus, descriptor-per-neighbor result, or global D(P)==D(Q) rate is claimed in this phase. A complete global corpus requires a new all-0x0E BRIF/MORE_INFO parser.

## Road-parser join diagnosis

- The deterministic CH_IDX/BRIF/MORE_INFO parser recovers 33,381 roads and 95,119 owned object occurrences in the 52 Phase39 source sectors.
- Phase39's `object_offset` is actually the BL_ADDR field offset (`object_start + 0x10`). Subtracting `0x10` joins 10,608/10,615 rows; seven rows are structural false positives.
- All 101 original readable Moscow controls match confirmed ownership. Sector identity is unchanged between datasets.
- The authoritative owned-object corpus contains 20,156 readable object occurrences with an in-bounds selected 32-byte window.
- Phase39–42 aggregate counts must be recomputed after removing the seven false positives and correcting the stored object offset; the confirmed 483/101-object findings remain valid.

## Authoritative readable-road corpus

- `build_authoritative_corpus.py` deterministically rebuilds 33,381 roads, 95,119 owned object occurrences, and 20,156 readable in-bounds objects for the confirmed 52-sector corpus.
- All readable targets use one stable pointer residue modulo 32. There are 2,886 unique readable slots across 30 targets; F is invariant in 2,797 slots.
- Authoritative referenced class counts are Z=12 and NZ=2,874. The old Phase40/41 Z/NZ and 10,757-position saturation counts are invalidated.
- Exact raw MULCOORD grouping yields 354 physical nodes with an exact 354↔354 node/target one-to-one mapping.
- Ordered ownership yields 24,419 transitions and 1,002 unique physical-node pairs; coverage is RR=2,200, RU=2,902, UR=2,978, UU=16,339.
- Descriptor selection is not one-neighbor/one-pointer. The strongest RR relation currently observed is raw32 BE16 `+0x10` equality: 1,593/2,200 versus 471/2,200 shuffled control.

## Phase 42 checkpoint

- The persisted Phase 41 lattice contains 10,757 materialized 32-byte positions across 23 type-0x00 targets; every position classifies as Z or NZ using BE16 at `+0x10` (zero/nonzero), so this discriminator does not prove physical table boundaries.
- Counts are Z=10,021 and NZ=736; referenced counts are Z=2,299 and NZ=159. NZ has 289 distinct values and 214 runs, including 522 NZ→NZ transitions, so it is not a universal header or extension.
- All 10,757 raw32 values are unique in the persisted lattice; no duplicate group or cross-target raw32 reuse was found.
- Expanded Phase 39 caller names are blank; road-name multiplicity by class is therefore undetermined. NZ semantics, independent boundary framing, and node/edge/index roles remain unresolved.

## Phase 41 checkpoint

- Persisted raw32 for all 10,757 known lattice positions: 2,458 referenced plus 8,299 intermediate.
- Every materialized position is Z (`+0x10==0`) or NZ (`+0x10!=0`): Z=10,021 and NZ=736; no padding/OTHER class occurred.
- Unreferenced positions are Z=7,722 and NZ=577, so all 8,299 intermediates match the primary Z/NZ split.
- Transitions are Z→Z=9,800, NZ→NZ=522, NZ→Z=213, Z→NZ=199; NZ is a mixed class, not proven header/extension. Physical table boundaries and semantic fields remain unresolved.

## Phase 40 checkpoint

- Referenced 32-byte slots split into Z (`BE16(+0x10)==0`): 2,299/2,458 (93.53%), and NZ: 159/2,458 (6.47%). NZ values are heterogeneous; no semantic meaning is assigned.
- The persisted intermediate-slot file has 4,880 compatible and 3,419 different positions but lacks raw32 bytes, so intermediate structural classes and transitions are not reproducible from saved artifacts.
- No exact caller-field relation, class-specific F explanation, anchor clustering distinction, paired-slot grammar, or geometry role is confirmed.

## Phase 39 checkpoint

- Persisted the full targeted dataset: 10,615 validated road-object references, 2,458 unique target/pointer slots, and 23 readable type-0x00 targets; Phase 36 counts reproduce exactly.
- Every target has a single known-pointer residue modulo 32 and delta gcd 32. Of 8,299 intermediate 32-byte positions, 4,880 (58.8%) match the dominant referenced-slot zero-mask signature.
- True table boundaries and slot semantics remain unresolved. Offset `+0x10` is zero in 93.53% of known slots; no semantic field or internal pointer is confirmed.
- F is invariant for 97.1% of unique target/pointer groups; 71 groups vary.

## Firmware RE checkpoint (F1)

- `tools/POISoN/patch.exe` was analyzed statically only; it was not executed and no source/research files were modified except the requested reports.
- The executable is a 16,896-byte PE32 i386 GUI host. Its expected firmware module name is exact lower-case `navboot` (literal file offset `0x34A5`).
- The input is a structured module/container format, not a flat map DB file. A big-endian outer/container magic `0x4DAD0002` is checked at code RVA `0x15B9`; module records carry size/alignment/name/type/CRC/parity validation.
- No fixed target-file size, filename extension, version text, concrete NAVBOOT patch offset, original-byte signature, replacement byte sequence, or concrete patch count is embedded in `patch.exe`. The executable contains only a generic module-relative patch writer and runtime/parser data.
- The generic writer performs bounds checking, expected-value checking, and big-endian replacement writes; exact target offsets require the external patch description/runtime inputs, not present in this binary.
- The patcher has no references to `lng_rel.tbl` or `voice.lst`; DB facts remain separate and are not inferred from this firmware result.
- Reports: `research/firmware/F1_PATCH_TARGET.md`, `f1_strings.txt`, `f1_patch_sites.csv`, `f1_target_signatures.csv`.

## Firmware RE checkpoint (F2)

- Static reconstruction confirms only the outer magic `4D AD 00 02`, a big-endian size invariant at record `+0x04` (`>0x5C`, 4-byte aligned, in-bounds), and the exact `navboot` module-name lookup.
- Complete outer-header/directory semantics, payload boundary, CRC parameters, parity algorithm, replacement-size update, and nested NAVBOOT format remain unresolved from `patch.exe` alone.
- Local read-only search under `~/Desktop/NCDR_MAP_RESEARCH/` found no matching firmware image. The only `navboot` hit is the patcher’s own literal.
- Added conservative non-destructive parser: `research/firmware/firmware_container.py`; F2 notes: `research/firmware/F2_CONTAINER_FORMAT.md`; local results: `research/firmware/f2_local_search.csv`.

## Phase 38 checkpoint

- The per-target 32-byte slot lattice remains confirmed for 2,458 saturated target/pointer pairs, but true table boundaries are not proven.
- The saved workspace does not contain the full row-level 10,615-reference saturation output, so complete slot field statistics, intermediate-slot validation, caller relations, and geographic clustering were not established in this phase.
- No semantic descriptor field, internal pointer, coordinate field, or F explanation is confirmed.

## Phase 37 checkpoint

- For all 23 readable targets, every one of 2,458 unique referenced pointers satisfies `(ptr-min_ptr_for_target) % 32 == 0`; the per-target 32-byte slot model is exact for known references.
- The slot base is target-specific; no global base is established. Larger gaps are compatible with unreferenced slot positions, but those intermediate slots are not fully validated.
- Slots have repeated descriptor-like 32-byte structure, but no secondary local pointer or geometry field is proven. F is invariant for 97.1% of target/slot groups and variable for 71 groups.

## Phase 36 checkpoint

- Targeted reverse search across all 861 type-0x0E blocks found 10,615 accepted road-object-layout hits for the 23 readable type-0x00 targets, yielding 2,458 unique `(target,ptr)` pairs.
- The 2,435 adjacent unique-pointer deltas have gcd 32 and range 32..2,592; delta 32 is most common (652 occurrences).
- F is identical for 2,387/2,458 unique pointer groups (97.1%), but differs in 71 groups; it is pointer-associated but not proven intrinsic record length/count.
- No universal descriptor signature, local subpointer, or geometry decoder is confirmed.

## Phase 35 checkpoint

- The readable sample contains 101 incoming pointers across 23 type-0x00 targets; 20 targets have at least two distinct pointers.
- All 101 `E & 0x3FFF` pointers are 4-byte aligned. The 74 distinct-pointer deltas range 32..12,608 bytes with median 1,152; all are divisible by 4.
- No stable record-start prefix, length prefix, terminal framing rule, or exact F-to-length relation is confirmed. Four duplicate-pointer groups have identical road identity, anchor, and F.
- Pointer-defined intervals remain candidate extents only; no variable-length geometry record or polyline decoder is confirmed.

## Phase 34 checkpoint

- Among 101 readable road objects, E-masked pointers are always 4-byte aligned but occupy all four 16-byte phases: 42 at phase 0, 15 at phase 4, 13 at phase 8, and 31 at phase 12.
- Pointer-to-next-pointer gaps are 16-byte divisible for 85/101 objects but not for 16/101; no global 16-byte element alignment or exact run boundary rule is confirmed.
- F has no exact relationship to candidate 16-byte run length. Repeated local 16-byte-looking patterns remain unresolved; no polyline decoder or coordinate field grammar is confirmed.

## Phase 33 checkpoint

- 101 of 483 validated road objects target readable type-0x00 blocks (compression 0x00 or 0x02), spanning 23 unique targets; the sample is all compression 0x02.
- `E & 0x3FFF` remains an in-bounds local pointer candidate. Readable pointer neighborhoods show repeated 16-byte-looking records, but no element/terminal grammar is confirmed.
- No complete road polyline or validated coordinate-delta decoder was recovered. F, A/B/C/D semantics, and compression-0x01 geometry remain unresolved.

## Phase 32 checkpoint

- 44 type-`0x08` records exist; the target family includes ten contiguous `0x30`-span members from `0x075EB7` through `0x076067` plus a `0x21`-span tail at `0x076097`.
- There are 5,491 type-`0x09` records. Target `0x76307` has a 44-byte header candidate, BE16 `0x0006` at logical `+0x06`, and six 4-byte child BL_ADDRs beginning at `+0x2C`.
- B is the fifth child (`07749B20`) in that six-child list. The bucket-selection key and exact range-field semantics remain unresolved.

## Phase 31 checkpoint

- Type-0x08 sector `0x75F47` contains the exact type-0x09 BL_ADDR `07630701` at logical offset `0x2BC8`.
- Type-0x09 sector `0x76307` contains six valid type-0x06 child BL_ADDRs, including changed leaf `07749B20` at logical offset `0x3C`.
- Type-0x07 sector `0x000003` points to primary block `075EB730`; the specific `0x075EB7` block has no direct `07630701` reference. The bridge is indirect through the type-0x08 primary-block family.
- The involved type-0x07/0x08/0x09 records are byte-identical between OUTPUT_A and OUTPUT_B. The type-0x09 hierarchy is a flat six-child bucket/list; exact key semantics remain unresolved.

## Phase 30 checkpoint

- Log candidate `075EB730` is a valid BL_ADDR to type-`0x08` sector `0x075EB7`, span `0x30`.
- Changed leaf BL_ADDR is `07749B20`; type-`0x09` sector `0x76307` contains it at local offset `0x44` with sibling leaf addresses.
- Type-`0x07` sector `0x000003` contains `075EB730` at local offset `0x30`, proving only a partial root→type-08 edge. A complete root→leaf chain is not proven.
- A/B changes remain confined to type-`0x06` sector `0x7749B`; no parent update is observed. `ad5`, `600000`, and `10000` remain unassigned.

## Phase 29 checkpoint

- OUTPUT_A and OUTPUT_B contain 5,433 type-`0x06` records each; 4,624 use compression `0x00`.
- The only A→B changed record is type-`0x06` sector `0x7749B`, span `0x20`, compression `0x00`; the rewrite is in place with no chain insertion/deletion.
- The known B point belongs to a local 28-byte sequence at logical offset `0x0C66`, with the point at `0x0C82`; its parent/count grammar is unresolved.
- Complete sibling-table accounting for 1,935 A points and 1,936 B points is not confirmed; arbitrary fixed-stride runs are insufficient evidence.

## Phase 28 checkpoint

- In the previously identified `OUTPUT_B` table (`0x7749B:0x0C66..0x3F7A`, 467 entries), only the B displayed point matched an exact valid X16/Y16 pair.
- B remains the sole confirmed origin cluster: `originX=0x59763F`, `originY=0x48A93F` at `0x0C82`.
- The other 16 supplied predicted pairs were absent from that scoped table; no additional clusters, merged-list conclusion, origin storage, or parent inheritance are confirmed.

## Phase 27 checkpoint

- An exact-boundary search of the identified `OUTPUT_B` table (`0x7749B:0x0C66..0x3F7A`, 467 entries) matched only the confirmed B X16/Y16 pair `2642/5A3D` at `0x0C82`.
- None of the 16 supplied neighboring predicted X16/Y16 pairs matched a valid entry in that table.
- B independently reproduces `originX=0x59763F` and `originY=0x48A93F`; no additional origin clusters or Ycell transitions are confirmed.
- Cell ownership, META16 correlation, and the correct tables for the unmatched displayed points remain unresolved.

## Phase 26 checkpoint

- One contiguous candidate 28-byte table is identified in type-`0x06` sector `0x7749B`, logical `0x0C66..0x3F7A`: 467 entries, 13,076 bytes.
- META16 varies across the table; `0x001C` occurs 7/467 (1.499%), so it is not established as a universal entry-length field. Alternate META16 values do not imply alternate entry widths because spacing remains 28 bytes.
- The seven controlled points share confirmed origins `originX=0x59763F`, `originY=0x48A93F`; no additional origin pair is proven without neighboring displayed-coordinate identities.
- Candidate cell width is 65,536 Q units, approximately 0.755914 degrees per axis. Origin storage, cell transitions, META16 semantics, and overflow behavior remain unresolved.

## Phase 25 checkpoint

- Parsing payload bytes 0..1 as BE X16 and bytes 2..3 as BE Y16 gives constant controlled origins `originX=0x59763F` and `originY=0x48A93F` across B/L1/L2/XCARRY/T1/T2/YCARRY.
- `META16=0x001C` in the seven controlled entries; neighboring values vary, so its exact semantic role is unresolved.
- Twenty adjacent raw entries were extracted and candidate-decoded. Only the controlled B entry has a verified displayed-coordinate match; neighboring display identities are unavailable.
- The X16/Y16 formula is confirmed for the controlled outputs, not yet database-wide; overflow behavior and origin scope remain unresolved.

## Phase 24 checkpoint

- Sorted POI entries are 28 bytes wide and adjacent at `0x1C` intervals; the verified six-byte payload begins at entry offset `+0x00`.
- B/L1/T1/T2/YCARRY use the rank-2 neighborhood at `0x0C82`; L2/XCARRY use rank 3 at `0x0CBA`.
- Longitude-only controls change payload bytes 0–2; latitude-only controls change bytes 3–5. This is axis-local behavior, not proof of independent absolute coordinates.
- No direct X24/Y24, mixed-radix, interleaved, Morton, or predecessor-delta decoder is confirmed. The table has a longitude-related sort key, but its exact field is unresolved.
- Twenty-neighbor coordinate validation and maximum decode error remain unavailable because neighboring POISoN-displayed coordinates are not recorded.

## Phase 22 checkpoint

- The same six-byte item is confirmed at sector `0x7749B`, raw offset `0x0C82`: B=`26425A3D001C`, XCARRY=`266257890024`, YCARRY=`26425B42001C`.
- The item has the shape `[X3][Y3]`; no flags are confirmed.
- The displayed-coordinate Q values are B=`0x599C81/0x49037C`, XCARRY=`0x599D86/0x49037C`, YCARRY=`0x599C81/0x490481`.
- Neither Phase 21 candidate permutation set yields a constant origin across the three raw items; unique byte order, encoder, decoder, and neighboring validation remain unresolved.

## Phase 23 checkpoint

- The editable type-0x06 table is a 28-byte-entry sorted sequence. The verified inserted item is rank 2 at offset `0x0C82` for B/L1/T1/T2/YCARRY and rank 3 at offset `0x0CBA` for L2/XCARRY.
- Verified inserted items: B=`26425A3D001C`, L1=`264B5A3D001C`, L2=`26995A3D001C`, T1=`26425A46001C`, T2=`26425A94001C`, XCARRY=`27475A3D001C`, YCARRY=`26425B42001C`.
- Phase 22's XCARRY value `266257890024` was a neighboring existing item and is invalidated for identity comparison.
- The item follows sorted-table movement, but no direct X/Y, interleaved, Morton, or neighbor-delta decoder is confirmed. Coarse/local and sorted-key-plus-payload models remain unresolved.

## Phase 22 checkpoint

- The same six-byte item is confirmed at sector `0x7749B`, raw offset `0x0C82`: B=`26425A3D001C`, XCARRY=`266257890024`, YCARRY=`26425B42001C`.
- The item has the shape `[X3][Y3]`; no flags are confirmed.
- The displayed-coordinate Q values are B=`0x599C81/0x49037C`, XCARRY=`0x599D86/0x49037C`, YCARRY=`0x599C81/0x490481`.
- Neither Phase 21 candidate permutation set yields a constant origin across the three raw items; unique byte order, encoder, decoder, and neighboring validation remain unresolved.

## Phase 16 checkpoint

- POISoN no-edit save A rewrites 697 in-place type-0x06 records; other families remain byte-identical.
- A→B changes one in-place type-0x06 record at sector `0x7749B`, span `0x20`.
- C is 1,024 bytes larger and has two additional main-chain records: one type-0x06 and one type-0x08 and one type-0x09 count increment are observed relative to A/B.
- No block relocation or new compression code is confirmed; the two added C records use compression `0x00`.
- The requested POI coordinate pairs were not found as confirmed BE uint32 MULCOORD variants in raw or decompressed DB_0; exact containing blocks remain unresolved.

## Phase 17 checkpoint

- The principal +1-point delta is type `0x06` sector `0x7749B`, span `0x20`, logical payload 16,376 bytes; 4,259 logical payload bytes differ A→B.
- The first observed field change is logical offset `0x03`, `0x3D`→`0x3E`; the rest is a broad sparse/table rewrite, not a proven fixed-size item insertion.
- C shifts the homologous region by one sector; equal-sector A→C comparisons are not valid record identity matching.
- C's appended records at `0x7868B..0x78697` are type `0x06`, one sector each, compression `0x00`; no new type-0x08/0x09 records are confirmed.
- No requested coordinate encoding, item size, scale/origin, or growth trigger is confirmed.

## Phase 18 checkpoint

- A→D changes exactly one DB_0 byte: type `0x06`, sector `0x76CE2`, logical offset `0x0837`, `D8→D9`.
- The edited longitude delta is `0.00001` degree, so the observed stored delta is `+1` and the derived scale is `100000` units per degree.
- A and E are byte-for-byte identical, including DB_0 SHA256; no persisted latitude change is confirmed.
- Exact editable-point item boundaries and the complete coordinate representation remain unresolved.

## Phase 19 checkpoint

- A→D changes only type-0x06 logical offset `0x0837`: `D8→D9`.
- A→F changes only offset `0x0839`: `D9→E1` (+8); A→G changes `0x0838..0x0839`: `B4D9→B52F` (+0x456 = 1110 as BE uint16).
- The F/G latitude deltas do not satisfy a direct 100,000-units/degree integer model; quantization/carry or another compact representation remains unresolved.
- No broad index/checksum regeneration is observed, but exact editable-point item boundaries and complete coordinate formula remain unresolved.

## Phase 20 checkpoint

- The added POI is a confirmed six-byte item in type-0x06 sector `0x7749B`: two adjacent 24-bit BE fields, longitude at `0x0C7B` and latitude at `0x0C7E` when in the B position.
- B item bytes are `26425A3D001C`; L1 changes longitude to `264B5A`; T1/T2 change latitude to `46001C`/`94001C`.
- L2 changes longitude to `26995A` and relocates the item to logical offset `0x0CA9` due to sorted-table placement.
- Coordinate fields are recovered, but the affine grid origin/quantization rule is not confirmed; the observed deltas are not a single 100000-units/degree scale.

## Phase 21 checkpoint

- MULCOORD>>6 exactly explains the observed differentials: Qlon B/L1/L2 = `5872769/5872778/5872856`; Qlat B/T1/T2 = `4785020/4785029/4785107`.
- Constant-origin models exist for longitude permutation `[0,2,1]` with origin `0x33423F`, and latitude permutation `[1,2,0]` with origin `0x48E73F`.
- Alternative constant permutations also exist (`[2,0,1]`, origin `-0x89C1`; `[2,1,0]`, origin `0x2D033F`); uniqueness is unresolved.
- Candidate origins were not found verbatim in the B type-0x06 logical payload; a carry-forcing coordinate experiment is required.

## Phase 15 checkpoint

- Static PE metadata, imports, strings, and auxiliary file snapshots were extracted for POISoN and patch; neither executable was run.
- No compression-0x01 decoder, coordinate routine, database writer strategy, or relocation behavior is confirmed yet.

## NCDR DB Laboratory milestone 1 validation (2026-10-05)

- Added the local Tkinter application under `research/db_lab/`; its DB_0 reader opens the source read-only and stores the source SHA256 in the run manifest.
- A read-only run against the project DB_0 observed size 252,521,472 bytes and indexed 54,010 physical records. Whole-database compression counts were 0x00=25,764, 0x01=11,875, 0x02=16,371.
- Type-0x00 compression counts reproduced the existing reference exactly: 0x00=196, 0x01=5,240, 0x02=3,036. The existing Moscow control parser again returned 185 roads.
- SHA256 observed for this DB_0: `c5f495efcd26a8bc49197c73b116fcbccf127a397e1d2751c1aa88a9ed8589ef`.
- The bounded first-stage search tested 263 transform hypotheses on 24 representative 0x01 blocks. Highest profile-similarity score was 88.4019 for identity; this is not evidence of a decoder and compression 0x01 remains unresolved.
- Run artifacts are in `research/db_lab/runs/NCDR_DB_LAB_20261005_232254/`; the original DB_0 was not copied or modified.


## NCDR RE LAB general workstation milestone 1 (2026-10-06)

- Added a native SwiftUI/AppKit Intel macOS app at `research/db_lab/macos/build/NCDR RE LAB.app`, plus its rebuild script and Python engine bridge. App version: 1.0.0.
- Added read-only artifact cataloging, SQLite provenance and knowledge bases, ISO/CUE detection and ISO-9660 indexing, static PE inspection, strings/constants search, controlled directory comparison, task manifests/templates, dated runs, reports, and ChatGPT packages. Existing DB_0, road, firmware, and compression research was retained.
- Completed `PROJECT_INVENTORY` run at `research/runs/2026-10-06_00-35-58_PROJECT_INVENTORY/`; package validation passed.
- Inventory: 23 artifacts, 1,101 files, 15 DB_0 files across 15 containing folders, 14 controlled sets, 0 disc images, 0 validated firmware containers, and no navboot file. `POISoN/poison.exe` and `tools/POISoN/patch.exe` were found and statically inspected. One `navboot` literal hit in patch.exe is not a module.
- Compute report: CPU backend available, Intel x86_64, 16 logical cores; no GPU backend available. No GPU acceleration was claimed.
- Each `ORIGINAL` vs `OUTPUT_*` detailed diff reached the 10,000-range cap. The run records that cap; full semantic interpretation was not attempted.
- Highest-priority next target: obtain a firmware/update disc or validated firmware container that can establish the navboot payload boundary. No compression brute force, firmware reverse engineering, geometry search, or routing reconstruction was started.
- Follow-up hardware capability check: macOS detects Intel UHD Graphics 630 and AMD Radeon Pro 5500M, both Metal-capable. No Metal compute adapter is wired into this version, so the current backend remains CPU; the native UI distinguishes GPU hardware from an available execution backend.

## NCDR RE LAB foundation and UI audit milestone (2026-10-06)

- Upgraded the native workstation to v1.1.0. Overview cards, artifact status, graphics capability, selected backend, and Research Map evidence now read from the shared project-summary response; cards navigate to their corresponding sections, and Research Map entries expose evidence, confidence, and update time in the inspector.
- Replaced the weak DB_0 prefix classification with complete 512-byte record-chain validation. All 15 inventory DB_0 files validate; The standalone root DB_0, ORIGINAL, and 12 non-C outputs have 54,010 records; OUTPUT_C has 54,012. `.DS_Store` and `CARINET` are retained as non-DB_0 files and fail strong validation.
- Added content-addressed record-parse reuse after source SHA256 and chain checks; the already completed DB_0 framing index is reused for ORIGINAL.
- Completed record-aware diffs for 13 OUTPUT_* sets with no 10,000-row cap: 13,047 changed/added/removed/relocated detail rows and per-record logical interpretation status. Records with zero logical units remain `NOT_COMPARABLE`; no logical extent is inferred from physical bytes. OUTPUT_A and OUTPUT_E group as identical by SHA256.
- PROJECT_STATE controls pass: OUTPUT_A→OUTPUT_B changes one type-0x06 record at sector `0x7749B`; OUTPUT_A→OUTPUT_D changes one type-0x06 record at sector `0x76CE2`.
- Current project summary: 23 artifacts, 1,101 files, 15 validated DB_0 files, 14 controlled sets, 0 disc images, 0 firmware media. POISoN and patch.exe are `FOUND`; firmware and NAVBOOT are `NOT FOUND`.
- Compute report separates Intel UHD Graphics 630 and AMD Radeon Pro 5500M (both Metal 3 capable) from the GPU execution backend (`None implemented`) and selected CPU backend.
- Created immutable runs and verified ZIP manifests: `research/runs/2026-10-06_01-46-36_071916_FOUNDATION_AUDIT_DB_DIFF/` and `research/runs/2026-10-06_02-09-43_226711_UI_FOUNDATION_AUDIT/`. Both packages are READY; the UI audit passes all 15 model-to-database/platform binding checks.
- Automated regression suite: 5 tests pass, covering structural false-positive rejection, complete record diff/grouping, ZIP manifest integrity, and Overview summary versus authoritative SQLite counts.
- This milestone stops before Phase 2. Firmware/NAVBOOT reverse engineering, compression 0x01 decoding, geometry, routing semantics, and DB_0 writing remain unstarted.


## NCDx native corpus import and firmware discovery milestone (2026-10-06)

- Completed `NCDX_NATIVE_CORPUS_INVENTORY` in run `research/runs/2026-10-06_02-47-53_NCDX_NATIVE_CORPUS_INVENTORY/`; application v1.1.0; ChatGPT package READY.
- Imported nine read-only `cd9660` volumes as `OPEL_NCDX_DISC`, separate from legacy DB_0. Persistent SHA256 manifests cover 1,428 files and 101 directories (4,342,723,295 bytes total). Each disc mapping, 2009Q4 prefix, 2010-08-09 date, and software version is confirmed from its `CDROM.TOC`; CD_7190 is EU/MRE + Update.
- Catalogued all observed extensions and began matched-path cross-disc comparisons. No road geometry or routing semantics assigned by extension.
- CD_7190 has 45 direct firmware/update-path artifacts (LK841/IDIS/SW), plus eight separately classified VOICE data files. Fifty-one selected evidence files from CD_7190 were copied and hash-verified; no mounted source was modified.
- Static inventory: 16 valid WinCE PE32 Hitachi SH4 files (2 EXE, 14 DLL). NAVIMAIN imports COREDLL.dll, ComMgr.dll, mfcce212.dll, ole32.dll and MemMgr.dll; its strings show it as a navigation process but do not prove a map reader or launch target.
- NK.BIN (11,021,915 bytes) has `FATFS` and `ECEC` strings, but no bounded embedded PE or validated filesystem/image extraction.
- NCDx vs DB_0 classification: WEAK SIMILARITY only, from one sampled ASCII `5555555` token in `CD_7187/DB/SPZ.MP0`; no shared coordinate representation or structure confirmed. No compression brute-force started.
- Updated native Discs/Firmware views and catalog summary counts. Highest-priority next task is static trace of NAVIMAIN/MMIDIS file-open/read behavior before choosing database suffix semantics.

## NCDx map reader discovery milestone (2026-10-06)

- Added the `NCDX_MAP_READER_DISCOVERY` task and native Map Reader Discovery, Executables, and Cross References views to NCDR RE LAB v1.2.0.
- The run analyzes all 16 verified CD_7190 SH4 PE copies, named and ordinal imports with IAT locations, ASCII/UTF-16 token hits across copied firmware artifacts, import dependencies, NAVIMAIN/MMIDIS metadata, NK.BIN signature neighborhoods, and nine-disc database header edges.
- Conclusions remain evidence-bounded: no SH4 disassembler or matching COREDLL ordinal export map was available, so no open/read/parser call path is claimed; NAVIMAIN remains a navigation-runtime hypothesis and NK.BIN structure remains unvalidated.
- The `.RD` suffix is selected only as the first neutral format-correlation target because its sample has a repeated 12-byte `SIEMENS`-prefixed header on all nine discs; no semantic meaning is assigned to the suffix.
- No mounted firmware/disc or native database was modified, no NK.BIN module was carved, and no DB_0 compression work was started.
- Final run: `research/runs/2026-10-06_12-50-35_NCDX_MAP_READER_DISCOVERY/`; package READY at `research/runs/2026-10-06_12-50-35_NCDX_MAP_READER_DISCOVERY/CHATGPT_PACKAGE.zip`. All 53 manifest-listed firmware/update artifacts were searched (43 verified evidence copies and 10 size/SHA-verified read-only mounted sources); 16 SH4 PE files were parsed.
- NAVIMAIN ranks first with HYPOTHESIS confidence based on navigation-process strings and its PDB path only. Its raw `CE` token is part of a Windows CE compiler path. No map extension token appears in a PE non-resource section. TMCUPDATE.DLL has four named MFC `CFile`/`CArchive` file routines, consistent with its update role; NAVIMAIN and MMIDIS have no named file-I/O imports. MMIDIS and NK.BIN remain INCONCLUSIVE.
- The native app rebuild succeeded as Intel macOS v1.2.0. Its Executables and Cross References pages bind to corpus records; Map Reader Discovery reads the ranked candidate and evidence output.
- Registration in `analysis.sqlite` was deferred because a concurrently active DB_0 inventory process held that catalog open. The completed run and package are present on disk and the discovery view reads them directly.
