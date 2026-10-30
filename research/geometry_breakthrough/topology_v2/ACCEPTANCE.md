# NCDR MP0 topology research v2 — acceptance

Date: 2026-10-29  
Result: **STRUCTURAL VALIDATION PASS; topology insertion remains blocked.**  
New edge emitted: **No.** No original MP0/CD, SQLite, Writer v1, Manager, GUI, Worker, Director, or Supervisor file was modified.

## Input integrity

Read-only source: `${NCDR_SOURCE_ROOT}\SW\DB\EUZ.MP0`  
SHA-256 before and after: `73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e`

## Confirmed rules

### Section 4 — node records

- **PASS:** All 2,956 blocks have a 10-byte Section 4 stride, and Section 4 node count equals the primary coordinate count. The validator counted 956,071 records.
- **Supported for the low-degree cohort:** The low nibble of byte `+0` behaves as an adjacency count for records whose value is at most 4. The first `degree` little-endian u16 values beginning at `+2` match the local primary-endpoint edge list exactly for **952,280** node records. They also include every corresponding primary endpoint in **2,141,367** checked edge-endpoint cases.
- **Unresolved exceptions:** **511** degree-≤4 records do not match their local endpoint multiset. All 511 have duplicate primary coordinates in their block; this makes coordinate equality insufficient to merge their graph identity. Examples with raw records and offsets are in `topology_validation.json`.
- When the low nibble is 4, bytes `+8/+9` are the fourth u16 reference in the exact local adjacency examples. This does not prove how the same bytes may be used when degree is below 4.
- Across 281,608 records with low nibble 3, the next u16 at `+8` is nonzero in **280,356**; it is numerically within the local edge-ID range in **234,204**, and equals a locally incident edge ID in **2,650**. Therefore it cannot be assumed to be a zero/padding slot when degree is 3.
- **Not decoded:** byte `+1`, the high nibble of byte `+0`, records with low-nibble values above 4, and any continuation/overflow linkage. There are **3,280** records with low-nibble values above 4; their relationship to actual edge incidence is reported separately in the JSON.
- Those 3,280 records split into local primary incidence counts 0: **1,325**, 5: **1,712**, 6: **222**, 7: **21**. The zero-incidence group is direct evidence that the low nibble cannot be treated as local Section 5 degree universally.

### Section 5 — edge records

- **PASS:** Every block has 14-byte Section 5 records. All edge endpoints are within the coordinate table selected by their flags: **0 out-of-range** across **1,090,323** edges.
- Confirmed byte layout from real records: `flags u16 @+0`, `attributes u16 @+2`, `unresolved u16 @+4`, endpoint indexes u16 at `+6/+8`, and length-like u32 at `+10`.
- `0x1000` and `0x2000` select the coordinate table for endpoints A and B; `0x8000` signals a shape span. These observations do not establish one-way/access semantics.
- Across **14,619** exact cross-block geometry-and-length groups, `attributes` matched in all 14,619; `unresolved` and non-coordinate flag bits matched in 14,618 each. The single differences are preserved as evidence, not assigned meaning. This comparison does not determine directionality.
- Direction/access semantics of `attributes`, `unresolved`, and remaining flag bits remain unconfirmed.

### Related structures and cross-block links

- **PASS:** 29,240 secondary coordinates match a primary coordinate in another block.
- Section 7 has 7-byte records in all 2,956 blocks. Populated Section 8 records have an 11-byte stride; populated Section 9 records have a 13-byte stride in 26 blocks. Their association with edges, routing, or adjacency has not been proven. Counts do not generally equal the Section 5 edge count.

## Whole-map checks

- **PASS:** 2,956/2,956 compressed streams inflate to their indexed sizes and container extents are contiguous.
- **PASS:** Current decode → encode is byte-identical for all 2,956 decompressed blocks; the complete Section 4/5 byte ranges are identical in all 2,956.
- **PASS:** Independent raw-file Reader `independent_verify.py` matched flags, stored lengths, and all points for **1,090,323/1,090,323** edges. It imports neither Writer v1 nor the current decoder.
- **PASS:** A second standalone parser `independent_topology_reader.py`, with no decoder, encoder, validator, or Writer imports, independently recovered the same 952,280 exact adjacency records, 511 duplicate-coordinate exceptions, 2,141,367/0 endpoint-reference membership checks, and 29,240/0 cross-block matches. Result: `independent_topology_result.json`.
- New tests: **10 passed, 0 failed.** Command: `python -X utf8 -B -m unittest research.geometry_breakthrough.topology_v2.test_topology -v`.

Machine-readable results: `topology_validation.json`; testable candidate/refusal record: `edge_insertion_gate.json`.

## Controlled insertion attempt

Block 886, nodes 412 and 414 are distinct primary coordinates about 9.79 m apart, not already joined by a local primary edge. Both currently have degree 3, and their three active references match their local incident edges:

- node 412 record `6308c5002702b0000602`, references `[197, 551, 176]`; u16 at `+8` is **518**.
- node 414 record `4308c300c40029020f01`, references `[195, 196, 553]`; u16 at `+8` is **271**.

The prospective edge ID if appended would be 706 in a block with 706 existing edges. Raising either degree to 4 would cause the current nonzero `+8/+9` word to be read as the fourth reference; replacing it might be correct, but no evidence establishes that those bytes are inactive for every consumer. More critically, safe values for Section 5 attributes, unresolved, and non-selector flags are unknown, and Sections 7–9 have unverified edge dependencies. The gate therefore refused **before mutation**. It wrote no candidate MP0 and did not invent defaults.

## Final decision

There is enough evidence for a structural reader and a partial validator, but not enough to safely create a new edge. No file in this result is presented as routable or device-compatible. Continue with firmware tracing of node records at the degree-5 example in block 1 and the Sections 7–9 references, then determine Section 5 routing/access semantics before attempting a copied-file mutation.
