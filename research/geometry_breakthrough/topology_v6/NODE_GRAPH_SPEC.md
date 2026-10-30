# Section4 physical specification

CONFIRMED on original EUZ.MP0 only. Node identity is(block,primary_table,physical_index); secondary coordinates have a separate namespace. Equal coordinates never merge identities.

## Layout by real degree
All active references below are little-endian u16 edge IDs. Byte0 low nibble is degree; byte0 high nibble and byte1 are UNKNOWN and preserved.

| Degree | Physical bytes | Active edge locations | Other bytes |
|---:|---:|---|---|
|0|UNKNOWN|No standalone degree0 head observed|All119 apparent zero records are continuations. Decoder rejects a degree0 head; no layout invented.|
|1|10|head+2|head+4..9 UNKNOWN|
|2|10|head+2,+4|head+6..9 UNKNOWN|
|3|10|head+2,+4,+6|head+8..9 UNKNOWN|
|4|10|head+2,+4,+6,+8|Header high nibble/byte1 UNKNOWN|
|5|20|head+4,+6,+8; next+0,+2|head+2..3 and next+4..9 UNKNOWN|
|6|20|head+4,+6,+8; next+0,+2,+4|head+2..3 and next+6..9 UNKNOWN|
|7|20|head+4,+6,+8; next+0,+2,+4,+6|head+2..3 and next+8..9 UNKNOWN|

Next means the immediately following10-byte physical record. It has no degree/header of its own. Reading its first edge ID as a header caused the old anomalies. Continue traversal two records later for degree5..7, otherwise one record later. Physical indices are never compacted. Degree8+ is unsupported.

The record's ordered edge list is preserved. Multiset agreement proves incidence, not that link ordering is irrelevant to routing.

## Exact census
956071 physical records =954116 logical heads +1955 continuation records.

| Logical degree | Heads |
|---:|---:|
|0|0 observed; unsupported|
|1|110228|
|2|527552|
|3|281489|
|4|32892|
|5|1712|
|6|222|
|7|21|

1712+222+21=1955 high-degree heads, each owns exactly one continuation. The old511 mismatches are checked by exact(block,index) set equality with v3 evidence. The remaining continuation cohorts are1325 apparent high-degree and119 apparent zero records. No primary edge endpoint targets a continuation.

## Edge-side oracle and duplication accounting
Section5 is read separately from Section4: endpointA at+6 andB at+8; flags0x1000/0x2000 select secondary instead of primary. Each PRIMARY endpoint SIDE contributes one(node ID,edge ID) membership. This side-based multiset would retain two occurrences for a self-loop, rather than silently collapsing it. No repeated memberships or same-table/index loops were observed in this corpus.
All1090323 edge records contribute2180646 endpoint sides:2151406 primary and29240 secondary. Section4 has exactly2151406 matching memberships. Missing=0; extra/foreign=0. Their canonical membership SHA256 digests are equal.
1061083 edge records have two primary ends;29240 have one primary and one secondary. Every secondary side resolves to a remote primary head via a unique two-copy edge group. Group signature uses both endpoint coordinates, stored length, flags with ONLY endpoint-table selector bits removed, attributes and the remaining u16 word. Coordinates constrain candidates but do not choose identities alone; the paired edge's real primary index supplies identity. All14620 groups have exactly two records in distinct blocks and resolve all29240 secondary sides. XOR0x3000 is not a direction flag.
There are1075703 edge objects under this verified two-copy storage rule; all1090323 physical edge records remain in the exported adjacency. Parallel objects are not merged just because coordinates match. This is not a directed routing-graph interpretation.

## Lossless representation
Each decoded Node retains degree, physical ID, local logical ordinal, high nibble, byte1, opaque prefix, ordered links and opaque suffix. The serializer builds new bytes from those fields; it does not merely return an original raw record. It checks original physical layout/opaque span sizes. It reproduces Section4 byte-for-byte in all2956 blocks. Unknown bytes are preserved exactly, with no normalization or defaults.

## Unknown scope
Header routing bits, high-degree+2/+3, inactive low-degree words, Section5 access/direction/cost semantics, Section6–9 reference consumers and RT/RL mapping remain UNKNOWN. Adjacency completeness does not remove these Writer safety gates.
