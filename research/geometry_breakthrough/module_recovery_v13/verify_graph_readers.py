#!/usr/bin/env python3
"""Execute actual recovered SH4 through pypcode on one original MP0 block.
Minimal fail-closed p-code interpreter; not a CE emulator. Only the independently
resolved COREDLL ordinal 1044 memcpy thunk is modeled as an external call.
"""
import hashlib,json,struct,zlib
from pathlib import Path
import pypcode
ROOT=Path(__file__).resolve().parent
class Machine:
 def __init__(self):
  self.ctx=pypcode.Context('SuperH4:LE:32:default');self.mem={};self.reg={};self.unique={};self.cache={};self.executed=set();self.steps=0;self.hooks=0
  p=ROOT/'modules/NavigationRem.dll';j=json.loads((p/'module.json').read_text());self.j=j
  self.sections=[(s,(p/('section_%d.bin'%s['index'])).read_bytes()) for s in j['sections']]
 def norm(self,a):
  for s,b in self.sections:
   if self.j['link_base']+s['rva']<=a<self.j['link_base']+s['rva']+s['virtual_size']:return s['runtime_va']+a-self.j['link_base']-s['rva']
  return a
 def readmem(self,a,n):
  if all(a+i in self.mem for i in range(n)):return bytes(self.mem[a+i] for i in range(n))
  for s,b in self.sections:
   o=self.norm(a)-s['runtime_va']
   if 0<=o and o+n<=len(b):return b[o:o+n]
  raise ValueError('unmapped emulated read %x size %d'%(a,n))
 def putmem(self,a,b):
  for i,v in enumerate(b):self.mem[a+i]=v
 def get(self,v):
  if v.space.name=='const':return v.offset
  if v.space.name=='ram':return int.from_bytes(self.readmem(v.offset,v.size),'little')
  store={'register':self.reg,'unique':self.unique}.get(v.space.name)
  if store is None:raise ValueError('unexpected varnode space')
  return sum(store.get(v.offset+i,0)<<(i*8) for i in range(v.size))
 def set(self,v,x):
  store={'register':self.reg,'unique':self.unique}[v.space.name];x&=(1<<(v.size*8))-1
  for i in range(v.size):store[v.offset+i]=(x>>(8*i))&255
 def r(self,k):return self.get(self.ctx.registers[k])
 def w(self,k,v):self.set(self.ctx.registers[k],v)
 def run(self,entry,src,count,outsize,setup=None,stop=0xffff0000):
  self.mem={};self.reg={};self.unique={};self.steps=0;self.hooks=0;self.executed=set()
  self.putmem(0x10000000,src);self.putmem(0x11000000,b'\xa5'*outsize);self.putmem(0x12000000,b'\0'*0x2000)
  self.w('r4',0x11000000);self.w('r5',count);self.w('r6',0x10000000);self.w('r15',0x12001000);self.w('PR',0xffff0000);pc=entry
  if setup:setup(self)
  while pc!=stop:
   self.steps+=1
   if self.steps>3000000:raise ValueError('step limit')
   pc=self.norm(pc);self.executed.add(pc)
   if pc not in self.cache:self.cache[pc]=self.ctx.translate(self.readmem(pc,8),pc,max_instructions=1).ops
   ops=self.cache[pc];nextpc=pc+2;idx=0
   while idx<len(ops):
    op=ops[idx];name=str(op.opcode).split('.')[-1];ins=op.inputs;vals=[x.offset if x.space.name=='ram' and name in ['IMARK','BRANCH','CBRANCH','CALL'] else self.get(x) for x in ins];v=None
    def signed(x,size):return x-(1<<(8*size)) if x&(1<<(8*size-1)) else x
    if name=='IMARK':nextpc=max(x.offset+x.size for x in ins)
    elif name=='COPY':v=vals[0]
    elif name=='LOAD':v=int.from_bytes(self.readmem(vals[1],op.output.size),'little')
    elif name=='STORE':self.putmem(vals[1],vals[2].to_bytes(ins[2].size,'little'))
    elif name=='INT_ADD':v=vals[0]+vals[1]
    elif name=='INT_SUB':v=vals[0]-vals[1]
    elif name=='INT_MULT':v=vals[0]*vals[1]
    elif name=='INT_LEFT':v=vals[0]<<vals[1]
    elif name=='INT_RIGHT':v=vals[0]>>vals[1]
    elif name=='INT_SRIGHT':v=signed(vals[0],ins[0].size)>>vals[1]
    elif name=='INT_AND':v=vals[0]&vals[1]
    elif name=='INT_OR':v=vals[0]|vals[1]
    elif name=='INT_XOR':v=vals[0]^vals[1]
    elif name=='INT_EQUAL':v=int(vals[0]==vals[1])
    elif name=='INT_NOTEQUAL':v=int(vals[0]!=vals[1])
    elif name=='INT_LESS':v=int(vals[0]<vals[1])
    elif name=='INT_LESSEQUAL':v=int(vals[0]<=vals[1])
    elif name=='INT_SLESS':v=int(signed(vals[0],ins[0].size)<signed(vals[1],ins[1].size))
    elif name=='INT_SLESSEQUAL':v=int(signed(vals[0],ins[0].size)<=signed(vals[1],ins[1].size))
    elif name=='INT_ZEXT':v=vals[0]
    elif name=='INT_SEXT':v=signed(vals[0],ins[0].size)
    elif name=='BOOL_NEGATE':v=int(not vals[0])
    elif name in ['BRANCH','CBRANCH','RETURN','BRANCHIND']:
     if name!='CBRANCH' or vals[1]:
      if ins[0].space.name=='const':idx+=signed(vals[0],ins[0].size);continue
      nextpc=vals[0];break
    elif name in ['CALL','CALLIND']:
     target=self.norm(vals[0])
     if target!=0x2ff87cc:raise ValueError('unmodeled call %x'%target)
     self.putmem(self.r('r4'),self.readmem(self.r('r5'),self.r('r6')));self.w('r0',self.r('r4'));self.hooks+=1
    else:raise ValueError('unsupported pcode '+name)
    if v is not None:self.set(op.output,v)
    idx+=1
   pc=nextpc
  return self.readmem(0x11000000,outsize),dict(translations_executed=self.steps,memcpy_hooks=self.hooks,unique_instruction_addresses=len(self.executed))

