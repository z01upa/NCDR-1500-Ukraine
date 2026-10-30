K:\siemens\src\db\db_read.c
0301271c  mov.l    r8,@-r15
0301271e  mov.l    r9,@-r15
03012720  mov.l    r10,@-r15
03012722  sts.l    PR,@-r15
03012724  mov      r4,r8
03012726  mov      r5,r10
03012728  mov      r6,r9
0301272a  add      #-0x4c,r15
0301272c  mov.l    0x3012870,r0
0301272e  jsr      @r0
03012730  nop      
03012732  tst      r10,r10
03012734  bf       0x3012740
03012736  mov.l    0x3012874,r0
03012738  mov.l    0x3012880,r4
0301273a  mov.w    0x3012888,r5
0301273c  jsr      @r0
0301273e  nop      
03012740  mov.l    0x3012868,r2
03012742  mov.l    @r2,r2
03012744  tst      r2,r2
03012746  bt       0x3012766
03012748  mov.l    0x301287c,r0
0301274a  mov      #0x14,r6
0301274c  mov.l    r9,@(0x10,r15)
0301274e  mov      r8,r4
03012750  mov      #0x7,r5
03012752  mov      #0x36,r7
03012754  jsr      @r0
03012756  add      r15,r6
03012758  tst      r0,r0
0301275a  bt       0x3012784
0301275c  mov.l    0x3012878,r0
0301275e  jsr      @r0
03012760  nop      
03012762  bra      0x30127a6
03012764  mov      #-0x1,r0
03012766  mov      #0x14,r6
03012768  mov.l    0x301287c,r0
0301276a  mov      r8,r4
0301276c  mov.l    r9,@(0x10,r15)
0301276e  mov      #0x7,r5
03012770  mov      #0x2e,r7
03012772  jsr      @r0
03012774  add      r15,r6
03012776  tst      r0,r0
03012778  bt       0x3012784
0301277a  mov.l    0x3012878,r0
0301277c  jsr      @r0
0301277e  nop      
03012780  bra      0x30127a6
03012782  mov      #-0x1,r0
03012784  mov.l    0x3012884,r0
03012786  mov      #0x14,r5
03012788  mov      r10,r4
0301278a  mov      #0xd,r6
0301278c  jsr      @r0
0301278e  add      r15,r5
03012790  mov.l    0x3012884,r0
03012792  add      #0xd,r10
03012794  mov      #0x21,r5
03012796  add      r15,r5
03012798  mov      #0x29,r6
0301279a  jsr      @r0
0301279c  mov      r10,r4
0301279e  mov.l    0x3012878,r0
030127a0  jsr      @r0
030127a2  nop      
030127a4  mov      #0x0,r0
030127a6  add      #0x4c,r15
030127a8  lds.l    @r15+,PR
030127aa  mov.l    @r15+,r10
030127ac  mov.l    @r15+,r9
030127ae  rts      
030127b0  mov.l    @r15+,r8
