# MP0 topology research v2

This is a read-only investigation of Sections 4 and 5 of the original `EUZ.MP0`. It reuses the current signed-secondary decoder and shape encoder, and checks reconstructed edge geometry with the independent raw-file reader. It does not import or modify Writer v1, SQLite, the Manager, or original media.

Run from the repository root:

```powershell
python -X utf8 -B research/geometry_breakthrough/topology_v2/topology_validator.py
python -X utf8 -B research/geometry_breakthrough/topology_v2/independent_topology_reader.py
python -X utf8 -B research/geometry_breakthrough/topology_v2/edge_insertion_gate.py
python -X utf8 -B -m unittest research.geometry_breakthrough.topology_v2.test_topology -v
```

`topology_validation.json` contains the full per-block results, node mismatch examples, field statistics, and independent geometry-reader totals. `independent_topology_result.json` is a second implementation of the Section 4/5 checks. `edge_insertion_gate.json` records a real candidate pair and refuses before any MP0 mutation because the remaining record semantics are not established. The probe script and `topology_probe.json` preserve lower-level raw field distributions.

No new-edge MP0 is emitted. A parser that can syntactically display a guessed edge would not verify routability or firmware acceptance.
