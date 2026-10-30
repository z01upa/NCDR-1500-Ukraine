#!/usr/bin/env python3
"""Read-only extraction and conservative reference tests for DB_0 text."""
from __future__ import annotations
import argparse,csv,mmap,zlib,re,bisect
from collections import defaultdict
from pathlib import Path
SECTOR=512; ZH=(b'\x78\x01',b'\x78\x5e',b'\x78\x9c',b'\x78\xda')
MAX_REPORTED_STRINGS=100000

def recs(d):
 n=len(d)//SECTOR; h={s:d[s*SECTOR+3] for s in range(n) if int.from_bytes(d[s*SECTOR:s*SECTOR+3],'big')==s}; return [(s,x) for s,x in h.items() if x and s+x in h]
def decode(b):
 if all(x<128 for x in b): return b.decode('ascii'),'ascii'
 return b.decode('latin-1'),'latin-1 (byte-preserving candidate)'
def extract(blob,source,sector,base=None,local_base=0):
 out=[]
 # Requiring a terminator avoids reporting arbitrary printable fragments in
 # compressed or numeric data as text.  Unterminated runs are intentionally
 # left for a later, separately labelled heuristic scan.
 for m in re.finditer(rb'([\x20-\x7e\xa0-\xff]{3,})\x00',blob):
  i=m.start();raw=m.group(1)
  # At least two letter-like bytes makes this a conservative *text* scan,
  # excluding most binary fragments that happen to be printable and nulled.
  if len(raw)>80 or sum((65<=b<=90) or (97<=b<=122) or b>=192 for b in raw) < 2: continue
  text,enc=decode(raw); out.append({'source':source,'record_sector':sector,'absolute_file_offset':base+i if base is not None else '','record_local_offset':local_base+i,'decompressed_offset':local_base+i if source=='decompressed' else '','length':len(raw),'raw_hex':raw.hex(),'decoded_text':text,'encoding_candidate':enc})
 return out
def first_stream(d,off,end):
 probe=d[off+4:min(off+68,end)]
 for i in range(max(0,len(probe)-1)):
  if probe[i:i+2] in ZH:
   try:
    z=zlib.decompressobj(); x=z.decompress(d[off+4+i:end])+z.flush()
    if z.eof:return 4+i,x
   except zlib.error:pass
 return None,b''
