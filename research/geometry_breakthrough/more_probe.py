from decoder import *
b=(Path(__file__).parent/'evidence/MP0_0.bin').read_bytes();p=list(struct.iter_unpack('<HH',b[:44]))
for e in range(15):print(e,struct.unpack_from('<5HI',b,p[5][0]+14*e))
for s in [7,8,9,10]:
 a,n=p[s];end=p[s+1][0] if s<10 else len(b);print(s,a,n,end,b[a:a+100].hex(' '))
