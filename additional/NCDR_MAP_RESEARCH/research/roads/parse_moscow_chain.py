#!/usr/bin/env python3
"""Read-only, type-aware traversal 0x0C Moskva -> 0x0F -> 0x0E."""
from __future__ import annotations
import argparse,csv,json,mmap,zlib
from pathlib import Path
S=512
def recs(d):
 n=len(d)//S;h={i:d[i*S+3] for i in range(n) if int.from_bytes(d[i*S:i*S+3],'big')==i};return h
def logical(d,sec,sp):
 raw=bytes(d[sec*S:sec*S+sp*S]);
 if raw[6]==2:return raw[:8]+zlib.decompress(raw[8:])
 return raw
def u16(b,p):return int.from_bytes(b[p:p+2],'big')
def addr(b,p):return int.from_bytes(b[p:p+3],'big'),b[p+3]
def pstr(b,p):
 if not 0<p<len(b):return ''
 e=b.find(b'\0',p,min(len(b),p+128));
 if e<0:return ''
 x=b[p:e]
 return x.decode('latin1') if x and all(32<=q<=126 for q in x) else ''
def main():
 ap=argparse.ArgumentParser();ap.add_argument('db0',type=Path);ap.add_argument('--output-dir',type=Path,default=Path(__file__).parent);a=ap.parse_args();out=a.output_dir
 cityout={};moreout={};entries=[];roads=[];trace=[];outlinks=[]
 with a.db0.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as d:
  H=recs(d); views={}
  def get(sec):
   if sec not in views:views[sec]=logical(d,sec,H[sec])
   return views[sec]
  found=None
  for sec,sp in H.items():
   h=get(sec)
   if h[5]!=0x0c or len(h)<0x30:continue
   cp,cc=u16(h,8),u16(h,10);mp,mc=u16(h,12),u16(h,14)
   if cp+cc*8>len(h):continue
   for i in range(cc):
    q=cp+i*8; nameptr=u16(h,q);name=pstr(h,nameptr)
    if name=='moskva':found=(sec,h,cp,cc,mp,mc,i,q);break
   if found:break
  if not found:raise SystemExit('No exact moskva BRIF found')
  sec,h,cp,cc,mp,mc,idx,q=found; regionptr=u16(h,q+4);pm=u16(h,q+6)
  cityout={'sector':sec,'physical_span':H[sec],'compression':h[6],'logical_size':len(h),'pl_all_cityes':{'ptr':cp,'count':cc},'pl_all_moreinfo':{'ptr':mp,'count':mc},'moskva':{'brif_index':idx,'brif_relative_offset':q,'name_pointer':u16(h,q),'name':pstr(h,u16(h,q)),'region_pointer':regionptr,'region':pstr(h,regionptr),'place_bitemask':h[q+2],'language':h[q+3],'p_moreinfo':pm}}
  trace.append(f'0x0C sector {sec:#x}, BRIF {q:#x}, p_moreinfo={pm:#x}')
  m=h[pm:pm+0x18];farsec,farsp=addr(m,0);lptr,lcnt=u16(m,4),u16(m,6);target=get(farsec)
  moreout={'logical_offset':pm,'raw_hex':m.hex(),'ch_roads':{'raw_bl_addr':m[:4].hex(),'target_sector':farsec,'target_physical_span':farsp,'target_header_bl_addr':target[:4].hex(),'target_block_type':f'0x{target[5]:02x}','list_ptr':lptr,'list_count':lcnt},'poi_category_list':{'ptr':u16(m,8),'count':u16(m,10)},'block_type_00':m[12:16].hex(),'city_id_candidate':u16(m,16),'zero_u16':u16(m,18),'zero_or_variant':m[20:24].hex()}
  trace.append(f'MORE_INFO {pm:#x}: ch_roads {m[:4].hex()} -> 0x0F sector {farsec:#x}; list {lptr:#x}/{lcnt}')
  # CH_IDX: BL_ADDR(4), char(1), flag(1), LIST(4), alignment(2).
  seen=set()
  def walk(s,offset,count,prefix=''):
   b=get(s)
   if offset+count*12>len(b):return
   for i in range(count):
    x=offset+i*12;ts,tsp=addr(b,x);ch=chr(b[x+4]) if 32<=b[x+4]<127 else '';childptr,childcnt=u16(b,x+6),u16(b,x+8);tt=get(ts)[5] if ts in H else None
    key=prefix+ch; row={'0F_sector':s,'0F_offset':x,'index_key':key,'child_count':childcnt,'local_child_ptr':childptr,'target_sector':ts,'target_type':f'0x{tt:02x}' if tt is not None else 'invalid','reference_raw':b[x:x+12].hex()};entries.append(row)
    if tt==0x0f and (s,x) not in seen:seen.add((s,x));walk(ts,childptr,childcnt,key)
    if tt==0x0e:
     e=get(ts)
     # index LIST convention: each target item begins with PSTR in target block.
     for j in range(childcnt):
      ep=childptr+j*8
      if ep+2>len(e):break
      np=u16(e,ep);name=pstr(e,np)
      if name:roads.append({'road_index':len(roads),'index_key':key,'road_name':name,'0F_sector':s,'0F_offset':x,'0E_sector':ts,'0E_span':H[ts],'reference_raw':b[x:x+12].hex()})
  if target[5]==0x0f:walk(farsec,lptr,lcnt)
  # Deduplicate only final road rows; preserve index provenance for first hit.
  uniq={r['road_name']:r for r in roads};roads=list(uniq.values())
  if roads:
   r=roads[0];e=get(r['0E_sector']);trace.append(f"0x0F {r['0F_sector']:#x}+{r['0F_offset']:#x} -> 0x0E {r['0E_sector']:#x}; name={r['road_name']!r}")
   for at in range(len(e)-3):
    ts,sp=addr(e,at)
    if ts in H and H[ts]==sp:outlinks.append({'source_0E_sector':r['0E_sector'],'source_offset':at,'raw_bl_addr':e[at:at+4].hex(),'target_sector':ts,'target_type':f'0x{get(ts)[5]:02x}'})
  else:trace.append('No structurally resolved PSTR road name; no single-road trace asserted.')
 with (out/'moscow_city_record.json').open('w') as f:json.dump(cityout,f,indent=2)
 with (out/'moscow_more_info.json').open('w') as f:json.dump(moreout,f,indent=2)
 with (out/'moscow_0F_entries.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['0F_sector','0F_offset','index_key','child_count','local_child_ptr','target_sector','target_type','reference_raw']);w.writeheader();w.writerows(entries)
 with (out/'moscow_roads.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=['road_index','index_key','road_name','0F_sector','0F_offset','0E_sector','0E_span','reference_raw']);w.writeheader();w.writerows(roads)
 with (out/'one_road_trace.md').open('w') as f:f.write('# Moscow road trace\n\n'+'\n\n'.join(trace)+'\n\n## Outgoing exact BL_ADDR fields\n\n'+ '\n'.join(str(x) for x in outlinks))
 with (out/'MOSCOW_CHAIN.md').open('w') as f:f.write('# Moscow chain\n\n'+ '\n'.join(trace)+f'\n\nReachable CH_IDX entries: {len(entries)}; unique structurally resolved road names: {len(roads)}.\n')
if __name__=='__main__':main()
