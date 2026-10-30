; Original module: NavigationRem.dll
; SHA-256: 4555a95f5bdd7d0479a39dcf8ab10a1d0dbe6e40d560d550df2461fee350ffcd
; .text SHA-256: 91d33ac02d82dc109e65d83c87e44a00cba02887fb14e6e5b136eb16db0a35a9
; Decoder: pypcode SuperH4:LE:32:default
; Focused original instruction windows; gaps include literal pools/data and are intentionally omitted.

## AC04C_ENTRY
### 0x010AC04C..0x010AC080; runtime 0x030AC04C; raw 0x000DB44C; PDATA owner 0x010AC04C
010ac04c 862f mov.l r8,@-r15
010ac04e 962f mov.l r9,@-r15
010ac050 a62f mov.l r10,@-r15
010ac052 b62f mov.l r11,@-r15
010ac054 c62f mov.l r12,@-r15
010ac056 d62f mov.l r13,@-r15
010ac058 224f sts.l PR,@-r15
010ac05a 436a mov r4,r10
010ac05c 5369 mov r5,r9
010ac05e 636d mov r6,r13
010ac060 736c mov r7,r12
010ac062 d07f add #-0x30,r15
010ac064 44e1 mov #0x44,r1
010ac066 ac31 add r10,r1
010ac068 1b1f mov.l r1,@(0x2c,r15)
010ac06a fae2 mov #-0x6,r2
010ac06c 1268 mov.l @r1,r8
010ac06e a154 mov.l @(0x4,r10),r4
010ac070 0900 nop 
010ac072 2c48 shad r2,r8
010ac074 fee1 mov #-0x2,r1
010ac076 1034 cmp/eq r1,r4
010ac078 01eb mov #0x1,r11
010ac07a 458f bf/s 0x10ac108
010ac07c b928 and r11,r8
010ac07e 01a0 bra 0x10ac084

## AC04C_R8_BRANCH_AND_SEED
### 0x010AC158..0x010AC1A0; runtime 0x030AC158; raw 0x000DB558; PDATA owner 0x010AC04C
010ac158 3030 cmp/eq r3,r0
010ac15a 018b bf 0x10ac160
010ac15c 1da2 bra 0x10ac59a
010ac15e ffe0 mov #-0x1,r0
010ac160 8828 tst r8,r8
010ac162 2903 movt r3
010ac164 3823 tst r3,r3
010ac166 0f8d bt/s 0x10ac188
010ac168 391f mov.l r3,@(0x24,r15)
010ac16a 34e3 mov #0x34,r3
010ac16c 38dc mov.l 0x10ac250,r12 ; [010ac250]=010f6d60
010ac16e c362 mov r12,r2
010ac170 1e4a ldc r10,GBR
010ac172 1dc5 mov.w @(0x3a,GBR),r0
010ac174 0d65 extu.w r0,r5
010ac176 1ec5 mov.w @(0x3c,GBR),r0
010ac178 0d60 extu.w r0,r0
010ac17a 5703 mul.l r5,r3
010ac17c 1a01 sts MACL,r1
010ac17e 1c32 add r1,r2
010ac180 1072 add #0x10,r2
010ac182 2c02 mov.b @(r0,r2),r2
010ac184 09a0 bra 0x10ac19a
010ac186 2c6b extu.b r2,r11
010ac188 31dc mov.l 0x10ac250,r12 ; [010ac250]=010f6d60
010ac18a a364 mov r10,r4
010ac18c f556 mov.l @(0x14,r15),r6
010ac18e cdb2 bsr 0x10ac72c
010ac190 c365 mov r12,r5
010ac192 036b mov r0,r11
010ac194 3ae0 mov #0x3a,r0
010ac196 ad02 mov.w @(r0,r10),r2
010ac198 2d65 extu.w r2,r5
010ac19a 3ae0 mov #0x3a,r0
010ac19c ad03 mov.w @(r0,r10),r3
010ac19e 3d63 extu.w r3,r3

## AC04C_CANDIDATE_GATE
### 0x010AC1F8..0x010AC204; runtime 0x030AC1F8; raw 0x000DB5F8; PDATA owner 0x010AC04C
010ac1f8 01ed mov #0x1,r13
010ac1fa fa51 mov.l @(0x28,r15),r1
010ac1fc 0900 nop 
010ac1fe 1c4d shad r1,r13
010ac200 d82b tst r13,r11
010ac202 ec8b bf 0x10ac1de
### 0x010AC350..0x010AC358; runtime 0x030AC350; raw 0x000DB750; PDATA owner 0x010AC04C
010ac350 0988 cmp/eq #0x9,r0
010ac352 018b bf 0x10ac358
010ac354 43af bra 0x10ac1de
010ac356 db2b or r13,r11

## AC72C
### 0x010AC72C..0x010AC79E; runtime 0x030AC72C; raw 0x000DBB2C; PDATA owner 0x010AC72C
010ac72c 862f mov.l r8,@-r15
010ac72e 962f mov.l r9,@-r15
010ac730 a62f mov.l r10,@-r15
010ac732 6368 mov r6,r8
010ac734 4366 mov r4,r6
010ac736 1e46 ldc r6,GBR
010ac738 1cc5 mov.w @(0x38,GBR),r0
010ac73a 0d6a extu.w r0,r10
010ac73c 1dc5 mov.w @(0x3a,GBR),r0
010ac73e 00e6 mov #0x0,r6
010ac740 00e4 mov #0x0,r4
010ac742 02a0 bra 0x10ac74a
010ac744 0d69 extu.w r0,r9
010ac746 0176 add #0x1,r6
010ac748 3475 add #0x34,r5
010ac74a 6738 cmp/gt r6,r8
010ac74c 228b bf 0x10ac794
010ac74e a367 mov r10,r7
010ac750 6b62 neg r6,r2
010ac752 0900 nop 
010ac754 2c47 shad r2,r7
010ac756 01e3 mov #0x1,r3
010ac758 3927 and r3,r7
010ac75a 10e0 mov #0x10,r0
010ac75c 5c30 add r5,r0
010ac75e 7c01 mov.b @(r0,r7),r1
010ac760 1c61 extu.b r1,r1
010ac762 0900 nop 
010ac764 9c43 shad r9,r3
010ac766 3821 tst r3,r1
010ac768 0489 bt 0x10ac774
010ac76a 01e1 mov #0x1,r1
010ac76c 0900 nop 
010ac76e 6c41 shad r6,r1
010ac770 0ea0 bra 0x10ac790
010ac772 1b24 or r1,r4
010ac774 5150 mov.l @(0x4,r5),r0
010ac776 1940 shlr8 r0
010ac778 03c9 and #0x3,r0
010ac77a 01e2 mov #0x1,r2
010ac77c 0177 add #0x1,r7
010ac77e 2927 and r2,r7
010ac780 0900 nop 
010ac782 7c42 shad r7,r2
010ac784 2820 tst r2,r0
010ac786 de8b bf 0x10ac746
010ac788 01e3 mov #0x1,r3
010ac78a 0900 nop 
010ac78c 6c43 shad r6,r3
010ac78e 3b24 or r3,r4
010ac790 d9af bra 0x10ac746
010ac792 0900 nop 
010ac794 4360 mov r4,r0
010ac796 f66a mov.l @r15+,r10
010ac798 f669 mov.l @r15+,r9
010ac79a 0b00 rts 
010ac79c f668 mov.l @r15+,r8

