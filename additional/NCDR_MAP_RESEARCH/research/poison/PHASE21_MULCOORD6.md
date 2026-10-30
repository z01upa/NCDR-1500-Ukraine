# Phase 21 — MULCOORD>>6 test

With `M=5,555,555`, `Qlon=floor((lon+30)M)>>6` is B `5,872,769`, L1 `5,872,778`, L2 `5,872,856`. `Qlat=floor(latM)>>6` is B `4,785,020`, T1 `4,785,029`, T2 `4,785,107`.

The stored six-byte item is two fields. Longitude bytes are `26 42 5A`, `26 4B 5A`, `26 99 5A`; latitude bytes are `3D 00 1C`, `46 00 1C`, `94 00 1C`. Permutation `[0,2,1]` gives local X `0x265A42/0x265A4B/0x265A99` and constant `originX=0x33423F`; permutation `[1,2,0]` gives local Y `0x1C3D/0x1C46/0x1C94` and constant `originY=0x48E73F`.

Two alternative permutations also remain constant: X `[2,0,1]`, origin `-0x89C1`; Y `[2,1,0]`, origin `0x2D033F`. The data do not distinguish these alternatives because the changed bytes remain in a stable range. The candidate origins were not found verbatim as 2-, 3-, or 4-byte values elsewhere in the B logical type-0x06 payload.

Therefore the confirmed model is `Q = local + constant` with byte-swizzled 24-bit local coordinates, but the unique physical byte permutation and whether the origin is block-global or an implicit transform remain unresolved. It is not possible to claim a unique Q-minus-origin formula from these controls alone. A carry-forcing coordinate delta is required.
