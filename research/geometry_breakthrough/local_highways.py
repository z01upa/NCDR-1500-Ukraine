"""Extract local reference highway geometry; no network."""
from pathlib import Path
import json,struct,zlib
HERE=Path(__file__).parent
# Reuse only protobuf helpers; do not rerun the node scan.
ns={'__file__':str(HERE/'local_pbf_check.py')};exec((HERE/'local_pbf_check.py').read_text().split('count=0;hits=')[0],ns)
fields,varints,zig=ns['fields'],ns['varints'],ns['zig'];source=ns['SOURCE']
nodes={r[0]:r[1:] for r in json.loads((HERE/'evidence/local_osm_overlap_nodes.json').read_text())['nodes']};ways=[]
with source.open('rb') as f:
 while h:=f.read(4):
  header=dict(fields(f.read(struct.unpack('>I',h)[0])));blob=dict(fields(f.read(header[3])))
  if header[1]!=b'OSMData':continue
  raw=blob.get(1) or zlib.decompress(blob[3]);fs=list(fields(raw));strings=[]
  for k,v in fs:
   if k==1:strings=[s.decode('utf8') for key,s in fields(v) if key==1]
  for k,g in fs:
   if k!=2:continue
   for kind,b in fields(g):
    if kind!=3:continue
    w=dict(fields(b));tags={strings[a]:strings[z] for a,z in zip(varints(w.get(2,b'')),varints(w.get(3,b'')))}
    if 'highway' not in tags:continue
    refs=[];rid=0
    for v in varints(w.get(8,b'')):rid+=zig(v);refs.append(rid)
    if not any(r in nodes for r in refs):continue
    parts=[];part=[]
    for r in refs:
     if r in nodes:part.append(nodes[r])
     else:
      if len(part)>1:parts.append(part)
      part=[]
    if len(part)>1:parts.append(part)
    if parts:ways.append({'id':w[1],'tags':tags,'parts':parts})
(HERE/'evidence/local_osm_highways.json').write_text(json.dumps({'source':str(source),'attribution':'OpenStreetMap contributors, ODbL','ways':ways}));print('highways',len(ways))