def main():
 project=ROOT.parents[2];source=project/'NCDR_ASTRA_TRANSFER/originals/NCDR/SW/DB/EUZ.MP0';b=source.read_bytes();digest=hashlib.sha256(b).hexdigest();assert digest=='73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e'
 off,usize,csize=struct.unpack_from('<IHH',b,130);raw=zlib.decompress(b[off:off+csize]);assert len(raw)==usize
 pairs=list(struct.iter_unpack('<HH',raw[:44]));nodeoff,nodes=pairs[4];edgeoff,edges=pairs[5];assert edgeoff-nodeoff==nodes*10 and pairs[6][0]-edgeoff==edges*14
 machine=Machine();nodebytes=raw[nodeoff:edgeoff];edgebytes=raw[edgeoff:edgeoff+edges*14]
 gotn,nstats=machine.run(0x304d848,nodebytes,nodes,nodes*10);assert gotn==nodebytes
 gote,estats=machine.run(0x304d8a0,edgebytes,edges,edges*16)
 expected=b''.join(x[:10]+b'\xa5\xa5'+x[10:] for x in [edgebytes[i:i+14] for i in range(0,len(edgebytes),14)])
 assert gote==expected
 probes=[]
 for field in [4,5]:
  for value in [0,1,2,15,16,64,127,128,255]:
   a=bytearray(edgebytes[:14]);a[field]=value;got,stat=machine.run(0x304d8a0,bytes(a),1,16);assert got==a[:10]+b'\xa5\xa5'+a[10:];probes.append(dict(field=field,value=value,pass_through=True))
 def cover_setup(m):
  m.putmem(0x13000000,b'\0'*0x40);m.putmem(0x1300002c,struct.pack('<I',0x12345000))
  m.putmem(0x14000000,b'\0'*0x40);m.putmem(0x14000034,struct.pack('<I',0x10000000))
  for reg,value in [('r8',0x13000000),('r10',0x11000000),('r11',0x14000000),('r12',0)]:m.w(reg,value)
 cover,cstats=machine.run(0x301fd18,gote[:16],0,32,setup=cover_setup,stop=0x301fd3a)
 assert cover[4:8]==edgebytes[:4] and cover[16:18]==edgebytes[4:6]
 out=ROOT/'routing';(out/'mp0_block0.bin').write_bytes(raw);(out/'block0_runtime_edges.bin').write_bytes(gote)
 report=dict(source_relative=str(source.relative_to(project)),source_sha256=digest,source_unchanged=hashlib.sha256(source.read_bytes()).hexdigest()==digest,block=0,compressed_offset=off,compressed_size=csize,raw_size=usize,raw_sha256=hashlib.sha256(raw).hexdigest(),node_section_offset=nodeoff,node_count=nodes,edge_section_offset=edgeoff,edge_count=edges,node_routine='0x0304d848',edge_routine='0x0304d8a0',node_replay=nstats,edge_replay=estats,node_exact=True,edge_exact=True,padding_10_11='untouched sentinel A5 A5; NOT zeroed or copied',attribute_probes=probes,attribute_forwarding=dict(start='0x0301fd18',stop_before='0x0301fd3a',edge4_to_cover16=True,edge5_to_cover17=True,execution=cstats),limitation='Static pcode replay on one block and 18 mutations; modeled memcpy only; no OS/hardware or route execution.')
 (out/'reader_verification.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ['attribute_probes']},indent=2))
if __name__=='__main__':main()
