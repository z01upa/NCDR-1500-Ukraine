#!/usr/bin/env python3
"""Read-only isolation of the first Moscow 0x0E road entry."""
from __future__ import annotations
import argparse,csv,json,mmap,zlib
from pathlib import Path
S=512
def recs(d):
 n=len(d)//S;return {i:d[i*S+3] for i in range(n) if int.from_bytes(d[i*S:i*S+3],'big')==i}
def view(d,s,sp):
 r=bytes(d[s*S:s*S+sp*S]);return r[:8]+zlib.decompress(r[8:]) if r[6]==2 else r
def u16(b,p):return int.from_bytes(b[p:p+2],'big')
def strp(b,p):
 if not 0<p<len(b):return ''
 e=b.find(b'\0',p,min(len(b),p+128));x=b[p:e] if e>=0 else b''
 return x.decode('latin1') if x and all(32<=q<=126 for q in x) else ''
def main():
 ap=argparse.ArgumentParser();ap.add_argument('db0',type=Path);ap.add_argument('--output-dir',type=Path,default=Path(__file__).parent);a=ap.parse_args();out=a.output_dir
 with a.db0.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as d:
  H=recs(d);cache={}
  def get(s):
   if s not in cache:cache[s]=view(d,s,H[s])
   return cache[s]
  fsec=0x1b19;foff=0x4a10;fb=get(fsec);ts=int.from_bytes(fb[foff:foff+3],'big');sp=fb[foff+3];childptr=u16(fb,foff+6);cnt=u16(fb,foff+8)
  e=get(ts);items=[]
  for i in range(cnt):
   p=childptr+i*8;np=u16(e,p);items.append({'item_index':i,'item_start_offset':p,'item_end_offset':p+8,'name_pointer':np,'name':strp(e,np),'place_bitemask':e[p+2],'language':e[p+3],'region_pointer':u16(e,p+4),'region':strp(e,u16(e,p+4)),'extended_info_ptr':u16(e,p+6),'raw_hex':e[p:p+8].hex()})
  road=next(x for x in items if x['name']=='1 iy mikrorayon')
  # Five controls: first valid parsed road from distinct E targets among the
  # Moscow root CH_IDX entries. Same 8-byte parser, no per-road adaptation.
  controls=[];seen={ts}
  for x in range(foff, min(len(fb)-12,foff+30*12),12):
   q=int.from_bytes(fb[x:x+3],'big');qsp=fb[x+3]
   if q in seen or q not in H or H[q]!=qsp or get(q)[5]!=0x0e:continue
   seen.add(q);b=get(q);ptr=u16(fb,x+6);n=u16(fb,x+8)
   for j in range(n):
    p=ptr+j*8
    if p+8>len(b):break
    name=strp(b,u16(b,p))
    if name:controls.append({'0F_offset':x,'0E_sector':q,'item_offset':p,'name':name,'raw_hex':b[p:p+8].hex()});break
   if len(controls)>=5:break
  entry={'0F_sector':fsec,'logical_offset':foff,'raw_ch_idx':fb[foff:foff+12].hex(),'key':chr(fb[foff+4]),'index_flag':fb[foff+5],'target_0E_sector':ts,'target_span':sp,'target_type':f'0x{e[5]:02x}','list_ptr_into_0E':childptr,'list_count':cnt,'conclusion':'CH_IDX identifies a list inside the 0x0E block through its LIST ptr/count, not merely the block.'}
  layout={'record_width':8,'list_start':childptr,'list_count':cnt,'fields':['uint16_be PSTR name','uint8 place_bitemask','uint8 language','uint16_be PSTR region','uint16_be PTR extended_info'],'validation':{'all_entries_in_bounds':childptr+cnt*8<=len(e),'named_entries':sum(bool(x['name']) for x in items),'extended_info_ptrs_in_bounds':sum(0<x['extended_info_ptr']<len(e) for x in items),'example_names':[x['name'] for x in items[:10]]}}
  # No field in the isolated 8-byte item is BL_ADDR/FAR_LIST; do not assign the
  # pointed extended-info region an ownership model before parsing it.
  owned=[];type00=[]
 with (out/'one_road_0F_entry.json').open('w') as f:json.dump(entry,f,indent=2)
 with (out/'one_road_0E_item.json').open('w') as f:json.dump(road,f,indent=2)
 with (out/'type0E_layout.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(items[0]));w.writeheader();w.writerows(items)
 with (out/'TYPE0E_FORMAT.md').open('w') as f:f.write('# Type 0x0E road-entry layout\n\n## Strongly supported\n\n'+json.dumps(layout,indent=2)+'\n\nThe extended-info target is only a block-local PTR at this stage; it has not been parsed as a FAR_LIST or attributed external ownership.\n')
 with (out/'one_road_owned_references.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['depth','source_type','source_sector','source_offset','field_name','raw_bytes','target_type','target_sector','target_offset','validation']);w.writeheader();w.writerows(owned)
 with (out/'one_road_type00.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['sector','span','compression','logical_size','list_pointer','list_count','element_index']);w.writeheader();w.writerows(type00)
 with (out/'type00_road_vs_poi.md').open('w') as f:f.write('# Type 0x00 road vs POI\n\nNo type-0x00 block is structurally owned by the isolated eight-byte road entry yet. Comparison is deferred until its extended-info PTR is parsed.\n')
 with (out/'one_road_trace.md').open('w') as f:f.write('# Isolated road trace\n\n'+json.dumps(entry,indent=2)+'\n\n'+json.dumps(road,indent=2)+'\n\nControls using the same parser:\n\n'+json.dumps(controls,indent=2))
if __name__=='__main__':main()
