from decoder import *
from collections import Counter
import math
b=(Path(__file__).parent/'evidence/MP0_0.bin').read_bytes();p=list(struct.iter_unpack('<HH',b[:44]));print('shapes',p[6],p[7]);print(b[p[6][0]:p[6][0]+160].hex(' '))
for e in range(p[5][1]):
 a=b[p[5][0]+14*e:p[5][0]+14*(e+1)];f,at,k,u,v,l=struct.unpack('<5HI',a)
 if at&0x800:print(e,hex(f),hex(at),k,u,v,l)
