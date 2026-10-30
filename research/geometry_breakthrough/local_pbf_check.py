"""Read-only minimal OSM PBF overlap check. Only dense nodes needed for exclusion."""
from pathlib import Path
import struct,zlib,json,hashlib,time
HERE=Path(__file__).parent
SOURCE=HERE.parents[1]/'data/osm/ukraine-latest.osm.pbf'
def varints(b):
 v=s=0
 for c in b:
  v|=(c&127)<<s
  if c<128:yield v;v=s=0
  else:s+=7
 if s:raise ValueError('truncated varint')
def zig(v):return (v>>1)^-(v&1)
def fields(b):
 p=0
 def one():
  nonlocal p
  v=s=0
  while True:
   c=b[p];p+=1;v|=(c&127)<<s
   if c<128:return v
   s+=7
 while p<len(b):
  tag=one();num=tag>>3;wire=tag&7
  if wire==0:yield num,one()
  elif wire==2:
   n=one();v=b[p:p+n];p+=n;yield num,v
  elif wire==1:p+=8
  elif wire==5:p+=4
  else:raise ValueError('wire')
count=0;hits=[];nearest=180.;started=time.time();sha=hashlib.sha256()
with SOURCE.open('rb') as fh:
 while True:
  head=fh.read(4)
  if not head:break
  h=fh.read(struct.unpack('>I',head)[0]);hd=dict(fields(h));data=fh.read(hd[3]);sha.update(head+h+data);blob=dict(fields(data));raw=blob.get(1) or zlib.decompress(blob[3])
  if hd[1]!=b'OSMData':continue
  fs=list(fields(raw));gran=next((v for k,v in fs if k==17),100);lat0=next((v for k,v in fs if k==19),0);lon0=next((v for k,v in fs if k==20),0)
  for k,group in fs:
   if k!=2:continue
   for kind,value in fields(group):
    if kind!=2:continue
    dense=dict(fields(value));node=lat=lon=0
    for di,dy,dx in zip(varints(dense[1]),varints(dense[8]),varints(dense[9])):
     node+=zig(di);lat+=zig(dy);lon+=zig(dx);count+=1
     y=(lat0+lat*gran)*1e-9;x=(lon0+lon*gran)*1e-9
     if 48.60<=y<=48.85 and 21.95<=x<=22.4:hits.append([node,x,y])
  if count and count%1000000<8000:print('nodes',count,'seconds',round(time.time()-started),flush=True)
r={'source':str(SOURCE),'sha256':sha.hexdigest(),'dense_nodes_examined':count,'query_bbox':[21.95,48.60,22.4,48.85],'nodes':hits,'elapsed_seconds':time.time()-started};(HERE/'evidence/local_osm_overlap_nodes.json').write_text(json.dumps(r));print('DONE',count,'hits',len(hits),flush=True)
