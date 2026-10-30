#!/usr/bin/env python3
"""Read-only Phase 6 validation of CARiN city/index/road blocks."""
from __future__ import annotations
import argparse,csv,mmap,re,zlib
from collections import Counter,defaultdict
from pathlib import Path
S=512; MUL=5555555
def recs(d):
 n=len(d)//S;h={i:d[i*S+3] for i in range(n) if int.from_bytes(d[i*S:i*S+3],'big')==i};return [(i,x) for i,x in h.items() if x and i+x in h]
def decode(d,o,e):
 if d[o+6]!=2:return bytes(d[o+8:e]),False
 z=zlib.decompressobj()
 try:
  p=z.decompress(d[o+8:e])+z.flush();return p,z.eof
 except zlib.error:return b'',False
def strings(p):return [x.decode('latin1') for x in re.findall(rb'([A-Za-z][A-Za-z .\x27-]{2,})\0',p)]
def coords(p):
 return sum(1 for i in range(0,len(p)-7,4) if 19<=int.from_bytes(p[i:i+4],'big')/MUL-30<=190 and 41<=int.from_bytes(p[i+4:i+8],'big')/MUL<=82)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('db0',type=Path);ap.add_argument('--output-dir',type=Path,default=Path(__file__).parent);a=ap.parse_args();out=a.output_dir;out.mkdir(parents=True,exist_ok=True)
 erows=[];frows=[];links=[];roadlinks=[];moscow=[];mismatch=[]; exact=total=0
 with a.db0.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as d:
  R=recs(d);heads={sec:(sp,d[sec*S+5]) for sec,sp in R}
  payload={}
  for sec,sp in R:
   o=sec*S;p,ok=decode(d,o,o+sp*S);payload[sec]=p
   if d[o+6]==2:
    total+=1;expected=d[o+7]*S-8
    if ok and len(p)==expected:exact+=1
    else:mismatch.append({'sector':sec,'physical_span':sp,'size_field':d[o+7],'expected_payload':expected,'actual_payload':len(p),'zlib_success':ok})
   t=d[o+5]
   if t in (0x0e,0x0f):
    row={'sector':sec,'physical_size':sp*S,'logical_size':d[o+7]*S if d[o+6]==2 else sp*S,'compressed':ok,'payload_size':len(p),'string_count':len(strings(p)),'coordinate_candidate_count':coords(p)}
    (erows if t==0x0e else frows).append(row)
  # Exact BL_ADDR-shaped references in payload: u24 target + byte span must
  # agree with a known physical record header. This validates the whole field.
  for sec,sp in R:
   typ=d[sec*S+5];p=payload[sec]
   if typ not in (0x0e,0x0f):continue
   for at in range(len(p)-3):
    target=int.from_bytes(p[at:at+3],'big');span=p[at+3]
    if target not in heads or heads[target][0]!=span:continue
    tt=heads[target][1]
    item={'source_sector':sec,'source_type':f'0x{typ:02x}','source_offset':at,'target_sector':target,'target_type':f'0x{tt:02x}','target_span':span,'evidence':'exact uint24_be sector + span matches target BL_HEAD'}
    if typ==0x0f and tt==0x0e:
     # A nearby null string is a key candidate, never asserted as association.
     before=p[max(0,at-96):at];key=''
     found=re.findall(rb'([A-Za-z][A-Za-z .\x27-]{1,})\0',before)
     if found:key=found[-1].decode('latin1')
     links.append({'source_0F_sector':sec,'source_offset':at,'key':key,'target_sector':target,'target_type':'0x0e'})
    if typ==0x0e:roadlinks.append(item)
  # Moscow is located as actual city text in type 0C.  References to 0F within
  # that same block are reported separately; associating a particular one with
  # ch_roads needs the published MORE_INFO offset layout and is not inferred.
  for sec,sp in R:
   if d[sec*S+5]!=0x0c:continue
   p=payload[sec]
   if b'moskva\0' not in p:continue
   pos=p.find(b'moskva\0')
   moscow.append({'city_sector':sec,'moskva_offset':pos,'city_strings':' | '.join(strings(p)[-30:]),'status':'Moskva text confirmed; MORE_INFO/ch_roads not yet structurally parsed'})
 with (out/'type0E_blocks.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(erows[0]));w.writeheader();w.writerows(erows)
 with (out/'type0F_blocks.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(frows[0]));w.writeheader();w.writerows(frows)
 with (out/'index0F_to_road0E.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['source_0F_sector','source_offset','key','target_sector','target_type']);w.writeheader();w.writerows(links)
 with (out/'road_links.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['source_sector','source_type','source_offset','target_sector','target_type','target_span','evidence']);w.writeheader();w.writerows(roadlinks)
 with (out/'moscow_roads.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['city_sector','moskva_offset','city_strings','status']);w.writeheader();w.writerows(moscow)
 with (out/'ROAD_FORMAT.md').open('w') as f:
  f.write('# Roads phase\n\n## Confirmed\n\n');f.write(f'- compression=0x02: {exact}/{total} payloads exactly satisfy `len(payload)+8 = byte7 × 512`.\n');f.write(f'- type 0x0E blocks: {len(erows)}; type 0x0F blocks: {len(frows)}.\n');f.write(f'- exact 0x0F→0x0E BL_ADDR-shaped fields: {len(links)}.\n')
  f.write('\n## Not established\n\nMoscow city text is present, but `ch_roads` has not yet been parsed from its MORE_INFO structure. Therefore no individual Moscow road name or end-to-end road trace is asserted.\n')
  f.write('\n## Outgoing references from 0x0E\n\n');f.write(str(Counter(x['target_type'] for x in roadlinks))+'\n')
 with (out/'one_road_trace.md').open('w') as f:f.write('# One-road trace\n\nNo trace emitted: a Moscow `ch_roads` FAR_LIST has not been structurally located, so selecting a road would be speculative.\n')
 # Append mismatch data only if present, preserving requested examples.
 with (out/'size_mismatches.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['sector','physical_span','size_field','expected_payload','actual_payload','zlib_success']);w.writeheader();w.writerows(mismatch)
if __name__=='__main__':main()
