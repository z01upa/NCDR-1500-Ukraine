from decoder_v1_unsigned_secondary import *
from collections import Counter
import math
out=Path(__file__).parent; report={}
for ext in ['MP0','MG1','MG2','MG3']:
 tally=Counter();examples=[]
 for i,box,off,cl,b in blocks((ROOT/('EUZ.'+ext)).read_bytes(),ext=='MP0'):
  p=list(struct.iter_unpack('<HH',b[:44]));nodes,_=decode_runs(b,p[0][0],p[1][0],p[0][1])
  try:secondary,_=decode_runs(b,p[2][0],p[3][0],p[2][1])
  except ValueError: tally['secondary_decode_failure']+=1;continue
  tally['secondary_points']+=len(secondary)
  adj={}
  for v in range(p[4][1]):
   a=b[p[4][0]+10*v:p[4][0]+10*(v+1)];degree=a[0]&15
   tally['degree_'+str(degree)]+=1
   for k in range(min(degree,3)):
    e=struct.unpack_from('<H',a,2+2*k)[0];adj.setdefault(e,[]).append(v)
  for e in range(p[5][1]):
   a=b[p[5][0]+14*e:p[5][0]+14*(e+1)];flags,attr,unknown,u,v,length=struct.unpack('<5HI',a)
   first=secondary if flags&0x1000 else nodes;second=secondary if flags&0x2000 else nodes
   tally['edges']+=1
   if u>=len(first) or v>=len(second):tally['endpoint_out_of_range']+=1;continue
   expected=([u] if not flags&0x1000 else [])+([v] if not flags&0x2000 else [])
   if sorted(adj.get(e,[]))==sorted(expected):tally['reciprocal']+=1
   else:tally['nonreciprocal']+=1
   x,y=first[u];xx,yy=second[v];dist=math.hypot((xx-x)*math.cos((y+yy)/200000*math.pi/180), yy-y)*1.11195
   if length+5<dist:tally['length_shorter_than_chord']+=1
   if len(examples)<12 and not flags&0x3000 and expected==adj.get(e,[]) and 30<length<150:
    examples.append({'block':i,'edge':e,'source_offset':off,'record_offset':p[5][0]+14*e,'hex':a.hex(),'endpoints_integer':[first[u],second[v]],'length_field':length,'chord_m':dist})
 report[ext]={'counts':dict(tally),'candidates_NOT_geographically_verified':examples}
 print(ext,tally)
(out/'evidence/graph_audit.json').write_text(json.dumps(report,indent=2))

