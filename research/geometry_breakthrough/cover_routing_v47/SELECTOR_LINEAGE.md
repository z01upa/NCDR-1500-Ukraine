# Selector lineage

## Proven register path

1. `0x0308C1F8 mov r6,r9` copies the incoming selector. `0x0308C210 shad r9,r2` uses it as a shift count for a one-bit mask. No range check is made in `0x0308C1F0`.
2. In `0x0306F484`, `0x0306F490 mov r5,r11`; immediately before the consumer, `0x0306F54A mov r11,r6`. Thus its selector is the function's original `r5` argument.
3. `0x0303DCCC` calls `0x0306F484` using the normalized pointer from literal `0x0303DE6C`. It passes its incoming `r5` through unchanged. At `0x0303D670`, `0x0303D684 mov r5,r8` retains a pointer to the caller-supplied word, and `0x0303D6E8 mov.l @r8,r5` loads that word before the call to `0x0303DCB0` at `0x0303D6F6`.
4. The parent call at `0x0303C748` passes `SP+0x14` to `0x0303D670` (`0x0303C73C mov #0x14,r5`; delay `0x0303C74A add r15,r5`). `0x0303C52E` stored the packed value at that stack slot.
5. `0x0303C50C` reloads the original context pointer, `0x0303C50E mov.l @(0x8,r3),r9` loads a pointer from context+8, and `0x0303C510` through `0x0303C52C` assembles a 32-bit word from bytes at that pointer+0x2F, +0x2E, +0x2D, +0x2C. No mask or clamp is applied before the word is passed as selector.

The backward slice therefore identifies the selector as a 32-bit context-derived value. It is not derived from the candidate-node comparison that chooses which attribute byte to read.

## Domain and meaning

- Values 0, 1, 2, and 3 are representable in the source word, and the replay tests those four values. The inspected code does not prove which values occur in real runtime contexts; no actual context snapshot was available.
- Values are not restricted to 0–3 by the traced instructions. For positive SHAD counts, the hardware operation selects by the low five count bits; behavior for other source values is not evidence of their intended domain.
- The endpoint/byte slot is a separate value: `0x0301EFE4` returns 0 on coordinate equality and 1 on mismatch. `0x0308C208` uses that result as the byte index; the selector is independently in `r9` and used for the bit index.
- No machine-code evidence maps this context-derived selector to travel direction. It may be a mask index for another class or condition; its semantic meaning remains UNKNOWN.
