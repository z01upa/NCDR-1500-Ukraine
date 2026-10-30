from independent_verify import *
from collections import Counter
counts=Counter();samples=[]
for i,nodes,other,lines in independent_blocks():
 pts=[(x,y) for x,y in nodes if 2200000<=x<=3100000 and 4400000<=y<=5300000]
 counts['nodes_in_broad_ukraine_bbox']+=len(pts)
 if pts:samples.append({'block':i,'count':len(pts),'min':[min(x for x,y in pts),min(y for x,y in pts)],'max':[max(x for x,y in pts),max(y for x,y in pts)]})
print(counts,samples[:15]);(HERE/'evidence/local_reference_overlap.json').write_text(json.dumps({'counts':dict(counts),'blocks':samples,'available_osm':'data/osm/ukraine-latest.osm.pbf and kryvyi_rih_20261025.osm; broad bbox is only an overlap screen'},indent=2))
