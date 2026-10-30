from decoder import *
from collections import Counter
b=(Path(__file__).parent/'evidence/MG3_0.bin').read_bytes();p=list(struct.iter_unpack('<HH',b[:44]));adj={i:[] for i in range(p[5][1])}
for i in range(p[4][1]):
 a=b[p[4][0]+10*i:p[4][0]+10*(i+1)];deg=a[0]&15
 for k in range(min(deg,3)):
  e=struct.unpack_from('<H',a,2+2*k)[0]
  if e in adj:adj[e].append(i)
for i in range(20):
 a=b[p[5][0]+14*i:p[5][0]+14*(i+1)];print(i,'adj',adj[i],'raw',struct.unpack('<7H',a))
print(Counter(len(v) for v in adj.values()))
