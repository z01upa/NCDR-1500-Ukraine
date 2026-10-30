"""One paired test of actual SH4 count-query wrapper; reuse v13 interpreter.
Loader stub supplies verified block886 tables; lock/unlock no-op.
0x00FFFB48 returns NULL under asserted zero output count; its body is not tested. No OS emulator.
No output materialization requested (capacity=0), no routing acceptance asserted.
"""
import sys,inspect,textwrap,struct,zlib,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parents[2]
sys.path.insert(0,str(ROOT.parent/'module_recovery_v13'))
from verify_graph_readers import Machine
src=inspect.getsource(Machine.run)
old="""if target!=0x2ff87cc:raise ValueError('unmodeled call %x'%target)
     self.putmem(self.r('r4'),self.readmem(self.r('r5'),self.r('r6')));self.w('r0',self.r('r4'));self.hooks+=1"""
new="""if target in [0x3000e50,0x30002e8]:
      self.w('PR',nextpc);nextpc=target;break
     elif target==0x2fffb48:
      assert self.r('r6')==0;self.w('r0',0);self.hooks+=1
     elif target in [0x301213c,0x301217c]:
      self.w('r0',0);self.hooks+=1
     elif target==0x300d19c:
      assert self.r('r4')==self.test_id and self.r('r5')==6
      self.putmem(self.r('r6'),struct.pack('<I',0x13000000));self.w('r0',0);self.hooks+=1
     else:raise ValueError('unmodeled call %x'%target)"""
assert old in src
scope={"struct":struct};exec(textwrap.dedent(src.replace(old,new).replace("elif name=='INT_ADD':","elif name=='INT_NEGATE':v=~vals[0]\n    elif name=='INT_ADD':")),scope);Machine.run=scope['run']
p=PROJECT/'NCDR_ASTRA_TRANSFER/originals/NCDR/SW/DB/EUZ.MP0'
with p.open('rb') as f:
 f.seek(114+24*886+16);off,usize,packed=struct.unpack('<IHH',f.read(8));f.seek(off);encoded=f.read(packed)
raw=zlib.decompress(encoded);assert len(raw)==usize
assert hashlib.sha256(raw).hexdigest()=='c4fd95701be3301b999d7e8886d08a6d2e8a3461e9f6caa973a5128959d983a6'
pairs=[struct.unpack_from('<HH',raw,4*i) for i in range(11)];tables={};keys={}
for section,stride,padding in [(7,7,1),(8,11,1),(9,13,1)]:
 start,count=pairs[section];rows=[raw[start+i*stride:start+(i+1)*stride] for i in range(count)]
 keys[section]=[struct.unpack_from('<H',x)[0] for x in rows]
 # Matches verified ROM unpacking: u16,+2 byte,padding,+3 u32,remaining words/bytes.
 tables[section]=b''.join(x[:3]+b'\0'+x[3:]+(b'\0\0' if section==9 else b'') for x in rows)
present=next(i for i in range(706) if i in keys[7] and i not in keys[8] and i not in keys[9]);absent=next(i for i in range(706) if i not in keys[7]); print('REAL DATA: absent from Section7',absent,'Section8 matches',keys[8].count(absent),'absent from both',sorted(set(range(706))-set(keys[7])-set(keys[8])))
results=[]
for edge in [present,absent]:
 machine=Machine();machine.test_id=(886<<12)|edge
 def setup(m):
  m.putmem(0x13000000,b'\0'*0x60)
  for k,ptr in [(7,0x44),(8,0x4c),(9,0x54)]:
   address=0x14000000+k*0x10000;m.putmem(address,tables[k]);m.putmem(0x13000000+ptr,struct.pack('<II',address,pairs[k][1]))
  m.w('r4',m.test_id);m.w('r5',0x11000000);m.w('r6',0) # output pointer valid, capacity zero
 _,stats=machine.run(0x3000e2c,b'',0,16,setup=setup)
 expected=sum(keys[k].count(edge) for k in [7,8,9]);assert machine.r('r0')==expected
 assert all(a in machine.executed for a in [0x3000e34,0x3000e3c,0x30010e4])
 results.append(dict(edge_id_used_as_key=edge,packed_input_id=hex(machine.test_id),section7_matches=keys[7].count(edge),section8_matches=keys[8].count(edge),returned=machine.r('r0'),expected=expected,trace=stats))
print(json.dumps({'test':'PASS','scenarios':results,'limits':'Capacity-zero count query; loader and lock/unlock stubbed; 0x00FFFB48 returns NULL under asserted zero output count; input-ID edge meaning assumed for test, not established by caller provenance.'},indent=2))
