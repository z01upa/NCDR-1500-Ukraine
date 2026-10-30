#!/usr/bin/env python3
"""Verify preserved sections against the pinned addressed image and packet outputs."""
import hashlib,json,struct
from pathlib import Path
from recover_modules import Image,ce_blocks,sha,u32
ROOT=Path(__file__).resolve().parent

def resolve_memcpy(im):
 c=im.meta['rom_candidates'][0];m=next(x for x in c['modules'] if x['name'].lower()=='coredll.dll');e=im.read(m['e32_va'],100);n=int.from_bytes(e[:2],'little')
 sections=[struct.unpack('<6I',im.read(m['o32_va']+24*i,24)) for i in range(n)]
 def read(rva,n):
  for vs,r,ps,dp,ra,f in sections:
   if r<=rva and rva+n<=r+min(ps,vs) and not f&0x2000:return im.read(dp+rva-r,n)
  raise ValueError('unmapped export')
 def string(r):
  b=bytearray()
  while read(r+len(b),1)!=b'\0':b+=read(r+len(b),1)
  return b.decode('ascii')
 rv=u32(e,28);_,_,_,_,name,ob,nf,nn,ft,nt,ot=struct.unpack('<IIHHIIIIIII',read(rv,40));ans=[]
 for i in range(nn):
  ordinal=int.from_bytes(read(ot+i*2,2),'little')+ob
  if ordinal==1044:ans.append(dict(ordinal=ordinal,name=string(u32(read(nt+i*4,4))),export_rva=u32(read(ft+(ordinal-ob)*4,4))))
 assert len(ans)==1 and ans[0]['name']=='memcpy'
 result=dict(module=m,export_directory_rva=rv,resolved=ans)
 (ROOT/'routing/memcpy_import.json').write_text(json.dumps(result,indent=2))
 return result

def main():
 decoded=ROOT.parent/'astra_final_breakthrough/decoded';im=Image(decoded);rep=json.loads((decoded/'decode_report.json').read_text());assert rep['complete'] and not rep['errors']
 assert sha(Path(rep['input']).read_bytes())==rep['input_sha256']
 assert im.meta['sha256']=='ed2f3546e83130e03e8e8ef713540417e56e4dd7eebd313cba1065408e4d7906'
 packet_ids=set();rows=[]
 for folder in sorted((ROOT/'modules').iterdir()):
  m=json.loads((folder/'module.json').read_text())
  assert not m.get('imports_error') and not m.get('exports_error')
  for s in m['sections']:
   data=(folder/('section_%d.bin'%s['index'])).read_bytes();raw=(folder/('section_%d.stored.bin'%s['index'])).read_bytes()
   assert raw==im.read(s['storage_va'],s['stored_bytes_read']) and sha(raw)==s['stored_sha256']
   assert sha(data)==s['sha256'] and data==(ce_blocks(raw)[0] if s['compressed'] else raw)
   ids=[];start=s['storage_va'];end=start+len(raw)
   for p in rep['packets']:
    lo=max(start,p['address']);hi=min(end,p['address']+p['actual_size'])
    if lo<hi:
     b=(decoded/p['file']).read_bytes();assert sha(b)==p['sha256'];assert b[lo-p['address']:hi-p['address']]==im.read(lo,hi-lo);ids.append(p['index']);packet_ids.add(p['index'])
   rows.append(dict(module=m['toc']['name'],section=s['index'],stored_bytes=len(raw),decoded_bytes=len(data),packets=ids,sha256=sha(data)))
  code=m['sections'][0];assert code['executable'] and not code['compressed']
  for target in [m['entry_runtime_va']]+[e['runtime_va'] for e in m['exports']]:assert code['runtime_va']<=target<code['runtime_va']+code['virtual_size'] and target%2==0
  scan=json.loads((folder/'sh4_analysis.json').read_text());assert not scan['decode_failures'] and not scan['branches_outside_text'];assert scan['pdata_partial_record_bytes']==6
 resolve_memcpy(im)
 # Safety controls: holes and malformed compressed input must not be silently filled.
 hole=next(r for r in im.meta['regions'] if not r['present'])
 try:im.read(hole['start'],1)
 except ValueError:pass
 else:raise AssertionError('hole accepted')
 compressed=(ROOT/'modules/NavigationRem.dll/section_3.stored.bin').read_bytes()
 try:ce_blocks(compressed[:-1])
 except ValueError:pass
 else:raise AssertionError('truncated section accepted')
 assert sha((decoded/'addressed_image.bin').read_bytes())==im.meta['sha256']
 result=dict(status='PASS',image_sha256=im.meta['sha256'],original_nk_sha256=rep['input_sha256'],sections=rows,distinct_source_packets_verified=len(packet_ids),hole_guard=True,truncation_guard=True,image_unchanged=True,windows_execution='NOT VERIFIED',hardware_execution='NOT VERIFIED')
 (ROOT/'verification.json').write_text(json.dumps(result,indent=2));print('PASS:',len(rows),'sections,',len(packet_ids),'source packets; hashes, mapping, entry/exports, hole and truncation guards')
if __name__=='__main__':main()
