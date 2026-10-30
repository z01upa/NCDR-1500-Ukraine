# Phase 35 — variable-length type-0x00 framing

The existing readable sample contains 101 incoming road-object pointers across 23 type-0x00 targets. Twenty targets have at least two distinct pointers. All 101 masked pointers are divisible by 4. Across targets there are 74 deltas between distinct sorted pointers, ranging from 32 to 12,608 bytes; median delta is 1,152 bytes. Every observed delta is divisible by 4, but there is no common fixed width.

The next-distinct-pointer interval is a valid candidate extent for the intervening region, but it is not yet proven to be a complete record. No uniform prefix at `ptr`, `ptr-1`, `ptr-2`, `ptr-4`, or `ptr-8` predicts the next pointer. No BE/LE 8/16/24-bit length-prefix model was validated.

F has no exact relation to pointer delta. The readable F distribution is 1..20; same F values occur with widely different intervals, and no tested `delta=a+bF` relation with small integer units achieves cross-target exactness. Four duplicate-pointer groups exist; each duplicate has identical road identity, anchor, and F, supporting shared/repeated references rather than independent geometries.

The strongest structural result is 4-byte alignment plus pointer-defined candidate extents. Variable payload start and terminal framing remain unresolved. Varint/LEB-style parsing was not accepted because no candidate consumed independently to the next-pointer boundaries across the sample. Geometry decoding is therefore deferred.
