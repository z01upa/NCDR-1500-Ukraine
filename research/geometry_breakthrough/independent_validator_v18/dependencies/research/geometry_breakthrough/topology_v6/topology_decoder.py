"""Independent, lossless EUZ.MP0 Section4 topology reader. Standard library only.
No imports from existing Reader, Writer, geometry, or topology implementations.
"""
from dataclasses import dataclass
from pathlib import Path
import os
import struct,zlib
SOURCE=Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[7])) / 'SW' / 'DB' / 'EUZ.MP0'
EXPECTED='73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e'

def read_blocks(data):
 if len(data)<114 or not data.startswith(b'(*$SIEMENS&^)') :raise ValueError('MP0 header')
 n=int.from_bytes(data[86:90],'little');end=114+28*n
 if int.from_bytes(data[112:114],'little')!=n or end>len(data):raise ValueError('index header')
 ranges=[]
 for i in range(n):
  at=114+24*i+16;offset,decoded,packed=struct.unpack_from('<IHH',data,at)
  if offset<end or offset+packed>len(data):raise ValueError('extent')
  stream=zlib.decompressobj();b=stream.decompress(data[offset:offset+packed],decoded+1)
  if not stream.eof or stream.unused_data or stream.unconsumed_tail or len(b)!=decoded:raise ValueError('compressed stream')
  ranges.append((offset,offset+packed));yield i,b
 ranges.sort()
 if ranges and (ranges[0][0]!=end or ranges[-1][1]!=len(data) or any(a[1]!=b[0] for a,b in zip(ranges,ranges[1:]))):raise ValueError('stream coverage')

def layout(b):
 if len(b)<46:raise ValueError('short block')
 pairs=[struct.unpack_from('<HH',b,4*i) for i in range(11)];s=[p[0] for p in pairs];c=[p[1] for p in pairs]
 if s[0]!=46 or s!=sorted(s) or s[-1]+int.from_bytes(b[44:46],'little')!=len(b):raise ValueError('section bounds')
 if s[5]-s[4]!=c[4]*10 or s[6]-s[5]!=c[5]*14 or c[0]!=c[4]:raise ValueError('record strides/count')
 return s,c

@dataclass(frozen=True)
class Node:
 physical_id:int
 logical_id:int
 degree:int
 upper_nibble:int
 byte1:int
 opaque_prefix:bytes
 edges:tuple
 opaque_suffix:bytes
 @property
 def physical_span(self):return 1 if self.degree<=4 else 2
 @property
 def continuation_id(self):return self.physical_id+1 if self.physical_span==2 else None

def decode_section4(section,edge_count):
 if len(section)%10:raise ValueError('unaligned section4')
 nodes=[];physical=0
 while physical<len(section)//10:
  pos=physical*10;degree=section[pos]&15
  if not 1<=degree<=7:raise ValueError('unsupported real head degree; degree0 has no proven representation')
  span=10 if degree<=4 else 20;start=2 if degree<=4 else 4
  if pos+span>len(section):raise ValueError('truncated continuation')
  refs=struct.unpack_from('<'+'H'*degree,section,pos+start)
  if any(e>=edge_count for e in refs):raise ValueError('edge index out of bounds')
  nodes.append(Node(physical,len(nodes),degree,section[pos]&240,section[pos+1],section[pos+2:pos+start],refs,section[pos+start+2*degree:pos+span]))
  physical+=span//10
 return nodes

def encode_section4(nodes):
 """Lossless assembly from known fields plus explicit opaque spans, not raw-record copying."""
 out=bytearray();logical=0
 for n in nodes:
  if n.physical_id!=len(out)//10 or n.logical_id!=logical or not 1<=n.degree<=7 or len(n.edges)!=n.degree:raise ValueError('identity/count/layout')
  prefix_len=0 if n.degree<=4 else 2;span=n.physical_span*10;start=2+prefix_len
  if len(n.opaque_prefix)!=prefix_len or len(n.opaque_suffix)!=span-start-2*n.degree:raise ValueError('opaque span size')
  if n.upper_nibble&15 or not 0<=n.upper_nibble<=240 or not 0<=n.byte1<=255:raise ValueError('header fields')
  out.extend(bytes([n.upper_nibble|n.degree,n.byte1]));out.extend(n.opaque_prefix);out.extend(struct.pack('<'+'H'*n.degree,*n.edges));out.extend(n.opaque_suffix);logical+=1
 return bytes(out)

def endpoint_oracle(b):
 """Independent endpoint-side oracle; does not inspect Section4 adjacency bytes."""
 s,c=layout(b);expected=[]
 for edge in range(c[5]):
  p=s[5]+14*edge;flags=int.from_bytes(b[p:p+2],'little')
  for side,off,mask in [('A',6,4096),('B',8,8192)]:
   table='secondary' if flags&mask else 'primary';index=int.from_bytes(b[p+off:p+off+2],'little')
   if index >= (c[2] if table=='secondary' else c[4]):raise ValueError('endpoint bounds')
   expected.append((edge,side,table,index))
 return expected

def coordinate_tables(b):
 # Identity matching candidate generation only; actual remote identity comes from paired edge records.
 s,c=layout(b);tables=[]
 for k in [0,2]:
  p=s[k];pts=[]
  while p<s[k+1]:
   if p+10>s[k+1]:raise ValueError('coordinate run')
   n,x,y=struct.unpack_from('<Hii',b,p);p+=10;pts.append((x,y))
   if p+4*n>s[k+1]:raise ValueError('coordinate delta bounds')
   for _ in range(n):
    dx,dy=struct.unpack_from('<Hh' if k==0 else '<hh',b,p);p+=4;x+=dx;y+=dy;pts.append((x,y))
  if p!=s[k+1] or len(pts)!=c[k]:raise ValueError('coordinate count')
  tables.append(pts)
 return tables

def transition_plan(node,new_edge_id):
 if node.degree==3:
  return {'allowed':False,'transition':'3->4','known_changes':['byte0 low nibble 3->4','edge word at +8/+9'],'opaque_conflict_hex':node.opaque_suffix.hex(),'blocker':'+8/+9 semantics unknown; other header bits may depend on degree/link order'}
 if node.degree==4:
  return {'allowed':False,'transition':'4->5','known_changes':['byte0 low nibble 4->5','reserve UNKNOWN +2/+3','move old links to contiguous u16 words starting +4','append fifth link at continuation +2','insert next 10-byte physical continuation and duplicate primary coordinate','reindex subsequent physical primary IDs and all consumers'],'blocker':'opaque initialization/header semantics and external consumers unknown'}
 return {'allowed':False,'blocker':'no connectivity mutation is implemented'}