## C1F0
### 0x0108C1F0..0x0108C220; runtime 0x0308C1F0; raw 0x000BB5F0; PDATA owner 0x0108C1F0
0108c1f0 862f mov.l r8,@-r15
0108c1f2 962f mov.l r9,@-r15
0108c1f4 224f sts.l PR,@-r15
0108c1f6 4368 mov r4,r8
0108c1f8 6369 mov r6,r9
0108c1fa f07f add #-0x10,r15
0108c1fc 09d0 mov.l 0x108c224,r0 ; [0108c224]=0101efe4
0108c1fe 5364 mov r5,r4
0108c200 0b40 jsr @r0
0108c202 8365 mov r8,r5
0108c204 0c60 extu.b r0,r0
0108c206 1078 add #0x10,r8
0108c208 8c01 mov.b @(r0,r8),r1
0108c20a 1c64 extu.b r1,r4
0108c20c 01e2 mov #0x1,r2
0108c20e 0900 nop 
0108c210 9c42 shad r9,r2
0108c212 2824 tst r2,r4
0108c214 018f bf/s 0x108c21a
0108c216 ffe0 mov #-0x1,r0
0108c218 00e0 mov #0x0,r0
0108c21a 107f add #0x10,r15
0108c21c 264f lds.l @r15+,PR
0108c21e f669 mov.l @r15+,r9

## AB6F0_context
### 0x010AB6F0..0x010AB770; runtime 0x030AB6F0; raw 0x000DAAF0; PDATA owner 0x010AB4D0
010ab6f0 1821 tst r1,r1
010ab6f2 138b bf 0x10ab71c
010ab6f4 7ad4 mov.l 0x10ab8e0,r4 ; [010ab8e0]=010f6f00
010ab6f6 4260 mov.l @r4,r0
010ab6f8 ffe4 mov #-0x1,r4
010ab6fa 0388 cmp/eq #0x3,r0
010ab6fc 4a64 negc r4,r4
010ab6fe 4824 tst r4,r4
010ab700 1189 bt 0x10ab726
010ab702 b365 mov r11,r5
010ab704 a366 mov r10,r6
010ab706 e9b1 bsr 0x10abadc
010ab708 9364 mov r9,r4
010ab70a 75d2 mov.l 0x10ab8e0,r2 ; [010ab8e0]=010f6f00
010ab70c 0c3d add r0,r13
010ab70e 2260 mov.l @r2,r0
010ab710 07a0 bra 0x10ab722
010ab712 0388 cmp/eq #0x3,r0
010ab714 72d4 mov.l 0x10ab8e0,r4 ; [010ab8e0]=010f6f00
010ab716 4260 mov.l @r4,r0
010ab718 03a0 bra 0x10ab722
010ab71a 0388 cmp/eq #0x3,r0
010ab71c 70d4 mov.l 0x10ab8e0,r4 ; [010ab8e0]=010f6f00
010ab71e 4260 mov.l @r4,r0
010ab720 0388 cmp/eq #0x3,r0
010ab722 ffe4 mov #-0x1,r4
010ab724 4a64 negc r4,r4
010ab726 4824 tst r4,r4
010ab728 0789 bt 0x10ab73a
010ab72a c9b1 bsr 0x10abac0
010ab72c b364 mov r11,r4
010ab72e 64e5 mov #0x64,r5
010ab730 d700 mul.l r13,r0
010ab732 63d0 mov.l 0x10ab8c0,r0 ; [010ab8c0]=00ff8838
010ab734 0b40 jsr @r0
010ab736 1a04 sts MACL,r4
010ab738 036d mov r0,r13
010ab73a fe53 mov.l @(0x38,r15),r3
010ab73c 3823 tst r3,r3
010ab73e 0089 bt 0x10ab742
010ab740 647d add #0x64,r13
010ab742 9952 mov.l @(0x24,r9),r2
010ab744 dc32 add r13,r2
010ab746 c82c tst r12,r12
010ab748 028d bt/s 0x10ab750
010ab74a 271f mov.l r2,@(0x1c,r15)
010ab74c 1fa1 bra 0x10ab98e
010ab74e 0900 nop 
010ab750 50e0 mov #0x50,r0
010ab752 62d1 mov.l 0x10ab8dc,r1 ; [010ab8dc]=010f7640
010ab754 1e02 mov.l @(r0,r1),r2
010ab756 0172 add #0x1,r2
010ab758 2601 mov.l r2,@(r0,r1)
010ab75a fe53 mov.l @(0x38,r15),r3
010ab75c 3823 tst r3,r3
010ab75e 0489 bt 0x10ab76a
010ab760 54e0 mov #0x54,r0
010ab762 5ed2 mov.l 0x10ab8dc,r2 ; [010ab8dc]=010f7640
010ab764 2e03 mov.l @(r0,r2),r3
010ab766 0173 add #0x1,r3
010ab768 3602 mov.l r3,@(r0,r2)
010ab76a 3db4 bsr 0x10abfe8
010ab76c b364 mov r11,r4
010ab76e 0820 tst r0,r0

