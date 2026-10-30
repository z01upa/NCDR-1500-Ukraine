# Phase 40 — type-0x00 32-byte slot classes

The persisted referenced-slot population splits deterministically by BE16 at `+0x10`: class Z (`+0x10==0`) has 2,299/2,458 slots (93.53%); class NZ has 159/2,458 (6.47%). The available intermediate-slot file records 8,299 positions and 4,880 compatible versus 3,419 structurally different, but does not persist raw32, so a corresponding intermediate class split cannot be recomputed without DB re-reading.

NZ values are heterogeneous: common values include `0x0300` (28), `0x0100` (20), `0x0200` (18), `0x1000` (16), and `0x009E` (11). This does not support one meaning such as a universal pointer, count, or flag. No exact caller-field equality or internal-pointer relation is established from the persisted rows.

F invariance remains 97.1% by target/slot; class-specific exception concentration and geographic spread are unavailable because the saved unique-slot file does not retain all caller rows and the intermediate file lacks raw32. No reproducible higher-level pair grammar or geometry role is proven.

Strongest confirmed discovery: referenced slots have a real, reproducible Z/NZ structural split, while the lattice as a whole is mixed. Next step is to persist raw32 for all intermediate positions and rerun class/transition analysis.
