"""Independent original-file MP0 parser and all-edge validation. No decoder imports."""
from pathlib import Path
import os
import struct,zlib,json,math,hashlib,statistics
from collections import Counter,defaultdict
HERE=Path(__file__).parent
SOURCE=Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[2])) / 'SW' / 'DB' / 'EUZ.MP0'
def word(b,o,n=2,signed=False):return int.from_bytes(b[o:o+n],'little',signed=signed)
def coords(b,start,end,expected,signed_x):
 result=[];p=start
 while p<end:
  count=word(b,p);x=word(b,p+2,4,True);y=word(b,p+6,4,True);p+=10;result.append((x,y))
  for _ in range(count):
   x+=word(b,p,2,signed_x);y+=word(b,p+2,2,True);p+=4;result.append((x,y))
 if p!=end or len(result)!=expected:raise ValueError('coordinate bounds/count')
 return result

def independent_blocks(source=SOURCE):
 d=Path(source).read_bytes();n=word(d,86,4)
 for block in range(n):
  ix=114+block*24;offset=word(d,ix+16,4);usize=word(d,ix+20);csize=word(d,ix+22)
  b=zlib.decompress(d[offset:offset+csize]);assert len(b)==usize
  sections=[word(b,4*j) for j in range(11)];counts=[word(b,4*j+2) for j in range(11)]
  main=coords(b,sections[0],sections[1],counts[0],False);other=coords(b,sections[2],sections[3],counts[2],True)
  shape=b[sections[10]:];ixs=[word(shape,2*j) for j in range(counts[10]+1)]
  assert ixs[0]==2*(counts[10]+1) and ixs[-1]==len(shape)==word(b,44)
  lines=[];shape_no=0
  for edge in range(counts[5]):
   p=sections[5]+edge*14;flags=word(b,p);a=other if flags&4096 else main;z=other if flags&8192 else main
   u,v=word(b,p+6),word(b,p+8);x,y=a[u];points=[(x,y)]
   if flags&32768:
    lo,hi=ixs[shape_no:shape_no+2];assert lo<=hi and (hi-lo)%4==0
    for k in range(lo,hi,4):x+=word(shape,k,2,True);y+=word(shape,k+2,2,True);points.append((x,y))
    shape_no+=1
   points.append(z[v]);lines.append({'block':block,'edge':edge,'flags':flags,'length_raw':word(b,p+10,4),'points':points,'source_offset':offset,'record_offset':p,'record_hex':b[p:p+14].hex()})
  assert shape_no==counts[10]
  yield block,main,other,lines

def distance(points):
 total=0
 for (x,y),(xx,yy) in zip(points,points[1:]):
  a,c=math.radians(y/1e5),math.radians(yy/1e5);dp=c-a;dl=math.radians((xx-x)/1e5)
  h=math.sin(dp/2)**2+math.cos(a)*math.cos(c)*math.sin(dl/2)**2
  total+=12742017.6*math.asin(min(1,math.sqrt(h)))
 return total

def main():
 stats=defaultdict(Counter);ratios=[];exceptions=[];features=[];primary_exceptions=[]
 for block,nodes,other,lines in independent_blocks():
  for k,row in enumerate(lines):
   m=distance(row['points']);raw=row['length_raw'];group='secondary' if row['flags']&0x3000 else 'primary';fold='even_holdout' if block%2==0 else 'odd_discovery'
   for name in ['all',group,fold]:
    s=stats[name];s['total']+=1
    for label,scale,val in [('feet',.3048,raw),('metres',1.,raw),('shuffled_feet',.3048,lines[(k+1)%len(lines)]['length_raw'])]:
     target=scale*val;s[label+'_within_5m_or_2pct']+=abs(m-target)<=max(5,target*.02)
   if raw:ratios.append(m/raw)
   if abs(m-raw*.3048)>max(5,raw*.3048*.02):
    exc=dict(row,measured_haversine_m=m,feet_m=raw*.3048);exceptions.append(exc)
    if group=='primary':primary_exceptions.append(exc)
   # Representative selection uses block and vertex count, NEVER length agreement.
   if block in [0,1,2] and len(row['points'])>=4 and not any(f['properties']['block']==block for f in features):
    props={k:v for k,v in row.items() if k!='points'};props.update({'independent_geography_confirmed':False,'selection':'first edge with >=4 vertices in block 0,1,2; no length filter','calculated_m':m})
    features.append({'type':'Feature','properties':props,'geometry':{'type':'LineString','coordinates':[[x/1e5,y/1e5] for x,y in row['points']]}})
 r={'source':str(SOURCE),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),'counts':{k:dict(v) for k,v in stats.items()},'median_metres_per_raw_unit':statistics.median(ratios),'primary_exceptions':primary_exceptions,'exceptions':exceptions,'selection':'ALL edges, no geography or length prefilter; fixed block parity holdout; cyclic edge-length permutation within each block as negative control'}
 (HERE/'evidence/independent_validation.json').write_text(json.dumps(r,indent=2));(HERE/'candidate_roads_UNCONFIRMED.geojson').write_text(json.dumps({'type':'FeatureCollection','features':features},indent=2));print({k:v for k,v in r.items() if k not in ['exceptions','primary_exceptions']})
if __name__=='__main__':main()

