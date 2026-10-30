# Topology v6 — NCDR-TOPOLOGY-CONSOLIDATE-006

Status: **DONE for complete endpoint adjacency of the exact EU44420940.82 MP0 corpus.** No unexplained adjacency discrepancies remain. This does not mean routing attributes, legal transitions, or safe new-edge insertion are decoded.

## Files and reproduction
- `topology_decoder.py`: standalone transport, Section4 decoder, lossless Section4 serializer, separate Section5 endpoint oracle and fail-closed transition planning. Standard library only; no imports from main Reader, Writer, geometry, v3 or v5.
- `verify_topology.py`: all-block reconciliation and evidence export.
- `test_topology_v6.py`: no-op, corruption, in-memory changes, identity/export and refusal tests.
- `NODE_GRAPH_SPEC.md`: exact observed record layouts and UNKNOWN fields.
- `TRANSITIONS.md`: known 3->4/4->5 changes and prohibited opaque overwrites.
- `evidence/logical_adjacency.jsonl.gz`: ALL954116 logical heads with ordered edge IDs, physical node IDs, block-local logical ordinals and continuation ownership.
- `evidence/remote_endpoint_links.json`: ALL29240 secondary endpoint mappings, including source edge side and actual paired remote primary head/edge IDs.
- `evidence/block_checks.json`: each block's counts and original/rebuilt Section4 hashes.
- `evidence/legacy_cohorts.json`: all prior pseudo-node IDs and their actual owners.
- `evidence/acceptance.json`: compact machine-readable acceptance, counts and exceptions (empty).

From this directory:
```
python -B verify_topology.py
python -B -m unittest discover -s . -p "test_*.py" -v
```
Evidence generation writes only under this directory. No modified MP0 is produced. Original source path and before/after SHA256 are in acceptance.json. `logical_ordinal` is an output convenience, NOT a replacement for physical endpoint indices.
