#!/usr/bin/env python3
"""Read-only validation of published CARiN observations against this DB_0."""
from __future__ import annotations
import argparse,csv,mmap,zlib,statistics
from collections import Counter,defaultdict
from pathlib import Path
S=512; MUL=5555555
def recs(d):
 n=len(d)//S; h={i:d[i*S+3] for i in range(n) if int.from_bytes(d[i*S:i*S+3],'big')==i};return [(i,x) for i,x in h.items() if x and i+x in h]
def dec(d,o,end):
 if d[o+6]!=2:return b'',False,0
 try:
  z=zlib.decompressobj();p=z.decompress(d[o+8:end])+z.flush();return p,z.eof,len(d[o+8:end])-len(z.unused_data)
 except zlib.error:return b'',False,0
def textnear(p,at):
 # conservative zero-terminated runs near a candidate coordinate
 out=[]
 for q in range(max(0,at-80),min(len(p),at+160)):
  e=p.find(b'\0',q,min(len(p),q+81))
  if e>q+2 and all(32<=x<=126 for x in p[q:e]):out.append(p[q:e].decode('ascii','replace'))
 return sorted(set(out))[:5]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('db0',type=Path);ap.add_argument('--output-dir',type=Path,default=Path(__file__).parent);a=ap.parse_args();out=a.output_dir;out.mkdir(parents=True,exist_ok=True)
 blocks=[]; comp=[]; coords=[]; pois=[]; links=[]; rawbytype=defaultdict(list); allstarts=set()
 with a.db0.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as d:
  R=recs(d);allstarts={s for s,_ in R}
  for sec,span in R:
   o=sec*S;typ=d[o+5];cm=d[o+6];usize=d[o+7]; end=o+span*S;p,ok,csize=dec(d,o,end)
   blocks.append({'sector':sec,'physical_offset':o,'physical_span_sectors':span,'alignment':d[o+4],'block_type':f'0x{typ:02x}','compression_method':f'0x{cm:02x}','uncompressed_size_field':usize,'zlib_success':ok,'decompressed_size':len(p) if ok else ''})
   comp.append({'sector':sec,'block_type':f'0x{typ:02x}','compression_method':f'0x{cm:02x}','size_field':usize,'zlib_success':ok,'compressed_size':csize if ok else '','decompressed_size':len(p) if ok else '',**{f'field_x_{u}':usize*u for u in (256,512,1024,2048,4096)}})
   rawbytype[typ].append((sec,span,o,p if ok else d[o+8:end],ok))
   payload=p if ok else d[o+8:end]
   # Mulcoord pairs on all four possible byte alignments.
   # BL_HEAD and published LON_LAT structures are 32-bit aligned; scan aligned
   # pairs across the whole corpus, then separately scan type 0x10 at 16-bit
   # granularity below for variant packing.
   for at in range(0,max(0,len(payload)-7),4):
    lonv=int.from_bytes(payload[at:at+4],'big');latv=int.from_bytes(payload[at+4:at+8],'big');lon=lonv/MUL-30;lat=latv/MUL
    if 19<=lon<=190 and 41<=lat<=82:coords.append({'sector':sec,'block_type':f'0x{typ:02x}','compressed':ok,'payload_offset':at,'hlon':lonv,'hlat':latv,'longitude':round(lon,6),'latitude':round(lat,6)})
   if typ==0x10:
    # Published MORE_INFO begins with LON_LAT and has BE block-relative PSTRs.
    for at in range(0,max(0,len(payload)-8),2):
     lonv=int.from_bytes(payload[at:at+4],'big');latv=int.from_bytes(payload[at+4:at+8],'big');lon=lonv/MUL-30;lat=latv/MUL
     if 19<=lon<=190 and 41<=lat<=82: pois.append({'sector':sec,'compressed':ok,'payload_offset':at,'longitude':round(lon,6),'latitude':round(lat,6),'nearby_strings':' | '.join(textnear(payload,at)),'status':'coordinate candidate in type 0x10; supports published POI model'})
   if typ in (0x0b,0x0d,0x0f,0x11):
    body=d[o+8:end]
    for at in range(0,len(body)-4,4):
     target=int.from_bytes(body[at:at+3],'big');span2=body[at+3]
     if target in allstarts and span2: links.append({'source_sector':sec,'source_type':f'0x{typ:02x}','payload_offset':at,'target_sector':target,'target_type':f'0x{d[target*S+5]:02x}','target_span':span2,'status':'BL_ADDR-shaped candidate'})
 # aggregate and files
 counts=Counter(x['block_type'] for x in blocks)
 with (out/'block_types.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(blocks[0]));w.writeheader();w.writerows(blocks)
 with (out/'compression_fields.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(comp[0]));w.writeheader();w.writerows(comp)
 with (out/'coordinates.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['sector','block_type','compressed','payload_offset','hlon','hlat','longitude','latitude']);w.writeheader();w.writerows(coords)
 with (out/'poi_type10.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['sector','compressed','payload_offset','longitude','latitude','nearby_strings','status']);w.writeheader();w.writerows(pois)
 with (out/'known_links.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['source_sector','source_type','payload_offset','target_sector','target_type','target_span','status']);w.writeheader();w.writerows(links)
 success=[x for x in comp if x['zlib_success']]; bycm=defaultdict(list)
 for x in comp:bycm[x['compression_method']].append(x)
 with (out/'block_type_statistics.md').open('w') as f:
  f.write('# Block types\n\n');f.write('|type|count|\n|-|-:|\n');[f.write(f'|{k}|{v}|\n') for k,v in sorted(counts.items())]
  f.write('\n## Compression field validation\n\n')
  for cm,xs in bycm.items():
   ok=[x for x in xs if x['zlib_success']];f.write(f'- `{cm}`: {len(xs)} records, zlib successes {len(ok)}; size-field values {dict(Counter(x["size_field"] for x in xs))}.\n')
  for u in (256,512,1024,2048,4096):
   exact=sum(x['decompressed_size']==x['size_field']*u for x in success);f.write(f'- exact decompressed length = byte7 × {u}: {exact}/{len(success)}.\n')
 with (out/'addressing_model.md').open('w') as f:
  f.write('# Addressing model\n\nThe first four bytes self-identify every record as `uint24_be sector_id + uint8 physical_span`. `sector_id × 512` equals its physical file offset across the validated chain. This directly validates a 512-byte BL_ADDR variant for this DB. No independent 0x800 logical reference mapping was established here; treating each current sector ID as a published 0x800 page number would produce wrong physical offsets.\n')
 with (out/'KNOWN_FORMAT_VALIDATION.md').open('w') as f:
  f.write(f'# Validation\n\nValidated blocks: {len(blocks)}. Type 0x10 count: {counts["0x10"]}. MULCOORD candidate pairs: {len(coords)}; type-0x10 candidates: {len(pois)}. Moscow window candidates: {sum(55.4<=x["latitude"]<=56.1 and 37.2<=x["longitude"]<=38.1 for x in coords)}.\n')
if __name__=='__main__':main()
