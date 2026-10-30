"""Border identity check using edge records and physical head IDs; never merge equal-coordinate nodes."""
from node_graph_probe import *
from node_graph_probe import _read_container,_sections
data,blocks=_read_container(SOURCE);groups=defaultdict(list)
for bi,b in enumerate(blocks):
 heads,owners=decode_node_links(b);s,c=_sections(b);a,z=coordinates(b)
 for e in range(c[5]):
  at=s[5]+14*e;flags,attr,opaque,u,v,length=struct.unpack_from('<5HI',b,at)
  if not flags&0x3000:continue
  points=[z[u] if flags&4096 else a[u],z[v] if flags&8192 else a[v]]
  ids=[('secondary',u) if flags&4096 else ('primary',u),('secondary',v) if flags&8192 else ('primary',v)]
  groups[(tuple(sorted(points)),length,flags&~0x3000,attr,opaque)].append({'block':bi,'edge':e,'ids':ids,'points':points,'primary_is_head':all(table!='primary' or n in heads for table,n in ids)})
counts=Counter();fail=[];examples=[]
for key,rows in groups.items():
 counts['group_size_'+str(len(rows))]+=1
 if len(rows)!=2:continue
 a,b=rows
 if a['block']==b['block']:counts['same_block_pair']+=1;continue
 for src,dst in [(a,b),(b,a)]:
  for side,(table,node) in enumerate(src['ids']):
   if table!='secondary':continue
   matches=[idx for idx,(typ,n) in enumerate(dst['ids']) if typ=='primary' and dst['points'][idx]==src['points'][side]]
   counts['secondary_endpoints_checked']+=1
   if len(matches)==1 and dst['primary_is_head']:
    counts['edge_backed_unique_remote_head']+=1
    if len(examples)<10:examples.append({'source':[src['block'],src['edge'],table,node],'target':[dst['block'],dst['edge'],*dst['ids'][matches[0]]],'matching_rule':'both endpoints+length+flags excluding table selectors+attributes; select actual primary endpoint ID of paired edge'})
   else:fail.append([src,dst])
r={'counts':dict(counts),'failures':fail,'examples':examples,'limits':'Matching is restricted to unique two-copy cross-block edge signatures. Larger groups are not resolved. Coordinate equality is only a candidate constraint, never identity by itself.'}
(HERE/'evidence/border_identity.json').write_text(json.dumps(r,indent=2));print(counts,'failures',len(fail))

