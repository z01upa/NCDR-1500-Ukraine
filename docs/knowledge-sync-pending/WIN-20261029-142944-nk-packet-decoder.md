# WIN-20261029-142944 — Complete LK841 NK packet decoding

- Status: confirmed on the pinned LK841 NK.BIN; module-code extraction unverified.
- Source SHA-256: d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847.
- Result: 1,065/1,065 packets; 17,845,716 output bytes; all header sums, decoded lengths and additive checksums match; contiguous encoded stream and terminal header at EOF; source hash unchanged.
- New files: research/geometry_breakthrough/astra_final_breakthrough/decode_nk.py, analyze_image.py, decoded/, verification.json, FORMAT_RULES.md, CHECKPOINT.md, NEXT_STEP.md.
- Verification: full local Python execution; independent saved-output audit; ZIP CRC verification. Windows execution not performed; decoder uses Python standard library only.
- Address map: no overlaps, 28,752 uncovered bytes. ROMHDR/TOC candidate 0x8D2F66CC has 154 readable module names, including both target DLLs; CPU field zero, executable extraction and SH4 validation not performed.
- Provenance: transferred v10 left CE fields unresolved. Exact packet semantics were established by the full input checksum/size/boundary validation in this run; prior topology work was not repeated.
- Reuse: preserve literal/backreference rules in FORMAT_RULES.md, restart via --resume, never treat uncovered image gaps as recovered zero bytes, validate e32/o32 structures before claiming module code.
- Stopped at user request after the address-map stage. No original firmware, MP0, SQLite or existing research was modified.
- Reviewed: no credentials, session data or private keys; evidence comes only from this approved civilian NCDR project. Shared knowledge checkout unavailable; queued locally, no Git publication or merge.
