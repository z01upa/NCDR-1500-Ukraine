# Next task for Astra on Mac
Start from decoded/address_map.json and modules.csv; do not rerun topology_v6 or rediscover packet compression.

1. Open the ROMHDR/TOC candidate and validate the e32_rom/o32_rom structures for NavigationRem.dll and nmicore_ce.dll using only present address regions. Confirm section counts, mapped bounds, flags and per-section physical/virtual sizes. The zero CPU field requires independent architecture evidence.
2. Extract actual section bytes through this address map. If individual ROM sections are additionally compressed, identify and validate that layer separately. Preserve actual addresses and distinguish missing bytes/BSS from stored zeros.
3. Reconstruct analysis executables only after headers/sections are coherent; keep raw mapped section bytes beside the reconstruction. Disassemble SH4 code, verify aligned entry points, branch targets, literal pools and calls. Names alone are not code evidence.
4. Then locate EUZ.MP0 references and actual readers of Section 4/5; use existing topology_v6 node/edge format as a control, without rerunning topology statistics. Do not infer direction/routing semantics from strings alone.

No further analysis was started because the user requested stopping after the decoding/address-map stage. Full packet decoding is complete, so the current blocker is validation/extraction of executable ROM modules, not NK packet compression.