## AC3BC_context
### 0x010AC3BC..0x010AC410; runtime 0x030AC3BC; raw 0x000DB7BC; PDATA owner 0x010AC04C
010ac3bc 5667 mov.l @r5+,r7
010ac3be 1e49 ldc r9,GBR
010ac3c0 5666 mov.l @r5+,r6
010ac3c2 7319 mov.l r7,@(0xc,r9)
010ac3c4 6419 mov.l r6,@(0x10,r9)
010ac3c6 5265 mov.l @r5,r5
010ac3c8 5519 mov.l r5,@(0x14,r9)
010ac3ca c263 mov.l @r12,r3
010ac3cc 3229 mov.l r3,@r9
010ac3ce c151 mov.l @(0x4,r12),r1
010ac3d0 1c19 mov.l r1,@(0x30,r9)
010ac3d2 0fe1 mov #0xf,r1
010ac3d4 fa50 mov.l @(0x28,r15),r0
010ac3d6 1dc1 mov.w r0,@(0x3a,GBR)
010ac3d8 3ce0 mov #0x3c,r0
010ac3da 4509 mov.w r4,@(r0,r9)
010ac3dc c156 mov.l @(0x4,r12),r6
010ac3de 0146 shlr r6
010ac3e0 1800 sett 
010ac3e2 0946 shlr2 r6
010ac3e4 128f bf/s 0x10ac40c
010ac3e6 1926 and r1,r6
010ac3e8 0be3 mov #0xb,r3
010ac3ea 6633 cmp/hi r6,r3
010ac3ec 248b bf 0x10ac438
010ac3ee c257 mov.l @(0x8,r12),r7
010ac3f0 1547 cmp/pl r7
010ac3f2 228b bf 0x10ac43a
010ac3f4 06d3 mov.l 0x10ac410,r3 ; [010ac410]=01000000
010ac3f6 7733 cmp/gt r7,r3
010ac3f8 1f8b bf 0x10ac43a
010ac3fa 48e4 mov #0x48,r4
010ac3fc 9c34 add r9,r4
010ac3fe 2846 shll16 r6
010ac400 1846 shll8 r6
010ac402 6224 mov.l r6,@r4
010ac404 c251 mov.l @(0x8,r12),r1
010ac406 1b26 or r1,r6
010ac408 20a0 bra 0x10ac44c
010ac40a 6224 mov.l r6,@r4
010ac40c 14a0 bra 0x10ac438
010ac40e 0900 nop 
### 0x010AC438..0x010AC45C; runtime 0x030AC438; raw 0x000DB838; PDATA owner 0x010AC04C
010ac438 c257 mov.l @(0x8,r12),r7
010ac43a 4bd0 mov.l 0x10ac568,r0 ; [010ac568]=010105e4
010ac43c 47d4 mov.l 0x10ac55c,r4 ; [010ac55c]=010d3f2c
010ac43e 0b40 jsr @r0
010ac440 c265 mov.l @r12,r5
010ac442 45d0 mov.l 0x10ac558,r0 ; [010ac558]=0100a868
010ac444 47d4 mov.l 0x10ac564,r4 ; [010ac564]=010d3d58
010ac446 9395 mov.w 0x10ac570,r5
010ac448 0b40 jsr @r0
010ac44a 0900 nop 
010ac44c c150 mov.l @(0x4,r12),r0
010ac44e 0140 shlr r0
010ac450 0940 shlr2 r0
010ac452 0fc9 and #0xf,r0
010ac454 0a88 cmp/eq #0xa,r0
010ac456 038b bf 0x10ac460
010ac458 9a52 mov.l @(0x28,r9),r2
010ac45a 7a93 mov.w 0x10ac552,r3

## AC5AC
### 0x010AC5AC..0x010AC610; runtime 0x030AC5AC; raw 0x000DB9AC; PDATA owner 0x010AC5AC
010ac5ac 862f mov.l r8,@-r15
010ac5ae 224f sts.l PR,@-r15
010ac5b0 bc7f add #-0x44,r15
010ac5b2 00e7 mov #0x0,r7
010ac5b4 02a0 bra 0x10ac5bc
010ac5b6 00e8 mov #0x0,r8
010ac5b8 0177 add #0x1,r7
010ac5ba 3475 add #0x34,r5
010ac5bc 7736 cmp/gt r7,r6
010ac5be 088b bf 0x10ac5d2
010ac5c0 5653 mov.l @(0x18,r5),r3
010ac5c2 4151 mov.l @(0x4,r4),r1
010ac5c4 1033 cmp/eq r1,r3
010ac5c6 f78b bf 0x10ac5b8
010ac5c8 01e3 mov #0x1,r3
010ac5ca 0900 nop 
010ac5cc 7c43 shad r7,r3
010ac5ce f3af bra 0x10ac5b8
010ac5d0 3b28 or r3,r8
010ac5d2 38e0 mov #0x38,r0
010ac5d4 38d3 mov.l 0x10ac6b8,r3 ; [010ac6b8]=010f6d00
010ac5d6 01e1 mov #0x1,r1
010ac5d8 8504 mov.w r8,@(r0,r4)
010ac5da 1e43 ldc r3,GBR
010ac5dc 14c6 mov.l @(0x50,GBR),r0
010ac5de 1730 cmp/gt r1,r0
010ac5e0 108b bf 0x10ac604
010ac5e2 10e5 mov #0x10,r5
010ac5e4 35d0 mov.l 0x10ac6bc,r0 ; [010ac6bc]=00ffb7ec
010ac5e6 4154 mov.l @(0x4,r4),r4
010ac5e8 0b40 jsr @r0
010ac5ea fc35 add r15,r5
010ac5ec 10e3 mov #0x10,r3
010ac5ee fc33 add r15,r3
010ac5f0 12e0 mov #0x12,r0
010ac5f2 3c03 mov.b @(r0,r3),r3
010ac5f4 3c64 extu.b r3,r4
010ac5f6 8034 cmp/eq r8,r4
010ac5f8 0489 bt 0x10ac604
010ac5fa 2cd0 mov.l 0x10ac6ac,r0 ; [010ac6ac]=0100a868
010ac5fc 30d4 mov.l 0x10ac6c0,r4 ; [010ac6c0]=010d3d58
010ac5fe 5495 mov.w 0x10ac6aa,r5
010ac600 0b40 jsr @r0
010ac602 0900 nop 
010ac604 00e0 mov #0x0,r0
010ac606 447f add #0x44,r15
010ac608 264f lds.l @r15+,PR
010ac60a 0b00 rts 
010ac60c f668 mov.l @r15+,r8
010ac60e 0900 nop 

