from independent_verify import *
from collections import defaultdict,Counter
pairs=defaultdict(list)
for block,nodes,other,lines in independent_blocks():
 for r in lines:
  if r['flags']&0x3000:
   a,b=r['points'][0],r['points'][-1];pairs[tuple(sorted((a,b)))].append(r)
counts=Counter();examples=[]
for key,rows in pairs.items():
 counts['groups_'+str(len(rows))]+=1
 if len(rows)==2:
  a,b=rows;points=b['points'] if a['points'][0]==b['points'][0] else list(reversed(b['points']))
  counts['equal_length_field']+=a['length_raw']==b['length_raw'];counts['equal_full_polyline']+=a['points']==points
  if a['points']!=points and len(examples)<20:examples.append({'a':a,'b':b})
print(counts);(HERE/'evidence/reciprocal_border_edges.json').write_text(json.dumps({'counts':dict(counts),'mismatches':examples},indent=2))
