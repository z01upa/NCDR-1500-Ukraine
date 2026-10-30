"""Reproduce bounded negative reference evidence; no firmware decode/disassembly."""
import hashlib,json,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parent
p=ROOT.parent/'module_recovery_v13/modules/NavigationRem.dll'
m=json.loads((p/'module.json').read_text());scan=json.loads((p/'sh4_analysis.json').read_text());target=0x01000e2c;runtime=target+0x02000000
calls=[];loads=[];branches=[];pointers=[]
for f in scan['functions']:
 calls.extend(dict(function=f['va'],**c) for c in f['calls'] if c.get('target')==runtime)
 loads.extend(dict(function=f['va'],**v) for v in f['literals'] if v['normalized']==runtime)
for s in m['sections']:
 b=(p/('section_%d.bin'%s['index'])).read_bytes();assert hashlib.sha256(b).hexdigest()==s['sha256']
 for value in [target,runtime]:
  pos=b.find(struct.pack('<I',value))
  while pos>=0:
   pointers.append(dict(section=s['index'],link_va=m['link_base']+s['rva']+pos,offset=pos,value=value))
   pos=b.find(struct.pack('<I',value),pos+1)
b=(p/'section_0.bin').read_bytes();base=m['link_base']+m['sections'][0]['rva']
# SH4 BRA/BSR use signed 12-bit displacement *2 from PC+4.
lo=max(base,target-4100)&~1;hi=min(base+len(b)-2,target+4100)
for va in range(lo,hi,2):
 w=struct.unpack_from('<H',b,va-base)[0]
 if w>>12 in [10,11]:
  d=w&4095;d=d-4096 if d&2048 else d
  if va+4+d*2==target:branches.append(dict(va=va,word=w))
assert calls==[] and loads==[] and branches==[]
assert len(pointers)==1 and pointers[0]['section']==3 and pointers[0]['link_va']==0x01152b30
assert pointers[0]['offset']%8==0  # function start word of a PDATA entry
assert any(f['va']==runtime for f in scan['functions'])
result=dict(status='PASS_BOUNDED_REFERENCE_CHECK',target_link=hex(target),target_runtime=hex(runtime),indexed_direct_call_count=len(calls),indexed_literal_load_count=len(loads),relative_branch_hits=branches,relative_search_range=[hex(lo),hex(hi)],pointer_occurrences=pointers,meaning='Only a PDATA entry found; no identified upper caller. NOT proof that the function is unreachable.',limitation='Saved CFG is incomplete for indirect transfers; computed pointers, other modules, loader/runtime modifications and dynamic dispatch are not resolved.')
print(json.dumps(result,indent=2))