## AC610_executable_slices
### 0x010AC610..0x010AC6AC; runtime 0x030AC610; raw 0x000DBA10; PDATA owner 0x010AC610
010ac610 862f mov.l r8,@-r15
010ac612 962f mov.l r9,@-r15
010ac614 a62f mov.l r10,@-r15
010ac616 b62f mov.l r11,@-r15
010ac618 c62f mov.l r12,@-r15
010ac61a d62f mov.l r13,@-r15
010ac61c 224f sts.l PR,@-r15
010ac61e 691f mov.l r6,@(0x24,r15)
010ac620 4368 mov r4,r8
010ac622 536d mov r5,r13
010ac624 736c mov r7,r12
010ac626 e47f add #-0x1c,r15
010ac628 03a0 bra 0x10ac632
010ac62a 00eb mov #0x0,r11
010ac62c 017b add #0x1,r11
010ac62e 347d add #0x34,r13
010ac630 347c add #0x34,r12
010ac632 40e0 mov #0x40,r0
010ac634 fe02 mov.l @(r0,r15),r2
010ac636 b732 cmp/gt r11,r2
010ac638 5c8b bf 0x10ac6f4
010ac63a 8751 mov.l @(0x1c,r8),r1
010ac63c d252 mov.l @(0x8,r13),r2
010ac63e 2031 cmp/eq r2,r1
010ac640 f48b bf 0x10ac62c
010ac642 8651 mov.l @(0x18,r8),r1
010ac644 d152 mov.l @(0x4,r13),r2
010ac646 2031 cmp/eq r2,r1
010ac648 f08b bf 0x10ac62c
010ac64a 20e0 mov #0x20,r0
010ac64c 8d01 mov.w @(r0,r8),r1
010ac64e d685 mov.w @(0xc,r13),r0
010ac650 0031 cmp/eq r0,r1
010ac652 eb8b bf 0x10ac62c
010ac654 16d0 mov.l 0x10ac6b0,r0 ; [010ac6b0]=01016684
010ac656 0b40 jsr @r0
010ac658 c154 mov.l @(0x4,r12),r4
010ac65a 0365 mov r0,r5
010ac65c 15d0 mov.l 0x10ac6b4,r0 ; [010ac6b4]=00ff8910
010ac65e 0b40 jsr @r0
010ac660 c254 mov.l @(0x8,r12),r4
010ac662 b369 mov r11,r9
010ac664 03a0 bra 0x10ac66e
010ac666 036a mov r0,r10
010ac668 0179 add #0x1,r9
010ac66a 347d add #0x34,r13
010ac66c 347c add #0x34,r12
010ac66e 40e0 mov #0x40,r0
010ac670 fe02 mov.l @(r0,r15),r2
010ac672 9732 cmp/gt r9,r2
010ac674 278b bf 0x10ac6c6
010ac676 8751 mov.l @(0x1c,r8),r1
010ac678 d252 mov.l @(0x8,r13),r2
010ac67a 2031 cmp/eq r2,r1
010ac67c f48b bf 0x10ac668
010ac67e 8651 mov.l @(0x18,r8),r1
010ac680 d152 mov.l @(0x4,r13),r2
010ac682 2031 cmp/eq r2,r1
010ac684 f08b bf 0x10ac668
010ac686 20e0 mov #0x20,r0
010ac688 8d01 mov.w @(r0,r8),r1
010ac68a d685 mov.w @(0xc,r13),r0
010ac68c 0031 cmp/eq r0,r1
010ac68e eb8b bf 0x10ac668
010ac690 07d0 mov.l 0x10ac6b0,r0 ; [010ac6b0]=01016684
010ac692 0b40 jsr @r0
010ac694 c154 mov.l @(0x4,r12),r4
010ac696 0365 mov r0,r5
010ac698 06d0 mov.l 0x10ac6b4,r0 ; [010ac6b4]=00ff8910
010ac69a 0b40 jsr @r0
010ac69c c254 mov.l @(0x8,r12),r4
010ac69e 0364 mov r0,r4
010ac6a0 473a cmp/gt r4,r10
010ac6a2 e18b bf 0x10ac668
010ac6a4 936b mov r9,r11
010ac6a6 dfaf bra 0x10ac668
010ac6a8 436a mov r4,r10
010ac6aa fe06 mov.l @(r0,r15),r6
### 0x010AC6C6..0x010AC72C; runtime 0x030AC6C6; raw 0x000DBAC6; PDATA owner 0x010AC610
010ac6c6 3ae0 mov #0x3a,r0
010ac6c8 b508 mov.w r11,@(r0,r8)
010ac6ca bb62 neg r11,r2
010ac6cc 1e48 ldc r8,GBR
010ac6ce 1cc5 mov.w @(0x38,GBR),r0
010ac6d0 0d60 extu.w r0,r0
010ac6d2 0900 nop 
010ac6d4 2c40 shad r2,r0
010ac6d6 8792 mov.w 0x10ac7e8,r2
010ac6d8 01c9 and #0x1,r0
010ac6da 1ec1 mov.w r0,@(0x3c,GBR)
010ac6dc 44e4 mov #0x44,r4
010ac6de b363 mov r11,r3
010ac6e0 8c34 add r8,r4
010ac6e2 4261 mov.l @r4,r1
010ac6e4 2921 and r2,r1
010ac6e6 0ce2 mov #0xc,r2
010ac6e8 2d43 shld r2,r3
010ac6ea 70e2 mov #0x70,r2
010ac6ec 1842 shll8 r2
010ac6ee 2923 and r2,r3
010ac6f0 3b21 or r3,r1
010ac6f2 1224 mov.l r1,@r4
010ac6f4 40e0 mov #0x40,r0
010ac6f6 fe01 mov.l @(r0,r15),r1
010ac6f8 103b cmp/eq r1,r11
010ac6fa 0c8b bf 0x10ac716
010ac6fc 8251 mov.l @(0x8,r8),r1
010ac6fe 141f mov.l r1,@(0x10,r15)
010ac700 8153 mov.l @(0x4,r8),r3
010ac702 351f mov.l r3,@(0x14,r15)
010ac704 35d1 mov.l 0x10ac7dc,r1 ; [010ac7dc]=010d73cc
010ac706 37d5 mov.l 0x10ac7e4,r5 ; [010ac7e4]=010d3d58
010ac708 1261 mov.l @r1,r1
010ac70a 6e96 mov.w 0x10ac7ea,r6
010ac70c 34d7 mov.l 0x10ac7e0,r7 ; [010ac7e0]=010d3f50
010ac70e 0b41 jsr @r1
010ac710 10e4 mov #0x10,r4
010ac712 01a0 bra 0x10ac718
010ac714 ffe0 mov #-0x1,r0
010ac716 00e0 mov #0x0,r0
010ac718 1c7f add #0x1c,r15
010ac71a 264f lds.l @r15+,PR
010ac71c f66d mov.l @r15+,r13
010ac71e f66c mov.l @r15+,r12
010ac720 f66b mov.l @r15+,r11
010ac722 f66a mov.l @r15+,r10
010ac724 f669 mov.l @r15+,r9
010ac726 0b00 rts 
010ac728 f668 mov.l @r15+,r8
010ac72a 0900 nop 

