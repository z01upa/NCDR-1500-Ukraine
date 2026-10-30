# MP0 Writer v2: topology gate

Writer v2 is an isolated, fail-closed topology research stage. It audits the
existing MP0 graph and companion containers, and exposes an insertion
preflight. It intentionally does **not** serialize a new edge while Section 4
overflow links, Section 5 routing attributes, or Sections 6-9 dependencies are
unresolved. Writer v1 remains the only serializer, for its already-verified
shape-only round-trip/edit operation.

## Run

From the `NCDR_MAP_RESEARCH` root:

```powershell
python research/geometry_breakthrough/writer_v2/topology_validator.py
python research/geometry_breakthrough/writer_v2/routing_file_audit.py
python -m unittest discover -s research/geometry_breakthrough/writer_v2/tests -p "test_*.py" -v
python research/geometry_breakthrough/writer_v2/writer_v2.py --block 886 --node-a 412 --node-b 414
```

The last command exits with status 3 after reporting `REFUSED_BEFORE_MUTATION`.
It validates the selected existing nodes, then refuses before opening any
output file. This is expected while the acceptance blockers remain.

The scripts bind their read-only inputs to the recorded source SHA-256 values.
Evidence is written under `evidence/`; no original database, disc, or SQLite
file is opened for writing.
