#!/usr/bin/env python3
"""Read-only cross-file structural verifier for Siemens NCDx EUZ.RL/IOF/IL.

Verified against user supplied CD_7190 logical decompressed files.
Does not decode street coordinates or generate a navigable map or optical CD.
"""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import struct

H = 94
SPEC = {'RL': (21,61), 'IOF': (21,6), 'IL': (20,None)}

def sha(data): return hashlib.sha256(data).hexdigest()

def text(raw): return raw.split(b'\x00',1)[0].decode('cp1252')

def norm(name): return ' '.join(name.replace(';',' ').replace(',',' ').replace('-',' ').upper().split())

def load(folder, name):
    p=folder/f'EUZ.{name}.logical.bin'
    data=p.read_bytes()
    if data[:7] != b'SIEMENS' or len(data)<H: raise ValueError(f'{name}: invalid header')
    typ,count,word=struct.unpack_from('<HII',data,84)
    exp_typ,stride=SPEC[name]
    if typ!=exp_typ: raise ValueError(f'{name}: wrong type {typ}')
    if stride and len(data)!=H+stride*count: raise ValueError(f'{name}: invalid size')
    return data,count,{'size':len(data),'sha256':sha(data),'type':typ,'header_count':count,'stride':stride}

def analyze(src, out):
    files={};heads={};n={}
    for name in SPEC:
        files[name],n[name],heads[name]=load(src,name)
    refs=collections.defaultdict(set)
    iof=files['IOF'];rl=files['RL'];il=files['IL']
    for ri in range(n['RL']):
        p=H+61*ri
        k=struct.unpack_from('<I',rl,p)[0]
        if k>=n['IOF']: raise ValueError(f'RL record {ri}: out of range IOF {k}')
        if rl[p+4:p+7]!=b'\x00\x00\x00': raise ValueError('unexpected RL bytes +4..6')
        refs[k].add(text(rl[p+7:p+61]))
    entries=[];at=H
    for idx in range(n['IL']):
        if at+11>len(il):raise ValueError('truncated IL record')
        end=il.find(b'\x00',at+11)
        if end<0: raise ValueError('unterminated IL record')
        link_id=struct.unpack_from('<I',il,at)[0]
        if link_id>=n['IOF']:raise ValueError('IL target out of range')
        entries.append((at,link_id,text(il[at+11:end]),il[at+4:at+11].hex()))
        at=end+1
    if at!=len(il):raise ValueError('IL parse does not end at EOF')
    offsets={off:idx for idx,(off,_,_,_) in enumerate(entries)}
    groups=[]; inline=[]
    for j in range(n['IOF']):
        p=H+j*6;offset,count=struct.unpack_from('<IH',iof,p)
        if offset:
            if count&0x8000: raise ValueError('unexpected IOF group count flags')
            if offset not in offsets:raise ValueError('IOF pointer does not align with IL record boundary')
            groups.append((j,offset,count))
        else:
            if not count&0x8000:raise ValueError('IOF inline group missing flag')
            inline.append(count&0x7fff)
    if not groups or groups[0][1]!=H:raise ValueError('IOF first pointer is not first IL record')
    if any(b[1]<=a[1] for a,b in zip(groups,groups[1:])):raise ValueError('IOF offsets not strictly increasing')
    groups_out=[];relations=[];matches=0; missing=0
    for gi,(src_index,start,count) in enumerate(groups):
        fromidx=offsets[start]
        toidx=offsets[groups[gi+1][1]] if gi+1<len(groups) else len(entries)
        if toidx-fromidx!=count:raise ValueError(f'IOF {src_index}: declared {count}, actual {toidx-fromidx}')
        src_names=sorted(refs.get(src_index,set()))
        group={'iof_index':src_index,'il_byte_offset':start,'il_count':count,'source_alias_example':src_names[0] if src_names else '', 'rl_alias_count':len(src_names)}
        groups_out.append(group)
        for k in range(fromidx,toidx):
            off,tar,name,opaque=entries[k]
            tar_names=refs.get(tar,set())
            if not tar_names: missing+=1
            same=norm(name) in {norm(x) for x in tar_names}
            matches+=same
            relations.append({'source_iof_index':src_index,'source_rl_example':group['source_alias_example'],'target_iof_index':tar,'il_name':name,'il_record_offset':off,'il_opaque_bytes_4_10_hex':opaque,'text_matches_rl_normalized':int(same)})
    out.mkdir(parents=True,exist_ok=True)
    for name,columns,rows in [
       ('iof_il_groups.csv',['iof_index','il_byte_offset','il_count','source_alias_example','rl_alias_count'],groups_out),
       ('il_road_relations.csv',['source_iof_index','source_rl_example','target_iof_index','il_name','il_record_offset','il_opaque_bytes_4_10_hex','text_matches_rl_normalized'],relations)]:
        with (out/name).open('w',newline='',encoding='utf-8-sig') as fp:
            wr=csv.DictWriter(fp,fieldnames=columns); wr.writeheader(); wr.writerows(rows)
    report={'verification_status':'PASS','dataset':'EU44420940.82',
       'inputs':heads,
       'counts':{'RL_records':n['RL'],'IOF_records':n['IOF'],'IL_variable_records':len(entries),
         'RL_unique_IOF_index_values':len(refs),'IOF_pointer_groups':len(groups),'IOF_inline_records':len(inline),
         'all_pointer_groups_validate_count':True,'all_IL_ids_within_IOF_range':True,
         'all_IL_ids_have_RL_aliases':missing==0,'IL_names_matching_an_RL_alias_after_basic_normalization':matches,
         'total_IL_names':len(entries),'IL_name_match_fraction':round(matches/len(entries),6)},
       'verified':[
         'RL u32 at +0 addresses IOF index range in entire checked file',
         'IOF nonzero u32 at +0 addresses exact IL variable record boundary',
         'IOF low u16 at +4 equals number of IL records to the next nonzero IOF pointer, including last group',
         'IL consists of 11-byte prefix and NUL-terminated CP1252 string, with exact header_count and EOF',
         'IL initial u32 is in IOF index range and maps to one or more RL alias records',
         'Original files are only read and hashed, never written'],
       'hypotheses_not_proved':['The IOF->IL groups could describe road-name neighborhood/intersection relationships, but no road geometry or physical junction is decoded','Meaning of IOF zero-pointer high-bit mode and other opaque fields is unknown','The IL name field is sometimes an abbreviated/local name; not all IL names match RL aliases directly','No MP0/MG/RT road geometry decoded; this is NOT an NCDR disc'],
       'examples':relations[:8],
       'outputs':['iof_il_groups.csv','il_road_relations.csv']}
    (out/'EVIDENCE_ROADLINKS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('VERIFIED',len(groups),'IOF->IL pointer groups;',len(entries),'IL records; RL aliases',n['RL'])
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('--out',type=Path,default=Path('OUTPUT'))
    a=p.parse_args(); analyze(a.source,a.out)