## AB4D0_CALL_AND_RETURN_TEST
### 0x010AB54C..0x010AB55E; runtime 0x030AB54C; raw 0x000DA94C; PDATA owner 0x010AB4D0
010ab54c 3cd6 mov.l 0x10ab640,r6 ; [010ab640]=010f6d60
010ab54e fc37 add r15,r7
010ab550 9364 mov r9,r4
010ab552 7bb5 bsr 0x10ac04c
010ab554 536b mov r5,r11
010ab556 ffe2 mov #-0x1,r2
010ab558 2030 cmp/eq r2,r0
010ab55a 0c8f bf/s 0x10ab576
010ab55c 061f mov.l r0,@(0x18,r15)

## AB4D0_RESULT_CONSUMER_98AE8
### 0x01099046..0x01099070; runtime 0x03099046; raw 0x000C8446; PDATA owner 0x01098AE8
01099046 3bd0 mov.l 0x1099134,r0 ; [01099134]=010ab4d0
01099048 f955 mov.l @(0x24,r15),r5
0109904a 0b40 jsr @r0
0109904c 9364 mov r9,r4
0109904e ffe3 mov #-0x1,r3
01099050 3030 cmp/eq r3,r0
01099052 058b bf 0x1099060
01099054 02e1 mov #0x2,r1
01099056 f752 mov.l @(0x1c,r15),r2
01099058 2263 mov.l @r2,r3
0109905a 1b23 or r1,r3
0109905c 7aa0 bra 0x1099154
0109905e 3222 mov.l r3,@r2
01099060 04e5 mov #0x4,r5
01099062 9364 mov r9,r4
01099064 e0b9 bsr 0x1098428
01099066 ec35 add r14,r5
01099068 0188 cmp/eq #0x1,r0
0109906a 188b bf 0x109909e
0109906c 34d2 mov.l 0x1099140,r2 ; [01099140]=010f77c0
0109906e 2154 mov.l @(0x4,r2),r4
### 0x01099220..0x01099248; runtime 0x03099220; raw 0x000C8620; PDATA owner 0x01098AE8
01099220 0364 mov r0,r4
01099222 4824 tst r4,r4
01099224 1e4e ldc r14,GBR
01099226 13c6 mov.l @(0x4c,GBR),r0
01099228 4220 mov.l r4,@r0
0109922a 018d bt/s 0x1099230
0109922c ffe4 mov #-0x1,r4
0109922e 00e4 mov #0x0,r4
01099230 4360 mov r4,r0
01099232 24e2 mov #0x24,r2
01099234 ec32 add r14,r2
01099236 2642 lds.l @r2+,PR
01099238 266d mov.l @r2+,r13
0109923a 266c mov.l @r2+,r12
0109923c 266b mov.l @r2+,r11
0109923e 266a mov.l @r2+,r10
01099240 2669 mov.l @r2+,r9
01099242 2668 mov.l @r2+,r8
01099244 236f mov r2,r15
01099246 0b00 rts 

## 98AE8_RESULT_CONSUMER_718AC
### 0x01071958..0x01071974; runtime 0x03071958; raw 0x000A0D58; PDATA owner 0x010718AC
01071958 1fd0 mov.l 0x10719d8,r0 ; [010719d8]=01098ae8
0107195a 10e6 mov #0x10,r6
0107195c 9364 mov r9,r4
0107195e b365 mov r11,r5
01071960 0b40 jsr @r0
01071962 fc36 add r15,r6
01071964 f453 mov.l @(0x10,r15),r3
01071966 0369 mov r0,r9
01071968 04e1 mov #0x4,r1
0107196a 1039 cmp/eq r1,r9
0107196c 028f bf/s 0x1071974
0107196e 3228 mov.l r3,@r8
01071970 27a0 bra 0x10719c2
01071972 9360 mov r9,r0
### 0x010719C0..0x010719CE; runtime 0x030719C0; raw 0x000A0DC0; PDATA owner 0x010718AC
010719c0 9360 mov r9,r0
010719c2 147f add #0x14,r15
010719c4 264f lds.l @r15+,PR
010719c6 f66b mov.l @r15+,r11
010719c8 f66a mov.l @r15+,r10
010719ca f669 mov.l @r15+,r9
010719cc 0b00 rts 

## 718AC_RESULT_CONSUMER_6D104
### 0x0106D2B6..0x0106D2D8; runtime 0x0306D2B6; raw 0x0009C6B6; PDATA owner 0x0106D104
0106d2b6 71d0 mov.l 0x106d47c,r0 ; [0106d47c]=010718ac
0106d2b8 01e1 mov #0x1,r1
0106d2ba 122c mov.l r1,@r12
0106d2bc 10e7 mov #0x10,r7
0106d2be b365 mov r11,r5
0106d2c0 fc37 add r15,r7
0106d2c2 9366 mov r9,r6
0106d2c4 0b40 jsr @r0
0106d2c6 f754 mov.l @(0x1c,r15),r4
0106d2c8 0820 tst r0,r0
0106d2ca 00e2 mov #0x0,r2
0106d2cc 036b mov r0,r11
0106d2ce 3a8d bt/s 0x106d346
0106d2d0 222c mov.l r2,@r12
0106d2d2 04e1 mov #0x4,r1
0106d2d4 103b cmp/eq r1,r11
0106d2d6 088b bf 0x106d2ea
### 0x0106D3C4..0x0106D3DC; runtime 0x0306D3C4; raw 0x0009C7C4; PDATA owner 0x0106D104
0106d3c4 00e3 mov #0x0,r3
0106d3c6 3b1a mov.l r3,@(0x2c,r10)
0106d3c8 b360 mov r11,r0
0106d3ca 547f add #0x54,r15
0106d3cc 264f lds.l @r15+,PR
0106d3ce f66d mov.l @r15+,r13
0106d3d0 f66c mov.l @r15+,r12
0106d3d2 f66b mov.l @r15+,r11
0106d3d4 f66a mov.l @r15+,r10
0106d3d6 f669 mov.l @r15+,r9
0106d3d8 0b00 rts 
0106d3da f668 mov.l @r15+,r8

