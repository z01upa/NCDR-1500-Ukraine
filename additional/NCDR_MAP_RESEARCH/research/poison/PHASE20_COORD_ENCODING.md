# Phase 20 — recovered POISoN coordinate encoding

The homologous added-POI item is a six-byte structure in a type-0x06 logical record (sector `0x7749B`, logical payload 16,376 bytes). It is two adjacent 24-bit big-endian fields: longitude at item offset `0x0C7B` and latitude at `0x0C7E`. In B the item is `26 42 5A 3D 00 1C`.

L1 changes the longitude field to `26 4B 5A`; L2 changes it to `26 99 5A` and the sorted item moves to `0x0CA9`. T1 changes latitude to `46 00 1C`; T2 changes it to `94 00 1C`. The untouched field remains identical in each pure-axis experiment.

The item boundaries are therefore confirmed as `[0x0C7B,0x0C80)` when the POI sorts at the B position. L2 demonstrates that the item is part of a sorted table: its bytes are relocated, not rewritten in place. The surrounding changed bytes are table-entry movement/rebuild noise.

The recovered representation is not a simple fixed decimal scale from the displayed deltas: longitude deltas are `0x900` for +0.00010 and `0x5700` for +0.00100; latitude deltas are `0x90000` for +0.00011 and `0x570000` for +0.00100. These exact ratios show quantized grid coordinates, but the affine origin/quantization rule is not recoverable from only these points. The model is nevertheless confirmed as separate 24-bit BE X/Y fields, not MULCOORD or a single interleaved integer.

Minimum direct edit: update the two 3-byte fields in the six-byte POI item and repair the sorted-table placement/associated lookup structures when the new coordinate changes ordering. Do not assume the fixed offset for points whose sort key changes.
