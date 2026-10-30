from decoder import *
from collections import defaultdict,Counter
out=Path(__file__).parent;data=(ROOT/'EUZ.MP0').read_bytes();main=defaultdict(list);secondary=[];degree=Counter()
for i,box,off,c,raw in blocks(data,True):
 p=list(struct.iter_unpack('<HH',raw[:44]));nodes,_=decode_runs(raw,p[0][0],p[1][0],p[0][1])
 for n,xy in enumerate(nodes):main[xy].append((i,n))
 pos=p[2][0]
 while pos<p[3][0]:
  n,x,y=struct.unpack_from('<Hii',raw,pos);pos+=10;secondary.append((i,(x,y)))
  for _ in range(n):dx,dy=struct.unpack_from('<hh',raw,pos);pos+=4;x+=dx;y+=dy;secondary.append((i,(x,y)))
counts=Counter();miss=[];examples=[]
for i,xy in secondary:
 matches=[j for j in main.get(xy,[]) if j[0]!=i];counts['secondary_points']+=1
 if matches:
  counts['exact_other_block_main_match']+=1
  if len(examples)<20:examples.append({'source_block':i,'xy':xy,'matching_nodes':matches})
 else:
  counts['no_exact_other_block_main_match']+=1
  if len(miss)<20:miss.append({'source_block':i,'xy':xy})
print(counts);(out/'evidence/crossblock_audit.json').write_text(json.dumps({'counts':dict(counts),'matches':examples,'unmatched':miss},indent=2))