## 6D104_RESULT_CONSUMER_7AC78
### 0x0107AC96..0x0107ACA2; runtime 0x0307AC96; raw 0x000AA096; PDATA owner 0x0107AC78
0107ac96 aad0 mov.l 0x107af40,r0 ; [0107af40]=0106d104
0107ac98 0b40 jsr @r0
0107ac9a 8364 mov r8,r4
0107ac9c 0820 tst r0,r0
0107ac9e 198f bf/s 0x107acd4
0107aca0 036a mov r0,r10
### 0x0107ACD4..0x0107AD8C; runtime 0x0307ACD4; raw 0x000AA0D4; PDATA owner 0x0107AC78
0107acd4 8fd0 mov.l 0x107af14,r0 ; [0107af14]=00ff87d8
0107acd6 14e4 mov #0x14,r4
0107acd8 9dd9 mov.l 0x107af50,r9 ; [0107af50]=010f7988
0107acda 00e5 mov #0x0,r5
0107acdc 14e6 mov #0x14,r6
0107acde 0b40 jsr @r0
0107ace0 fc34 add r15,r4
0107ace2 5fe1 mov #0x5f,r1
0107ace4 0041 shll r1
0107ace6 24e0 mov #0x24,r0
0107ace8 140f mov.b r1,@(r0,r15)
0107acea 9262 mov.l @r9,r2
0107acec 2822 tst r2,r2
0107acee 0589 bt 0x107acfc
0107acf0 99d0 mov.l 0x107af58,r0 ; [0107af58]=0106d660
0107acf2 f9e1 mov #-0x7,r1
0107acf4 0b40 jsr @r0
0107acf6 151f mov.l r1,@(0x14,r15)
0107acf8 01a0 bra 0x107acfe
0107acfa 0900 nop 
0107acfc a51f mov.l r10,@(0x14,r15)
0107acfe 43e0 mov #0x43,r0
0107ad00 8c04 mov.b @(r0,r8),r4
0107ad02 1844 shll8 r4
0107ad04 1e48 ldc r8,GBR
0107ad06 42c4 mov.b @(0x42,GBR),r0
0107ad08 0c63 extu.b r0,r3
0107ad0a 41c4 mov.b @(0x41,GBR),r0
0107ad0c 0c61 extu.b r0,r1
0107ad0e 40c4 mov.b @(0x40,GBR),r0
0107ad10 3b24 or r3,r4
0107ad12 1e4f ldc r15,GBR
0107ad14 0c62 extu.b r0,r2
0107ad16 24c4 mov.b @(0x24,GBR),r0
0107ad18 0c63 extu.b r0,r3
0107ad1a 25c4 mov.b @(0x25,GBR),r0
0107ad1c 1844 shll8 r4
0107ad1e 1b24 or r1,r4
0107ad20 0c61 extu.b r0,r1
0107ad22 7fd0 mov.l 0x107af20,r0 ; [0107af20]=00ff89b0
0107ad24 1841 shll8 r1
0107ad26 1c33 add r1,r3
0107ad28 3d67 extu.w r3,r7
0107ad2a 01e3 mov #0x1,r3
0107ad2c 1844 shll8 r4
0107ad2e 2b24 or r2,r4
0107ad30 14e5 mov #0x14,r5
0107ad32 fc35 add r15,r5
0107ad34 00e6 mov #0x0,r6
0107ad36 0b40 jsr @r0
0107ad38 341f mov.l r3,@(0x10,r15)
0107ad3a 9261 mov.l @r9,r1
0107ad3c 1821 tst r1,r1
0107ad3e 1e8b bf 0x107ad7e
0107ad40 7bd0 mov.l 0x107af30,r0 ; [0107af30]=010b33fc
0107ad42 73d4 mov.l 0x107af10,r4 ; [0107af10]=010c978c
0107ad44 0b40 jsr @r0
0107ad46 0900 nop 
0107ad48 1e48 ldc r8,GBR
0107ad4a 31c4 mov.b @(0x31,GBR),r0
0107ad4c 0c63 extu.b r0,r3
0107ad4e 30c4 mov.b @(0x30,GBR),r0
0107ad50 1843 shll8 r3
0107ad52 0c61 extu.b r0,r1
0107ad54 1b23 or r1,r3
0107ad56 3f63 exts.w r3,r3
0107ad58 30e0 mov #0x30,r0
0107ad5a 01e2 mov #0x1,r2
0107ad5c 2b23 or r2,r3
0107ad5e 3408 mov.b r3,@(r0,r8)
0107ad60 1943 shlr8 r3
0107ad62 31e0 mov #0x31,r0
0107ad64 3408 mov.b r3,@(r0,r8)
0107ad66 00e3 mov #0x0,r3
0107ad68 2ce0 mov #0x2c,r0
0107ad6a 3408 mov.b r3,@(r0,r8)
0107ad6c 1943 shlr8 r3
0107ad6e 2de0 mov #0x2d,r0
0107ad70 3408 mov.b r3,@(r0,r8)
0107ad72 1943 shlr8 r3
0107ad74 2ee0 mov #0x2e,r0
0107ad76 3408 mov.b r3,@(r0,r8)
0107ad78 1943 shlr8 r3
0107ad7a 2fe0 mov #0x2f,r0
0107ad7c 3408 mov.b r3,@(r0,r8)
0107ad7e 00e0 mov #0x0,r0
0107ad80 287f add #0x28,r15
0107ad82 264f lds.l @r15+,PR
0107ad84 f66a mov.l @r15+,r10
0107ad86 f669 mov.l @r15+,r9
0107ad88 0b00 rts 
0107ad8a f668 mov.l @r15+,r8

