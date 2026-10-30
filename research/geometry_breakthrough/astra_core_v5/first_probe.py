from pathlib import Path
import sys,struct,json
HERE=Path(__file__).parent
sys.path.insert(0,str(HERE.parent/'topology_v3'))
from node_link_validator import _read_container,_sections,SOURCE
_,blocks=_read_container(SOURCE)
for bi,ni in [(7,55),(10,220),(16,328)]:
 b=blocks[bi];s,c=_sections(b)
 for n in [ni,ni+1]:
  r=b[s[4]+n*10:s[4]+n*10+10];inc=[]
  for e in range(c[5]):
   f=struct.unpack_from('<H',b,s[5]+14*e)[0];u,v=struct.unpack_from('<HH',b,s[5]+14*e+6)
   if (not f&4096 and u==n) or (not f&8192 and v==n):inc.append(e)
  print(bi,n,r.hex(),struct.unpack('<5H',r),inc)