def main():
 ap=argparse.ArgumentParser();ap.add_argument('db0',type=Path);ap.add_argument('--output-dir',type=Path,default=Path(__file__).parent);a=ap.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
 strings=[]; edges=[]; pages=defaultdict(list)
 with a.db0.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as d:
  R=recs(d)
  for sec,span in R:
   off=sec*SECTOR;end=off+span*SECTOR
   raw=extract(d[off+4:end],'raw',sec,off+4,4)
   if len(strings)<MAX_REPORTED_STRINGS: strings.extend(raw[:MAX_REPORTED_STRINGS-len(strings)])
   for x in raw: pages[int(int(x['absolute_file_offset'])//1024)].append(x)
   zo,plain=first_stream(d,off,end)
   if plain and len(strings)<MAX_REPORTED_STRINGS: strings.extend(extract(plain,'decompressed',sec,None,0)[:MAX_REPORTED_STRINGS-len(strings)])
  # Conservative page-reference candidate: scan the full raw file for BE u32
  # values in the possible DB page range, then retain only pages that actually
  # hold extracted raw text and an immediate printable key.  The regex is a
  # broad C-level prefilter; it does not define the representation.
  starts=[s*SECTOR for s,_ in R]
  spans={s*SECTOR:x for s,x in R}
  dictionary_pages={p for p,items in pages.items() if len(items)>=3}
  for m in re.finditer(rb'(?=(\x00[\x00-\x07][\x00-\xff]{2}))',d):
   pos=m.start(); page=int.from_bytes(m.group(1),'big')
   if page not in dictionary_pages: continue
   idx=bisect.bisect_right(starts,pos)-1
   if idx<0: continue
   roff=starts[idx]; rend=roff+spans[roff]*SECTOR
   if pos+4>=rend: continue
   tail=bytes(d[pos+4:min(pos+100,rend)])
   if tail and (32<=tail[0]<=126 or 160<=tail[0]<=255):
    nul=tail.find(b'\0')
    keyraw=tail[:nul] if nul>=3 else b''
    if keyraw and sum((65<=b<=90) or (97<=b<=122) or b>=192 for b in keyraw)>=2:
     key,_=decode(keyraw)
     edges.append({'source_record':roff//SECTOR,'source_offset':pos,'target_page':page,'key':key,'confidence':'candidate: BE u32 page + immediate printable key'})
 with (a.output_dir/'strings.csv').open('w',newline='',encoding='utf8') as o:
  w=csv.DictWriter(o,fieldnames=['source','record_sector','absolute_file_offset','record_local_offset','decompressed_offset','length','raw_hex','decoded_text','encoding_candidate']);w.writeheader();w.writerows(strings)
 raw=sorted((x for x in strings if x['source']=='raw'),key=lambda x:int(x['absolute_file_offset']))
 regions=[]
 if raw:
  first=prev=raw[0]; count=1
  for x in raw[1:]:
   if int(x['absolute_file_offset'])-int(prev['absolute_file_offset'])<=2048: prev=x;count+=1
   else:
    regions.append({'start_offset':first['absolute_file_offset'],'end_offset':int(prev['absolute_file_offset'])+int(prev['length']),'string_count':count,'first_text':first['decoded_text'],'last_text':prev['decoded_text']});first=prev=x;count=1
  regions.append({'start_offset':first['absolute_file_offset'],'end_offset':int(prev['absolute_file_offset'])+int(prev['length']),'string_count':count,'first_text':first['decoded_text'],'last_text':prev['decoded_text']})
 with (a.output_dir/'string_regions.csv').open('w',newline='',encoding='utf8') as o:
  w=csv.DictWriter(o,fieldnames=['start_offset','end_offset','string_count','first_text','last_text']);w.writeheader();w.writerows(regions)
 with (a.output_dir/'string_index_edges.csv').open('w',newline='',encoding='utf8') as o:
  w=csv.DictWriter(o,fieldnames=['source_record','source_offset','target_page','key','confidence']);w.writeheader();w.writerows(edges)
 # One row per candidate representation, including zero matches: no confirmation
 # is made by this scan.  Direct raw absolute BE references are also enumerated.
 refs=[]
 # Exact byte-offset tests begin with supplied independently known targets.
 # This avoids treating every incidental text-run offset as a dictionary entry.
 targets={int(x['absolute_file_offset']):x for x in raw if int(x['absolute_file_offset']) in (0x0e2b219d,0x0ed3fc00,0x01e25f38)}
 with a.db0.open('rb') as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as d:
  for v,t in targets.items():
   needle=v.to_bytes(4,'big'); p=d.find(needle)
   while p>=0:
    idx=bisect.bisect_right(starts,p)-1
    if idx>=0: refs.append({'representation':'uint32_be_absolute_byte_offset','source_record':starts[idx]//SECTOR,'source_offset':p,'raw_value':f'0x{v:08x}','target_offset':v,'target_text':t['decoded_text'],'status':'candidate'})
    p=d.find(needle,p+1)
 with (a.output_dir/'string_references.csv').open('w',newline='',encoding='utf8') as o:
  w=csv.DictWriter(o,fieldnames=['representation','source_record','source_offset','raw_value','target_offset','target_text','status']);w.writeheader();w.writerows(refs)
 with (a.output_dir/'STRING_FORMAT.md').open('w',encoding='utf8') as o:
  o.write('# String extraction and reference candidates\n\n')
  o.write('Raw strings are printable ASCII or bytes 0xa0–0xff runs of at least three bytes followed by a null terminator. Latin-1 output preserves every source byte; it is a display candidate, not an encoding claim. Decompressed strings use the same rule. Unterminated printable runs are not included in this conservative pass.\n\n')
  o.write(f'Reported {len(strings)} strings (the conservative scan is capped at {MAX_REPORTED_STRINGS} rows to prevent binary false-positive output from dominating the corpus): raw={sum(x["source"]=="raw" for x in strings)}, decompressed={sum(x["source"]=="decompressed" for x in strings)}. Raw regions join adjacent strings when the next starts within 2,048 bytes; this is a reporting heuristic, not a dictionary boundary.\n\n')
  o.write(f'Found {len(edges)} page-pointer-plus-immediate-key candidates and {len(refs)} exact big-endian absolute-offset candidates. Neither representation is confirmed: repeated independent source/target validation is still required.\n')
if __name__=='__main__':main()