## FCD8_COVER_CONVERTER
### 0x0101FCD8..0x0101FD40; runtime 0x0301FCD8; raw 0x0004F0D8; PDATA owner 0x0101FCD8
0101fcd8 862f mov.l r8,@-r15
0101fcda 962f mov.l r9,@-r15
0101fcdc a62f mov.l r10,@-r15
0101fcde b62f mov.l r11,@-r15
0101fce0 c62f mov.l r12,@-r15
0101fce2 d62f mov.l r13,@-r15
0101fce4 224f sts.l PR,@-r15
0101fce6 691f mov.l r6,@(0x24,r15)
0101fce8 436a mov r4,r10
0101fcea 536c mov r5,r12
0101fcec 7369 mov r7,r9
0101fcee fb58 mov.l @(0x2c,r15),r8
0101fcf0 ec7f add #-0x14,r15
0101fcf2 a82a tst r10,r10
0101fcf4 058f bf/s 0x101fd02
0101fcf6 8a5b mov.l @(0x28,r8),r11
0101fcf8 26d0 mov.l 0x101fd94,r0 ; [0101fd94]=0100a868
0101fcfa 27d4 mov.l 0x101fd98,r4 ; [0101fd98]=010c0e88
0101fcfc 4e95 mov.w 0x101fd9c,r5
0101fcfe 0b40 jsr @r0
0101fd00 0900 nop 
0101fd02 114c cmp/pz r12
0101fd04 038b bf 0x101fd0e
0101fd06 10e3 mov #0x10,r3
0101fd08 1843 shll8 r3
0101fd0a c733 cmp/gt r12,r3
0101fd0c 0489 bt 0x101fd18
0101fd0e 21d0 mov.l 0x101fd94,r0 ; [0101fd94]=0100a868
0101fd10 21d4 mov.l 0x101fd98,r4 ; [0101fd98]=010c0e88
0101fd12 4495 mov.w 0x101fd9e,r5
0101fd14 0b40 jsr @r0
0101fd16 0900 nop 
0101fd18 8b55 mov.l @(0x2c,r8),r5
0101fd1a f0e2 mov #-0x10,r2
0101fd1c 1842 shll8 r2
0101fd1e 2925 and r2,r5
0101fd20 cb25 or r12,r5
0101fd22 522a mov.l r5,@r10
0101fd24 084c shll2 r12
0101fd26 bd56 mov.l @(0x34,r11),r6
0101fd28 084c shll2 r12
0101fd2a cc36 add r12,r6
0101fd2c 6263 mov.l @r6,r3
0101fd2e 1e4a ldc r10,GBR
0101fd30 311a mov.l r3,@(0x4,r10)
0101fd32 6584 mov.b @(0x5,r6),r0
0101fd34 11c0 mov.b r0,@(0x11,GBR)
0101fd36 6484 mov.b @(0x4,r6),r0
0101fd38 10c0 mov.b r0,@(0x10,GBR)
0101fd3a fe50 mov.l @(0x38,r15),r0
0101fd3c 01c8 tst #0x1,r0
0101fd3e 3189 bt 0x101fda4
### 0x0101FD3A..0x0101FD80; runtime 0x0301FD3A; raw 0x0004F13A; PDATA owner 0x0101FCD8
0101fd3a fe50 mov.l @(0x38,r15),r0
0101fd3c 01c8 tst #0x1,r0
0101fd3e 3189 bt 0x101fda4
0101fd40 a150 mov.l @(0x4,r10),r0
0101fd42 f4e1 mov #-0xc,r1
0101fd44 1d40 shld r1,r0
0101fd46 01c9 and #0x1,r0
0101fd48 0188 cmp/eq #0x1,r0
0101fd4a 0e89 bt 0x101fd6a
0101fd4c 6385 mov.w @(0x6,r6),r0
0101fd4e f0e3 mov #-0x10,r3
0101fd50 1843 shll8 r3
0101fd52 3925 and r3,r5
0101fd54 0d61 extu.w r0,r1
0101fd56 1b25 or r1,r5
0101fd58 551a mov.l r5,@(0x14,r10)
0101fd5a 0ce3 mov #0xc,r3
0101fd5c 6385 mov.w @(0x6,r6),r0
0101fd5e 0d62 extu.w r0,r2
0101fd60 b754 mov.l @(0x1c,r11),r4
0101fd62 2703 mul.l r2,r3
0101fd64 1a01 sts MACL,r1
0101fd66 09a0 bra 0x101fd7c
0101fd68 1c34 add r1,r4
0101fd6a fee3 mov #-0x2,r3
0101fd6c 351a mov.l r3,@(0x14,r10)
0101fd6e 0ce2 mov #0xc,r2
0101fd70 6385 mov.w @(0x6,r6),r0
0101fd72 0d61 extu.w r0,r1
0101fd74 b954 mov.l @(0x24,r11),r4
0101fd76 1702 mul.l r1,r2
0101fd78 1a03 sts MACL,r3
0101fd7a 3c34 add r3,r4
0101fd7c 4367 mov r4,r7
0101fd7e 40e1 mov #0x40,r1
### 0x0101FDC2..0x0101FDE0; runtime 0x0301FDC2; raw 0x0004F1C2; PDATA owner 0x0101FCD8
0101fdc2 fe50 mov.l @(0x38,r15),r0
0101fdc4 02c8 tst #0x2,r0
0101fdc6 1f89 bt 0x101fe08
0101fdc8 f3e3 mov #-0xd,r3
0101fdca a150 mov.l @(0x4,r10),r0
0101fdcc 3d40 shld r3,r0
0101fdce 01c9 and #0x1,r0
0101fdd0 0188 cmp/eq #0x1,r0
0101fdd2 0e89 bt 0x101fdf2
0101fdd4 f0e2 mov #-0x10,r2
0101fdd6 6485 mov.w @(0x8,r6),r0
0101fdd8 1842 shll8 r2
0101fdda 2925 and r2,r5
0101fddc 0d63 extu.w r0,r3
0101fdde 3b25 or r3,r5

## STRIDE_58_CALL_SETUP
### 0x01099360..0x0109937A; runtime 0x03099360; raw 0x000C8760; PDATA owner 0x01099288
01099360 3eb1 bsr 0x10995e0
01099362 c364 mov r12,r4
01099364 50b2 bsr 0x1099808
01099366 b364 mov r11,r4
01099368 76b2 bsr 0x1099858
0109936a a364 mov r10,r4
0109936c 7ad0 mov.l 0x1099558,r0 ; [01099558]=010aa0f8
0109936e 0b40 jsr @r0
01099370 0900 nop 
01099372 78d0 mov.l 0x1099554,r0 ; [01099554]=01071dfc
01099374 0b40 jsr @r0
01099376 0900 nop 
01099378 64d2 mov.l 0x109950c,r2 ; [0109950c]=7fffffff
### 0x010995E0..0x01099620; runtime 0x030995E0; raw 0x000C89E0; PDATA owner 0x010995E0
010995e0 862f mov.l r8,@-r15
010995e2 224f sts.l PR,@-r15
010995e4 4368 mov r4,r8
010995e6 f07f add #-0x10,r15
010995e8 75d4 mov.l 0x10997c0,r4 ; [010997c0]=010f6d00
010995ea 4474 add #0x44,r4
010995ec 4265 mov.l @r4,r5
010995ee 5825 tst r5,r5
010995f0 0b89 bt 0x109960a
010995f2 0ce4 mov #0xc,r4
010995f4 6dd0 mov.l 0x10997ac,r0 ; [010997ac]=00ff87cc
010995f6 20e6 mov #0x20,r6
010995f8 0b40 jsr @r0
010995fa 8c34 add r8,r4
010995fc 6bd0 mov.l 0x10997ac,r0 ; [010997ac]=00ff87cc
010995fe 64e4 mov #0x64,r4
01099600 0ce5 mov #0xc,r5
01099602 8c35 add r8,r5
01099604 20e6 mov #0x20,r6
01099606 0b40 jsr @r0
01099608 8c34 add r8,r4
0109960a 6cd2 mov.l 0x10997bc,r2 ; [010997bc]=010f6bf0
0109960c 2062 mov.b @r2,r2
0109960e 2822 tst r2,r2
01099610 018b bf 0x1099616
01099612 f7be bsr 0x1099404
01099614 8364 mov r8,r4
01099616 00e0 mov #0x0,r0
01099618 107f add #0x10,r15
0109961a 264f lds.l @r15+,PR
0109961c 0b00 rts 
0109961e f668 mov.l @r15+,r8

