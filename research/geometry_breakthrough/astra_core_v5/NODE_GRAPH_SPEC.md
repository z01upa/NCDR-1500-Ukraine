# NODE_GRAPH_SPEC — verified Section4 continuation mechanism
Date:2026-10-29. Scope: exact EU44420940.82 original MP0; other discs not tested.

## Record identity and traversal — CONFIRMED on this corpus
Section4 has956071 physical10-byte records aligned with the primary coordinate table. They represent954116 graph heads and1955 continuation records. A continuation retains its own physical index and an equal coordinate, but is NOT an independent graph node. Do not compact IDs or merge coordinates.
For a head at physical index n, degree d=byte0&15:
- d=1..4: active edge IDs are d little-endian u16 values from head+2.
- d=5..7: active IDs are three u16 at head+4,+6,+8, followed by d-3 u16 beginning at byte0 of physical record n+1. Consume that next record as continuation; resume head traversal at n+2.
- Higher degrees, standalone degree0 heads and missing continuation are unsupported: fail closed. No real heads of degree0 or8..15 occur after correct traversal.

Pseudocode:
```
n=0
while n < physical_node_count:
    d = section4[10*n] & 15
    if 1 <= d <= 4:
        refs = u16_array(section4, 10*n+2, d)
        emit_head(id=n, degree=d, refs=refs)
        n += 1
    elif 5 <= d <= 7:
        require n+1 < physical_node_count
        refs = u16_array(section4, 10*n+4, 3)
             + u16_array(section4, 10*(n+1), d-3)
        emit_head(id=n, degree=d, refs=refs)
        mark_continuation(physical_id=n+1, owner=n)
        n += 2
    else:
        reject_unsupported_layout()
```
This reads adjacency only. It does not decode direction/access/turn masks. Original list ordering is preserved; equality of multisets does NOT authorize permuting link order.

## Evidence and independent controls
Discovery:20 blocks,7586 heads,24 continuations. Frozen rule extrapolated to degree7 before encountering degree7 in control.
Control:2876 blocks,925246 heads,1882 continuations; EVERY head's multiset equals the independent Section5 primary endpoint incidence multiset. No failures.
Quarantine:60 blocks sharing any main/secondary coordinate with discovery;21284 heads and49 continuations also agree, but are not counted as independent control.
Across all blocks:954116/954116 head multisets exact;1955/1955 continuation records have no Section5 primary endpoints and repeat their owning head coordinate.
All511 prior mismatch IDs are individually checked as continuation records. The1325 apparent high-degree records without endpoints are continuation data, as are119 apparent degree0 records. No coordinate-based merging was used to produce these results.

Split uses coordinate overlap only to EXCLUDE potentially shared objects. Exact primary node identity is (block,primary-table,index). Secondary indices retain their own namespace. Discovery/control share zero tested border-edge endpoint-pair+length signatures. These new controls were not consulted when fitting the continuation rule; pre-existing aggregate v3 statistics were known, so this is not a blind study of previously unseen corpus data.

## Meaning of the remaining bytes
| Field | Status | Finding |
|---|---|---|
| Head byte0 low nibble | CONFIRMED | Number of active adjacent edge memberships,1..7 in this corpus |
| Head byte0 high nibble | UNKNOWN | Preserve; no direction/turn interpretation |
| Head byte1 | UNKNOWN | Preserve; no routing-mask interpretation |
| Head +2/+3, d1..4 | CONFIRMED | First active edge ID |
| Head +2/+3, d5..7 | UNKNOWN | Not required to locate adjacency. NOT direct next-record/node index:1955/1955 differ from n+1;1934 exceed local node index range;1930 exceed local edge index range. Encoded flags, tagged data or other meanings remain possible |
| Head +4/+6/+8, d5..7 | CONFIRMED | First three edge IDs |
| Continuation +0 onward | CONFIRMED | Remaining d-3 edge IDs, no header/nibble |
| Head +8/+9, d4 | CONFIRMED | Fourth edge ID |
| Head +8/+9, d3 | UNKNOWN semantics | Not active adjacency: confirmed three-edge multiset already complete. Nonzero value must be preserved; not proven free padding |
| Unused words after active links | UNKNOWN | No mutation authorization from this decoder |

An in-memory change of high-degree +2 leaves this adjacency algorithm unchanged; this is NOT evidence that the navigation runtime ignores the word. Likewise degree3 +8 could affect routing even though it is not another adjacency edge.

## Section5 and cross-block identity
Existing14-byte edge layout is reused: flags u16@0, attributes u16@2, unresolved u16@4, endpoints u16@6/+8, length u32@10. Only0x1000/0x2000 endpoint-table selectors and0x8000 shape presence are already established. XOR0x3000 is NOT direction.
The new border check groups copies by BOTH endpoint coordinates, length, flags excluding table-selector bits, attributes and the unresolved word. It obtains14620 two-copy groups. For all29240 secondary endpoints, the paired edge yields exactly one actual remote PRIMARY head ID. No target is a continuation. Unlike coordinate-only grouping, this resolves the previously ambiguous four-copy groups by edge record attributes. This is corpus validation of an identity matching rule, not proof of the firmware's lookup algorithm. See evidence/border_identity.json for exact source/target IDs.

## Contract for adding one edge — NOT YET SAFE
1. Preserve endpoint identity as (block,coordinate-table,index). CONFIRMED. Do not use continuation indices as heads.
2. Add14-byte Section5 record and allocate edge ID; preserve/update header counts and offsets, shape-presence/table entries and container sizes using known transport rules. CONFIRMED layout; flags@0 beyond known bits, attributes@2, word@4 and route-specific length semantics remain UNKNOWN. Copying arbitrary defaults is not justified.
3. Increase endpoint degree and serialize links with the rule above. CONFIRMED storage. Preserve ordering pending UNKNOWN turn-mask dependency.
4. At d4->5, replace one-record representation by two-record representation, place first3 links at head+4/+6/+8 and remaining2 at continuation+0/+2. A corresponding duplicate-coordinate slot is observed for every continuation. Any insertion shifts following PRIMARY physical IDs; update affected Section5 primary references and coordinate counts/runs. CONFIRMED necessary dependency; header and formerly inactive word initialization UNKNOWN.
5. At d5->6 or d6->7, extend the same continuation by one u16 and update degree; those bytes were previously opaque and other header bits may encode routing constraints. At d7->8 stop: no proven layout. For d3->4, +8 becomes an active edge slot, but disposal of its old unknown value is unproven.
6. Every index-changing operation must audit all dependent consumers. Sections7/8/9 have edge-index-shaped first fields; Section6 variable text associations and RT/RL mapping are UNKNOWN. No machine-code consumer has been recovered. Counts/keys alone do not establish safe rekeying semantics.
7. Cross-block edges must preserve/update both copies and relevant remote primary/secondary coordinate entries. Exact paired identities can now be established from the existing graph; creation of new cross-block identity records is still UNKNOWN.
8. Independently validate exact head incidence, continuation ownership, no references to continuations, counts/offsets, copied edge consistency, geometry and routing behavior. Existing byte/graph validation cannot substitute for route-consumer correctness.

No MP0 permutation or new-edge experiment was performed: unknown dependencies explicitly trigger the requested no-mutation branch. Tests alter small in-memory buffers only to falsify an adjacency link and to demonstrate the limited scope of opaque-word handling; no modified MP0 file is written.
