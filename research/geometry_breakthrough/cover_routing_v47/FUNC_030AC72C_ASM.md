# Bounded function evidence: `0x030AC72C–0x030AC79E`

This 114-byte function range was independently decoded offline from the local recovered NavigationRem section with pypcode 2.0.0. The listing below preserves addresses, mnemonics, and operands only; encoded bytes and the containing binary are not published. Re-run the read-only check with `verify_030AC72C.py` and the local `module.json` plus `section_0.bin`.

```asm
0x030AC72C  mov.l    r8,@-r15
0x030AC72E  mov.l    r9,@-r15
0x030AC730  mov.l    r10,@-r15
0x030AC732  mov      r6,r8
0x030AC734  mov      r4,r6
0x030AC736  ldc      r6,GBR
0x030AC738  mov.w    @(0x38,GBR),r0
0x030AC73A  extu.w   r0,r10
0x030AC73C  mov.w    @(0x3a,GBR),r0
0x030AC73E  mov      #0x0,r6
0x030AC740  mov      #0x0,r4
0x030AC742  bra      0x30ac74a
0x030AC744  extu.w   r0,r9
0x030AC746  add      #0x1,r6
0x030AC748  add      #0x34,r5
0x030AC74A  cmp/gt   r6,r8
0x030AC74C  bf       0x30ac794
0x030AC74E  mov      r10,r7
0x030AC750  neg      r6,r2
0x030AC752  nop
0x030AC754  shad     r2,r7
0x030AC756  mov      #0x1,r3
0x030AC758  and      r3,r7
0x030AC75A  mov      #0x10,r0
0x030AC75C  add      r5,r0
0x030AC75E  mov.b    @(r0,r7),r1
0x030AC760  extu.b   r1,r1
0x030AC762  nop
0x030AC764  shad     r9,r3
0x030AC766  tst      r3,r1
0x030AC768  bt       0x30ac774
0x030AC76A  mov      #0x1,r1
0x030AC76C  nop
0x030AC76E  shad     r6,r1
0x030AC770  bra      0x30ac790
0x030AC772  or       r1,r4
0x030AC774  mov.l    @(0x4,r5),r0
0x030AC776  shlr8    r0
0x030AC778  and      #0x3,r0
0x030AC77A  mov      #0x1,r2
0x030AC77C  add      #0x1,r7
0x030AC77E  and      r2,r7
0x030AC780  nop
0x030AC782  shad     r7,r2
0x030AC784  tst      r2,r0
0x030AC786  bf       0x30ac746
0x030AC788  mov      #0x1,r3
0x030AC78A  nop
0x030AC78C  shad     r6,r3
0x030AC78E  or       r3,r4
0x030AC790  bra      0x30ac746
0x030AC792  nop
0x030AC794  mov      r4,r0
0x030AC796  mov.l    @r15+,r10
0x030AC798  mov.l    @r15+,r9
0x030AC79A  rts
0x030AC79C  mov.l    @r15+,r8
```


Register roles are limited to what this function's data flow shows: `r8` is the incoming `r6` loop bound, `r5` is advanced by `0x34`, `r4` accumulates the returned mask, and `r0` receives that mask on exit. These names do not assign application-level meanings. See [CFG, T flag, and delay-slot analysis](CFG_T_AND_DELAY_SLOTS.md). Recheck command: `python verify_030AC72C.py --module-dir <local NavigationRem.dll module directory>` with pypcode 2.0.0 installed.