## STRIDE_58_WRITERS
### 0x01099404..0x01099424; runtime 0x03099404; raw 0x000C8804; PDATA owner 0x01099404
01099404 862f mov.l r8,@-r15
01099406 45d5 mov.l 0x109951c,r5 ; [0109951c]=010f77c0
01099408 5265 mov.l @r5,r5
0109940a 5360 mov r5,r0
0109940c 01c8 tst #0x1,r0
0109940e 058b bf 0x109941c
01099410 40e1 mov #0x40,r1
01099412 0841 shll2 r1
01099414 1825 tst r1,r5
01099416 018b bf 0x109941c
01099418 38a0 bra 0x109948c
0109941a 00e0 mov #0x0,r0
0109941c 01a0 bra 0x1099422
0109941e 00e5 mov #0x0,r5
01099420 0175 add #0x1,r5
01099422 08e2 mov #0x8,r2
### 0x01099468..0x01099476; runtime 0x03099468; raw 0x000C8868; PDATA owner 0x01099404
01099468 0589 bt 0x1099476
0109946a 01e1 mov #0x1,r1
0109946c 4153 mov.l @(0x4,r4),r3
0109946e 0900 nop 
01099470 5c41 shad r5,r1
01099472 1b23 or r1,r3
01099474 3114 mov.l r3,@(0x4,r4)
### 0x01099480..0x01099490; runtime 0x03099480; raw 0x000C8880; PDATA owner 0x01099404
01099480 0900 nop 
01099482 5c42 shad r5,r2
01099484 2b21 or r2,r1
01099486 cbaf bra 0x1099420
01099488 1116 mov.l r1,@(0x4,r6)
0109948a 00e0 mov #0x0,r0
0109948c 0b00 rts 
0109948e f668 mov.l @r15+,r8
### 0x010997CC..0x01099808; runtime 0x030997CC; raw 0x000C8BCC; PDATA owner 0x010997CC
010997cc 862f mov.l r8,@-r15
010997ce 224f sts.l PR,@-r15
010997d0 bc7f add #-0x44,r15
010997d2 6dd0 mov.l 0x1099988,r0 ; [01099988]=00ffb92c
010997d4 5264 mov.l @r5,r4
010997d6 10e5 mov #0x10,r5
010997d8 70d8 mov.l 0x109999c,r8 ; [0109999c]=010f7880
010997da 0b40 jsr @r0
010997dc fc35 add r15,r5
010997de f550 mov.l @(0x14,r15),r0
010997e0 07c9 and #0x7,r0
010997e2 00e4 mov #0x0,r4
010997e4 01a0 bra 0x10997ea
010997e6 0365 mov r0,r5
010997e8 0174 add #0x1,r4
010997ea 4735 cmp/gt r4,r5
010997ec 068b bf 0x10997fc
010997ee 01e3 mov #0x1,r3
010997f0 8152 mov.l @(0x4,r8),r2
010997f2 0900 nop 
010997f4 4c43 shad r4,r3
010997f6 3b22 or r3,r2
010997f8 f6af bra 0x10997e8
010997fa 2118 mov.l r2,@(0x4,r8)
010997fc 00e0 mov #0x0,r0
010997fe 447f add #0x44,r15
01099800 264f lds.l @r15+,PR
01099802 0b00 rts 
01099804 f668 mov.l @r15+,r8
01099806 0900 nop 

## SECTION5_ADJACENCY_COPY
### 0x0106886C..0x01068882; runtime 0x0306886C; raw 0x00097C6C; PDATA owner 0x0106886C
0106886c 5261 mov.l @r5,r1
0106886e f0e2 mov #-0x10,r2
01068870 1114 mov.l r1,@(0x4,r4)
01068872 1842 shll8 r2
01068874 5584 mov.b @(0x5,r5),r0
01068876 7f67 exts.w r7,r7
01068878 1e44 ldc r4,GBR
0106887a 6f66 exts.w r6,r6
0106887c 11c0 mov.b r0,@(0x11,GBR)
0106887e 5484 mov.b @(0x4,r5),r0
01068880 10c0 mov.b r0,@(0x10,GBR)

## SECTION5_EXPANSION_ENTRY
### 0x0104D8A0..0x0104D8C0; runtime 0x0304D8A0; raw 0x0007CCA0; PDATA owner 0x0104D8A0
0104d8a0 862f mov.l r8,@-r15
0104d8a2 962f mov.l r9,@-r15
0104d8a4 a62f mov.l r10,@-r15
0104d8a6 224f sts.l PR,@-r15
0104d8a8 4368 mov r4,r8
0104d8aa 536a mov r5,r10
0104d8ac 6369 mov r6,r9
0104d8ae f07f add #-0x10,r15
0104d8b0 8828 tst r8,r8
0104d8b2 048b bf 0x104d8be
0104d8b4 1fd0 mov.l 0x104d934,r0 ; [0104d934]=0100a868
0104d8b6 21d4 mov.l 0x104d93c,r4 ; [0104d93c]=010c539c
0104d8b8 4295 mov.w 0x104d940,r5
0104d8ba 0b40 jsr @r0
0104d8bc 0900 nop 
0104d8be 9829 tst r9,r9

## Literal values
0x010AC6B8 raw=006d0f01 value=0x010F6D00
0x010AC6BC raw=ecb7ff00 value=0x00FFB7EC
0x010AC7E8 raw=ff8f value=0x8FFF
0x010AB614 raw=00800000 value=0x00008000
0x010AB634 raw=40760f01 value=0x010F7640
0x010AB640 raw=606d0f01 value=0x010F6D60
0x010AB644 raw=a0c70a01 value=0x010AC7A0
0x0108C224 raw=e4ef0101 value=0x0101EFE4
