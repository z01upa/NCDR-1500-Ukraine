# Phase 48 — global readable road corpus checkpoint

The complete type-0x00 header inventory reproduces the confirmed readable count: 3,232 records, consisting of 196 compression-0 and 3,036 compression-2 records. Compression-2 logical views are already validated as zlib payloads.

The persisted Phase 39 reverse-reference corpus contains 10,615 validated 24-byte road-object-shaped references, all to 23 readable compression-2 targets. It is not a global road-ownership corpus: expanded rows do not retain the MORE_INFO owner, BRIF boundary, road ID, or ordered object-array membership. Consequently it cannot safely produce global road transitions, RR edge pairs, descriptor-per-neighbor mappings, or a global D(P)==D(Q) rate.

The requested Phase 48 transition and edge-link CSVs are intentionally marked not-computed rather than treating reverse-reference rows as ordered roads. The readable type-0x00 inventory and bounded Phase 39 corpus are persisted. A complete Phase 48 requires a new parser that recovers every 0x0E BRIF→MORE_INFO object array, including compression-0x01 handling where encountered.
