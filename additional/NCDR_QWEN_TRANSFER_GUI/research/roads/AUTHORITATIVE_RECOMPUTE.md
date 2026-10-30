# Authoritative readable-road recomputation

The deterministic builder produced 33,381 roads, 95,119 owned object
occurrences, and exactly 20,156 readable objects with an in-bounds selected
32-byte window. These files replace Phase39 reverse-search aggregates as the
source for future road analysis.

## Confirmed after recomputation

- Each readable target uses one stable pointer residue modulo 32; the 32-byte
  lattice survives globally.
- There are 2,886 unique readable `(target,ptr)` slots across 30 targets.
- F is invariant in 2,797/2,886 unique slots (96.92%).
- Exact raw MULCOORD grouping yields 354 physical nodes. Every node maps to
  one target, and every target represented by these objects maps to one node:
  354↔354 exact one-to-one mapping.
- Ordered roads yield 24,419 distinct-node transition occurrences and 1,002
  unique unordered physical-node pairs. Coverage is RR=2,200, RU=2,902,
  UR=2,978, UU=16,339.

## Changed

- Unique readable slots changed from the Phase39 value to 2,886.
- Authoritative referenced classes are Z=12 and NZ=2,874, replacing the old
  Phase40/41 referenced counts.
- The strongest RR endpoint discriminator tested is equality of BE16 at raw32
  `+0x10`: 1,593/2,200 (72.41%) versus 471/2,200 (21.41%) in shuffled control.
  This is a repeatable relation, but its meaning is not assigned.

## Invalidated

- The uncorrected 10,615-row object-offset corpus and all exact aggregate
  counts derived from treating its BL_ADDR offsets as object starts.
- Phase40/41 Z/NZ counts and the 10,757-position saturation totals.

## Not yet retested

- Complete semantic interpretation of Z/NZ and raw32 `+0x10`.
- Detailed geometry and travel-direction semantics.
- Descriptor choice is not one-neighbor/one-pointer: only 784/1,963 eligible
  node-neighbor mappings use one ptr, and 295/303 eligible nodes reuse a ptr
  across neighbors.
