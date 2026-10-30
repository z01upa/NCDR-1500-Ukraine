K:\siemens\src\db\db_upack.c
0304d848  mov.l    r8,@-r15
0304d84a  mov.l    r9,@-r15
0304d84c  mov.l    r10,@-r15
0304d84e  mov.l    r11,@-r15
0304d850  sts.l    PR,@-r15
0304d852  mov      r4,r8
0304d854  mov      r5,r11
0304d856  mov      r6,r10
0304d858  add      #-0x10,r15
0304d85a  tst      r8,r8
0304d85c  bf       0x304d868
0304d85e  mov.l    0x304d934,r0
0304d860  mov.l    0x304d93c,r4
0304d862  mov.w    0x304d946,r5
0304d864  jsr      @r0
0304d866  nop      
0304d868  tst      r10,r10
0304d86a  bf       0x304d876
0304d86c  mov.l    0x304d934,r0
0304d86e  mov.l    0x304d93c,r4
0304d870  mov.w    0x304d948,r5
0304d872  jsr      @r0
0304d874  nop      
0304d876  bra      0x304d87c
0304d878  mov      #0x0,r9
0304d87a  add      #0x1,r9
0304d87c  cmp/gt   r9,r11
0304d87e  bf       0x304d890
0304d880  mov.l    0x304d938,r0
0304d882  mov      r10,r5
0304d884  mov      #0xa,r6
0304d886  jsr      @r0
0304d888  mov      r8,r4
0304d88a  add      #0xa,r10
0304d88c  bra      0x304d87a
0304d88e  add      #0xa,r8
0304d890  add      #0x10,r15
0304d892  lds.l    @r15+,PR
0304d894  mov.l    @r15+,r11
0304d896  mov.l    @r15+,r10
0304d898  mov.l    @r15+,r9
0304d89a  rts      
0304d89c  mov.l    @r15+,r8
