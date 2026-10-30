# Phase 29 — POISoN-generated editable-point tables

OUTPUT_A and OUTPUT_B have the same physical chain. The only changed record is type `0x06`, sector `0x7749B`, span `0x20`, compression `0x00`, header `07 74 9B 20 00 06 00 00`; its logical payload is rewritten in place. No record insertion, deletion, or relocation is confirmed.

The known B point is payload `26425A3D001C` at logical offset `0x0C82`. Its local neighborhood has 28-byte entries at `0x0C66`, `0x0C82`, `0x0C9E`, and `0x0CBA`, proving a 28-byte stride locally. The full table count and parent/count field remain unresolved.

Both A and B contain 5,433 type-0x06 records, of which 4,624 use compression `0x00`. Blind fixed-stride scans produce many false runs in unrelated compression-0 payloads, so no additional editable-point tables are claimed without a parent/count grammar. Exact 1,935/1,936 structural accounting is unresolved.

Confirmed writer behavior: one added point rewrites the owning type-0x06 record in place. Parent pointer/count repair is not evidenced by the single A→B changed record. Origin is not tied to a proven table/parent field; X16/Y16 remains controlled-output validated only.

Next step: recover the type-0x06 parent/index grammar, then enumerate sibling tables and reconcile counts to 1,935 and 1,936.
