from decoder_v1_unsigned_secondary import *
import math
from collections import Counter
out=Path(__file__).parent;counts=Counter();exceptions=[]
for i,box,off,c,raw in blocks((ROOT/'EUZ.MP0').read_bytes(),True):
 p=list(struct.iter_unpack('<HH',raw[:44]));secondary=[];pos=p[2][0]
 while pos<p[3][0]:
  n,x,y=struct.unpack_from('<Hii',raw,pos);pos+=10;secondary.append((x,y))
  for _ in range(n):dx,dy=struct.unpack_from('<hh',raw,pos);pos+=4;x+=dx;y+=dy;secondary.append((x,y))
 for row in decode_mp0_polylines(raw):
  pts=row['coordinates_integer'];e=row['edge'];f=row['flags'];u,v=struct.unpack_from('<HH',raw,p[5][0]+14*e+6)
  if f&0x1000:
   x,y=secondary[u];ox,oy=pts[0];pts=[(xx+x-ox,yy+y-oy) for xx,yy in pts[:-1]]+[pts[-1]]
  if f&0x2000:pts[-1]=secondary[v]
  m=sum(math.hypot((xx-x)*math.cos((y+yy)/200000*math.pi/180),yy-y)*1.11195 for (x,y),(xx,yy) in zip(pts,pts[1:]));l=row['length_field']*.3048;kind='secondary' if f&0x3000 else 'primary';counts[kind+'_total']+=1
  if abs(m-l)>max(5,l*.02):
   counts[kind+'_mismatch']+=1
   exceptions.append(dict(row,block=i,source_offset=off,measured_m=m,expected_feet_m=l))
print(counts);(out/'evidence/signed_secondary_audit.json').write_text(json.dumps({'counts':dict(counts),'exceptions':exceptions},indent=2))

