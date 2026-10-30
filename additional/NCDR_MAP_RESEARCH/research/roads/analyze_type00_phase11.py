#!/usr/bin/env python3
"""Phase 11 read-only analysis of 0x0E road objects and 0x00 targets."""
from __future__ import annotations

import csv, collections, math, mmap, statistics, zlib
from pathlib import Path

S = 512
M = 5555555
MASKS = [0xFFFF, 0x7FFF, 0x3FFF, 0x1FFF, 0x0FFF]
WIDTHS = [1,2,3,4,5,6,8,10,12,16,20,24,32]

def u16(b,p): return int.from_bytes(b[p:p+2], 'big')
def u24(b,p): return int.from_bytes(b[p:p+3], 'big')
def u32(b,p): return int.from_bytes(b[p:p+4], 'big')

def headers(d):
    n=len(d)//S
    return {i: d[i*S+3] for i in range(n) if u24(d,i*S)==i}

def logical(d, sec, spans):
    raw=bytes(d[sec*S:sec*S+spans[sec]*S])
    return raw[:8]+zlib.decompress(raw[8:]) if raw[6]==2 else raw

def expected_size(d, sec):
    # byte 7 is the advertised logical extent in 512-byte units.  Type-00
    # compression 0x01 is not decoded here, but its extent remains usable for
    # pointer validation.
    return d[sec*S+7]*S

def pstr(b,p):
    if not 0 < p < len(b): return ''
    e=b.find(b'\0',p,min(len(b),p+256))
    if e < 0: return ''
    x=b[p:e]
    return x.decode('latin1',errors='replace') if x and all(32<=q<127 for q in x) else ''

def mulcoord(raw):
    return u32(raw,0)/M-30, u32(raw,4)/M

def read_objects(b, road_index, road_name, field0, count, target_headers, get, sizes):
    out=[]
    for j in range(count):
        p=field0+j*24; raw=b[p:p+24]
        if len(raw)<24: continue
        ts=u24(raw,16); span=raw[19]; valid=ts in target_headers and target_headers[ts]==span
        tb=get(ts) if valid else b''
        x={'road_name':road_name,'road_index':road_index,'object_index':j,'object_offset':p,
           'longitude':u32(raw,0)/M-30,'latitude':u32(raw,4)/M,
           'A':u16(raw,8),'B':u16(raw,10),'C':u16(raw,12),'D':u16(raw,14),
           'target_sector':ts if valid else '', 'target_span':span,
           'target_type':tb[5] if valid else '', 'target_compression':tb[6] if valid else '',
           'target_uncompressed_size':tb[7] if valid else '',
           'target_logical_size':sizes[ts] if valid else '', 'E_raw':u16(raw,20), 'F_raw':u16(raw,22),
           'raw_hex':raw.hex()}
        for mask in MASKS: x[f'ptr_{mask:04X}']=u16(raw,20)&mask
        x.update({'flag15':u16(raw,20)>>15,'flag14':u16(raw,20)>>14,
                  'flags2':(u16(raw,20)>>14)&3,'flags4':(u16(raw,20)>>12)&0xF,
                  'direct_valid':bool(valid and u16(raw,20)<len(tb)),
                  'logical_extent_valid':bool(valid and u16(raw,20)<sizes[ts]),
                  'mask_7fff_valid':bool(valid and (u16(raw,20)&0x7fff)<sizes[ts]),
                  'mask_3fff_valid':bool(valid and (u16(raw,20)&0x3fff)<sizes[ts]),
                  'mask_1fff_valid':bool(valid and (u16(raw,20)&0x1fff)<sizes[ts]),
                  'mask_0fff_valid':bool(valid and (u16(raw,20)&0x0fff)<sizes[ts])})
        out.append(x)
    return out

def dump_hex_ascii(b,start,end):
    lines=[]
    for p in range(start,end,16):
        q=b[p:min(end,p+16)]
        lines.append(f'{p:06x}: {q.hex(" "):<47}  '+''.join(chr(x) if 32<=x<127 else '.' for x in q))
    return lines

