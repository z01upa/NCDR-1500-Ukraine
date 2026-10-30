# EDGE DEPENDENCIES — NCDR-MAC-019, 2026-10-30
Scope: required changes for new edge706 in original EUZ.MP0 block886; no Writer/map edits.
Budget used: 3 targeted searches of existing artifacts + 1 verification test; analysis stopped.
Addresses are link VAs; saved SH4 evidence uses runtime VA = link VA + 0x02000000.

| Structure | Verdict for edge706 | Verified evidence / limit |
|---|---|---|
|Section6|UNKNOWN|4 variable-length records in block886. Loader 0x0104D994, dispatch 0x0104DDAE; downstream ownership not established.|
|Section7|UNKNOWN|Consumer 0x01000E50 reads context+0x44/count+0x48; compares record first u16 to input ID low12 bits (0x01000EBA..0x01000F04); RAM stride8 at 0x01000F44. Whether edge706 needs a record is unproved.|
|Section8|UNKNOWN|Same consumer reads context+0x4C/count+0x50 (0x01000F46..54); compares first u16 to the same key at 0x01000F5C..64. Additional filtering exists; no safe default established.|
|Section9|UNKNOWN|Original block has zero records with 706 edges; loader count gate 0x0104DE3A..76. Optional for existing block contents, not proved optional for new edge706.|
|EUZ.RT|UNKNOWN|Existing routing_file_audit.json validates container only; no proven Section5 relation.|
|EUZ.RL|UNKNOWN|Existing audit validates container only; neither mandatory update nor independence is established.|

## Concrete new finding
Section7/8 are searched by a masked 12-bit input key, not indexed one-for-one by edge ordinal in this consumer.
Count-controlled loops permit zero matches locally; this does not prove caller acceptance or global routing correctness.
Existing index-domain evidence supports edge-key interpretation; caller-to-edge706 provenance is still missing.

## One verification test (PASS)
Checked only original block886 plus exact saved instructions of function 0x01000E50; no topology/mask/NK rerun.
Decoded block SHA256: c4fd95701be3301b999d7e8886d08a6d2e8a3461e9f6caa973a5128959d983a6.
All tested first-u16 keys sorted and <706; section extents exactly count × 7/11/13 bytes.
|Section|Records|Distinct keys|Existing edge IDs without key|First missing IDs|
|---|---:|---:|---:|---|
|7|835|705|1|593|
|8|108|77|629|0,1,2,3,4,5,6,7|
|9|0|0|706|0,1,2,3,4,5,6,7|
Reproduce data check: use existing dependency_handoff/check_block886.py to locate section spans; read LE16 at sectionStart + i×stride, compare set to range(706).
Instruction check: read saved reachable.jsonl.gz root 0x03000E50; verify table/count loads, u16 comparisons and literal 0xFFF at instruction 0x03000EBA.

## Minimum proven requirements, not sufficient authorization to serialize
Append Section5 record706: count706→707, disk span +14 bytes; preserve old edge IDs/records/geometry.
Preserve node identities; any new endpoint needs a coordinate and Section4 head with coherent adjacency. v17 endpoint details are not available here.
Recompute affected section offsets, decoded/compressed sizes, and moved physical block pointers; shape table/count only if actual shape records are added.
No justified new Section6–9 records or RT/RL updates can be specified. Do not fill unknown fields with zeros or infer independence from unchanged bytes.
No valid minimum attribute/auxiliary-record set is proved; a test MP0 may only be an explicitly unvalidated experiment, not a device-ready or dependency-validated map.

## One next check
Trace the direct callers of 0x01000E50 for the v17 edge706 request: establish the ID argument and whether a zero-match Section7/8 result is accepted or triggers failure/fallback. This resolves the largest newly narrowed uncertainty.

Evidence: module_recovery_v13/modules/NavigationRem.dll/reachable.jsonl.gz; independent_validator_v18/evidence/sh4_selected.json; NCDR_ASTRA_TRANSFER/project/research/geometry_breakthrough/writer_v2/ACCEPTANCE.md and evidence/routing_file_audit.json.
