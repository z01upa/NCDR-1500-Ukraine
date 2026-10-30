K:\siemens\src\db\db_read.c
03012b90  mov.l    r8,@-r15
03012b92  mov.l    r9,@-r15
03012b94  mov.l    r10,@-r15
03012b96  sts.l    PR,@-r15
03012b98  mov      r4,r8
03012b9a  mov      r5,r10
03012b9c  mov      r6,r9
03012b9e  mov.w    0x3012d38,r1
03012ba0  sub      r1,r15
03012ba2  mov.l    0x3012d24,r0
03012ba4  jsr      @r0
03012ba6  nop      
03012ba8  tst      r10,r10
03012baa  bf       0x3012bb6
03012bac  mov.l    0x3012d20,r0
03012bae  mov      #0x75,r5
03012bb0  mov.l    0x3012d30,r4
03012bb2  jsr      @r0
03012bb4  shll2    r5
03012bb6  mov      #0x14,r6
03012bb8  mov.l    0x3012d2c,r0
03012bba  mov      #0x59,r7
03012bbc  mov.l    r9,@(0x10,r15)
03012bbe  shll     r7
03012bc0  mov      r8,r4
03012bc2  mov      #0x3,r5
03012bc4  jsr      @r0
03012bc6  add      r15,r6
03012bc8  tst      r0,r0
03012bca  bt       0x3012bd6
03012bcc  mov.l    0x3012d28,r0
03012bce  jsr      @r0
03012bd0  nop      
03012bd2  bra      0x3012be6
03012bd4  mov      #-0x1,r0
03012bd6  mov      #0x14,r5
03012bd8  mov      r10,r4
03012bda  bsr      0x3012bf4
03012bdc  add      r15,r5
03012bde  mov.l    0x3012d28,r0
03012be0  jsr      @r0
03012be2  nop      
03012be4  mov      #0x0,r0
03012be6  mov.w    0x3012d38,r2
03012be8  add      r2,r15
03012bea  lds.l    @r15+,PR
03012bec  mov.l    @r15+,r10
03012bee  mov.l    @r15+,r9
03012bf0  rts      
03012bf2  mov.l    @r15+,r8
