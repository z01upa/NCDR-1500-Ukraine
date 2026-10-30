# DB_0 research state for local continuation

Only project facts needed for the next local analysis are included here.

## Source and framing

- `DB_0` is a 252,521,472-byte image, framed as 512-byte physical sectors.
- At validated record starts, bytes `0..2` are the sector number (uint24 BE),
  byte `3` is physical span in sectors, and next sector is `sector + span`.
- The validated chain starts at sector `0x000002` and contains 54,010 records.
- BL_HEAD bytes `+4..+7` are alignment, type, compression, and logical-size
  units. Logical extent is `byte7 * 512`; physical span is independent.
- For compression `0x02`, zlib starts at local `+8` and every validated payload
  satisfies `decompressed_length + 8 == logical_extent`.
- Compression `0x01` remains undecoded. The database has 11,875 such records,
  including 5,240 type-`0x00` records. Tested standard codecs did not decode
  the 100 sampled compression-`0x01` records.
- The known blocker record is sector `0x11576`: BL_HEAD bytes
  `0115760d00000117`, physical size 6,656 bytes, advertised logical size
  11,776 bytes. Physical payload begins
  `007400030094000500c80012017c0007019c00bc193c00991e0400051e54017f`.
  No trusted decoded logical-buffer oracle is included for this record.

## Confirmed format pieces

- Local PTRs are uint16 BE offsets into the logical block.
- LIST is uint16 BE pointer followed by uint16 BE count.
- A four-byte BL_ADDR stores uint24 BE target sector then one-byte physical
  span. The target header must match sector/span; target type is header byte 5.
- MULCOORD is two uint32 BE values: `lon = hlon / 5555555 - 30`,
  `lat = hlat / 5555555`.
- The confirmed Moscow chain is type `0x0C` sector `0x0899` → FAR_LIST target
  type `0x0F` sector `0x1B19` → CH_IDX target type `0x0E` sector `0x31A0`.
- The selected type-`0x0E` road list is logical offset `0x0F20`, count 185.
  BRIF entries are 8 bytes: name PTR, place byte, language byte, region PTR,
  extended-info PTR.
- Moscow road MORE_INFO entries are 6 bytes: three uint16 BE fields. Field 0
  points to the 24-byte object array; high byte of field 1 counts objects;
  low byte is a one-byte flag; field 2 is zero for the 185 roads.
- The 24-byte object has MULCOORD at `+0x00`, A/B/C/D uint16 BE at `+0x08`,
  type-`0x00` BL_ADDR at `+0x10`, E uint16 BE at `+0x14`, F uint16 BE at `+0x16`.
- E's strongest tested interpretation is `pointer = E & 0x3FFF`, with upper
  bits as unresolved flags. F behaves as a count. A/B/C/D semantics, element
  width, and detailed road geometry are not confirmed.

## Current authoritative road results

- Deterministic CH_IDX/BRIF/MORE_INFO parsing recovers 33,381 roads and
  95,119 owned object occurrences in the 52-sector confirmed source corpus.
- The corrected authoritative corpus contains 20,156 readable objects with
  in-bounds selected 32-byte windows, from 30 type-`0x00` compression-`0x02`
  targets. Compression `0x01` targets account for 74,963 road-object
  occurrences across 324 target blocks in that corpus.
- Exact raw MULCOORD grouping yields 354 physical nodes and 24,419 ordered
  transitions. Run-level analysis identifies paired, directional endpoint
  descriptors, but no geometry decoder is confirmed.
- Raw32 correlation work reached a documented stop condition. Do not repeat
  the same W-field correlation search as if it were new evidence. The next
  target is a separate geometry structure referenced by road/object or
  selected-descriptor data.
- The compression-`0x01` static POISoN loader paths are localized, but static
  evidence does not establish the active path or token grammar. The exact
  blocker is a trusted logical-buffer oracle for one known record, such as
  sector `0x11576`; do not execute POISoN or patch to obtain it.

## Immediate objective

Continue with read-only, falsifiable tests over the included DB_0 and the
authoritative corpus. Prioritize distinguishing compression-`0x01` framing
and locating any structurally owned geometry data. Keep hypotheses, candidate
decoders, and confirmed formats separate. If the next step requires the
missing logical-buffer oracle, record that dependency and finish without
inventing a decoder.

## Evidence files shipped in this package

- `research/FORMAT.md`, `research/FINDINGS.md`
- `research/compression/COMP01_DECODER_RE.md` and compact compression tables
- `research/roads/TYPE0_BLOCK_STRUCTURE.md`
- `research/roads/RAW32_FINAL_ATTRIBUTE_MODEL.md`
- `research/roads/RUN_ARC_GRAMMAR.md`
- `research/roads/HALFEDGE_N_TEST.md`
- `research/roads/authoritative_summary.json` and authoritative CSV corpus
- `research/known_format/KNOWN_FORMAT_VALIDATION.md`
