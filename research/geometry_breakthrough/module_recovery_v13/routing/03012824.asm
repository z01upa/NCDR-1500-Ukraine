K:\siemens\src\db\db_read.c
03012824  mov.l    r8,@-r15
03012826  mov.l    r9,@-r15
03012828  mov.l    r10,@-r15
0301282a  sts.l    PR,@-r15
0301282c  mov      r4,r8
0301282e  mov      r5,r10
03012830  mov      r6,r9
03012832  mov.w    0x301288c,r1
03012834  sub      r1,r15
03012836  mov.l    0x3012870,r0
03012838  jsr      @r0
0301283a  nop      
0301283c  tst      r10,r10
0301283e  bf       0x301284a
03012840  mov.l    0x3012874,r0
03012842  mov      #0x52,r5
03012844  mov.l    0x3012880,r4
03012846  jsr      @r0
03012848  shll2    r5
0301284a  mov      #0x14,r6
0301284c  mov.l    0x301287c,r0
0301284e  mov      r8,r4
03012850  mov.l    r9,@(0x10,r15)
03012852  mov      #0x1,r5
03012854  mov      #0x72,r7
03012856  jsr      @r0
03012858  add      r15,r6
0301285a  tst      r0,r0
0301285c  bt       0x301288e
0301285e  mov.l    0x3012878,r0
03012860  jsr      @r0
03012862  nop      
03012864  bra      0x301289e
03012866  mov      #-0x1,r0
0301288e  mov      #0x14,r5
03012890  mov      r10,r4
03012892  bsr      0x30128ac
03012894  add      r15,r5
03012896  mov.l    0x3012a24,r0
03012898  jsr      @r0
0301289a  nop      
0301289c  mov      #0x0,r0
0301289e  mov.w    0x3012a38,r2
030128a0  add      r2,r15
030128a2  lds.l    @r15+,PR
030128a4  mov.l    @r15+,r10
030128a6  mov.l    @r15+,r9
030128a8  rts      
030128aa  mov.l    @r15+,r8
