# Phase 12 findings

- Road references: 483 objects; 413 unique target-block pointers; 413 with known F.
- Exact extents: 413; known next-greater pointer boundaries are used without assuming a terminal element width.
- F remains count-like, but fixed-width records are not confirmed. Width fits are concentrated in F=1 and do not generalize robustly to F>1.
- Raw regions show multiple structural fingerprints; no uniform variable-length grammar or pointer-table grammar achieved cross-road validation.
- No geometry GeoJSON was emitted because no decoder met the required structural and geographic validation threshold.
- The 1 iy list is preserved as an unresolved 31-item road-owned region; its exact terminal boundary is reported in the dedicated analysis.
