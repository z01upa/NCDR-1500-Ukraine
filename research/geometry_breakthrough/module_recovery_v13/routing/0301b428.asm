0301b428 sts.l    PR,@-r15
0301b42a add      #-0x10,r15
0301b42c mov.l    @(0x34,r4),r1
0301b42e shll2    r5
0301b430 shll2    r5
0301b432 add      r5,r1
0301b434 mov.l    @(0xc,r1),r4
0301b436 cmp/pl   r4
0301b438 bf       0x301b43e
0301b43a bra      0x301b448
0301b43c mov      r4,r0
0301b43e mov.l    0x301b460,r0
0301b440 mov.l    0x301b464,r4
0301b442 mov.w    0x301b46a,r5
0301b444 jsr      @r0
0301b446 nop      
0301b448 add      #0x10,r15
0301b44a lds.l    @r15+,PR
0301b44c rts      
0301b44e nop      