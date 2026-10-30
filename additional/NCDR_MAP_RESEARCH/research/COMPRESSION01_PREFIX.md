# compression=0x01 prefix analysis

- Analyzed referenced type-0x00 blocks: 79 total; compression=0x01: 79; compression=0x00: 0.
- compression=0x01: sharp entropy offsets (16-byte bins): 16: 54, 64: 1, 112: 8, 128: 16
- compression=0x01: recurring LIST/PTR candidate offsets: 0 (79), 4 (79), 8 (79), 12 (79), 16 (79), 20 (79), 24 (79), 28 (79), 36 (79), 40 (79), 56 (79), 100 (79)
- compression=0x00: sharp entropy offsets (16-byte bins): 
- compression=0x00: recurring LIST/PTR candidate offsets: 
- Candidate compressed-body offsets: no boundary is confirmed by this structural/entropy pass; offsets are recorded per block in CSV.
- Cross-block byte-prefix agreement: 6 stored bytes are common to all 79 blocks (`00 74 00 03 00 94`); 8 bytes are common to 61/79. No common boundary was established within the first 256 stored bytes.
- Weak entropy-change clusters: offset 0x10 (54/79), 0x80 (16/79), and 0x70 (8/79); these are not confirmed compressed-body boundaries.
- Road-reference comparison: no referenced compression=0x00 type-0x00 blocks were present in `type00_targets.csv`, so a direct uncompressed control comparison is unavailable.
- No codec probing performed.
