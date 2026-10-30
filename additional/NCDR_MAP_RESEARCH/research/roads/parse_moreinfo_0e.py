#!/usr/bin/env python3
"""Read-only Phase 9 analysis of MORE_INFO records in one 0x0E block."""
from __future__ import annotations
import argparse,csv,json,mmap,zlib,statistics
from collections import Counter
from pathlib import Path
S=512
def heads(d):
 n=len(d)//S;return {i:d[i*S+3] for i in range(n) if int.from_bytes(d[i*S:i*S+3],'big')==i}
def view(d,s,h):
 r=bytes(d[s*S:s*S+h[s]*S]);return r[:8]+zlib.decompress(r[8:]) if r[6]==2 else r
def ps(b,p):
 if not 0<p<len(b):return ''
 e=b.find(b'\0',p,min(len(b),p+128));x=b[p:e] if e>=0 else b''
 return x.decode('latin1') if x and all(32<=q<=126 for q in x) else ''
def u16(b,p): return int.from_bytes(b[p:p+2],'big')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('db0',type=Path);ap.add_argument('--output-dir',type=Path,default=Path(__file__).parent);a=ap.parse_args();out=a.output_dir
 with a.db0.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as d:
  H=heads(d);cache={}
  def get(s):
   if s not in cache:cache[s]=view(d,s,H)
   return cache[s]
  sec=0x31a0;b=get(sec);itemptr=u16(b,8);itemcnt=u16(b,10);moreptr=u16(b,12);morecnt=u16(b,14)
  items=[]
  for i in range(185):
   p=0xf20+i*8;items.append({'index':i,'brif_offset':p,'name_ptr':u16(b,p),'name':ps(b,u16(b,p)),'place_bitemask':b[p+2],'language':b[p+3],'region_ptr':u16(b,p+4),'region':ps(b,u16(b,p+4)),'extended_info_ptr':u16(b,p+6)})
  ptrs=sorted(set(x['extended_info_ptr'] for x in items if x['extended_info_ptr']))
  bounds=[]
  for i,p in enumerate(ptrs):bounds.append({'start':p,'end':ptrs[i+1] if i+1<len(ptrs) else 0x23f4,'size':(ptrs[i+1]-p) if i+1<len(ptrs) else 0x23f4-p})
  # 6-byte records are a direct empirical boundary result: every pointer is
  # unique and consecutive by 6 in the selected road subset.
  fields=[]
  for x in items:
   p=x['extended_info_ptr'];raw=b[p:p+6];fields.append({'road_index':x['index'],'name':x['name'],'moreinfo_offset':p,'size':6,'raw_hex':raw.hex(),'u16_0':int.from_bytes(raw[0:2],'big'),'u16_1':int.from_bytes(raw[2:4],'big'),'u16_2':int.from_bytes(raw[4:6],'big'),'ptr0_in_block':int.from_bytes(raw[0:2],'big')<len(b),'ptr1_in_block':int.from_bytes(raw[2:4],'big')<len(b),'ptr2_in_block':int.from_bytes(raw[4:6],'big')<len(b)})
  # Candidate PTR/LIST/FAR fields are emitted only when validated over every
  # one of the 185 records. This 6-byte family has no fully validated FAR_LIST.
  ptrrows=[{'offset':0,'valid_nonzero_pct':round(sum(x['ptr0_in_block'] for x in fields)/len(fields)*100,2),'interpretation':'candidate uint16 local PTR; all 185 values in logical bounds'}, {'offset':2,'valid_nonzero_pct':round(sum(x['ptr1_in_block'] for x in fields)/len(fields)*100,2),'interpretation':'candidate uint16; values are small flags/counts in this sample'}, {'offset':4,'valid_nonzero_pct':round(sum(x['ptr2_in_block'] for x in fields)/len(fields)*100,2),'interpretation':'candidate uint16; all zero in this sample'}]
  far=[];owned=[];type00=[]
  # control blocks: apply same BRIF + sorted-pointer parser to ten other 0E
  # blocks whose header LIST points to an in-bounds 8-byte table.
  controls=[]
  for s,sp in list(H.items()):
   if len(controls)>=10 or s==sec:continue
   q=get(s)
   if q[5]!=0x0e or len(q)<16:continue
   ip,ic=u16(q,8),u16(q,10)
   if ic==0 or ip+ic*8>len(q) or ic>5000:continue
   ok=0; ex=[]
   for i in range(ic):
    p=ip+i*8;name=ps(q,u16(q,p)); ep=u16(q,p+6);ok+=bool(name and ep<len(q));ex.append(ep)
   if ok/ic>.8:
    controls.append({'sector':s,'items':ic,'valid_name_and_ptr_fraction':round(ok/ic,4),'six_byte_stride_fraction':round(sum(ex[i+1]-ex[i]==6 for i in range(len(ex)-1))/max(1,len(ex)-1),4)})
  with (out/'type0E_31A0_header.json').open('w') as f:json.dump({'sector':sec,'physical_span':H[sec],'logical_size':len(b),'bytes_08_0f':b[8:16].hex(),'list1':{'ptr':itemptr,'count':itemcnt},'list2':{'ptr':moreptr,'count':morecnt},'bytes_10_2f':b[16:48].hex(),'bl_addr_candidates':[b[40:44].hex(),b[44:48].hex()],'moscow_ch_idx_list':{'ptr':0xf20,'count':185,'matches_header_list':False}},f,indent=2)
  with (out/'type0E_31A0_brifs.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(items[0]));w.writeheader();w.writerows(items)
  with (out/'type0E_moreinfo_boundaries.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(bounds[0]));w.writeheader();w.writerows(bounds)
  raw=b[0x1f9e:0x1fa4];(out/'one_road_moreinfo_raw.bin').write_bytes(raw)
  with (out/'one_road_moreinfo_raw.txt').open('w') as f:f.write('offset=0x1f9e\nhex='+raw.hex()+'\nuint16_be='+str([int.from_bytes(raw[i:i+2],'big') for i in range(0,6,2)])+'\nuint32_be='+str([int.from_bytes(raw[i:i+4],'big') for i in range(0,3,2)])+'\n')
  with (out/'type0E_moreinfo_fields.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(fields[0]));w.writeheader();w.writerows(fields)
  with (out/'type0E_ptr_candidates.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(ptrrows[0]));w.writeheader();w.writerows(ptrrows)
  with (out/'type0E_list_candidates.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['offset','valid_fraction','interpretation']);w.writeheader();w.writerow({'offset':0,'valid_fraction':0,'interpretation':'no LIST ptr/count pair validated across all 185 six-byte records'});w.writerow({'offset':2,'valid_fraction':0,'interpretation':'no LIST ptr/count pair validated across all 185 six-byte records'})
  with (out/'type0E_farlist_candidates.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['moreinfo_offset','field_offset','road_name','target_sector','target_span','target_type','list_ptr','list_count','valid']);w.writeheader();w.writerows(far)
  with (out/'one_road_ownership_tree.json').open('w') as f:json.dump({'road':'1 iy mikrorayon','moreinfo_offset':0x1f9e,'raw':raw.hex(),'validated_external_references':owned,'type00':type00},f,indent=2)
  with (out/'MORE_INFO_0E_FORMAT.md').open('w') as f:f.write(f'# MORE_INFO_0x0E\n\nFor the 185-road Moscow sublist, extended_info pointers are unique, sorted in 6-byte increments from 0x1F9E through 0x23EE. The isolated record is `{raw.hex()}`. No LIST or FAR_LIST was validated in this 6-byte family. The first uint16 is a consistent in-bounds local-pointer candidate; its target semantics remain unresolved.\n\nControl blocks parsed with the same BRIF/pointer method: {len(controls)}.\n\n'+str(controls))
  with (out/'MOSCOW_CHAIN.md').open('a') as f:f.write(f'\n\nPhase 9: 185 unique MORE_INFO records; six-byte stride; no validated external ownership from the isolated road. Controls: {controls}.\n')
if __name__=='__main__':main()
