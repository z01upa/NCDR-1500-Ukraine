# compression=0x01

- Records with byte6=0x01: **11875**
- Block types: 0x00 (5240), 0x14 (156), 0x15 (1218), 0x16 (4922), 0x1C (264), 0x1D (60), 0x1E (15)
- Valid codec successes: **0/11875** (0.00%)
- Successful codecs: none
- Validation: decoded length + 8 equals byte7 × 512; stream offsets tested: 8..32 inclusive.
- No requested codec succeeded; CSV retains tested-offset header/signature evidence.
