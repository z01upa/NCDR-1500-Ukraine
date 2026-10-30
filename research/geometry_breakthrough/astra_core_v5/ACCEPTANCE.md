# ACCEPTANCE — NCDR-ASTRA-CORE-005
2026-10-29

NEW VERIFIED MECHANISM: high-degree adjacency continues in the next physical Section4 record. Not a repeat of earlier geometry/no-op tests.

- Frozen discovery set:20 blocks. Control2876; quarantine60. Zero discovery/control tested border-copy leakage.
- All954116 real graph heads agree exactly with Section5 endpoint incidences. Control alone925246/925246.
- All1955 continuation records identified by traversal, never by coordinate merging.
- Exact prior511 mismatch record IDs are now continuations;1325 false high-degree records and119 false degree0 records are likewise explained.
- Real degree5/6/7 heads:1712/222/21. New decoder preserves physical IDs and link ordering.
- Cross-block test:14620 paired edge groups;29240/29240 secondary endpoints resolve to unique remote primary heads using edge identity evidence. No failed targets.
-8 NEW tests passed, including exact previous mismatch IDs, held-out endpoint oracle, degrees2–7, corruption detection and source immutability. Prior34 regression passes were not rerun or presented as new evidence.
- Original MP0 SHA256 before/after unchanged:73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e.
- No original CD, SQLite, production decoder, Writer, Worker, Manager or Supervisor changed. All new files are inside astra_core_v5.

Not achieved: a machine-code MP0 reader procedure; semantics of high-degree+2, low-degree inactive words, byte0 high nibble/byte1, remaining edge routing attributes, Section6–9/RT/RL dependencies. No topology mutation, edge permutation, new edge, or routing readiness claim.

Reproduce from this directory:
```
python -B pass_a.py
python -B node_graph_probe.py
python -B border_identity.py
python -B -m unittest discover -s . -p "test_*.py" -v
```
Standard-library Python only. Transport and coordinate parsing are imported read-only from existing topology_v3; the new adjacency reader is local. PassA recreates the documented freeze file; it does not select its rule from control results. Evidence includes binary-source hashes/entry bytes, frozen rule, all1955 continuation HEX records, exact head/edge IDs, representative control-block raw fixtures and tests.

Remaining top blocker for insertion: semantics and dependent consumers of routing/header fields are unknown. Even complete adjacency cannot justify overwriting degree3+8 or constructing new routing masks. The new mechanism removes the continuation blocker, not the routing-consistency gate.
