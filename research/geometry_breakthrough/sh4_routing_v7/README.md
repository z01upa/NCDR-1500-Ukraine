# SH4 routing-code check (v7)

This is a bounded, read-only examination of the existing `NAVIMAIN.EXE`. It
reuses the project's PE/import readers and the immutable source hash recorded
in `xref_v4`; it does not edit Astra evidence, MP0, SQLite, or firmware.

## Run

From the project root:

```powershell
python research/geometry_breakthrough/sh4_routing_v7/sh4_scan.py
python -m unittest discover -s research/geometry_breakthrough/sh4_routing_v7/tests -v
```

The local `vendor` folder contains `pypcode 4.0.1`, using the Ghidra SLEIGH
language `SuperH4:LE:32:default`. The scan checks known SH4 opcodes before
looking at the image. Results are written under `evidence/`.

## Scope

The scan follows direct control flow from the 45 increasing `.pdata` first-word
addresses, bounded by the next such address. It records unresolved indirect
transfers and does not follow indirect jump-table targets. It does not inspect
NK.BIN or modify any original data. A negative result applies only to this
bounded static view of `NAVIMAIN.EXE`.
