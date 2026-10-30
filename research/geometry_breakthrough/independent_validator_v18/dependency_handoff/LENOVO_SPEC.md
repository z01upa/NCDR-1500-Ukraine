# MAC-018 priority clarification — bounded handoff, 2026-10-30

No new SH4 consumer search was started: the remaining task-specific share of the original 20% budget cannot be established. Account-wide usage was 8% at MAC-018 start, 24% before its final checks, and 62% at this clarification; shared usage cannot be attributed to Mac. This is a handoff of existing code evidence plus one original block-header check, not completion of the newly requested dependency investigation.

## Independently checked block 886
File offset 28,578,738; compressed 17,471 bytes; decoded 30,061 bytes. SHA-256 of decoded block: c4fd95701be3301b999d7e8886d08a6d2e8a3461e9f6caa973a5128959d983a6.
Section4: 664 physical records at +3270. Section5: 706 records at +9910. New appended edge ID 706 is consistent with the original count.

| Section | Count | Bytes | Existing machine-code evidence (link VA) |
|---|---:|---:|---|
|6|4|114|Dispatcher 0x0104DDAE calls 0x0104D994; variable stored records, 58-byte RAM slots|
|7|835|5845|Dispatcher 0x0104DDE6 calls 0x0104DA1C; 7 stored / 8 RAM bytes|
|8|108|1188|Dispatcher 0x0104DE24 calls 0x0104DA98; 11 stored / 12 RAM bytes|
|9|0|0|Dispatcher 0x0104DE64 calls 0x0104DB44; 13 stored / 16 RAM bytes|

These counts disprove a simple one-record-per-edge requirement for these tables in this block. Section9 is absent while 706 edges exist, so its records are not universally required for every edge. This does NOT prove that a particular new edge can omit Section9, nor that Sections6–8 have no indirect/shared references. Global tables or conditional records remain possible.

The dispatcher's tested count gates skip zero-count tables. Parsing is established; downstream consumers and field meanings are not. Code snippets: ../evidence/sh4_selected.json. Original section contents were not interpreted as indexes merely because values fit edge IDs.

## What Lenovo can update with current evidence
- Retain all existing physical node IDs, edge IDs, geometry and unknown fields. The reported in-memory v17 result is user-provided, not independently rerun here; its artifacts are absent on Mac.
- If edge706 is appended, Section5 count becomes707 and its stored extent grows14 bytes. RAM stride16 must never be written into MP0.
- Section4 physical count, Section0 primary-coordinate count, node adjacency and endpoint IDs must remain coherent. A new endpoint requires its own coordinate and physical head. Whether one or two endpoints are new must come from the v17 artifact, not an assumption.
- Recompute each affected section offset from actual serialized spans. Recompute tail shape offsets/count/length only if shapes are added; preserve old edge-to-shape ordering. Recompute decoded size, zlib stream size and physical stream pointers affected by repacking. Existing opaque index bytes are not proven free to change.
- Sections6–9: do NOT synthesize zero-filled records, increment counts automatically, or claim unchanged bytes are sufficient. No minimal valid record set for edge706 is yet established.
- RT/RL: update necessity is UNKNOWN. Neither presence of the files nor absence of literal filenames in a DLL proves independence. No write specification for RT/RL is justified.
- New attributes/masks and degree1 node opaque fields must come from established v17 evidence; no values are invented here.

## Exact stop gate and next investigation
The minimum correct on-disk addition remains UNKNOWN; do not publish an MP0 from this note. Needed artifacts: v17 block/edge/endpoint diff and the current mask proof. The next bounded machine-code investigation is to trace loads through the dispatched table pointers (context +0x3C, +0x44, +0x4C, +0x54 for Sections6–9), prove their callers/record identities, then test whether edge706's type/endpoints select them. Numeric offset matches alone are not proof. Follow any resulting external-file lookup into RT/RL before declaring those files unchanged.

Reproduce only the header evidence:
python check_block886.py PATH/TO/ORIGINAL/EUZ.MP0 --out block886.json

Writer, original MP0 and companion files were not modified. The previous validator ZIP remains unchanged; this addendum is separate.
