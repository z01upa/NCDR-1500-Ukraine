#!/usr/bin/env python3
"""Build one addressed image and inspect mapped ROM signatures/TOCs. No external packages."""
import argparse,json,struct,hashlib,csv
from pathlib import Path

def main():
 ap=argparse.ArgumentParser();ap.add_argument('decoded',type=Path);a=ap.parse_args();root=a.decoded
 r=json.loads((root/'decode_report.json').read_text());ps=[p for p in r['packets'] if p['status']=='ok']
 base=min(p['address'] for p in ps);end=max(p['address']+p['actual_size'] for p in ps)
 if end-base>256*1024*1024:raise SystemExit('Sparse range too large')
 mem=bytearray(end-base);cov=bytearray(end-base);overlaps=[]
 for p in ps:
  b=(root/p['file']).read_bytes();o=p['address']-base
  if any(cov[o:o+len(b)]):overlaps.append(p['index'])
  mem[o:o+len(b)]=b;cov[o:o+len(b)]=b'\1'*len(b)
 (root/'addressed_image.bin').write_bytes(mem)
 def read(va,n):
  off=va-base
  if off<0 or off+n>len(mem) or not all(cov[off:off+n]):return None
  return bytes(mem[off:off+n])
 def string(va):
  b=bytearray()
  for i in range(256):
   x=read(va+i,1)
   if x is None:return None
   if x==b'\0':return b.decode('ascii',errors='replace')
   b+=x
  return None
 regions=[];cur=0
 while cur<len(cov):
  e=cur+1
  while e<len(cov) and cov[e]==cov[cur]:e+=1
  regions.append(dict(start=base+cur,end=base+e,size=e-cur,present=bool(cov[cur])));cur=e
 result=dict(base=base,end=end,image_file='addressed_image.bin',sha256=hashlib.sha256(mem).hexdigest(),mapped_bytes=sum(cov),holes=len(cov)-sum(cov),overlapping_packets=overlaps,regions=regions,rom_candidates=[])
 sig=b'ECEC';off=mem.find(sig)
 while off>=0:
  p=read(base+off+4,4)
  if p:
   va=struct.unpack('<I',p)[0];b=read(va,84)
   if b:
    f=struct.unpack('<17I2HI2I',b);n=f[4]
    if 0<n<4096:
     cand=dict(signature_va=base+off,romhdr_va=va,romhdr_fields=list(f),nummods=n,cpu=f[17],modules=[])
     for i in range(n):
      t=read(va+84+i*32,32)
      if not t:break
      at,tl,th,sz,name,e32,o32,load=struct.unpack('<8I',t)
      cand['modules'].append(dict(index=i,name=string(name),size=sz,name_va=name,e32_va=e32,o32_va=o32,load_va=load,attributes=at))
     cand['all_names_readable']=len(cand['modules'])==n and all(m['name'] for m in cand['modules']);result['rom_candidates'].append(cand)
  off=mem.find(sig,off+1)
 (root/'address_map.json').write_text(json.dumps(result,indent=2))
 print(json.dumps({k:v for k,v in result.items() if k not in ['regions','rom_candidates']},indent=2))
 for c in result['rom_candidates']:
  print('ROM',hex(c['romhdr_va']),c['nummods'],hex(c['cpu']),'coherent',c['all_names_readable'])
  for m in c['modules']:
   if m['name'] and m['name'].lower() in ['navigationrem.dll','nmicore_ce.dll','nk.exe']:print(m)
if __name__=='__main__':main()
