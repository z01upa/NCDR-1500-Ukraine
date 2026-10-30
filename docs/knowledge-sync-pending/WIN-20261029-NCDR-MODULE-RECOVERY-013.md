# WIN-20261029-NCDR-MODULE-RECOVERY-013
Status: CONFIRMED OFFLINE; synchronization QUEUED.
Project: approved civilian NCDR navigation research.
Problem: decoded CE image had no validated target module extraction.
Result: both target executable sections recovered; 10 total sections checked against original decoded image and packet bytes. CE2 e32 directories start +0x1C; compressed sections use strict indexed CE blocks. Preserve link/runtime/storage addresses separately. Do not fill holes/alignment as code.
Evidence: research/geometry_breakthrough/module_recovery_v13/verification.json, routing/reader_verification.json, modules/*/module.json, modules/*/sh4_analysis.json.
Changed files: only new module_recovery_v13 scripts/docs/section artifacts and the new ZIP; no product code or originals.
Tests: 4584 complete PDATA roots; 433567 reachable observations; zero decode failures/out-of-text direct branches. Hole and truncated-section guards reject invalid input. Actual pcode replay matches original MP0 block0: 128 nodes,151 edges; 18 opaque attribute mutations preserved; consumer prefix forwards +4/+5 to +0x10/+0x11. COREDLL memcpy resolved from original export metadata.
Limits: offline analysis only; no Windows/hardware execution; final incomplete PDATA record excluded in each module; no complete relinkable PE; route semantics NOT VERIFIED. No Writer rule inferred from names, stride or successful disassembly.
Prevention/reuse: retain 14-byte disk vs16-byte RAM edge distinction; RAM padding+10/+11 is untouched. Track actual pointers into downstream structures before assigning bit semantics.
Provenance: pinned original NK and MP0 hashes in verification artifacts; independent script code, upstream format references attributed in README. No upstream parser bundled.
Review: no secrets, credentials, personal communications, or external unapproved project content in this packet. Evidence paths resolve locally. Duplicate check limited to local queue; shared merged checkout unavailable. No external publication or automatic merge.
Sync: shared AI-Engineering-Knowledge checkout unavailable; packet queued for the local Knowledge Sync tool. No Git commands executed.
