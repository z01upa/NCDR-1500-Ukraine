030688e8  mov.l    r8,@-r15                    
030688ea  mov.l    r9,@-r15                    
030688ec  mov.l    r10,@-r15                   
030688ee  mov.l    r11,@-r15                   
030688f0  mov.l    r12,@-r15                   
030688f2  mov.l    r13,@-r15                   
030688f4  sts.l    PR,@-r15                    
030688f6  mov.l    r7,@(0x28,r15)              
030688f8  mov.l    r5,@(0x20,r15)              
030688fa  mov      r4,r10                      
030688fc  mov      r6,r8                       
030688fe  add      #-0x64,r15                  
03068900  mov.l    0x3068a6c,r0                 ; literal[03068a6c]=0101213c normalized=0301213c
03068902  jsr      @r0                         
03068904  nop                                  
03068906  mov      r10,r0                      
03068908  mov.l    0x3068a64,r1                 ; literal[03068a64]=f0000000 normalized=f0000000
0306890a  and      r1,r0                       
0306890c  mov.l    0x3068a60,r1                 ; literal[03068a60]=0ffff000 normalized=0ffff000
0306890e  mov      #-0x1c,r3                   
03068910  mov      r10,r2                      
03068912  shld     r3,r0                       
03068914  mov.w    r0,@(0x10,r15)              
03068916  mov      r10,r0                      
03068918  and      r1,r0                       
0306891a  mov.w    0x3068a56,r1                 ; literal[03068a56]=00000fff normalized=00000fff
0306891c  mov      #-0xc,r3                    
0306891e  mov      r10,r4                      
03068920  shld     r3,r0                       
03068922  mov.w    r0,@(0x12,r15)              
03068924  and      r1,r2                       
03068926  mov.l    r2,@(0x1c,r15)              
03068928  mov      #0x14,r6                    
0306892a  mov.w    0x3068a84,r0                 ; literal[03068a84]=0000008c normalized=0000008c
0306892c  mov.l    @(r0,r15),r5                
0306892e  mov.l    0x3068a74,r0                 ; literal[03068a74]=0100d19c normalized=0300d19c
03068930  jsr      @r0                         
03068932  add      r15,r6                      
03068934  tst      r0,r0                       
03068936  bt       0x3068942                   
03068938  mov.l    0x3068a70,r0                 ; literal[03068a70]=0101217c normalized=0301217c
0306893a  jsr      @r0                         
0306893c  nop                                  
0306893e  bra      0x3068d08                   
03068940  mov      #-0x1,r0                    
03068942  mov.l    @(0x14,r15),r2              
03068944  mov.l    @(0x1c,r15),r3              
03068946  mov.l    @(0x30,r2),r2               
03068948  cmp/ge   r2,r3                       
0306894a  bf       0x306895a                   
0306894c  mov.l    0x3068a70,r0                 ; literal[03068a70]=0101217c normalized=0301217c
0306894e  mov.l    0x3068a7c,r2                 ; literal[03068a7c]=010d89ac normalized=030d89ac
03068950  mov.w    0x3068a86,r3                 ; literal[03068a86]=00000202 normalized=00000202
03068952  jsr      @r0                         
03068954  mov.l    r3,@r2                      
03068956  bra      0x3068d08                   
03068958  mov      #-0x1,r0                    
0306895a  mov.l    @(0x14,r15),r2              
0306895c  mov.l    @(0x38,r2),r2               
0306895e  tst      r2,r2                       
03068960  bf       0x3068970                   
03068962  mov.l    0x3068a70,r0                 ; literal[03068a70]=0101217c normalized=0301217c
03068964  mov.l    0x3068a7c,r1                 ; literal[03068a7c]=010d89ac normalized=030d89ac
03068966  mov.w    0x3068a86,r2                 ; literal[03068a86]=00000202 normalized=00000202
03068968  jsr      @r0                         
0306896a  mov.l    r2,@r1                      
0306896c  bra      0x3068d08                   
0306896e  mov      #-0x1,r0                    
03068970  mov.l    @(0x1c,r15),r2              
03068972  mov      #0xa,r1                     
03068974  mov.l    @(0x14,r15),r3              
03068976  mul.l    r2,r1                       
03068978  mov.l    @(0x2c,r3),r0               
0306897a  mov      #0xf,r1                     
0306897c  sts      MACL,r13                    
0306897e  mov.b    @(r0,r13),r3                
03068980  extu.b   r3,r11                      
03068982  and      r1,r11                      
03068984  mov      #0x8,r2                     
03068986  cmp/gt   r2,r11                      
03068988  bf       0x306898c                   
0306898a  mov      #0x8,r11                    
0306898c  bra      0x3068992                   
0306898e  mov      #0x0,r10                    
03068990  add      #0x1,r10                    
03068992  cmp/gt   r10,r11                     
03068994  bf       0x3068a38                   
03068996  mov      #0x34,r3                    
03068998  mov.l    0x3068a5c,r2                 ; literal[03068a5c]=f0000fff normalized=f0000fff
0306899a  mov      r8,r12                      
0306899c  mov.w    @(0x12,r15),r0              
0306899e  mul.l    r10,r3                      
030689a0  mov.l    0x3068a58,r1                 ; literal[03068a58]=0fffffff normalized=0fffffff
030689a2  sts      MACL,r4                     
030689a4  add      r4,r12                      
030689a6  mov      r12,r4                      
030689a8  mov.l    @r4,r3                      
030689aa  and      r2,r3                       
030689ac  mov      #0xc,r2                     
030689ae  shld     r2,r0                       
030689b0  or       r0,r3                       
030689b2  mov.l    r3,@r4                      
030689b4  and      r1,r3                       
030689b6  mov.w    @(0x10,r15),r0              
030689b8  mov      #0x1c,r1                    
030689ba  shld     r1,r0                       
030689bc  mov      #0x4,r2                     
030689be  cmp/hs   r11,r2                      
030689c0  or       r0,r3                       
030689c2  bf/s     0x30689d8                   
030689c4  mov.l    r3,@r4                      
030689c6  mov      #-0x10,r2                   
030689c8  mov.l    @(0x14,r15),r3              
030689ca  shll8    r2                          
030689cc  mov.l    @(0x2c,r3),r3               
030689ce  add      r13,r3                      
030689d0  mov.l    @r4,r1                      
030689d2  add      #0x2,r3                     
030689d4  bra      0x30689e8                   
030689d6  and      r2,r1                       
030689d8  mov.l    @(0x14,r15),r3              
030689da  mov      #-0x10,r2                   
030689dc  mov.l    @(0x2c,r3),r3               
030689de  shll8    r2                          
030689e0  mov.l    @r4,r1                      
030689e2  and      r2,r1                       
030689e4  add      r13,r3                      
030689e6  add      #0x4,r3                     
030689e8  mov      r10,r0                      
030689ea  shll     r0                          
030689ec  mov.w    @(r0,r3),r3                 
030689ee  extu.w   r3,r3                       
030689f0  or       r3,r1                       
030689f2  mov.l    r1,@r4                      
030689f4  mov.l    @(0x14,r15),r1              
030689f6  mov      #0x34,r3                    
030689f8  mov.l    @(0x38,r1),r1               
030689fa  mul.l    r10,r3                      
030689fc  mov.w    0x3068a56,r3                 ; literal[03068a56]=00000fff normalized=00000fff
030689fe  sts      MACL,r0                     
03068a00  mov.l    @(r0,r8),r6                 
03068a02  and      r3,r6                       
03068a04  cmp/gt   r6,r1                       
03068a06  bt       0x3068a1e                   
03068a08  mov.l    0x3068a68,r0                 ; literal[03068a68]=0100a868 normalized=0300a868
03068a0a  mov      #0x4c,r5                    
03068a0c  mov.l    0x3068a80,r4                 ; literal[03068a80]=010c8648 normalized=030c8648
03068a0e  jsr      @r0                         
03068a10  shll2    r5                          
03068a12  mov      #0x34,r3                    
03068a14  mul.l    r10,r3                      
03068a16  mov.w    0x3068a56,r3                 ; literal[03068a56]=00000fff normalized=00000fff
03068a18  sts      MACL,r0                     
03068a1a  mov.l    @(r0,r8),r6                 
03068a1c  and      r3,r6                       
03068a1e  shll2    r6                          
03068a20  mov.l    @(0x14,r15),r1              
03068a22  shll2    r6                          
03068a24  mov.l    @(0x34,r1),r5               
03068a26  add      r6,r5                       
03068a28  mov.w    @(0x10,r15),r0              
03068a2a  mov      r0,r6                       
03068a2c  mov.w    @(0x12,r15),r0              
03068a2e  mov      r12,r4                      
03068a30  bsr      0x306886c                   
03068a32  mov      r0,r7                       
03068a34  bra      0x3068990                   
03068a36  nop                                  
03068a38  mov.l    @(0x14,r15),r3              
03068a3a  mov      #0xc,r1                     
03068a3c  mov.l    @(0x1c,r3),r4               
03068a3e  mov      #0x0,r10                    
03068a40  mov.l    @(0x1c,r15),r2              
03068a42  mul.l    r2,r1                       
03068a44  sts      MACL,r3                     
03068a46  add      r3,r4                       
03068a48  mov.l    @r4+,r5                     
03068a4a  mov.l    @r4+,r6                     
03068a4c  mov.l    r5,@(0x34,r15)              
03068a4e  mov.l    r6,@(0x38,r15)              
03068a50  mov.l    @r4,r4                      
03068a52  bra      0x3068a8a                   
03068a54  mov.l    r4,@(0x3c,r15)              
03068a88  add      #0x1,r10                    
03068a8a  cmp/gt   r10,r11                     
03068a8c  bt       0x3068a92                   
03068a8e  bra      0x3068d00                   
03068a90  nop                                  
03068a92  mov.l    @(0x14,r15),r1              
03068a94  mov      #0xa,r2                     
03068a96  mov.l    @(0x2c,r1),r5               
03068a98  mov.l    @(0x1c,r15),r3              
03068a9a  mul.l    r3,r2                       
03068a9c  sts      MACL,r1                     
03068a9e  add      r1,r5                       
03068aa0  mov.b    @r5,r2                      
03068aa2  extu.b   r2,r4                       
03068aa4  mov      r4,r0                       
03068aa6  mov      #0x4,r2                     
03068aa8  and      #0xf,r0                     
03068aaa  cmp/hi   r2,r0                       
03068aac  bf       0x3068abc                   
03068aae  mov.b    @(0x1,r5),r0                
03068ab0  extu.b   r0,r6                       
03068ab2  neg      r10,r2                      
03068ab4  shld     r2,r6                       
03068ab6  mov      #0x1,r3                     
03068ab8  bra      0x3068ad0                   
03068aba  and      r3,r6                       
03068abc  mov      #-0x4,r2                    
03068abe  nop                                  
03068ac0  shad     r2,r4                       
03068ac2  mov      #0xf,r3                     
03068ac4  and      r3,r4                       
03068ac6  neg      r10,r1                      
03068ac8  shld     r1,r4                       
03068aca  mov      #0x1,r2                     
03068acc  and      r2,r4                       
03068ace  mov      r4,r6                       
03068ad0  mov      #0x34,r3                    
03068ad2  mov.l    r6,@(0x28,r15)              
03068ad4  mov      #0x1,r0                     
03068ad6  mov      r8,r2                       
03068ad8  add      r6,r0                       
03068ada  mov      r8,r12                      
03068adc  and      #0x1,r0                     
03068ade  mov.l    r0,@(0x24,r15)              
03068ae0  shll2    r0                          
03068ae2  mul.l    r10,r3                      
03068ae4  mov.w    0x3068bac,r3                 ; literal[03068bac]=00000fff normalized=00000fff
03068ae6  sts      MACL,r4                     
03068ae8  add      r4,r2                       
03068aea  add      #0x14,r2                    
03068aec  add      r0,r2                       
03068aee  mov.l    r2,@(0x2c,r15)              
03068af0  mov.l    @r2,r2                      
03068af2  and      r3,r2                       
03068af4  mov.l    r2,@(0x18,r15)              
03068af6  mov      #0x1,r2                     
03068af8  cmp/eq   r2,r6                       
03068afa  bf/s     0x3068b14                   
03068afc  add      r4,r12                      
03068afe  mov      r8,r4                       
03068b00  mov      #0x34,r1                    
03068b02  mul.l    r10,r1                      
03068b04  mov      #0x1,r1                     
03068b06  sts      MACL,r2                     
03068b08  add      r2,r4                       
03068b0a  mov.l    @(0x4,r4),r4                
03068b0c  mov      #-0xc,r3                    
03068b0e  shld     r3,r4                       
03068b10  bra      0x3068b28                   
03068b12  and      r1,r4                       
03068b14  mov      #0x34,r3                    
03068b16  mov      r8,r4                       
03068b18  mov      #-0xd,r2                    
03068b1a  mul.l    r10,r3                      
03068b1c  mov      #0x1,r3                     
03068b1e  sts      MACL,r1                     
03068b20  add      r1,r4                       
03068b22  mov.l    @(0x4,r4),r4                
03068b24  shld     r2,r4                       
03068b26  and      r3,r4                       
03068b28  mov      #0x1,r1                     
03068b2a  cmp/eq   r1,r4                       
03068b2c  bt       0x3068bae                   
03068b2e  mov      #0x34,r0                    
03068b30  mul.l    r10,r0                      
03068b32  add      #0x50,r0                    
03068b34  mov.l    @(r0,r15),r13               
03068b36  mov      #-0x10,r3                   
03068b38  sts      MACL,r1                     
03068b3a  add      r1,r13                      
03068b3c  mov.l    @r13,r2                     
03068b3e  shll8    r3                          
03068b40  mov.l    @(0x18,r15),r1              
03068b42  and      r3,r2                       
03068b44  mov.l    0x3068ba0,r3                 ; literal[03068ba0]=f0000fff normalized=f0000fff
03068b46  or       r1,r2                       
03068b48  mov.l    r2,@r13                     
03068b4a  and      r3,r2                       
03068b4c  mov.w    @(0x12,r15),r0              
03068b4e  mov      #0xc,r1                     
03068b50  mov.l    0x3068b9c,r3                 ; literal[03068b9c]=0fffffff normalized=0fffffff
03068b52  shld     r1,r0                       
03068b54  or       r0,r2                       
03068b56  mov.l    r2,@r13                     
03068b58  and      r3,r2                       
03068b5a  mov.w    @(0x10,r15),r0              
03068b5c  mov      #0x1c,r3                    
03068b5e  shld     r3,r0                       
03068b60  or       r0,r2                       
03068b62  mov.l    r2,@r13                     
03068b64  mov.l    @(0x14,r15),r2              
03068b66  mov.l    @(0x1c,r2),r1               
03068b68  mov.l    r1,@(0x20,r15)              
03068b6a  mov.l    @(0x20,r2),r2               
03068b6c  mov.l    @(0x18,r15),r3              
03068b6e  cmp/gt   r3,r2                       
03068b70  bt       0x3068b7c                   
03068b72  mov.l    0x3068ba4,r0                 ; literal[03068ba4]=0100a868 normalized=0300a868
03068b74  mov.l    0x3068ba8,r4                 ; literal[03068ba8]=010c8648 normalized=030c8648
03068b76  mov.w    0x3068b9a,r5                 ; literal[03068b9a]=00000155 normalized=00000155
03068b78  jsr      @r0                         
03068b7a  nop                                  
03068b7c  mov.w    @(0x10,r15),r0              
03068b7e  mov      r0,r5                       
03068b80  mov.w    @(0x12,r15),r0              
03068b82  mov      #0xa,r3                     
03068b84  mov      r0,r6                       
03068b86  mov.l    @(0x14,r15),r2              
03068b88  mov      r13,r4                      
03068b8a  mov.l    @(0x2c,r2),r7               
03068b8c  mov.l    @(0x18,r15),r1              
03068b8e  mul.l    r1,r3                       
03068b90  sts      MACL,r2                     
03068b92  bsr      0x30687a8                   
03068b94  add      r2,r7                       
03068b96  bra      0x3068bda                   
03068b98  nop                                  
03068bae  mov.l    @(0x14,r15),r2              
03068bb0  mov.l    @(0x24,r2),r1               
03068bb2  mov.l    r1,@(0x20,r15)              
03068bb4  mov.l    @(0x28,r2),r2               
03068bb6  mov.l    @(0x18,r15),r3              
03068bb8  cmp/gt   r3,r2                       
03068bba  bt       0x3068bc6                   
03068bbc  mov.l    0x3068d1c,r0                 ; literal[03068d1c]=0100a868 normalized=0300a868
03068bbe  mov      #0x57,r5                    
03068bc0  mov.l    0x3068d30,r4                 ; literal[03068d30]=010c8648 normalized=030c8648
03068bc2  jsr      @r0                         
03068bc4  shll2    r5                          
03068bc6  mov      #0x34,r0                    
03068bc8  mul.l    r10,r0                      
03068bca  add      #0x50,r0                    
03068bcc  mov.l    @(r0,r15),r13               
03068bce  mov      #-0x2,r1                    
03068bd0  sts      MACL,r3                     
03068bd2  add      r3,r13                      
03068bd4  mov.l    r1,@r13                     
03068bd6  mov.l    @(0x2c,r15),r3              
03068bd8  mov.l    r1,@r3                      
03068bda  mov      #0xc,r1                     
03068bdc  mov.l    @(0x18,r15),r2              
03068bde  add      #0x4,r13                    
03068be0  mov.l    @(0x20,r15),r3              
03068be2  mul.l    r2,r1                       
03068be4  mov.w    0x3068d34,r0                 ; literal[03068d34]=0000008c normalized=0000008c
03068be6  mov      #0xc,r2                     
03068be8  sts      MACL,r4                     
03068bea  add      r4,r3                       
03068bec  mov      r3,r5                       
03068bee  mov      #0x1c,r1                    
03068bf0  mov.l    @r5+,r6                     
03068bf2  add      r12,r1                      
03068bf4  mov.l    @r5+,r4                     
03068bf6  mov.l    r6,@r13                     
03068bf8  mov.l    r4,@(0x4,r13)               
03068bfa  mov.l    @r5+,r4                     
03068bfc  mov.l    r4,@(0x8,r13)               
03068bfe  mov.l    r3,@(0x20,r15)              
03068c00  mov.l    @(0x24,r15),r3              
03068c02  mul.l    r3,r2                       
03068c04  mov.l    @(0x20,r15),r3              
03068c06  sts      MACL,r2                     
03068c08  mov.l    @r3+,r4                     
03068c0a  add      r2,r1                       
03068c0c  mov.l    @r3+,r5                     
03068c0e  mov      #0xc,r2                     
03068c10  mov.l    r4,@r1                      
03068c12  mov.l    r5,@(0x4,r1)                
03068c14  mov.l    @r3+,r4                     
03068c16  mov      #0x40,r5                    
03068c18  mov.l    r4,@(0x8,r1)                
03068c1a  mov      #0x1c,r1                    
03068c1c  mov.l    @(0x28,r15),r3              
03068c1e  add      r12,r1                      
03068c20  mov.l    @(0x34,r15),r6              
03068c22  mul.l    r3,r2                       
03068c24  mov.l    @(0x38,r15),r4              
03068c26  sts      MACL,r2                     
03068c28  add      r2,r1                       
03068c2a  mov.l    r6,@r1                      
03068c2c  mov.l    r4,@(0x4,r1)                
03068c2e  mov.l    @(0x3c,r15),r4              
03068c30  mov.l    r4,@(0x8,r1)                
03068c32  mov.l    @(r0,r15),r0                
03068c34  cmp/eq   #0x8,r0                     
03068c36  bf/s     0x3068c3e                   
03068c38  add      r15,r5                      
03068c3a  bra      0x3068a88                   
03068c3c  nop                                  
03068c3e  mov.l    0x3068d2c,r0                 ; literal[03068d2c]=0101b428 normalized=0301b428
03068c40  mov      r12,r6                      
03068c42  mov.l    @r12,r5                     
03068c44  mov.w    0x3068d1a,r3                 ; literal[03068d1a]=00000fff normalized=00000fff
03068c46  mov.l    @(0x14,r15),r4              
03068c48  jsr      @r0                         
03068c4a  and      r3,r5                       
03068c4c  mov      r0,r5                       
03068c4e  mov      #0x34,r1                    
03068c50  mov.l    r5,@(0x8,r12)               
03068c52  mov      r8,r3                       
03068c54  mul.l    r10,r1                      
03068c56  mov      #0xf,r1                     
03068c58  sts      MACL,r2                     
03068c5a  add      r2,r3                       
03068c5c  mov.l    @(0x4,r3),r4                
03068c5e  mov      r4,r7                       
03068c60  shlr     r7                          
03068c62  shlr2    r7                          
03068c64  and      r1,r7                       
03068c66  mov      r7,r6                       
03068c68  mov      #0x7,r2                     
03068c6a  cmp/eq   r6,r2                       
03068c6c  bf       0x3068c76                   
03068c6e  mov      r4,r0                       
03068c70  tst      #0x7,r0                     
03068c72  bt       0x3068c76                   
03068c74  mov      #0x3,r6                     
03068c76  mov      #0x5,r1                     
03068c78  cmp/eq   r1,r7                       
03068c7a  bf       0x3068cce                   
03068c7c  mov      #0x7,r3                     
03068c7e  and      r3,r4                       
03068c80  tst      r4,r4                       
03068c82  bt       0x3068ca0                   
03068c84  mov      #0x1,r2                     
03068c86  cmp/eq   r4,r2                       
03068c88  bt       0x3068ca0                   
03068c8a  mov      #0x2,r1                     
03068c8c  cmp/eq   r4,r1                       
03068c8e  bt       0x3068ca0                   
03068c90  mov      #0x3,r3                     
03068c92  cmp/eq   r4,r3                       
03068c94  bt       0x3068ca6                   
03068c96  mov      #0x4,r2                     
03068c98  cmp/eq   r4,r2                       
03068c9a  bt       0x3068cac                   
03068c9c  bra      0x3068cca                   
03068c9e  nop                                  
03068ca0  mov.l    0x3068d24,r9                 ; literal[03068d24]=01137260 normalized=03137260
03068ca2  bra      0x3068cb0                   
03068ca4  mov      #0xf,r2                     
03068ca6  mov.l    0x3068d24,r9                 ; literal[03068d24]=01137260 normalized=03137260
03068ca8  bra      0x3068cb0                   
03068caa  mov      #0xc,r2                     
03068cac  mov.l    0x3068d24,r9                 ; literal[03068d24]=01137260 normalized=03137260
03068cae  mov      #0xb,r2                     
03068cb0  mov.l    0x3068d20,r0                 ; literal[03068d20]=00ff8910 normalized=02ff8910
03068cb2  mul.l    r5,r2                       
03068cb4  mov      #0xa,r5                     
03068cb6  jsr      @r0                         
03068cb8  sts      MACL,r4                     
03068cba  mov      r0,r4                       
03068cbc  mov.l    @(0xc,r9),r5                
03068cbe  mov      #0x4c,r0                    
03068cc0  mov.l    @(r0,r9),r3                 
03068cc2  mov.l    0x3068d20,r0                 ; literal[03068d20]=00ff8910 normalized=02ff8910
03068cc4  jsr      @r0                         
03068cc6  add      r3,r4                       
03068cc8  extu.w   r0,r9                       
03068cca  bra      0x3068ce6                   
03068ccc  nop                                  
03068cce  shll2    r6                          
03068cd0  mov.l    0x3068d24,r9                 ; literal[03068d24]=01137260 normalized=03137260
03068cd2  mov      #0x40,r0                    
03068cd4  add      r6,r0                       
03068cd6  mov.l    @(r0,r9),r4                 
03068cd8  mov      r6,r0                       
03068cda  add      r5,r4                       
03068cdc  mov.l    @(r0,r9),r5                 
03068cde  mov.l    0x3068d20,r0                 ; literal[03068d20]=00ff8910 normalized=02ff8910
03068ce0  jsr      @r0                         
03068ce2  nop                                  
03068ce4  extu.w   r0,r9                       
03068ce6  tst      r9,r9                       
03068ce8  bf       0x3068cec                   
03068cea  mov      #0x1,r9                     
03068cec  mov.l    @(0x28,r15),r1              
03068cee  mov      #0xc,r0                     
03068cf0  add      r12,r0                      
03068cf2  shll     r1                          
03068cf4  mov.w    r9,@(r0,r1)                 
03068cf6  add      #0xc,r12                    
03068cf8  mov.l    @(0x24,r15),r0              
03068cfa  shll     r0                          
03068cfc  bra      0x3068a88                   
03068cfe  mov.w    r9,@(r0,r12)                
03068d00  mov.l    0x3068d28,r0                 ; literal[03068d28]=0101217c normalized=0301217c
03068d02  jsr      @r0                         
03068d04  nop                                  
03068d06  mov      r11,r0                      
03068d08  add      #0x64,r15                   
03068d0a  lds.l    @r15+,PR                    
03068d0c  mov.l    @r15+,r13                   
03068d0e  mov.l    @r15+,r12                   
03068d10  mov.l    @r15+,r11                   
03068d12  mov.l    @r15+,r10                   
03068d14  mov.l    @r15+,r9                    
03068d16  rts                                  
03068d18  mov.l    @r15+,r8                    
