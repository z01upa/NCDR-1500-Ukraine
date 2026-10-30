# NEXT_STEP — one practical task
Recover the CE00FF packet codec and addressed-memory image from the existing NK.BIN, then identify the navigation module that consumes Section4 headers.

Bounded entry point: file0x400 CE00FF header, first packet0x410; exact bytes/hashes in evidence/pass_a_binary.json. Work on isolated outputs. First establish packet extents, decompressed lengths/checksums and nonoverlapping memory mapping; only then extract modules and trace the node-reader consumer. Do not scan constants10/14 and call matches functions.

Required result: one actual procedure with executable address and instruction-derived pseudocode explaining whether high-degree+2 and degree3+8 are read as routing data, masks, tagged values or ignored storage. Test its predicted behavior on the saved degree3/5/6/7 fixtures. This addresses the strongest remaining insertion blocker; no new Writer or topology mutation until the relevant routing dependencies are justified.
