K:\siemens\src\db\db_read.c
030129b8  mov.l    r8,@-r15
030129ba  mov.l    r9,@-r15
030129bc  mov.l    r10,@-r15
030129be  sts.l    PR,@-r15
030129c0  mov      r4,r8
030129c2  mov      r5,r10
030129c4  mov      r6,r9
030129c6  mov.w    0x3012a34,r1
030129c8  sub      r1,r15
030129ca  mov.l    0x3012a20,r0
030129cc  jsr      @r0
030129ce  nop      
030129d0  tst      r10,r10
030129d2  bf       0x30129de
030129d4  mov.l    0x3012a1c,r0
030129d6  mov.l    0x3012a2c,r4
030129d8  mov.w    0x3012a36,r5
030129da  jsr      @r0
030129dc  nop      
030129de  mov      #0x14,r6
030129e0  mov.l    0x3012a28,r0
030129e2  mov      #0x57,r7
030129e4  mov.l    r9,@(0x10,r15)
030129e6  shll     r7
030129e8  mov      r8,r4
030129ea  mov      #0x2,r5
030129ec  jsr      @r0
030129ee  add      r15,r6
030129f0  tst      r0,r0
030129f2  bt       0x30129fe
030129f4  mov.l    0x3012a24,r0
030129f6  jsr      @r0
030129f8  nop      
030129fa  bra      0x3012a0e
030129fc  mov      #-0x1,r0
030129fe  mov      #0x14,r5
03012a00  mov      r10,r4
03012a02  bsr      0x3012a3c
03012a04  add      r15,r5
03012a06  mov.l    0x3012a24,r0
03012a08  jsr      @r0
03012a0a  nop      
03012a0c  mov      #0x0,r0
03012a0e  mov.w    0x3012a34,r2
03012a10  add      r2,r15
03012a12  lds.l    @r15+,PR
03012a14  mov.l    @r15+,r10
03012a16  mov.l    @r15+,r9
03012a18  rts      
03012a1a  mov.l    @r15+,r8
