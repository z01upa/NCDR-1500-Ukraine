from independent_verify import *
from collections import defaultdict,Counter
SCALE_X=111195*math.cos(math.radians(48.72));SCALE_Y=111195

def project(p):return (p[0]*SCALE_X,p[1]*SCALE_Y)
def dseg(p,a,b):
 dx=b[0]-a[0];dy=b[1]-a[1];den=dx*dx+dy*dy;t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den)) if den else 0
 return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
def samples(points):
 out=[]
 for a,b in zip(points,points[1:]):
  n=max(1,math.ceil(math.dist(a,b)/20))
  out.extend((a[0]+(b[0]-a[0])*k/n,a[1]+(b[1]-a[1])*k/n) for k in range(n))
 return out+[points[-1]]
ways=json.loads((HERE/'evidence/local_osm_highways.json').read_text())['ways'];grid=defaultdict(list);segments=[];lookup={w['id']:w for w in ways}
for w in ways:
 if w['tags']['highway'] in ['footway','path','steps','cycleway','construction','proposed']:continue
 for part in w['parts']:
  p=list(map(project,part))
  for a,b in zip(p,p[1:]):
   idx=len(segments);segments.append((a,b,w['id']))
   for x in range(math.floor(min(a[0],b[0])/100),math.floor(max(a[0],b[0])/100)+1):
    for y in range(math.floor(min(a[1],b[1])/100),math.floor(max(a[1],b[1])/100)+1):grid[x,y].append(idx)
def residuals(points,shift=0):
 ds=[];ids=[]
 for x,y in samples(points):
  p=(x+shift,y);cell=(math.floor(p[0]/100),math.floor(p[1]/100));indices=set()
  for dx in [-1,0,1]:
   for dy in [-1,0,1]:indices.update(grid.get((cell[0]+dx,cell[1]+dy),[]))
  best=min(((dseg(p,segments[k][0],segments[k][1]),segments[k][2]) for k in indices),default=(1e6,0));ds.append(best[0]);ids.append(best[1])
 return ds,ids
metrics=[];candidates=[]
for block,nodes,other,lines in independent_blocks():
 if block!=886:continue
 for row in lines:
  ll=[(x/1e5,y/1e5) for x,y in row['points']]
  if len(ll)<4 or not all(21.95<=x<=22.4 and 48.6<=y<=48.85 for x,y in ll):continue
  points=list(map(project,ll));length=distance(row['points'])
  if length<100:continue
  ds,ids=residuals(points);control,_=residuals(points,500)
  m={'block':block,'edge':row['edge'],'vertices':len(ll),'length_m':length,'sample_count':len(ds),'median_residual_m':statistics.median(ds),'max_residual_m':max(ds),'shift500_median_m':statistics.median(control),'osm_way_ids':sorted(set(ids))}
  metrics.append(m)
  if max(ds)<25 and statistics.median(ds)<10 and statistics.median(control)>40:candidates.append((m,row,ll))
print('tested',len(metrics),'matches',len(candidates));print(sorted(metrics,key=lambda m:m['max_residual_m'])[:6])
selected=[]
for m,r,ll in sorted(candidates,key=lambda item:item[0]['max_residual_m']):
 if any(set(m['osm_way_ids'])&set(old[0]['osm_way_ids']) for old in selected):continue
 selected.append((m,r,ll))
 if len(selected)==3:break
features=[];refs=[]
for m,r,ll in selected:
 details=[{'id':i,'tags':lookup[i]['tags']} for i in m['osm_way_ids'] if i in lookup];props=dict(m,reference_ways=details,validation='local OSM fixed-position point-to-road comparison, no transform fit',source_offset=r['source_offset'],record_offset=r['record_offset'],record_hex=r['record_hex']);features.append({'type':'Feature','properties':props,'geometry':{'type':'LineString','coordinates':ll}})
 for i in m['osm_way_ids']:
  if i in lookup:
   w=lookup[i];refs.append({'type':'Feature','properties':{'osm_way_id':i,**w['tags'],'attribution':'OpenStreetMap contributors, ODbL'},'geometry':{'type':'MultiLineString','coordinates':w['parts']}})
(HERE/'evidence/local_comparison.json').write_text(json.dumps({'all_candidate_metrics':metrics,'selected':[f['properties'] for f in features],'selection_rules':'vertex count>=4, length>=100m, fully in local reference window; all candidates reported; match max<25m median<10m; shifted500m median>40m; three disjoint OSM way sets'},indent=2))
(HERE/'locally_matched_roads.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features},indent=2));(HERE/'local_osm_reference.geojson').write_text(json.dumps({'type':'FeatureCollection','features':refs},indent=2))
