"""Isolated execution of recovered producer, real caller suffix and real mask consumer.
Requires pypcode and v13 recovery; not a Windows CE emulator. Stubs are explicit.
"""
import argparse,hashlib,inspect,json,os,struct,sys,textwrap,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
ap=argparse.ArgumentParser();ap.add_argument('--recovery',type=Path,default=ROOT.parent/'module_recovery_v13');ap.add_argument('--mp0',type=Path);ap.add_argument('--out',type=Path,default=ROOT/'replay_results.json');a=ap.parse_args()
sys.path.insert(0,str(a.recovery));from verify_graph_readers import Machine
src=inspect.getsource(Machine.run)
old="""if target!=0x2ff87cc:raise ValueError('unmodeled call %x'%target)
     self.putmem(self.r('r4'),self.readmem(self.r('r5'),self.r('r6')));self.w('r0',self.r('r4'));self.hooks+=1"""
new="""if target in [0x301213c,0x301217c]:
      self.w('r0',0);self.hooks+=1
     elif target==0x300d19c:
      assert self.r('r4')==self.edge_id and self.r('r5') in [2,6]
      self.putmem(self.r('r6'),struct.pack('<I',0x13000000));self.w('r0',0);self.hooks+=1
     elif target in [0x301b428,0x2ff8910]:
      # Length helper and division helper isolated: no writes to output or mask bytes.
      self.w('r0',100 if target==0x301b428 else 1);self.hooks+=1
     elif target in [0x2ffb92c,0x2ffbb00,0x308c1f0,0x301efe4]:
      self.w('PR',nextpc);nextpc=target;break
     else:raise ValueError('unmodeled call %x'%target)"""
assert old in src
src=src.replace(old,new).replace("elif name=='INT_ADD':","elif name=='INT_NEGATE':v=~vals[0]\n    elif name=='INT_ADD':")
src=src.replace("pc=self.norm(pc);self.executed.add(pc)","pc=self.norm(pc);self.executed.add(pc);self.trace.append(pc)\n   if pc in [0x2ffb92c,0x2ffbb00,0x308c1f0,0x301efe4,0x306f536,0x306f54c]:self.snapshots[pc]={r:self.r(r) for r in ['r0','r4','r5','r6','r8','r9','r10','r11','r15']}")
src=src.replace("if name=='IMARK':nextpc=max(x.offset+x.size for x in ins)","if name=='IMARK':\n     nextpc=max(x.offset+x.size for x in ins)\n     self.instruction_addresses.update(x.offset for x in ins)")
scope={'struct':struct};exec(textwrap.dedent(src),scope);Machine.run=scope['run']
_original_readmem=Machine.readmem
def _diagnostic_readmem(self,a,n):
 try:return _original_readmem(self,a,n)
 except Exception:
  print('READ_FAILURE',hex(a),n,'TRACE',[hex(x) for x in self.trace[-20:]])
  raise
Machine.readmem=_diagnostic_readmem
def init():
 m=Machine();m.trace=[];m.instruction_addresses=set();m.snapshots={};return m
# Local pinned input; if omitted, use the established source in this project.
source_root=Path(os.environ['NCDR_SOURCE_ROOT']) if os.environ.get('NCDR_SOURCE_ROOT') else None
mp0=a.mp0 or (source_root/'originals/NCDR/SW/DB/EUZ.MP0' if source_root else None)
if mp0 is None:raise SystemExit('Pass --mp0 or set NCDR_SOURCE_ROOT to the local source package root')
with mp0.open('rb') as f:
 f.seek(114+24*886+16);off,usize,csize=struct.unpack('<IHH',f.read(8));f.seek(off);raw=zlib.decompress(f.read(csize))
assert len(raw)==usize and hashlib.sha256(raw).hexdigest()=='c4fd95701be3301b999d7e8886d08a6d2e8a3461e9f6caa973a5128959d983a6'
s5,n=struct.unpack_from('<HH',raw,20)
edge=next(i for i in range(n) if not struct.unpack_from('<I',raw,s5+14*i)[0]&0x3000)
disk=raw[s5+14*edge:s5+14*(edge+1)];base=disk[:10]+b'\xa5\xa5'+disk[10:];edge_id=(886<<12)|edge
NODE_A=struct.pack('<iii',100,200,300);NODE_B=struct.pack('<iii',400,500,600)
def setup_common(m,eb):
 m.edge_id=edge_id;m.putmem(0x13000000,b'\0'*0x80)
 m.putmem(0x13000034,struct.pack('<II',0x14000000,n))
 m.putmem(0x14000000+16*edge,eb)
 m.putmem(0x1300001c,struct.pack('<I',0x15000000));m.putmem(0x13000024,struct.pack('<I',0x16000000))
 ia,ib=struct.unpack_from('<HH',eb,6)
 for table in [0x15000000,0x16000000]:
  m.putmem(table+12*ia,NODE_A);m.putmem(table+12*ib,NODE_B)
 m.putmem(0x1137260,b'\1\0\0\0'*32) # link-address static cost table, controlled fixture
 m.putmem(0x3137260,b'\1\0\0\0'*32)

def consumer(cover,selector):
 m=init()
 def setup(q):
  q.putmem(0x11000000,cover);q.putmem(0x17000000,b'\0'*16)
  # Actual selector compares node+4/+8/+c against cover+1c/+20/+24.
  q.putmem(0x17000004,cover[0x1c:0x28] if selector==0 else struct.pack('<iii',-100,-200,-300))
  q.w('r4',0x11000000);q.w('r5',0x17000000);q.w('r6',selector)
 m.run(0x308c1f0,b'',0,len(cover),setup=setup)
 assert m.hooks==0
 expected=0xffffffff if cover[0x10+selector] & (1<<selector) else 0
 assert m.r('r0')==expected
 return dict(selector=selector,returned=hex(m.r('r0')),trace=[hex(x) for x in m.trace],hooks=m.hooks)
