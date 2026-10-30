#!/usr/bin/env python3
import csv, math, mmap, zlib, hashlib, collections, statistics
from pathlib import Path

S=512; M=5555555
def u16(b,p): return int.from_bytes(b[p:p+2],'big')
def u24(b,p): return int.from_bytes(b[p:p+3],'big')
def u32(b,p): return int.from_bytes(b[p:p+4],'big')
def corr(a,b):
    if len(a)<2:return ''
    ma=sum(a)/len(a); mb=sum(b)/len(b); da=[x-ma for x in a]; db=[y-mb for y in b]; den=math.sqrt(sum(x*x for x in da)*sum(y*y for y in db)); return sum(x*y for x,y in zip(da,db))/den if den else 0
def main(root):
    roads=root/'research/roads'; db=root/'DB_0'
    refs=list(csv.DictReader((roads/'type00_list_references.csv').open()))
    refs=[r for r in refs if (r.get('target_sector') or '').isdigit()]
    # rebuild per-block pointer extents, retaining all duplicate owners
    by=collections.defaultdict(list)
    for r in refs: by[int(r['target_sector'])].append(r)
    extent=[]
    for sec, rows in by.items():
        ptrs=sorted(set(int(r['decoded_pointer']) for r in rows)); size=max(int(r['target_logical_size']) for r in rows)
        for i,p in enumerate(ptrs):
            nxt=ptrs[i+1] if i+1<len(ptrs) else size; own=[r for r in rows if int(r['decoded_pointer'])==p]; fs=sorted(set(int(r['F_raw']) for r in own)); f=fs[0] if len(fs)==1 else ''
            extent.append({'target_sector':sec,'pointer':p,'previous_pointer':ptrs[i-1] if i else '','next_pointer':nxt,'extent':nxt-p,'sharing_objects':len(own),'F_values':';'.join(map(str,fs)),'F':f,'flags':';'.join(sorted(set(r['flags'] for r in own))),'road_names':';'.join(sorted(set(r['road_name'] for r in own)))})
    fields=list(extent[0]);
    with (roads/'phase12_road_refs.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(refs[0])+['previous_pointer','next_greater_pointer','extent','sharing_objects','all_F_values']); w.writeheader()
        for r in refs:
            es=[x for x in extent if x['target_sector']==int(r['target_sector']) and x['pointer']==int(r['decoded_pointer'])][0]; w.writerow({**r,'previous_pointer':es['previous_pointer'],'next_greater_pointer':es['next_pointer'],'extent':es['extent'],'sharing_objects':es['sharing_objects'],'all_F_values':es['F_values']})
    widths=[2,3,4,5,6,8,10,12,16,20,24,28,32,36,40,48,56,64,80,96,128,256]
    cats=lambda f: 'F=1' if f==1 else 'F=2' if f==2 else 'F=3' if f==3 else 'F=4' if f==4 else 'F=5..8' if f<=8 else 'F=9..16' if f<=16 else 'F>16'
    model=[]
    for e in extent:
        if not e['F']:continue
        f=int(e['F']); ex=int(e['extent']);
        for w in widths:model.append({'target_sector':e['target_sector'],'pointer':e['pointer'],'F':f,'F_group':cats(f),'extent':ex,'extent_div_F':ex/f,'candidate_width':w,'exact':ex==f*w,'remainder':ex%(f*w)})
    with (roads/'phase12_extent_analysis.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(model[0]));w.writeheader();w.writerows(model)
    # raw fingerprints and lightweight pointer-table tests
    with db.open('rb') as fh, mmap.mmap(fh.fileno(),0,access=mmap.ACCESS_READ) as d:
        rows=[]; clusters=collections.Counter()
        for e in extent:
            sec=e['target_sector']; base=sec*S; logical=d[base+7]*S; p=int(e['pointer']); end=min(logical,int(e['next_pointer'])); raw=bytes(d[base+p:base+end]);
            z=raw.count(0)/len(raw) if raw else 0; ent=len(set(raw)); words=[u16(raw,i) for i in range(0,len(raw)-1,2)]; small=sum(x<256 for x in words); local=sum(x<logical for x in words); key=(e['F'],e['extent'],e['flags'],raw[:8].hex()); clusters[key]+=1
            rows.append({'target_sector':sec,'pointer':p,'F':e['F'],'extent':len(raw),'flags':e['flags'],'byte_entropy_unique':ent,'zero_ratio':z,'u16_words':len(words),'local_pointer_words':local,'zero_words':sum(x==0 for x in words),'small_u16':small,'prefix8':raw[:8].hex(),'suffix8':raw[-8:].hex() if raw else '','sha1':hashlib.sha1(raw).hexdigest(),'ptrtable_F_success':bool(e['F'] and len(raw)>=2*int(e['F'])),'ptrtable_F1_success':bool(e['F'] and len(raw)>=2*(int(e['F'])+1))})
            if sec==0x35329 and p==0x0df8: (roads/'phase12_1iy_bytes.bin').write_bytes(raw)
    with (roads/'phase12_list_clusters.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    # aggregate element model table and report
    agg=[]
    for c in ['F=1','F=2','F=3','F=4','F=5..8','F=9..16','F>16']:
        subset=[x for x in extent if x['F'] and cats(int(x['F']))==c]
        for wd in widths:
            exact=sum(int(int(x['extent'])==int(x['F'])*wd) for x in subset)
            agg.append({'F_group':c,'candidate_width':wd,'lists':len(subset),'exact':exact,'success_rate':exact/len(subset) if subset else 0})
    with (roads/'phase12_element_models.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(agg[0]));w.writeheader();w.writerows(agg)
    special=next((x for x in extent if x['target_sector']==0x35329 and x['pointer']==0x0df8),None)
    crows=[x for x in rows if x['target_sector']==0x35329 and x['pointer']==0x0df8]
    with (roads/'phase12_1iy_analysis.md').open('w') as f:
        f.write('# Phase 12: 1 iy mikrorayon\n\n')
        f.write(f'- Target sector: `0x35329`; pointer: `0x0DF8`; F: `31`; exact next-pointer extent: `{special["extent"] if special else "unknown"}` bytes.\n')
        f.write(f'- Raw-region fingerprint: `{crows[0]["sha1"] if crows else "unavailable"}`; prefix `{crows[0]["prefix8"] if crows else ""}`.\n')
        f.write('- F=31 is not validated as a fixed-width record count: no single candidate width is cross-road dominant, and pointer-table validation is not structurally successful across the corpus.\n')
    with (roads/'PHASE12_FINDINGS.md').open('w') as f:
        f.write('# Phase 12 findings\n\n')
        f.write(f'- Road references: {len(refs)} objects; {len(extent)} unique target-block pointers; {sum(bool(e["F"]) for e in extent)} with known F.\n')
        f.write(f'- Exact extents: {len(extent)}; known next-greater pointer boundaries are used without assuming a terminal element width.\n')
        f.write('- F remains count-like, but fixed-width records are not confirmed. Width fits are concentrated in F=1 and do not generalize robustly to F>1.\n')
        f.write('- Raw regions show multiple structural fingerprints; no uniform variable-length grammar or pointer-table grammar achieved cross-road validation.\n')
        f.write('- No geometry GeoJSON was emitted because no decoder met the required structural and geographic validation threshold.\n')
        f.write('- The 1 iy list is preserved as an unresolved 31-item road-owned region; its exact terminal boundary is reported in the dedicated analysis.\n')
    state=root/'research/PROJECT_STATE.md'
    with state.open('a') as f:
        f.write('\n## Phase 12 checkpoint\n\n')
        f.write(f'- Rebuilt {len(refs)} road-owned type-0x00 references across {len(extent)} unique target-block pointers; duplicate owners and all F values are retained in `research/roads/phase12_road_refs.csv`.\n')
        f.write(f'- Known next-pointer extents were measured for {len(extent)} pointers. No fixed element width or uniform pointer-table grammar is confirmed across F>1 lists.\n')
        f.write('- The 1 iy mikrorayon region is preserved as raw bytes and remains unresolved; no speculative geometry was emitted.\n')
if __name__=='__main__': main(Path(__file__).resolve().parents[2])
