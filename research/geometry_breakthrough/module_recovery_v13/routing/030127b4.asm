K:\siemens\src\db\db_read.c
030127b4  mov.l    r8,@-r15
030127b6  mov.l    r9,@-r15
030127b8  mov.l    r10,@-r15
030127ba  sts.l    PR,@-r15
030127bc  mov      r4,r8
030127be  mov      r5,r10
030127c0  mov      r6,r9
030127c2  add      #-0x40,r15
030127c4  mov.l    0x3012870,r0
030127c6  jsr      @r0
030127c8  nop      
030127ca  tst      r10,r10
030127cc  bf       0x30127d8
030127ce  mov.l    0x3012874,r0
030127d0  mov.l    0x3012880,r4
030127d2  mov.w    0x301288a,r5
030127d4  jsr      @r0
030127d6  nop      
030127d8  mov.l    0x301287c,r0
030127da  mov      #0x14,r6
030127dc  mov.l    r9,@(0x10,r15)
030127de  mov      r8,r4
030127e0  mov      #0x6,r5
030127e2  mov      #0x2c,r7
030127e4  jsr      @r0
030127e6  add      r15,r6
030127e8  tst      r0,r0
030127ea  bt       0x30127f6
030127ec  mov.l    0x3012878,r0
030127ee  jsr      @r0
030127f0  nop      
030127f2  bra      0x3012818
030127f4  mov      #-0x1,r0
030127f6  mov      #0x14,r5
030127f8  mov.l    0x3012884,r0
030127fa  mov      r10,r4
030127fc  mov      #0x3,r6
030127fe  jsr      @r0
03012800  add      r15,r5
03012802  mov.l    0x3012884,r0
03012804  add      #0x3,r10
03012806  mov      #0x17,r5
03012808  add      r15,r5
0301280a  mov      #0x29,r6
0301280c  jsr      @r0
0301280e  mov      r10,r4
03012810  mov.l    0x3012878,r0
03012812  jsr      @r0
03012814  nop      
03012816  mov      #0x0,r0
03012818  add      #0x40,r15
0301281a  lds.l    @r15+,PR
0301281c  mov.l    @r15+,r10
0301281e  mov.l    @r15+,r9
03012820  rts      
03012822  mov.l    @r15+,r8
