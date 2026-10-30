# Phase 42 — type-0x00 boundaries and Z/NZ semantics

## Inputs and scope

This phase uses the persisted Phase 39–41 datasets and targeted reads already materialized there. No road-object rescan was performed. The lattice contains 10,757 positions across 23 type-0x00 targets: 10,021 Z and 736 NZ.

## Boundary result

The observed lattice ranges do not prove physical table starts or ends. Every materialized 32-byte position, including all intermediate positions, classifies as Z or NZ by the `+0x10` BE16 discriminator. No padding, sentinel, repeated boundary transition, or independently validated count/length field was found in the 64-byte outside windows. Therefore no target can be marked as having a proven start or end from this evidence.

## Z/NZ fields

The only exact class discriminator is BE16 at `+0x10`: zero = Z, nonzero = NZ. Other byte offsets do not provide a class-wide exact separator. NZ contains 289 distinct values; common values include `0x0300` (123), `0x0200` (76), `0x009E` (66), `0x1000` (59), and `0x0100` (54). Values occur across all residues modulo 32, so this field is not a slot-index encoding.

NZ runs are mixed: 214 NZ runs, including 125 length-1, 41 length-2, and 13 length-3 runs; 522 NZ→NZ transitions occur. Z has 221 runs. The resulting pattern does not support NZ as a universal header or extension.

## Duplicates, callers, and F

All 10,757 raw32 values are unique in the persisted lattice; there are no duplicate groups or cross-target raw32 reuses. Referenced slots include both classes (Z 2,299; NZ 159). Caller anchors span the same Moscow coordinate envelope for both classes; per-slot caller spread is zero because the expanded references are usually single-caller. The expanded Phase 39 dataset contains blank road names, so name multiplicity cannot be tested here. F distributions overlap: Z references use 33 values (1–80), NZ 16 values (1–57); this is not a class discriminator.

## Conclusion

No node/edge/index semantic label is proven. The strongest result is negative: Z/NZ is a reliable field-level classification, but it neither establishes physical table boundaries nor identifies the NZ field's meaning. The next experiment must recover independent table framing or semantic labels from a known type-0x00 consumer.
