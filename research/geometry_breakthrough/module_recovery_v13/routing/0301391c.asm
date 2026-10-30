K:\siemens\src\db\db_read.c
0301391c  mov.l    r8,@-r15
0301391e  mov.l    r9,@-r15
03013920  mov.l    r10,@-r15
03013922  mov.l    r11,@-r15
03013924  sts.l    PR,@-r15
03013926  mov      r4,r8
03013928  mov      r5,r9
0301392a  mov      r6,r11
0301392c  mov      r7,r10
0301392e  add      #-0x10,r15
03013930  tst      r8,r8
03013932  bf       0x301393e
03013934  mov.l    0x3013974,r0
03013936  mov.l    0x301397c,r4
03013938  mov.w    0x301396a,r5
0301393a  jsr      @r0
0301393c  nop      
0301393e  mov.l    0x3013970,r0
03013940  jsr      @r0
03013942  nop      
03013944  mov.l    0x301396c,r2
03013946  mov      #0x1e,r4
03013948  mov      r9,r5
0301394a  mov      r11,r6
0301394c  mov      r10,r7
0301394e  bsr      0x3013888
03013950  mov.l    r8,@r2
03013952  mov      r0,r8
03013954  mov.l    0x3013978,r0
03013956  jsr      @r0
03013958  nop      
0301395a  mov      r8,r0
0301395c  add      #0x10,r15
0301395e  lds.l    @r15+,PR
03013960  mov.l    @r15+,r11
03013962  mov.l    @r15+,r10
03013964  mov.l    @r15+,r9
03013966  rts      
03013968  mov.l    @r15+,r8