results=[]
for entry in [0x2ffb92c,0x2ffbb00]:
 for name in ['baseline','A_edge4','B_edge5','C_bit13']:
  eb=bytearray(base)
  if name=='A_edge4':eb[4]^=1
  if name=='B_edge5':eb[5]^=2
  if name=='C_bit13':eb[1]^=0x20
  m=init()
  def setup(q):
   setup_common(q,eb);q.w('r4',edge_id);q.w('r5',0x11000000)
  cover,stats=m.run(entry,b'',0,0x34,setup=setup)
  assert cover[16:18]==eb[4:6]
  out14,out18=struct.unpack_from('<II',cover,0x14)
  assert out14==((886<<12)|struct.unpack_from('<H',eb,6)[0])
  assert out18==(0xfffffffe if name=='C_bit13' else ((886<<12)|struct.unpack_from('<H',eb,8)[0]))
  case=dict(producer=hex(entry),experiment=name,edge_bytes=bytes(eb).hex(),cover=cover.hex(),output10=cover[16],output11=cover[17],output14=hex(out14),output18=hex(out18),trace=[hex(x) for x in m.trace],instruction_addresses=[hex(x) for x in sorted(m.instruction_addresses)],consumers=[consumer(cover,0),consumer(cover,1)],stats=stats)
  results.append(case)
# Actual caller suffix: stack output S+0x40 -> real producer -> real consumer -> caller branch.
caller=[]
for name in ['baseline','A_edge4','B_edge5','C_bit13']:
 for selector in [0,1]:
  eb=bytearray(base)
  if name=='A_edge4':eb[4]^=1
  if name=='B_edge5':eb[5]^=2
  if name=='C_bit13':eb[1]^=0x20
  m=init()
  def setup(q):
   setup_common(q,eb);q.w('r4',edge_id);q.w('r11',selector)
   q.putmem(0x12001088,struct.pack('<I',edge_id))
   q.putmem(0x120010a8,b'\0'*16);q.putmem(0x120010ac,NODE_A if selector==0 else struct.pack('<iii',-100,-200,-300))
  m.run(0x306f52a,b'',0,0x34,setup=setup,stop=0x306f558)
  cover=m.readmem(0x12001040,0x34)
  expected=0xffffffff if eb[4+selector] & (1<<selector) else 0
  assert m.r('r0')==expected
  assert all(x in m.instruction_addresses for x in [0x306f536,0x306f538,0x306f54c,0x306f54e,0x308c208,0x308c212,0x306f552,0x306f554])
  assert (0x306f556 in m.instruction_addresses)==(expected==0)
  caller.append(dict(experiment=name,selector=selector,returned=hex(m.r('r0')),output=cover.hex(),trace=[hex(x) for x in m.trace],snapshots={hex(k):{str(r):hex(v) for r,v in m.snapshots.get(k,{}).items()} for k in [0x306f536,0x306f54c,0x2ffb92c,0x308c1f0,0x301efe4]}))
# Explicit compare traces; A/B cannot change producer branches, C must change bit13 branch.
for entry in [0x2ffb92c,0x2ffbb00]:
 group=[x for x in results if x['producer']==hex(entry)];ref=group[0]
 for x in group[1:]:
  x['producer_trace_matches_baseline']=x['trace']==ref['trace']
  x['entered_vs_baseline']=sorted(set(x['trace'])-set(ref['trace']));x['skipped_vs_baseline']=sorted(set(ref['trace'])-set(x['trace']))
  assert x['producer_trace_matches_baseline']==(x['experiment']!='C_bit13')
report=dict(result='PASS_OFFLINE_CHAIN',block=886,edge=edge,edge_id=hex(edge_id),original_disk_edge=disk.hex(),code_sha256=hashlib.sha256((a.recovery/'modules/NavigationRem.dll/section_0.bin').read_bytes()).hexdigest(),producer_cases=results,real_caller_suffix_cases=caller,limitations=['Starts at the caller stack-lookup sequence at 0x0306F52A with an explicit one-entry caller stack array; prior route/search context is supplied.','Lock/unlock no-op; loader returns prepared context; length helper=100 and division helper=1 (neither writes masks); coordinate tables are controlled fixtures.','Actual 0x0308C1F0 and selector 0x0301EFE4 execute without hooks or synthetic callback.','No OS, complete route, hardware or new-MP0 compatibility claim.'])
a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(dict(result=report['result'],edge=edge,producer_cases=len(results),real_caller_suffix_cases=len(caller),consumer_cases=16),indent=2))
summary=dict(
 result=report['result'],block=886,edge=edge,edge_id=hex(edge_id),
 producers=[dict(producer=x['producer'],experiment=x['experiment'],output10=x['output10'],output11=x['output11'],output14=x['output14'],output18=x['output18'],producer_trace_matches_baseline=x.get('producer_trace_matches_baseline',True),entered_vs_baseline=list(x.get('entered_vs_baseline',[])),skipped_vs_baseline=list(x.get('skipped_vs_baseline',[]))) for x in results],
 caller_paths=[dict(experiment=x['experiment'],selector=x['selector'],returned=x['returned'],snapshots=x['snapshots']) for x in caller],
 limitations=report['limitations'])
(ROOT/'replay_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
