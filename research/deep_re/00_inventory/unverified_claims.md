# Unverified or unavailable (do not rely on)

- Commit fa70c06834cbcf7206298b0f944f635149404f0b (V4.1 toolkit): NOT present in the clone (HEAD is 3e40996, 5 commits, shallow fetch to 200 found nothing). Status: UNAVAILABLE. Nothing was assumed about its contents.
- Stage 079 / 080 / 081B / 084 reports and addresses 0x01000E2C, 0x01000E40, 0x01000E50: no matching files in this clone. Not the same address space as this DLL's runtime VAs (0x02FD1000..0x03162000) by value; the link-time view of this DLL is 0x00FD1000..0x01162000, so they may or may not belong to it. Status: UNVERIFIED.
- S5 flag bit 0x8000 meaning, S4 high nibble, S4 inactive slot +8 at degree 3: still UNKNOWN. Loaders confirm raw copy only (see 02_s4_semantics/conclusions.md).
- S5 +10 unit (metres?) : UNKNOWN. Loader only confirms it is a u32.
- EUZ.MP0 / EUZ.RT / EUZ.RL: not inspected. EUZ.z01 (23068672 B, PK\x07\x08 split marker) + EUZ.zip (7145312 B, last segment) need to be joined first (e.g. `zip -FF` / 7z) before any reading. Status: BLOCKED (not attempted).
- Git remote persistence: session has read-only access. Any commit is LOCAL_ONLY_VERIFIED.
- Hardware compatibility with a physical NCDR 1500: BLOCKED, never claimed.
