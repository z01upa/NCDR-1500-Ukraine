# Phase 22 — 24-bit coordinate byte order

## Result

The same six-byte item is at sector `0x7749B`, raw offset `0x0C82` in all three outputs:

| output | raw item |
|---|---|
| B | `26 42 5A 3D 00 1C` |
| XCARRY | `26 62 57 89 00 24` |
| YCARRY | `26 42 5B 42 00 1C` |

The item is structurally two adjacent 24-bit fields `[X3][Y3]`; no flag bits are evidenced.

## Q values

Using `M=5,555,555`, `Qlon=floor((lon+30)*M)>>6`, and `Qlat=floor(lat*M)>>6`:

| output | Qlon | Qlat |
|---|---:|---:|
| B | `0x599C81` (5,872,769) | `0x49037C` (4,785,020) |
| XCARRY | `0x599D86` (5,873,030) | `0x49037C` (4,785,020) |
| YCARRY | `0x599C81` (5,872,769) | `0x490481` (4,785,281) |

The displayed-coordinate deltas are therefore `+0x105` in longitude and `+0x105` in latitude.

## Permutation test

Neither Phase 21 longitude candidate `[0,2,1]` or `[2,0,1]` maps B→XCARRY to `+0x105`; neither latitude candidate `[1,2,0]` or `[2,1,0]` maps B→YCARRY to `+0x105`. The resulting origins vary between controls, so carry behavior does not resolve the candidates; it falsifies both candidate sets against these raw items.

For B alone, the previous local/origin pairs remain:

* longitude `[0,2,1]`: local `0x265A42`, origin `0x33423F`;
  `[2,0,1]`: local `0x5A2642`, origin `-0x89C1`.
* latitude `[1,2,0]`: local `0x1C3D`, origin `0x48E73F`;
  `[2,1,0]`: local `0x1C003D`, origin `0x2D033F`.

## Encoder/decoder status

No exact encoder or decoder can be confirmed from the supplied controls. The only confirmed transform is the MULCOORD quantizer above and the six-byte `[X3][Y3]` storage shape. A 20-neighbor validation and maximum decode-error result are not available because no candidate passes the three-control carry test.

Next unresolved structure: determine whether XCARRY/YCARRY were reopened with the same item identity/table position and obtain a carry experiment whose stored-byte deltas correspond to the quantized `Q` deltas.
