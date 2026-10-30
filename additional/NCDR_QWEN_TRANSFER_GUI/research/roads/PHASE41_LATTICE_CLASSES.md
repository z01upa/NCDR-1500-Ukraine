# Phase 41 — complete 32-byte lattice classes

All 10,757 known lattice positions were materialized with raw32: 2,458 referenced plus 8,299 intermediate positions. Every position has either `+0x10 BE16 == 0` (Z) or nonzero (NZ); no all-zero/all-FF padding or OTHER class was observed.

Global counts: Z=10,021, NZ=736. Referenced counts are Z=2,299 and NZ=159; unreferenced counts are Z=7,722 and NZ=577. Thus 100% of the previously intermediate positions match one of the referenced primary grammars under the Z/NZ split, replacing the earlier 58.8% zero-mask compatibility measure.

The transition matrix is Z→Z=9,800, NZ→NZ=522, NZ→Z=213, Z→NZ=199. The lattice therefore consists mostly of long Z runs, with NZ appearing in short runs and boundaries; there are 435 class runs. NZ is not a universal header or extension: it occurs both referenced and unreferenced and appears in NZ→NZ runs.

NZ `+0x10` values remain heterogeneous; no exact relation to slot index, neighboring run length, F, A/B/C/D, or E flags is established. The complete raw32 field summaries are in `phase41_z_nz_fields.csv`; no additional semantic field is confirmed.

Table boundaries remain unresolved because the full known lattice is Z/NZ-compatible throughout the scanned ranges, with no repeated padding transition establishing a physical end.
