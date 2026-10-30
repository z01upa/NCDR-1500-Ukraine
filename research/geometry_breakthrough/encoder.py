"""Experimental MP0 shape-tail encoder. Not a complete navigation-map Writer."""
from decoder import decode_mp0_polylines
import struct

def encode_shapes(raw,lines):
 original=decode_mp0_polylines(raw)
 if len(lines)!=len(original):raise ValueError('edge count changed')
 chunks=[]
 for base,row in zip(original,lines):
  pts=row['coordinates_integer'];old=base['coordinates_integer']
  if row['edge']!=base['edge'] or row['flags']!=base['flags'] or pts[0]!=old[0] or pts[-1]!=old[-1]:raise ValueError('topology mutation is unsupported')
  if not base['flags']&0x8000:
   if pts!=old:raise ValueError('cannot add shape to unflagged edge')
   continue
  chunk=bytearray()
  for (x,y),(xx,yy) in zip(pts,pts[1:-1]):
   dx,dy=xx-x,yy-y
   if not(-32768<=dx<=32767 and -32768<=dy<=32767):raise ValueError('shape delta overflow')
   chunk.extend(struct.pack('<hh',dx,dy))
  chunks.append(bytes(chunk))
 offsets=[2*(len(chunks)+1)]
 for chunk in chunks:offsets.append(offsets[-1]+len(chunk))
 if offsets[-1]>65535:raise ValueError('shape section overflow')
 tail=struct.pack('<'+'H'*len(offsets),*offsets)+b''.join(chunks);start=struct.unpack_from('<H',raw,40)[0]
 result=bytearray(raw[:start]+tail)
 if len(result)>65535:raise ValueError('block overflow')
 struct.pack_into('<HH',result,42,len(chunks),len(tail))
 return bytes(result)
