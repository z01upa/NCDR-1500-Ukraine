from decoder_v1_unsigned_secondary import *
from collections import Counter
import math
counts=Counter();bad=[]
for i,box,off,c,raw in blocks((ROOT/'EUZ.MP0').read_bytes(),True):
 for row in decode_mp0_polylines(raw):
  pts=row['coordinates_integer'];m=sum(math.hypot((xx-x)*math.cos((y+yy)/200000*math.pi/180),yy-y)*1.11195 for (x,y),(xx,yy) in zip(pts,pts[1:]));l=row['length_field']*.3048;kind='secondary' if row['flags']&0x3000 else 'primary'
  counts[kind+'_total']+=1
  if abs(m-l)>max(5,l*.02):
   counts[kind+'_length_mismatch']+=1
   if len(bad)<20:bad.append(dict(row,block=i,calculated_m=m))
print(counts);(Path(__file__).parent/'evidence/length_exceptions.json').write_text(json.dumps({'counts':dict(counts),'first_20':bad},indent=2))

