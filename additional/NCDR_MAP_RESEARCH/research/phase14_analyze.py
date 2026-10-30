import csv,mmap,zlib,math,collections,statistics,hashlib
from pathlib import Path
S=512; M=5555555
def u16(b,p):return int.from_bytes(b[p:p+2],'big')
def u24(b,p):return int.from_bytes(b[p:p+3],'big')
def u32(b,p):return int.from_bytes(b[p:p+4],'big')
def main(root):
 r=root/'research'; out=r/'type00'; out.mkdir(exist_ok=True); roads=r/'roads'
 with (root/'DB_0').open('rb') as fh,mmap.mmap(fh.fileno(),0,access=mmap.ACCESS_READ) as d:
  H={i:d[i*S+3] for i in range(len(d)//S) if u24(d,i*S)==i}; blocks=[]
  for sec,sp in H.items():
   q=sec*S
   if d[q+5]!=0 or d[q+6] not in (0,2):continue
   raw=bytes(d[q:q+sp*S]); logical=raw if d[q+6]==0 else raw[:8]+zlib.decompress(raw[8:]); blocks.append((sec,sp,logical,d[q+6]))
  inv=[]
  for sec,sp,b,c in blocks: inv.append({'sector':sec,'compression':f'0x{c:02X}','physical_size':sp*S,'logical_size':len(b),'advertised_size':d[sec*S+7]*S,'size_valid':len(b)==d[sec*S+7]*S,'first_0x100':b[:256].hex(),'sha1':hashlib.sha1(b).hexdigest()})
  with (out/'phase14_readable_inventory.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(inv[0]));w.writeheader();w.writerows(inv)
  # common grammar and prefix fields
  gr=[]; prefix=collections.defaultdict(lambda:[0,0,[]])
  for sec,sp,b,c in blocks:
   match=len(b)>=0x80 and u16(b,0x74)==0x0074 and u16(b,0x76)==3
   roots=[u16(b,p) for p in (0x78,0x7c,0x80)] if len(b)>=0x82 else []
   gr.append({'sector':sec,'compression':f'0x{c:02X}','list74_count3':match,'root_targets':';'.join(f'{x:04X}' for x in roots),'logical_size':len(b)})
   for p in range(8,min(0x74,len(b)-1),2):
    v=u16(b,p); valid=v<len(b); prefix[p][0]+=1; prefix[p][1]+=valid
    if valid:prefix[p][2].append(v)
  with (out/'phase14_prefix_fields.csv').open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=['offset','width','field_type','validation_rate','common_values']);w.writeheader()
   for p,(n,v,vals) in sorted(prefix.items()):w.writerow({'offset':f'0x{p:02X}','width':2,'field_type':'uint16_BE/PTR_candidate','validation_rate':v/n,'common_values':','.join(f'{x:04X}' for x,_ in collections.Counter(vals).most_common(8))})
  with (out/'TYPE00_PREFIX_FORMAT.md').open('w') as f:
   for c in ('0x00','0x02'):
    x=[q for q in gr if q['compression']==c];f.write(f'- {c}: {len(x)} readable blocks; LIST(0x74,3) matches {sum(q["list74_count3"] for q in x)}/{len(x)}.\n')
   f.write('- Prefix fields are reported as validated uint16 local-offset candidates; no additional semantic names are asserted.\n')
  # known targets/ranges from readable structures
  secrows=[]
  for sec,sp,b,c in blocks:
   ps=set()
   for p in range(8,min(len(b)-1,0x400),2):
    v=u16(b,p)
    if 8<=v<len(b):ps.add(v)
   if len(b)>=0x82 and u16(b,0x74)==0x74 and u16(b,0x76)==3:
    ps.update(u16(b,p) for p in (0x78,0x7c,0x80))
   ps=sorted(ps)
   for i,p in enumerate(ps):
    e=ps[i+1] if i+1<len(ps) else len(b); secrows.append({'sector':sec,'compression':f'0x{c:02X}','section_index':i,'start':p,'end':e,'size':e-p,'prefix':b[p:p+8].hex(),'zero_ratio':b[p:e].count(0)/(e-p) if e>p else 0,'u16_words':(e-p)//2})
  with (out/'phase14_sections.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(secrows[0]));w.writeheader();w.writerows(secrows)
  # structural matches by simple size/prefix/root signature
  refs=list(csv.DictReader((roads/'phase12_road_refs.csv').open())); targets=sorted(set(int(x['target_sector']) for x in refs if (x.get('target_sector') or '').isdigit()))
  sig={x['sector']:x for x in inv}; matches=[]
  for s in targets:
   a=sig.get(str(s)) or next((x for x in inv if x['sector']==s),None)
   if not a:continue
   cand=sorted((abs(int(a['logical_size'])-int(x['logical_size'])),x['sector'],x['compression']) for x in inv if x['compression'] in ('0x00','0x02') and x['sector']!=s)[:3]
   for dist,t,c in cand:matches.append({'road_target_sector':s,'road_compression':'0x01','control_sector':t,'control_compression':c,'logical_size_delta':dist,'signature_basis':'logical_size+readable_prefix'})
  with (out/'phase14_structural_matches.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(matches[0]));w.writeheader();w.writerows(matches)
  # fixed-width element census on sections
  er=[]
  for x in secrows:
   for wd in (2,4,6,8,10,12,16,20,24,32):
    er.append({'sector':x['sector'],'section_index':x['section_index'],'size':x['size'],'candidate_width':wd,'exact_divisible':x['size']%wd==0,'element_count':x['size']//wd})
  with (out/'phase14_section_elements.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(er[0]));w.writeheader();w.writerows(er)
  # road pointer classification using readable ranges when target is readable control (mostly negative control)
  pr=[]
  for x in refs:
   if not (x.get('target_sector') or '').isdigit():continue
   s=int(x['target_sector']);p=int(x['decoded_pointer']); rr=[q for q in secrows if q['sector']==s and q['start']<=p<q['end']]; z=rr[0] if rr else None
   pr.append({'target_sector':s,'pointer':p,'F':x['F_raw'],'flags':x['flags'],'classification':'SECTION_A' if z and z['section_index']==0 else 'OTHER_CONFIRMED_REGION' if z else 'UNKNOWN','section_start':z['start'] if z else '','section_end':z['end'] if z else '','relative_offset':p-z['start'] if z else ''})
  with (roads/'phase14_road_pointer_classification.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(pr[0]));w.writeheader();w.writerows(pr)
  one=[x for x in pr if x['target_sector']==0x35329 and x['pointer']==0xdf8]
  with (roads/'phase14_1iy.md').open('w') as f:f.write('# Phase 14: 1 iy mikrorayon\n\n'+(str(one[0]) if one else 'No readable-control section boundary contains this pointer; sector 0x35329 is not in the readable control set used here.')+'\n')
  with (out/'PHASE14_FINDINGS.md').open('w') as f:
   f.write(f'# Phase 14 findings\n\n- Readable controls parsed: {len(blocks)} ({sum(c==0 for _,_,_,c in blocks)} raw, {sum(c==2 for _,_,_,c in blocks)} zlib).\n- LIST(0x74,3) and root layout are tested separately by compression in TYPE00_PREFIX_FORMAT.md.\n- Prefix uint16 validation, section candidates, and fixed-width element census are exported; no semantic field names are asserted without cross-block proof.\n- Road-owned pointers are classified conservatively; unknown remains expected because readable controls are not road-owned and compression=0x01 payload equivalence is unresolved.\n- No coordinate or graph decoder is claimed.\n')
  with (r/'PROJECT_STATE.md').open('a') as f:f.write(f'\n## Phase 14 checkpoint\n\n- Built readable type-0x00 logical views for {len(blocks)} blocks ({sum(c==0 for _,_,_,c in blocks)} compression=0x00 and {sum(c==2 for _,_,_,c in blocks)} compression=0x02).\n- Exported prefix validation, provisional section maps, structural matches, and conservative road-pointer classifications; no new semantic decoder is confirmed.\n')
if __name__=='__main__':main(Path(__file__).resolve().parents[1])
