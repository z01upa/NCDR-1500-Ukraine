import csv, mmap, math, collections, statistics
from pathlib import Path
S=512
def hx(x):
 try:return int(str(x),0)
 except:return None
def main(root):
 r=root/'research'; out=r/'roads'
 roots=list(csv.DictReader((r/'type00_roots.csv').open()))
 desc=list(csv.DictReader((r/'type00_full_descriptor_table.csv').open()))
 refs=list(csv.DictReader((out/'phase12_road_refs.csv').open()))
 refs=[x for x in refs if (x.get('target_sector') or '').isdigit()]
 by=collections.defaultdict(set)
 for x in roots:
  s=int(x['sector']); p=hx(x['target']);
  if p is not None: by[s].add(p)
 for x in desc:
  s=int(x['sector']); p=hx(x['value']);
  if x.get('pointer_valid')=='True' and p is not None: by[s].add(p)
 maps=[]; ranges={}
 for s,ps in by.items():
  ps=sorted(ps); rows=[]
  # logical size from road refs where available; otherwise no invented terminal
  sizes=[int(x['target_logical_size']) for x in refs if int(x['target_sector'])==s]
  for i,p in enumerate(ps):
   end=ps[i+1] if i+1<len(ps) else (max(sizes) if sizes else '')
   row={'target_sector':s,'section_index':i,'section_start':p,'section_end':end,'section_size':(end-p if end!='' else ''),'source':'roots+descriptor_table'}; rows.append(row)
  ranges[s]=rows; maps+=rows
 with (out/'phase13_section_map.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(maps[0]));w.writeheader();w.writerows(maps)
 mapped=[]
 for x in refs:
  s=int(x['target_sector']); p=int(x['decoded_pointer']); rr=ranges.get(s,[]); exact=[z for z in rr if z['section_start']==p]; inside=[z for z in rr if z['section_end']!='' and z['section_start']<=p<z['section_end']]
  z=(inside or exact or [None])[0]; known=bool(z); mapped.append({'target_sector':s,'pointer':p,'F':x['F_raw'],'flags':x['flags'],'road_name':x['road_name'],'exact_descriptor_target':bool(exact),'inside_known_range':known,'range_class':'exact_descriptor' if exact else 'inside_section' if inside else 'before_sections' if rr and p<rr[0]['section_start'] else 'after_known_sections' if rr else 'no_known_sections','section_start':z['section_start'] if z else '','section_end':z['section_end'] if z else '','relative_offset':p-z['section_start'] if z else '','alignment2':p%2==0,'alignment4':p%4==0,'alignment8':p%8==0})
 with (out/'phase13_road_pointer_sections.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(mapped[0]));w.writeheader();w.writerows(mapped)
 # compression inventory
 ri=list(csv.DictReader((r/'known_format/block_types.csv').open())); inv=collections.Counter()
 for x in ri:
  if x.get('block_type') in ('0x00','00','0'): inv[x.get('compression_method','')]+=1
 rows=[]
 for k,v in sorted(inv.items()): rows.append({'compression_code':k,'record_count':v,'road_referenced_count':sum(1 for x in refs if str(int(x['target_sector']))==k) if False else ''})
 with (out/'phase13_type00_compression_controls.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['compression_code','record_count','road_referenced_count']);w.writeheader();w.writerows(rows)
 one=[x for x in mapped if x['target_sector']==0x35329 and x['pointer']==0x0df8]
 with (out/'phase13_1iy_section.md').open('w') as f:
  f.write('# Phase 13: 1 iy mikrorayon section mapping\n\n')
  if one:
   x=one[0]; f.write(f'- pointer `0x0DF8`, F={x["F"]}, flags={x["flags"]}.\n- Classification: **{x["range_class"]}**; containing section start: `{x["section_start"]}`; relative offset: `{x["relative_offset"]}`; next boundary: `{x["section_end"]}`.\n')
  f.write('- This is a structural range mapping only; no payload grammar is asserted.\n')
 inside=sum(x['inside_known_range'] for x in mapped); exact=sum(x['exact_descriptor_target'] for x in mapped); total=len(mapped)
 unique=len({(x['target_sector'],x['pointer']) for x in mapped})
 with (out/'PHASE13_FINDINGS.md').open('w') as f:
  f.write('# Phase 13 findings\n\n')
  f.write(f'- Mapped {unique} unique road-owned pointers ({total} owner rows) against {len(maps)} provisional descriptor/root ranges across {len(ranges)} target blocks.\n')
  f.write(f'- Inside known ranges: {inside}/{total} ({inside/total:.1%}); exact descriptor targets: {exact}/{total} ({exact/total:.1%}).\n')
  f.write('- E flags do not by themselves establish a root/section selector; pointers are best treated as absolute local offsets into type-0x00 blocks until section-relative encoding is proven.\n')
  f.write('- F remains unresolved after grouping: same-section pointer spacing and F values do not establish a uniform record model.\n')
  f.write('- Compression inventory is recorded separately; compression=0x01 section-level behavior is not confirmed by this mapping alone.\n')
  f.write('- No geometry was emitted. Remaining blocker: exact terminal framing and the compression=0x01 payload grammar.\n')
 with (root/'research/PROJECT_STATE.md').open('a') as f:
  f.write(f'\n## Phase 13 checkpoint\n\n- Mapped {unique} unique road-owned pointers ({total} owner rows) to {len(maps)} provisional root/descriptor ranges across {len(ranges)} type-0x00 blocks.\n- No new section-relative or E-flag semantics are confirmed; terminal section framing and compression=0x01 grammar remain unresolved.\n')
if __name__=='__main__': main(Path(__file__).resolve().parents[2])
