# CALLERS — cover attribute producers

Scan source: pinned recovered `NavigationRem.dll` PDATA roots and complete executable Section 0, runtime range `0x02FD1000–0x030B3FBC` (exclusive), as defined by recovered section metadata. `scan_xrefs.py` checked all `%section_0.bin` bytes against the pinned SHA-256 and enumerated decoded PDATA instructions plus aligned raw SH4 literal/branch encodings over the entire executable section.

## Inventory

The database has 4,054 PDATA roots. The all-section scan found 76 reachable `jsr @r0` sites loaded from literals pointing at the requested routines: 74 sites to `0x02FFB92C`, 2 to `0x02FFBB00`; no direct BRA/BSR targets. The table records the function, callsite, indirect-call form, and closest textual argument definitions for `r4/r5` (including a `jsr` delay slot). For these 76 sites the argument setup is an inventory hint; it is not path-sensitive dataflow proof. `xref_inventory.json` retains raw-reference addresses and PDATA/reachability classification.

| Target | Function | Call instruction | Form | nearest r4 definition | nearest r5/output-buffer definition | post-return buffer use |
|---|---|---|---|---|---|
| 0x2ffb92c | 0x2ffeda8 | `0x2ffedc6` | `jsr literal-register` | `02ffedc4 mov.l    @(0x8,r8),r4` | `02ffedc8 add      r15,r5; 02ffedc2 mov      #0x20,r5` | not established in this trace |
| 0x2ffb92c | 0x3002b7c | `0x3002bae` | `jsr literal-register` | `03002ba8 mov      r8,r4` | `03002bac mov      r9,r5` | not established in this trace |
| 0x2ffb92c | 0x3002d80 | `0x3002da8` | `jsr literal-register` | `03002da4 mov.l    @(r0,r4),r4` | `03002d9c mov      r8,r5` | not established in this trace |
| 0x2ffb92c | 0x3002ddc | `0x3002e26` | `jsr literal-register` | `03002e24 mov.l    @r13,r4` | `03002e28 add      r15,r5; 03002e22 mov      #0x50,r5` | not established in this trace |
| 0x2ffb92c | 0x300b2c0 | `0x300b360` | `jsr literal-register` | `0300b35e mov.l    @(0x8,r8),r4` | `0300b362 add      r14,r5; 0300b35a mov      #0x2c,r5` | not established in this trace |
| 0x2ffb92c | 0x3011f6c | `0x3012040` | `jsr literal-register` | `0301203e mov      r6,r4` | `03012042 add      r15,r5; 0301203c mov      #0x50,r5` | not established in this trace |
| 0x2ffb92c | 0x301cb74 | `0x301cbaa` | `jsr literal-register` | `0301cba8 mov.l    @r9,r4` | `0301cbac add      r15,r5; 0301cba6 mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x301d014 | `0x301d16e` | `jsr literal-register` | `0301d16a mov.l    @(r0,r1),r4` | `0301d170 add      r14,r5; 0301d164 mov      #0x1c,r5` | not established in this trace |
| 0x2ffb92c | 0x301edac | `0x301edc0` | `jsr literal-register` | `unknown / incoming register` | `0301edc2 add      r15,r5; 0301edbe mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x301ee4c | `0x301ee90` | `jsr literal-register` | `0301ee8c mov.l    @(r0,r2),r4` | `0301ee92 mov      r10,r5` | not established in this trace |
| 0x2ffb92c | 0x301f008 | `0x301f020` | `jsr literal-register` | `unknown / incoming register` | `0301f022 mov      r8,r5` | not established in this trace |
| 0x2ffb92c | 0x301f2b8 | `0x301f2d4` | `jsr literal-register` | `unknown / incoming register` | `0301f2d6 mov      r9,r5` | not established in this trace |
| 0x2ffb92c | 0x301f3f8 | `0x301f418` | `jsr literal-register` | `unknown / incoming register` | `0301f41a mov.l    @(0x30,r14),r5` | not established in this trace |
| 0x2ffb92c | 0x3034eec | `0x3034f0c` | `jsr literal-register` | `unknown / incoming register` | `03034f0e mov.l    @(0x30,r14),r5` | not established in this trace |
| 0x2ffb92c | 0x303c330 | `0x303c3c0` | `jsr literal-register` | `0303c3c2 mov.l    @r10,r4` | `0303c3be add      r15,r5` | not established in this trace |
| 0x2ffb92c | 0x303d2e8 | `0x303d384` | `jsr literal-register` | `0303d382 mov.l    @(0x18,r8),r4` | `0303d386 add      r15,r5; 0303d380 mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x303fc38 | `0x303fd62` | `jsr literal-register` | `0303fd2c mov      r0,r4` | `0303fd64 mov.l    @(0x10,r15),r5; 0303fd2a add      r3,r5` | not established in this trace |
| 0x2ffb92c | 0x3040af0 | `0x3040b4a` | `jsr literal-register` | `03040b34 mov      r0,r4` | `03040b4c add      r2,r5; 03040b40 mov.l    @(r0,r8),r5` | not established in this trace |
| 0x2ffb92c | 0x3040e10 | `0x3040e1e` | `jsr literal-register` | `unknown / incoming register` | `unknown / incoming register` | not established in this trace |
| 0x2ffb92c | 0x30415dc | `0x3041658` | `jsr literal-register` | `03041652 mov.l    @(r0,r3),r4` | `0304165a add      r15,r5; 03041656 mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x30454dc | `0x3045572` | `jsr literal-register` | `03045574 mov.l    @r2,r4; 03045552 mov      r7,r4` | `0304556e add      r10,r5` | not established in this trace |
| 0x2ffb92c | 0x304902c | `0x304904c` | `jsr literal-register` | `03049044 cmp/eq   r1,r4` | `0304904e add      r15,r5; 0304904a mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x3049d8c | `0x3049e22` | `jsr literal-register` | `03049e06 mov.l    @(0xc,r4),r4` | `03049e24 mov.l    @(0x24,r15),r5; 03049e1a mov.l    @(0x24,r15),r5` | not established in this trace |
| 0x2ffb92c | 0x3059670 | `0x3059720` | `jsr literal-register` | `0305971e mov.l    @r8,r4` | `03059722 add      r15,r5; 0305971a mov      #0x28,r5` | not established in this trace |
| 0x2ffb92c | 0x305ef94 | `0x305efca` | `jsr literal-register` | `0305efc8 mov      r11,r4` | `0305efcc add      r14,r5; 0305efc6 mov      #0x4c,r5` | not established in this trace |
| 0x2ffbb00 | 0x3060fa0 | `0x30611b4` | `jsr literal-register` | `030611b6 mov      r12,r4; 030611a0 mov      #0x1c,r4` | `030611b0 add      r14,r5` | not established in this trace |
| 0x2ffbb00 | 0x3060fa0 | `0x3061282` | `jsr literal-register` | `03061284 mov      r12,r4; 03061232 mov      #0x1c,r4` | `0306127e add      r14,r5` | not established in this trace |
| 0x2ffb92c | 0x30647e8 | `0x30647f0` | `jsr literal-register` | `unknown / incoming register` | `030647f2 add      r15,r5; 030647ee mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x3064848 | `0x3064850` | `jsr literal-register` | `unknown / incoming register` | `03064852 add      r15,r5; 0306484e mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x3064884 | `0x306488a` | `jsr literal-register` | `unknown / incoming register` | `unknown / incoming register` | not established in this trace |
| 0x2ffb92c | 0x3068e04 | `0x3068e20` | `jsr literal-register` | `03068e10 cmp/eq   r8,r4` | `03068e22 add      r15,r5; 03068e1e mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x3068e04 | `0x3068e3a` | `jsr literal-register` | `03068e38 mov      r8,r4` | `03068e3c add      r15,r5; 03068e36 mov      #0x44,r5` | not established in this trace |
| 0x2ffb92c | 0x3069de0 | `0x3069df2` | `jsr literal-register` | `unknown / incoming register` | `unknown / incoming register` | not established in this trace |
| 0x2ffb92c | 0x3069ee0 | `0x3069efc` | `jsr literal-register` | `03069eee cmp/eq   r9,r4` | `03069efa mov.l    0x306a098,r5` | not established in this trace |
| 0x2ffb92c | 0x3069ee0 | `0x3069f0c` | `jsr literal-register` | `03069f0e mov      r9,r4; 03069eee cmp/eq   r9,r4` | `03069f0a mov.l    0x306a09c,r5` | not established in this trace |
| 0x2ffb92c | 0x306ac90 | `0x306ad7c` | `jsr literal-register` | `0306ad7a mov.l    @(0x38,r11),r4` | `0306ad7e add      r15,r5; 0306ad78 mov      #0x34,r5` | not established in this trace |
| 0x2ffb92c | 0x306ac90 | `0x306ade2` | `jsr literal-register` | `0306ade0 mov.l    @(0x38,r11),r4` | `0306ade4 add      r15,r5; 0306addc mov      #0x34,r5` | not established in this trace |
| 0x2ffb92c | 0x306d104 | `0x306d388` | `jsr literal-register` | `0306d38a mov.l    @(0x18,r2),r4` | `0306d384 add      r15,r5` | not established in this trace |
| 0x2ffb92c | 0x306d3dc | `0x306d3f8` | `jsr literal-register` | `unknown / incoming register` | `0306d3fa add      r15,r5; 0306d3ee mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x306d3dc | `0x306d426` | `jsr literal-register` | `0306d424 mov      r8,r4` | `0306d428 add      r15,r5; 0306d422 mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x306d4dc | `0x306d570` | `jsr literal-register` | `0306d56e mov      r10,r4` | `0306d572 add      r15,r5; 0306d56a mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x306d71c | `0x306d864` | `jsr literal-register` | `0306d860 mov.l    @r5,r4` | `0306d866 add      r15,r5; 0306d862 mov      #0x3c,r5` | not established in this trace |
| 0x2ffb92c | 0x306e178 | `0x306e218` | `jsr literal-register` | `0306e214 mov.l    @(r0,r1),r4` | `0306e21a mov      r9,r5; 0306e1fa add      r15,r5` | not established in this trace |
| 0x2ffb92c | 0x306f11c | `0x306f202` | `jsr literal-register` | `0306f1fc mov.l    @(r0,r10),r4` | `0306f204 add      r15,r5; 0306f200 mov      #0x40,r5` | not established in this trace |
| 0x2ffb92c | 0x306f484 | `0x306f536` | `jsr literal-register` | `0306f530 mov.l    @(r0,r10),r4` | `0306f538 add      r15,r5; 0306f532 mov      #0x40,r5` | not established in this trace |
| 0x2ffb92c | 0x306f5e4 | `0x306f64a` | `jsr literal-register` | `0306f64c mov.l    @r9,r4; 0306f636 mov.l    @r11,r4` | `0306f648 add      r15,r5` | not established in this trace |
| 0x2ffb92c | 0x306f6bc | `0x306f6e4` | `jsr literal-register` | `0306f6e2 mov.l    @r4,r4` | `0306f6e6 add      r15,r5; 0306f6de mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x306f8a4 | `0x306f8b4` | `jsr literal-register` | `unknown / incoming register` | `0306f8b6 add      r15,r5; 0306f8b2 mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x30724b4 | `0x30725b2` | `jsr literal-register` | `030725ac mov.l    @(r0,r4),r4` | `030725b4 add      r15,r5; 030725b0 mov      #0x18,r5` | not established in this trace |
| 0x2ffb92c | 0x3077268 | `0x3077288` | `jsr literal-register` | `03077286 mov.l    @(0x10,r15),r4` | `0307728a add      r15,r5; 03077282 mov      #0x4c,r5` | not established in this trace |
| 0x2ffb92c | 0x307afcc | `0x307afe8` | `jsr literal-register` | `0307afda cmp/eq   r9,r4` | `0307afe6 mov.l    0x307b204,r5` | not established in this trace |
| 0x2ffb92c | 0x307afcc | `0x307aff8` | `jsr literal-register` | `0307affa mov      r9,r4; 0307afda cmp/eq   r9,r4` | `0307aff6 mov.l    0x307b208,r5` | not established in this trace |
| 0x2ffb92c | 0x307b098 | `0x307b0aa` | `jsr literal-register` | `unknown / incoming register` | `unknown / incoming register` | not established in this trace |
| 0x2ffb92c | 0x3086994 | `0x30869cc` | `jsr literal-register` | `030869ca mov.l    @(0x8,r11),r4` | `030869ce add      r15,r5; 030869c6 mov      #0x34,r5` | not established in this trace |
| 0x2ffb92c | 0x3086c78 | `0x3086c8e` | `jsr literal-register` | `03086c8c mov.l    @(0x8,r8),r4` | `03086c90 add      r15,r5; 03086c8a mov      #0x28,r5` | not established in this trace |
| 0x2ffb92c | 0x30914d8 | `0x30914e8` | `jsr literal-register` | `unknown / incoming register` | `unknown / incoming register` | not established in this trace |
| 0x2ffb92c | 0x30968e4 | `0x3096924` | `jsr literal-register` | `03096922 mov.l    @r8,r4` | `03096926 add      r15,r5; 03096920 mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x30968e4 | `0x3096934` | `jsr literal-register` | `03096932 mov      #0x0,r4` | `03096936 add      r15,r5; 0309692e mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x3099740 | `0x3099758` | `jsr literal-register` | `03099756 mov.l    @r4,r4` | `0309975a add      r15,r5; 03099752 mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x30997cc | `0x30997da` | `jsr literal-register` | `030997d4 mov.l    @r5,r4` | `030997dc add      r15,r5; 030997d6 mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x30a7324 | `0x30a736c` | `jsr literal-register` | `030a736a mov.l    @(0x10,r15),r4` | `030a736e add      r15,r5; 030a7366 mov      #0x4c,r5` | not established in this trace |
| 0x2ffb92c | 0x30a73a4 | `0x30a7488` | `jsr literal-register` | `030a7486 mov.l    @(0x10,r15),r4` | `030a748a add      r14,r5; 030a7484 mov      #0x8,r5` | not established in this trace |
| 0x2ffb92c | 0x30a73a4 | `0x30a7526` | `jsr literal-register` | `030a7524 mov.l    @(0x10,r15),r4` | `030a7528 add      r14,r5; 030a7520 mov      #0x8,r5` | not established in this trace |
| 0x2ffb92c | 0x30a75d4 | `0x30a76a0` | `jsr literal-register` | `030a769e mov.l    @(0x10,r15),r4` | `030a76a2 add      r15,r5; 030a769c mov      #0x24,r5` | not established in this trace |
| 0x2ffb92c | 0x30a76f8 | `0x30a77ee` | `jsr literal-register` | `030a77f0 mov.l    @r11,r4` | `030a77ec add      r15,r5` | not established in this trace |
| 0x2ffb92c | 0x30a7a60 | `0x30a7ab4` | `jsr literal-register` | `030a7ab6 mov      r10,r4` | `030a7aae add      r14,r5` | not established in this trace |
| 0x2ffb92c | 0x30a7a60 | `0x30a7c08` | `jsr literal-register` | `030a7c06 mov.l    @r13,r4` | `030a7c0a add      r14,r5; 030a7c04 mov      #0x14,r5` | not established in this trace |
| 0x2ffb92c | 0x30a7d44 | `0x30a7d52` | `jsr literal-register` | `unknown / incoming register` | `030a7d54 add      r15,r5; 030a7d4e mov      #0x38,r5` | not established in this trace |
| 0x2ffb92c | 0x30a7eb0 | `0x30a7ed6` | `jsr literal-register` | `030a7ed0 mov.l    @(r0,r14),r4` | `030a7ed8 add      r14,r5; 030a7ece mov      #0x3c,r5` | not established in this trace |
| 0x2ffb92c | 0x30a7eb0 | `0x30a800c` | `jsr literal-register` | `030a800a mov.l    @r13,r4` | `030a800e add      r14,r5; 030a8008 mov      #0x8,r5` | not established in this trace |
| 0x2ffb92c | 0x30a81f4 | `0x30a8234` | `jsr literal-register` | `030a8230 mov.l    @(r0,r1),r4` | `030a8236 add      r15,r5; 030a822e mov      #0x24,r5` | not established in this trace |
| 0x2ffb92c | 0x30a84b0 | `0x30a84ea` | `jsr literal-register` | `030a84ec mov      r8,r4` | `030a84e0 add      r14,r5` | not established in this trace |
| 0x2ffb92c | 0x30a84b0 | `0x30a8628` | `jsr literal-register` | `030a8626 mov.l    @r13,r4` | `030a862a add      r14,r5; 030a8624 mov      #0x3c,r5` | not established in this trace |
| 0x2ffb92c | 0x30aaa70 | `0x30aaa8c` | `jsr literal-register` | `030aaa88 mov.l    @r8,r4` | `030aaa8e add      r15,r5; 030aaa86 mov      #0x14,r5` | not established in this trace |
| 0x2ffb92c | 0x30ab324 | `0x30ab378` | `jsr literal-register` | `030ab376 mov.l    @r13,r4` | `030ab37a add      r15,r5; 030ab372 mov      #0x10,r5` | not established in this trace |
| 0x2ffb92c | 0x30ab324 | `0x30ab404` | `jsr literal-register` | `030ab3fe mov.l    @(r0,r8),r4` | `030ab406 add      r15,r5; 030ab400 mov      #0x10,r5` | not established in this trace |

## Proven caller and buffer

At function `0x0306F484`, `0x0306F52A–0x0306F530` loads `r4` from the caller stack item array at `SP+0x88+4*r10`; the tested item is packed `block<<12 | edge`. The producer confirms this input shape by retaining `r4`, taking low 12 bits as edge index and upper bits as block index before the block lookup. It calls the `0x02FFB92C` literal at `0x0306F536`; the delay slot `0x0306F538 add r15,r5` makes `r5` point to stack buffer `SP+0x40`. After return, `0x0306F542–0x0306F54C` sets the same `r4=SP+0x40` and calls `0x0308C1F0`; `r5=SP+0xA8` is the node candidate and `r6=r11` is the selector. Thus producer output pointer aliases the real consumer input.

At `0x0306F550` `tst r0,r0`; `0x0306F552 bf/s 0x0306F558` with delay slot `0x0306F554 mov #-1,r0`. A nonzero consumer result (attribute bit set) returns `-1`; zero falls through to `0x0306F556 mov #0,r0`. This is a concrete caller-visible rejection/success return path.

`0x02FFBB00` is called twice at `0x030611B4` and `0x03061282` in `0x03060FA0`. Its pointer and output arguments are in the table; no downstream attribute consumer was established for these two sites in this task.
