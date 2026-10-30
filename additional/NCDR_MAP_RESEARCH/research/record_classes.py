#!/usr/bin/env python3
"""Read-only classification of framed DB_0 records.

The labels emitted here are observations and scores, not a file-format claim.
"""
from __future__ import annotations
import argparse, csv, mmap, zlib, re
from collections import Counter, defaultdict
from pathlib import Path

SECTOR = 512
ZH = (b'\x78\x01', b'\x78\x5e', b'\x78\x9c', b'\x78\xda')

def records(data):
    n=len(data)//SECTOR; starts={s:data[s*SECTOR+3] for s in range(n) if int.from_bytes(data[s*SECTOR:s*SECTOR+3],'big')==s}
    return [(s,span) for s,span in starts.items() if span and s+span in starts]

PRINTABLE = bytes(1 if 32 <= x <= 126 else 0 for x in range(256))
def printable_ratio(blob): return round(blob.translate(PRINTABLE).count(1)/len(blob),6) if blob else 0.0
def zero_ratio(blob): return round(blob.count(0)/len(blob),6) if blob else 0.0
def strings(blob):
    matches=list(re.finditer(rb'[\x20-\x7e\xa0-\xff]{3,}',blob))
    return len(matches),sum(len(m.group()) for m in matches)

def zstreams(data,start,end):
    """Return all independently successful streams beginning within a record."""
    out=[]; probe=data[start+4:min(start+68,end)]
    for rel in range(max(0,len(probe)-1)):
        if probe[rel:rel+2] not in ZH: continue
        p=start+4+rel
        try:
            d=zlib.decompressobj(); raw=d.decompress(data[p:end])+d.flush()
            if d.eof: out.append((p-start,len(data[p:end])-len(d.unused_data),raw))
        except zlib.error: pass
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('db0',type=Path); ap.add_argument('--output-dir',type=Path,default=Path(__file__).parent); a=ap.parse_args(); a.output_dir.mkdir(parents=True,exist_ok=True)
    classes=[]; subheaders=[]; semantic=[]
    with a.db0.open('rb') as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as d:
      for sec,span in records(d):
        off=sec*SECTOR; end=off+span*SECTOR; body=d[off+4:end]; zs=zstreams(d,off,end)
        dec=zs[0][2] if zs else b''
        rawpr=printable_ratio(body); decpr=printable_ratio(dec)
        rawzero=zero_ratio(body); deczero=zero_ratio(dec)
        rr,rt=strings(body); dr,dt=strings(dec)
        row={'sector':sec,'file_offset':off,'span':span,'record_size_bytes':span*SECTOR,'bytes_4_5':d[off+4:off+6].hex(),'bytes_4_7':d[off+4:off+8].hex(),'bytes_4_15':d[off+4:off+16].hex(),'zlib_present':bool(zs),'zlib_offset':zs[0][0] if zs else '', 'zlib_success':bool(zs),'compressed_size':zs[0][1] if zs else '', 'decompressed_size':len(dec) if zs else '', 'printable_ratio_raw':rawpr,'printable_ratio_decompressed':decpr,'zero_ratio_raw':rawzero,'zero_ratio_decompressed':deczero,'raw_string_runs':rr,'decompressed_string_runs':dr}
        classes.append(row)
        if zs:
          pre=d[off+4:off+zs[0][0]]
          subheaders.append({'sector':sec,'class_signature':row['bytes_4_7'],'span':span,'zlib_offset':zs[0][0],'pre_zlib_hex':pre.hex(),'pre_zlib_length':len(pre),'compressed_size':zs[0][1],'decompressed_size':len(dec),'stream_count':len(zs),'bytes_before_zlib':pre.hex()})
        # Scores use only directly measurable counts, and are intentionally heuristic.
        text=min(1,(rr+dr)/8 + (rawpr+decpr)/2)
        # Sample at most 4,096 aligned u32s; this is a classification score,
        # never evidence for a pointer representation.
        words=min(len(dec)//4,4096)
        p4=sum(1 for i in range(words) if int.from_bytes(dec[i*4:i*4+4],'big') < len(d)//1024)
        density=p4/max(1,words)
        geometry=min(1,(1-decpr)*.45+(1-deczero)*.25+(1 if len(dec)>3000 else 0)*.2)
        routing=min(1,density*5+(1-decpr)*.25)
        poi=min(1,text*.6+geometry*.35)
        index=min(1,density*4 + (0.25 if dr else 0))
        scores={'TEXT':text,'INDEX':index,'POI':poi,'GEOMETRY':geometry,'ROUTING':routing}
        label=max(scores,key=scores.get); confidence=round(scores[label],3)
        semantic.append({'sector':sec,'class_signature':row['bytes_4_7'],'candidate':label if confidence>=.35 else 'UNKNOWN','confidence':confidence,'reasons':f'raw_strings={rr}; decompressed_strings={dr}; printable={decpr}; plausible_u32_page_density={density:.4f}'})
    fields=list(classes[0]);
    with (a.output_dir/'record_classes.csv').open('w',newline='',encoding='utf8') as o: w=csv.DictWriter(o,fieldnames=fields);w.writeheader();w.writerows(classes)
    with (a.output_dir/'record_subheaders.csv').open('w',newline='',encoding='utf8') as o: w=csv.DictWriter(o,fieldnames=list(subheaders[0]));w.writeheader();w.writerows(subheaders)
    with (a.output_dir/'semantic_candidates.csv').open('w',newline='',encoding='utf8') as o: w=csv.DictWriter(o,fieldnames=list(semantic[0]));w.writeheader();w.writerows(semantic)
    groups=defaultdict(list)
    for r in classes: groups[(r['bytes_4_7'],r['zlib_present'])].append(r)
    with (a.output_dir/'record_class_statistics.txt').open('w',encoding='utf8') as o:
      o.write('Class signature means bytes 4..7 only; its semantic meaning is not established.\n\n')
      for (sig,z),rs in sorted(groups.items(),key=lambda x:len(x[1]),reverse=True)[:100]:
        spans=Counter(r['span'] for r in rs); ex=', '.join(f"0x{r['sector']:06x}" for r in rs[:10]); total=sum(r['record_size_bytes'] for r in rs)
        comp=sum(int(r['compressed_size'] or 0) for r in rs); dec=sum(int(r['decompressed_size'] or 0) for r in rs)
        o.write(f'class_signature={sig} zlib={z} count={len(rs)} bytes={total} span_distribution={dict(spans)}\n')
        o.write(f'  compression_ratio={(comp/dec if dec else 0):.6f}; examples={ex}\n')
        s=rs[0]; o.write(f"  representative_header={s['bytes_4_15']}; representative_sector=0x{s['sector']:06x}\n")
      o.write('\nZlib subheader patterns (signature, offset, bytes before zlib):\n')
      pats=Counter((r['class_signature'],r['zlib_offset'],r['pre_zlib_hex']) for r in subheaders)
      for key,count in pats.most_common(100): o.write(f'  {key}: {count}\n')

if __name__=='__main__': main()