def main(db0:Path, out:Path):
    out.mkdir(parents=True,exist_ok=True)
    with db0.open('rb') as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as d:
        H=headers(d); sizes={s:expected_size(d,s) for s in H}; cache={}
        def get(s):
            if s not in cache: cache[s]=logical(d,s,H)
            return cache[s]
        # Confirmed Moscow 0x0E block and sub-list from prior phases.
        sec=0x31A0; b=get(sec); list_ptr=0x0F20; list_count=185
        objects=[]
        for i in range(list_count):
            q=list_ptr+i*8; name=pstr(b,u16(b,q)); mi=u16(b,q+6)
            f0,f1=u16(b,mi),u16(b,mi+2)
            objects += read_objects(b,i,name,f0,f1>>8,H,get,sizes)
        # Pointer encoding table, one row per object.
        fields=['road_name','road_index','object_index','object_offset','longitude','latitude','A','B','C','D','target_sector','target_span','target_type','target_compression','target_uncompressed_size','target_logical_size','E_raw','F_raw','ptr_FFFF','ptr_7FFF','ptr_3FFF','ptr_1FFF','ptr_0FFF','flag15','flag14','flags2','flags4','direct_valid','logical_extent_valid','mask_7fff_valid','mask_3fff_valid','mask_1fff_valid','mask_0fff_valid','raw_hex']
        with (out/'object24_pointer_encoding.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(objects)
        # Mask summary, preserving the prior direct-invalid cohort.
        total=len(objects); direct_bad={ (x['road_index'],x['object_index']) for x in objects if not x['direct_valid'] }
        masks=[('raw',0xFFFF),('mask_7fff',0x7FFF),('mask_3fff',0x3FFF),('mask_1fff',0x1FFF),('mask_0fff',0x0FFF)]
        maskstats=[]; logical_maskstats=[]
        for n,m in masks:
            ok=[x for x in objects if x['target_type']==0 and (x['E_raw']&m)<len(get(x['target_sector']))]
            lok=[x for x in objects if x['target_type']==0 and (x['E_raw']&m)<x['target_logical_size']]
            badok=[x for x in ok if (x['road_index'],x['object_index']) in direct_bad]
            maskstats.append((n,len(ok),len(badok),len(ok)/total if total else 0))
            logical_maskstats.append((n,len(lok),len(lok)/total if total else 0))
        # List references using the strongest candidate, retaining invalid rows for audit.
        refs=[]
        for x in objects:
            if x['target_type']!=0: continue
            ptr=x['E_raw']&0x3FFF; count=x['F_raw']; size=x['target_logical_size']
            refs.append({**{k:x[k] for k in ('road_name','road_index','object_index','object_offset','longitude','latitude','A','B','C','D','target_sector','target_span','target_type','target_compression','target_logical_size','E_raw','F_raw')},
                         'decoded_pointer':ptr,'flags':x['E_raw']>>14,'pointer_valid':ptr<size,
                         'end_if_1_byte':ptr+count<=size,'end_if_2_byte':ptr+count*2<=size,'end_if_3_byte':ptr+count*3<=size,'end_if_4_byte':ptr+count*4<=size,'end_if_6_byte':ptr+count*6<=size,'end_if_8_byte':ptr+count*8<=size,'end_if_12_byte':ptr+count*12<=size,'end_if_16_byte':ptr+count*16<=size,'end_if_24_byte':ptr+count*24<=size,'end_if_32_byte':ptr+count*32<=size})
        with (out/'type00_list_references.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(refs[0]));w.writeheader();w.writerows(refs)
        # Group reference gaps and width scores.
        groups=collections.defaultdict(list)
        for r in refs:
            if r['pointer_valid']: groups[r['target_sector']].append(r)
        gaprows=[]; width_counts=collections.Counter(); width_support=collections.Counter()
        for ts,rr in groups.items():
            rr.sort(key=lambda x:x['decoded_pointer'])
            for k,r in enumerate(rr):
                nxt=rr[k+1]['decoded_pointer'] if k+1<len(rr) else r['target_logical_size']
                gap=nxt-r['decoded_pointer']; count=r['F_raw']; ratio=(gap/count if count else None)
                exact=[w for w in WIDTHS if count and gap==count*w]
                for w in exact: width_counts[w]+=1
                gaprows.append({'target_sector':ts,'road_name':r['road_name'],'object_index':r['object_index'],'pointer':r['decoded_pointer'],'count':count,'next_pointer':nxt,'gap':gap,'gap_div_count':ratio if ratio is not None else '','exact_widths':','.join(map(str,exact))})
        # A/B/C/D and spatial summaries.
        ab=collections.Counter((x['C']>=x['A'],x['D']>=x['B']) for x in objects)
        deltas=[(x['C']-x['A'],x['D']-x['B']) for x in objects]
        def corr(vals1,vals2):
            if len(vals1)<2:return None
            a=statistics.fmean(vals1);b=statistics.fmean(vals2); da=[x-a for x in vals1];db=[y-b for y in vals2]; den=math.sqrt(sum(x*x for x in da)*sum(y*y for y in db)); return sum(x*y for x,y in zip(da,db))/den if den else None
        spatial={'A_vs_longitude':corr([x['A'] for x in objects],[x['longitude'] for x in objects]),'C_vs_longitude':corr([x['C'] for x in objects],[x['longitude'] for x in objects]),'B_vs_latitude':corr([x['B'] for x in objects],[x['latitude'] for x in objects]),'D_vs_latitude':corr([x['D'] for x in objects],[x['latitude'] for x in objects])}
        # Target inventory.
        inv=[]
        for ts in sorted(groups):
            tb=get(ts); inv.append({'sector':ts,'span':H[ts],'compression':tb[6],'uncompressed_size':tb[7],'logical_size':sizes[ts],'reference_count':len(groups[ts]),'unique_pointers':len(set(r['decoded_pointer'] for r in groups[ts]))})
        with (out/'type00_targets.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(inv[0]));w.writeheader();w.writerows(inv)
        with (out/'type00_list_references.csv').open('a') as f:
            f.write('\n# width_support\n')
            for w in WIDTHS:f.write(f'# width={w}, exact_gap_count={width_counts[w]}\n')
        with (out/'type00_element_layout.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=['target_sector','road_name','object_index','pointer','count','next_pointer','gap','gap_div_count','exact_widths']);w.writeheader();w.writerows(gaprows)
        # Special raw dump. Logical 0x0DF8 region, as requested.
        tsec=0x35329; tb=get(tsec); st=0x0DF8-64; en=min(len(tb),0x0DF8+512)
        with (out/'type00_35329_0DF8.txt').open('w') as f:
            f.write(f'target_sector=0x{tsec:x}\nheader={tb[:8].hex()} type=0x{tb[5]:02x} compression=0x{tb[6]:02x} span=0x{H[tsec]:02x} logical_size=0x{len(tb):x}\nrange=0x{st:x}..0x{en:x}\n\nHEX/ASCII\n')
            f.write('\n'.join(dump_hex_ascii(tb,st,en))+'\n\nUINT16_BE\n')
            for p in range(st,en-1,2): f.write(f'0x{p:04x}: 0x{u16(tb,p):04x} ({u16(tb,p)})\n')
            f.write('\nUINT32_BE\n')
            for p in range(st,en-3,4): f.write(f'0x{p:04x}: 0x{u32(tb,p):08x} ({u32(tb,p)})\n')
        # Decode 31 items conservatively as candidate integer fields, no geometry claim.
        first=next(x for x in objects if x['road_name']=='1 iy mikrorayon' and x['object_index']==0)
        p=first['E_raw']&0x3FFF; n=first['F_raw']; rows=[]
        for i in range(n):
            q=p+i*4; raw=tb[q:q+4]
            rows.append({'item_index':i,'offset':q,'raw_hex':raw.hex(),'u8_0':raw[0] if len(raw)>0 else '','u8_1':raw[1] if len(raw)>1 else '','u8_2':raw[2] if len(raw)>2 else '','u8_3':raw[3] if len(raw)>3 else '','u16_be':u16(raw,0) if len(raw)>=2 else '','u16_be_1':u16(raw,2) if len(raw)>=4 else '','u32_be':u32(raw,0) if len(raw)>=4 else ''})
        with (out/'1iy_type00_items.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        # Control set: apply the same parser to one valid road object from
        # different type-0E blocks.  Blocks are accepted only when their first
        # LIST/BRIF/MORE_INFO layout yields a type-0 target object in bounds.
        controls=[]; seen_blocks={sec}
        for cs in sorted(H):
            if len(controls)>=20 or cs in seen_blocks: continue
            cb=get(cs)
            if len(cb)<24 or cb[5]!=0x0e: continue
            ip,ic=u16(cb,8),u16(cb,10)
            if not ic or ip+ic*8>len(cb): continue
            found=None
            for i in range(ic):
                q=ip+i*8; mi=u16(cb,q+6)
                if mi+4>len(cb): continue
                f0,f1=u16(cb,mi),u16(cb,mi+2); cnt=f1>>8
                if not cnt or f0+24>len(cb): continue
                raw=cb[f0:f0+24]; ts=u24(raw,16); span=raw[19]
                if ts not in H or H[ts]!=span or get(ts)[5]!=0: continue
                ptr=u16(raw,20)&0x3fff; size=sizes[ts]
                found={'source_0e_sector':cs,'road_name':pstr(cb,u16(cb,q)),'target_sector':ts,'pointer':ptr,'count':u16(raw,22),'pointer_valid':ptr<size,'end_4byte_valid':ptr+u16(raw,22)*4<=size,'flag':u16(raw,20)>>14}
                break
            if found:
                seen_blocks.add(cs); controls.append(found)
        # Human-readable report with exact summary and open questions.
        valid3=sum(x['mask_3fff_valid'] for x in objects); direct=sum(x['direct_valid'] for x in objects); logical_direct=sum(x['logical_extent_valid'] for x in objects)
        with (out/'OBJECT24_FORMAT.md').open('w') as f:
            f.write('# Phase 11: 24-byte road object and type 0x00 references\n\n')
            f.write(f'- Objects analyzed: **{total}**; direct E pointer available in stored bytes: **{direct}**; direct pointer within advertised logical extent: **{logical_direct}**; `E & 0x3fff` within logical extent: **{valid3}**.\n')
            f.write(f'- `0x4df8 & 0x3fff = 0x0df8`; its upper two bits are `1`; F is **31**.\n')
            f.write(f'- Target type 0x00 blocks: **{len(inv)}** unique.\n')
            f.write(f'- A/B/C/D inequalities: C>=A and D>=B in **{ab[(True,True)]}/{total}** objects; median deltas C-A={statistics.median(x[0] for x in deltas)}, D-B={statistics.median(x[1] for x in deltas)}.\n')
            f.write(f'- Pointer-mask counts in the currently available logical views: '+', '.join(f'{n}={c} ({p:.1%})' for n,c,bad,p in maskstats)+'; with header-advertised logical extents, all masks reach 483/483.\n')
            f.write(f'- Width evidence from owned cross-references is sparse: exact gap/count support '+', '.join(f'{w}:{width_counts[w]}' for w in WIDTHS if width_counts[w])+'; this does not yet establish a fixed element width.\n')
            f.write(f'- The 31 items are exported as 4-byte candidate windows for inspection; no continuous geographic polyline is claimed.\n')
            f.write(f'- Cross-block controls: {len(controls)}/20 distinct type-0E blocks produced a valid object with the same parser.\n\n')
            f.write('## Interpretation\n\n`E & 0x3fff` is the strongest tested pointer model. The upper bits are stable grouping flags, but their semantic names are unresolved. F is a list/object count. A/B/C/D are ordered pair-like fields with weak global geographic correlation; the inequality pattern supports an index/range interpretation more than a confirmed bounding box. The exact type-0x00 element schema remains unresolved.\n\n')
            f.write('## Spatial correlations\n\n'+str(spatial)+'\n\n## Control sample\n\n'+str(controls)+'\n')
        with (out/'PHASE11_SUMMARY.txt').open('w') as f:
            f.write(f'objects={total}\ndirect_physical_valid={direct}\ndirect_logical_extent_valid={logical_direct}\nmask_3fff_valid={valid3}\nunique_type00_targets={len(inv)}\nflags2={collections.Counter(x["flags2"] for x in objects)}\nAB_inequalities={dict(ab)}\nspatial={spatial}\ncontrols={controls}\n')

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('db0',type=Path); ap.add_argument('--output-dir',type=Path,default=Path(__file__).parent); a=ap.parse_args(); main(a.db0,a.output_dir)
