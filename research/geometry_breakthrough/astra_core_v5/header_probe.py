exec((__import__('pathlib').Path(__file__).parent/'first_probe.py').read_text().split('for bi,ni')[0])
from collections import Counter
out={}
for bi,b in enumerate(blocks):
 s,c=_sections(b);inc=[[] for _ in range(c[4])]
 for e in range(c[5]):
  f=struct.unpack_from('<H',b,s[5]+14*e)[0];u,v=struct.unpack_from('<HH',b,s[5]+14*e+6)
  if not f&4096:inc[u].append(e)
  if not f&8192:inc[v].append(e)
 for n,es in enumerate(inc):
  r=b[s[4]+10*n:s[4]+10*n+10];deg=r[0]&15
  if bi>=20:continue
  if deg>4 and es:
   nxt=b[s[4]+10*(n+1):s[4]+10*(n+2)];refs=list(struct.unpack_from('<3H',r,4))+list(struct.unpack('<5H',nxt))[:deg-3]
   print(bi,n,deg,r.hex(),nxt.hex(),'refs',refs,'equal',sorted(refs)==sorted(es),'headerbits',[(int.from_bytes(r[:4],'little')>>(4+3*j))&7 for j in range(deg)])
