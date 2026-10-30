# MP0 node-link investigation v3

Read-only follow-up to `topology_v2`; it reuses the confirmed 10-byte Section 4 / 14-byte Section 5 layout and does not import the project decoder, Writer, or topology_v2 validator.

Run from the repository root:

```powershell
python -X utf8 -B research/geometry_breakthrough/topology_v3/node_link_validator.py
python -X utf8 -B research/geometry_breakthrough/topology_v3/firmware_scope.py
python -X utf8 -B -m unittest discover -s research/geometry_breakthrough/topology_v3/tests -p 'test*.py' -v
```

The validator verifies the original MP0 hash before and after reading, inflates all 2,956 streams, and writes evidence only under this `topology_v3/evidence/` folder. `topology_editor.py` is deliberately refusal-first: its no-op is byte-exact, while all topology mutations remain disabled until the unresolved dependencies listed in `ACCEPTANCE.md` are proven.
