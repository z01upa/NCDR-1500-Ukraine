# ACCEPTANCE — NCDR-TOPOLOGY-CONSOLIDATE-006
Date:2026-10-29

**DONE: complete logical-node and endpoint adjacency reconstruction on the exact original MP0.** Zero unaccounted topology discrepancies. Routing semantics and insertion safety remain outside this acceptance.

| Check | Result |
|---|---:|
| Blocks independently parsed |2956/2956|
| Physical Section4 records |956071|
| Logical heads |954116|
| High-degree heads / continuations |1955 /1955|
| Section5 edge records |1090323|
| Primary endpoint-side memberships |2151406|
| Secondary sides mapped to actual remote heads |29240/29240|
| Missing primary memberships |0|
| Extra, duplicate or foreign primary memberships |0|
| Primary endpoints on continuation records |0|
| Old511 anomaly exact identity set explained |511/511|
| Apparent high-degree pseudo-nodes explained |1325/1325|
| Apparent degree0 pseudo-nodes explained |119/119|
| Section4 byte-exact no-op blocks |2956/2956|
| New consolidation tests |8 passed|

Original SHA256 before/after:
`73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e`

Section4 adjacency and independent Section5 primary-membership canonical digest both:
`616e6af7818fcdd009cf3c181f60cfd0a3e5bf16e7550153d668ed82b84b88d9`

Source integrity, all-block census, per-block Section4 hashes, exact anomalies, full compressed adjacency export and explicit cross-block endpoint links are preserved in evidence/. Tests also read the entire adjacency export to verify954116 unique ordered head identities and1955 continuation owners.

The implementation imports no earlier decoder/Writer. It uses the established format rule but independently parses original bytes and reconciles against an endpoint-side oracle. Prior v3 evidence is read only to verify the exact old511 ID set. No old geometry research or legacy regression pass counts are presented as this task's result.

No standalone degree0 head exists in this corpus; its hypothetical layout remains UNKNOWN. Decoding all observed adjacency does not prove unknown routing fields or give permission to overwrite opaque data. Both requested degree transitions remain blocked for a future Writer as documented in TRANSITIONS.md.

All writes are confined to topology_v6. Original MP0, CDs, SQLite, main Reader, Writer and GUI are unmodified. No new MP0 is created.
