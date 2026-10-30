# CHECKPOINT — 2026-10-29
Stopped after the requested decoding/address-map/ROMHDR stage at the user’s instruction.

FULL PACKET DECODE VERIFIED: 1065 / 1065; 17,845,716 decoded bytes; 0 packet errors; exact EOF terminator; original hash unchanged.
Address map: 0x8C1F0000..0x8D2FBE24, 28,752 explicit holes, no overlaps.
ROMHDR/TOC candidate: 0x8D2F66CC, 154 modules, all names mapped; CPU field zero.

- NavigationRem.dll: TOC index 105; e32=0x8C8395C8, o32=0x8C83962C, load=0x8CF3D000, recorded file size=1219659.
- nmicore_ce.dll: TOC index 108; e32=0x8C839844, o32=0x8C8398A8, load=0x8D0EC000, recorded file size=179784.

No DLL executable/code section was extracted; no SH4 disassembly, routing reader, Section 4/5 semantics or direction flags are claimed. No MP0, SQLite, Writer, Manager, GUI or earlier research was changed.

Artifacts: decode_nk.py; analyze_image.py; decoded/decode_report.json; decoded/packets.csv; decoded/packets/*.bin; decoded/addressed_image.bin; decoded/address_map.json; address_regions.csv; modules.csv; verification.json.

Original input remains at: ${NCDR_SOURCE_ROOT}/input_reference/originals/NCDR/SW/LK841/HU_HARDWARE_LOC_0000000001/HU_KERNEL_LOC_0101000870/NK.BIN
The transfer ZIP contains only this new result directory, excluding this finalize helper and the original image.
