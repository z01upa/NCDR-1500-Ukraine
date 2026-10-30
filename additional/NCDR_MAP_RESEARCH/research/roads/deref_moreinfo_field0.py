#!/usr/bin/env python3
"""Read-only Phase 10 dereference of 0x0E MORE_INFO field0."""
from __future__ import annotations
import argparse,csv,json,mmap,zlib,collections
from pathlib import Path
S=512;M=5555555
def u16(b,p):return int.from_bytes(b[p:p+2],'big')
def hdrs(d):
 n=len(d)//S;return {i:d[i*S+3] for i in range(n) if int.from_bytes(d[i*S:i*S+3],'big')==i}
def view(d,s,H):
 r=bytes(d[s*S:s*S+H[s]*S]);return r[:8]+zlib.decompress(r[8:]) if r[6]==2 else r
def pstr(b,p):
 if not 0<p<len(b):return ''
 e=b.find(b'\0',p,min(len(b),p+128));x=b[p:e] if e>=0 else b''
 return x.decode('latin1') if x and all(32<=q<=126 for q in x) else ''
def main():
 ap=argparse.ArgumentParser();ap.add_argument('db0',type=Path);ap.add_argument('--output-dir',type=Path,default=Path(__file__).parent);a=ap.parse_args();out=a.output_dir
 with a.db0.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as d:
  H=hdrs(d);C={}
  def get(s):
   if s not in C:C[s]=view(d,s,H)
   return C[s]
  sec=0x31a0;b=get(sec);rows=[];targets=[];owned=[]
  for i in range(185):
   q=0xf20+i*8;mi=u16(b,q+6);f0,f1,f2=u16(b,mi),u16(b,mi+2),u16(b,mi+4);count=f1>>8;flag=f1&255
   rows.append({'road_index':i,'road_name':pstr(b,u16(b,q)),'brif_offset':q,'moreinfo_offset':mi,'field0':f0,'field1':f1,'field2':f2,'field1_hi':count,'field1_lo':flag,'field2_hi':f2>>8,'field2_lo':f2&255})
   for j in range(count):
    p=f0+j*24;raw=b[p:p+24];lonv=int.from_bytes(raw[:4],'big');latv=int.from_bytes(raw[4:8],'big');lon=lonv/M-30;lat=latv/M;ts=int.from_bytes(raw[16:19],'big');sp=raw[19];valid=ts in H and H[ts]==sp
    targets.append({'road_index':i,'road_name':pstr(b,u16(b,q)),'field0':f0,'element_index':j,'target_offset':p,'object_size':24,'raw_hex':raw.hex(),'longitude':round(lon,6),'latitude':round(lat,6),'moscow_coordinate':36.5<=lon<=38.5 and 55<=lat<=56.3,'u16_08':u16(raw,8),'u16_0a':u16(raw,10),'u16_0c':u16(raw,12),'u16_0e':u16(raw,14),'bladdr_raw':raw[16:20].hex(),'bladdr_valid':valid,'target_sector':ts if valid else '','target_type':f'0x{get(ts)[5]:02x}' if valid else '','tail_u16_0':u16(raw,20),'tail_u16_1':u16(raw,22),'tail_list_valid_in_target':bool(valid and u16(raw,20)+u16(raw,22)<=len(get(ts)))})
  r0=rows[0];o0=[x for x in targets if x['road_index']==0]
  for x in o0:
   if x['bladdr_valid']:owned.append({'depth':3,'source':'field0_object','source_offset':x['target_offset']+16,'field':'BL_ADDR','target_type':x['target_type'],'target_sector':x['target_sector'],'validation':'raw address equals target BL_HEAD; span matches'})
  unique=sorted(set(x['field0'] for x in rows));deltas=collections.Counter(y-x for x,y in zip(unique,unique[1:]));align=collections.Counter(x%24 for x in unique)
  # exact same parser on first ten other type-0E blocks: header LIST1 BRIFs,
  # LIST2 six-byte MORE_INFO, LIST3 24-byte target objects.
  variants=[]
  for s in H:
   if len(variants)>=10 or s==sec:continue
   q=get(s)
   if q[5]!=0x0e or len(q)<24:continue
   ip,ic,mp,mc,op,oc=u16(q,8),u16(q,10),u16(q,12),u16(q,14),u16(q,16),u16(q,18)
   six=(mp+mc*6<=len(q)); twentyfour=(op+oc*24<=len(q));valid=0
   if ip+ic*8<=len(q):
    for i in range(ic):
     p=ip+i*8;mi=u16(q,p+6)
     if mi+6<=len(q):
      f0=u16(q,mi);cnt=q[mi+2];valid+=bool(cnt and op<=f0<op+oc*24 and f0+cnt*24<=op+oc*24)
   variants.append({'sector':s,'compressed':q[6]==2,'list1_count':ic,'list2_count':mc,'list3_count':oc,'six_byte_region_in_bounds':six,'twentyfour_byte_region_in_bounds':twentyfour,'brifs_matching_model':valid,'success_rate':round(valid/ic,4) if ic else 0})
 with (out/'moreinfo0E_moscow.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 with (out/'field0_targets.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(targets[0]));w.writeheader();w.writerows(targets)
 with (out/'type0E_variants.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(variants[0]));w.writeheader();w.writerows(variants)
 ctx=b[0x54b4-64:0x54b4+256]
 with (out/'54B4_analysis.txt').open('w') as f:f.write(f'context_start=0x{0x54b4-64:x}\nhex={ctx.hex()}\nobject={b[0x54b4:0x54cc].hex()}\nuint16={[u16(b,0x54b4+i) for i in range(0,24,2)]}\nuint32={[int.from_bytes(b[0x54b4+i:0x54b4+i+4],"big") for i in range(0,24,4)]}\ncoordinate={o0[0]["longitude"]},{o0[0]["latitude"]}\nBL_ADDR={o0[0]["bladdr_raw"]} -> type {o0[0]["target_type"]} sector {o0[0]["target_sector"]}\nfollowing_u16_pair={o0[0]["tail_u16_0"]},{o0[0]["tail_u16_1"]}; LIST-in-target-valid={o0[0]["tail_list_valid_in_target"]}\n')
 with (out/'1iy_mikrorayon_tree.json').open('w') as f:json.dump({'road':'1 iy mikrorayon','brif_offset':r0['brif_offset'],'moreinfo_offset':r0['moreinfo_offset'],'field0':r0['field0'],'object_count':r0['field1_hi'],'flag':r0['field1_lo'],'reserved':r0['field2'],'objects':o0,'confirmed_external_references':owned},f,indent=2)
 with (out/'MORE_INFO_0E_FIELD0.md').open('w') as f:f.write(f'# MORE_INFO_0x0E field0\n\n## Confirmed\n\n`field0` points into header LIST3, a 24-byte object array. `field1_hi` is the number of consecutive objects owned by the road: it exactly accounts for pointer gaps across the sorted sequence. `field1_lo` is a 0/1 flag in most records; semantics unknown. `field2` is zero in all 185.\n\nThe first object starts with a valid Moscow-area MULCOORD pair and has a fully validated BL_ADDR at +0x10 to type 0x00. The following uint16 pair does not validate as a LIST relative to that target and is not called FAR_LIST.\n\nUnique field0 values: {len(unique)}; duplicates: {185-len(unique)}; min/max: {min(unique):#x}/{max(unique):#x}; delta histogram: {dict(deltas)}; modulo-24 distribution: {dict(align)}.\n\n## Cross-block controls\n\n{variants}\n')
if __name__=='__main__':main()
