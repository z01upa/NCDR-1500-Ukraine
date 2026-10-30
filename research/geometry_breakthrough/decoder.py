"""Strict experimental NCDx block index and coordinate-run decoder. No road semantics."""
from pathlib import Path
import os
import struct,zlib,hashlib,json
ROOT=Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[2])) / 'SW' / 'DB'
def blocks(d,interleaved):
 n=struct.unpack_from('<I',d,86)[0]
 for i in range(n):
  bo=114+(24 if interleaved else 16)*i
  po=bo+16 if interleaved else 114+16*n+8*i
  box=struct.unpack_from('<iiii',d,bo);p,u,c=struct.unpack_from('<IHH',d,po)
  if p<114+28*n or p+c>len(d):raise ValueError('block extent')
  z=zlib.decompressobj();raw=z.decompress(d[p:p+c],65537)
  if not z.eof or z.unused_data or z.unconsumed_tail or len(raw)!=u:raise ValueError('zlib extent')
  yield i,box,p,c,raw

def decode_runs(raw,start,end,count,*,signed_x=False):
 pts=[];runs=[];pos=start
 while pos<end:
  if pos+10>end:raise ValueError('truncated run')
  n,x,y=struct.unpack_from('<Hii',raw,pos);pos+=10
  if n+1>count-len(pts) or pos+4*n>end:raise ValueError('run length')
  runs.append({'offset':pos-10,'points':n+1});pts.append((x,y))
  for _ in range(n):
   dx,dy=struct.unpack_from('<hh' if signed_x else '<Hh',raw,pos);pos+=4;x+=dx;y+=dy;pts.append((x,y))
 if pos!=end or len(pts)!=count:raise ValueError('section count')
 return pts,runs

def main():
 result={};out=Path(__file__).parent; (out/'evidence').mkdir(exist_ok=True)
 for ext in ['MP0','MG1','MG2','MG3']:
  d=(ROOT/('EUZ.'+ext)).read_bytes();rows=[];tot=0;fail=[];outside=0
  for i,box,p,c,raw in blocks(d,ext=='MP0'):
   pairs=list(struct.iter_unpack('<HH',raw[:44]));start,count=pairs[0];end=pairs[1][0]
   try:
    pts,runs=decode_runs(raw,start,end,count)
    bad=sum(not(box[0]<=x<=box[2] and box[1]<=y<=box[3]) for x,y in pts)
    outside+=bad;tot+=len(pts)
    rows.append({'index':i,'box':box,'offset':p,'packed_size':c,'raw_size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'points':len(pts),'runs':len(runs),'outside_box':bad})
    if i<3:(out/'evidence'/f'{ext}_{i}.bin').write_bytes(raw)
   except ValueError as e:fail.append([i,str(e)])
  result[ext]={'source':str(ROOT/('EUZ.'+ext)),'source_sha256':hashlib.sha256(d).hexdigest(),'blocks':len(rows),'points':tot,'outside':outside,'failures':fail,'rows':rows}
  print(ext,len(rows),tot,'outside',outside,'fails',fail[:4])
 (out/'evidence'/'coordinate_audit.json').write_text(json.dumps(result,indent=2))
if __name__=='__main__':main()

def decode_mp0_polylines(raw):
 """Recover MP0 candidate polylines; geographic road identity is not certified."""
 p=list(struct.iter_unpack('<HH',raw[:44]));nodes,_=decode_runs(raw,p[0][0],p[1][0],p[0][1]);secondary,_=decode_runs(raw,p[2][0],p[3][0],p[2][1],signed_x=True)
 start,n=p[10];tail=raw[start:];size=struct.unpack_from('<H',raw,44)[0]
 if len(tail)!=size:raise ValueError('tail size')
 offsets=struct.unpack_from('<'+'H'*(n+1),tail)
 if offsets[0]!=2*(n+1) or offsets[-1]!=len(tail) or any(a>b or (b-a)%4 for a,b in zip(offsets,offsets[1:])):raise ValueError('shape offsets')
 if p[6][0]-p[5][0]!=14*p[5][1]:raise ValueError('edge stride')
 shapes=0;lines=[]
 for e in range(p[5][1]):
  f,at,k,u,v,length=struct.unpack_from('<5HI',raw,p[5][0]+14*e)
  a=secondary if f&0x1000 else nodes;b=secondary if f&0x2000 else nodes
  if u>=len(a) or v>=len(b):raise ValueError('endpoint index')
  x,y=a[u];coords=[(x,y)]
  if f&0x8000:
   if shapes>=n:raise ValueError('shape count')
   for dx,dy in struct.iter_unpack('<hh',tail[offsets[shapes]:offsets[shapes+1]]):x+=dx;y+=dy;coords.append((x,y))
   shapes+=1
  coords.append(b[v]);lines.append({'edge':e,'flags':f,'length_field':length,'coordinates_integer':coords,'record_offset':p[5][0]+14*e})
 if shapes!=n:raise ValueError('unused shapes')
 return lines

