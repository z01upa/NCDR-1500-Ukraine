from decoder import *
from collections import Counter
b=(Path(__file__).parent/'evidence/MP0_0.bin').read_bytes();p=list(struct.iter_unpack('<HH',b[:44]));rs=[struct.unpack_from('<5HI',b,p[5][0]+14*i) for i in range(p[5][1])]
for k in range(16):print(k,sum(bool(r[0]&(1<<k)) for r in rs),sum(bool(r[1]&(1<<k)) for r in rs))
print('lengthfield', [r[5] for r in rs[:25]])
