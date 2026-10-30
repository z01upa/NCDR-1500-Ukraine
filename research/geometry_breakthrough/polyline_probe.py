from decoder_v1_unsigned_secondary import *
import math
b=(Path(__file__).parent/'evidence/MP0_0.bin').read_bytes();p=list(struct.iter_unpack('<HH',b[:44]));ns,_=decode_runs(b,46,p[1][0],p[0][1]);s,n=p[10];shape=b[s:];offs=struct.unpack_from('<'+str(n+1)+'H',shape);j=0
for e in range(12):
 f,at,k,u,v,l=struct.unpack_from('<5HI',b,p[5][0]+14*e)
 if not f&0x8000:continue
 ds=list(struct.iter_unpack('<hh',shape[offs[j]:offs[j+1]]));j+=1;x,y=ns[u];coords=[(x,y)]
 for dx,dy in ds:x+=dx;y+=dy;coords.append((x,y))
 coords.append(ns[v]);distance=sum(math.hypot((xx-x)*math.cos((y+yy)/200000*math.pi/180),yy-y)*1.11195 for (x,y),(xx,yy) in zip(coords,coords[1:]));print(e,u,v,l,round(distance),coords)

