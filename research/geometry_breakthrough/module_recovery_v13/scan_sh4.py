#!/usr/bin/env python3
"""Bounded reachable SH4 scan of the two recovered modules only.
CFG handles conditional delay slots separately. Indirect transfers stop traversal;
this is static evidence, not emulation or complete indirect-call coverage.
"""
import bisect,csv,gzip,json,re,struct
from collections import deque
from pathlib import Path
import pypcode
ROOT=Path(__file__).resolve().parent
LANG='SuperH4:LE:32:default'
def scan(folder):
 j=json.loads((folder/'module.json').read_text());secs=j['sections'];text=(folder/'section_0.bin').read_bytes();base=secs[0]['runtime_va'];link=j['link_base'];delta=base-(link+secs[0]['rva']);end=base+len(text)
 data={s['index']:(folder/('section_%d.bin'%s['index'])).read_bytes() for s in secs}
 def read(va,n):
  for s in secs:
   for start in [s['runtime_va'],link+s['rva']]:
    off=va-start
    if 0<=off and off+n<=len(data[s['index']]):return data[s['index']][off:off+n]
  return None
 def normalize(va):
  for s in secs:
   if link+s['rva']<=va<link+s['rva']+s['virtual_size']:return s['runtime_va']+va-link-s['rva']
  return va
 strings={}
 for s in secs:
  if s['executable']:continue
  for m in re.finditer(rb'[\x20-\x7e]{5,}',data[s['index']]):strings[s['runtime_va']+m.start()]=m.group().decode('ascii')
 pdata=data[3];partial_pdata=len(pdata)%8  # Do not invent the omitted virtual tail bytes.
 funcs=[]
 for off in range(0,len(pdata)-partial_pdata,8):
  va,w=struct.unpack_from('<II',pdata,off);va=normalize(va);length=((w>>8)&0x3fffff)*2
  assert not(w&0x40000000) and base<=va<end and length>0 and va+length<=end
  funcs.append(dict(va=va,end=va+length,pdata_word=w,synthetic_tail_bytes=max(0,off+8-len(data[3]))))
 assert all(a['va']<b['va'] for a,b in zip(funcs,funcs[1:]))
 ctx=pypcode.Context(LANG);controls=[]
 for code,mnem in [('0900','nop'),('0b00','rts'),('0b40','jsr')]:
  ins=ctx.disassemble(bytes.fromhex(code),0x1000,max_instructions=1).instructions[0];assert ins.mnem.lower()==mnem;controls.append(code)
 total=0;failures=[];xrefs=[];branches=[]
 with gzip.open(folder/'reachable.jsonl.gz','wt') as output:
  for f in funcs:
   pending=[f['va']];seen={};errors=[];calls=[];literals=[]
   def decode(a):
    if a in seen:return seen[a]
    ins=ctx.disassemble(text[a-base:a-base+2],a,max_instructions=1).instructions[0]
    row=dict(va=a,bytes=text[a-base:a-base+2].hex(),mnem=ins.mnem.lower(),body=ins.body.strip());seen[a]=row;return row
   while pending:
    a=pending.pop()
    if a in seen or not f['va']<=a<f['end']:continue
    try:row=decode(a)
    except Exception as ex:errors.append(dict(va=a,error=str(ex)));continue
    m=row['mnem'];body=row['body'];target=None
    if re.fullmatch('0x[0-9a-fA-F]+',body):target=int(body,16)
    delayed=m in ['bra','bsr','bt/s','bf/s','jsr','jmp','rts','rte','bsrf','braf']
    if delayed:
     try:decode(a+2)
     except Exception as ex:errors.append(dict(va=a+2,error=str(ex)))
    if m in ['bt','bf','bt/s','bf/s','bra']:
     if target is not None:
      branches.append(dict(va=a,target=target,in_text=base<=target<end))
      if f['va']<=target<f['end']:pending.append(target)
     if m!='bra':pending.append(a+(4 if delayed else 2))
    elif m in ['bsr','jsr','bsrf']:
     calls.append(dict(va=a,target=target,body=body));pending.append(a+4)
    elif m not in ['jmp','braf','rts','rte','sleep']:pending.append(a+2)
   for row in seen.values():
    if row['mnem'] in ['mov.l','mov.w']:
     match=re.fullmatch(r'0x([0-9a-fA-F]+),r(\d+)',row['body'])
     if match:
      literal=int(match[1],16);raw=read(literal,4 if row['mnem']=='mov.l' else 2)
      if raw:
       value=int.from_bytes(raw,'little');normalized=normalize(value);r=dict(instruction_va=row['va'],literal_va=literal,value=value,normalized=normalized,register=int(match[2]));literals.append(r)
       if normalized in strings:xrefs.append(dict(function_va=f['va'],**r,text=strings[normalized]))
   ordered=sorted(seen.values(),key=lambda r:r['va']);f.update(reachable=len(seen),errors=errors,calls=calls,literals=literals)
   output.write(json.dumps(dict(**f,instructions=ordered))+'\n');total+=len(seen);failures.extend(errors)
 result=dict(module=j['toc']['name'],language=LANG,pypcode_version=pypcode.__version__,runtime_delta=delta,pdata_functions=len(funcs),pdata_partial_record_bytes=partial_pdata,pdata_virtual_zero_tail_not_used=secs[3]['virtual_zero_tail'],reachable_instructions=total,decode_failures=failures,controls=controls,branches_outside_text=[b for b in branches if not b['in_text']],functions=funcs,string_xrefs=xrefs,exact_map_strings=[dict(va=va,text=t) for va,t in strings.items() if re.search(r'(?i)(EUZ|\.MP0|\.RT\b|\.RL\b)',t)])
 (folder/'sh4_analysis.json').write_text(json.dumps(result,indent=2))
 with (folder/'string_xrefs.tsv').open('w') as fp:
  fp.write('function_va\tinstruction_va\tstring_va\ttext\n')
  for x in xrefs:fp.write('%08x\t%08x\t%08x\t%s\n'%(x['function_va'],x['instruction_va'],x['normalized'],x['text']))
 print(j['toc']['name'],len(funcs),total,'errors',len(failures),'external branches',len(result['branches_outside_text']),'string xrefs',len(xrefs),'map strings',result['exact_map_strings'])
 return result
if __name__=='__main__':
 for folder in sorted((ROOT/'modules').iterdir()):
  if folder.is_dir():scan(folder)
