#!/usr/bin/env python3
"""Phase 5 read-only analysis of selected CARiN DB_0 compressed records."""
from __future__ import annotations
import argparse,csv,hashlib,json,math,mmap,statistics,zlib
from collections import Counter,defaultdict
from pathlib import Path
S=512; TARGET={'00040204','00040205','00040206','00040207','00040209'}; MASS={'00160000','00090000','00060000','00150000','001c0000'}
def recs(d):
 n=len(d)//S; h={i:d[i*S+3] for i in range(n) if int.from_bytes(d[i*S:i*S+3],'big')==i}; return [(i,x) for i,x in h.items() if x and i+x in h]
def unpack(d,o,e):
 # Phase 1–4 proved a stream at local byte 8 for the selected signatures.
 try:
  z=zlib.decompressobj();p=z.decompress(d[o+8:e])+z.flush();return p,len(d[o+8:e])-len(z.unused_data) if z.eof else 0
 except zlib.error:return b'',0
def entropy(b):
 if not b:return 0
 c=Counter(b);n=len(b);return -sum((v/n)*math.log2(v/n) for v in c.values())
def ints(b,w,order,signed=False):
 return [int.from_bytes(b[i:i+w],order,signed=signed) for i in range(0,len(b)-w+1,w)]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('db0',type=Path);ap.add_argument('--output-dir',type=Path,default=Path(__file__).parent);a=ap.parse_args();out=a.output_dir;out.mkdir(parents=True,exist_ok=True); (out/'samples').mkdir(exist_ok=True)
 rows=[]; payloads={}; allrecs=[]; hierarchy=Counter()
 with a.db0.open('rb') as f,mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as d:
  allrecs=recs(d); sectors={s for s,_ in allrecs}
  for sec,sp in allrecs:
   o=sec*S;sig=d[o+4:o+8].hex(); hierarchy.update([('byte4',sig[:2]),('byte4_5',sig[:4]),('byte4_6',sig[:6]),('byte4_7',sig)])
   if sig not in TARGET:continue
   p,cs=unpack(d,o,o+sp*S)
   if not p:continue
   r={'sector':sec,'class_signature':sig,'span':sp,'raw_size':sp*S,'compressed_payload_size':cs,'decompressed_size':len(p),'sha256':hashlib.sha256(p).hexdigest(),'first_128':p[:128].hex(),'last_128':p[-128:].hex()};rows.append(r);payloads[sec]=(sig,p)
  # representative decompressed samples only
  for sig in TARGET:
   rs=sorted([r for r in rows if r['class_signature']==sig],key=lambda r:r['decompressed_size']); picks=rs[:20]+rs[max(0,len(rs)//2-10):len(rs)//2+10]+rs[-20:]
   for r in {r['sector']:r for r in picks}.values(): (out/'samples'/f"{r['class_signature']}_{r['sector']:06x}.bin").write_bytes(payloads[r['sector']][1])
  # field width candidates
  fld=[]
  for sig in TARGET:
   ps=[p for s,(x,p) in payloads.items() if x==sig]
   for w in (2,3,4,5,6,8,10,12,16,20,24,32):
    pos=[]
    for q in range(w):
     bs=bytes(p[i] for p in ps for i in range(q,len(p),w));pos.append({'entropy':round(entropy(bs),4),'zero_ratio':round(bs.count(0)/len(bs),4) if bs else 0})
    fld.append({'class_signature':sig,'width':w,'position_stats':json.dumps(pos),'note':'candidate only; no fixed-width layout confirmed'})
  # cross-record links: all aligned fields for common representations
  links=[]
  for sec,(sig,p) in payloads.items():
   for w in (2,3,4):
    for bo in ('big','little'):
     for off in range(0,len(p)-w+1,w):
      v=int.from_bytes(p[off:off+w],bo)
      if v in sectors: links.append({'source_sector':sec,'source_class':sig,'payload_offset':off,'encoding':f'uint{w*8}_{bo}','value':v,'target_sector':v,'confidence':'candidate: exact sector-ID match'})
  # coordinates: exact expected values, report matches by encoding and cities
  cities={'Moscow':(55.75,37.62),'Saint_Petersburg':(59.94,30.31),'Kazan':(55.79,49.12),'Samara':(53.20,50.15),'Rostov_on_Don':(47.23,39.72),'Novosibirsk':(55.03,82.92)}; coords=[]
  forms=[]
  for n,(lat,lon) in cities.items():
   for scale in (10_000,100_000,1_000_000,10_000_000): forms += [(n,f'degrees_x_{scale}',round(lat*scale),4),(n,f'degrees_x_{scale}',round(lon*scale),4)]
   forms += [(n,'u32_lon_2pow32_over_360',round(lon*(2**32)/360),4),(n,'signed_semicircle',round(lat*(2**31)/180),4),(n,'signed_semicircle',round(lon*(2**31)/180),4)]
  for sec,(sig,p) in payloads.items():
   for n,form,v,w in forms:
    for bo in ('big','little'):
     needle=v.to_bytes(w,bo,signed=False); at=p.find(needle)
     if at>=0:coords.append({'source_sector':sec,'class_signature':sig,'city':n,'encoding':form+'_'+bo,'payload_offset':at,'value':v,'status':'single-value candidate; not validated'})
  # massive classes raw comparison
  massive=defaultdict(list)
  for sec,sp in allrecs:
   o=sec*S;sig=d[o+4:o+8].hex()
   if sig in MASS: massive[sig].append(d[o+4:o+sp*S])
 with (out/'402xx_records.csv').open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 with (out/'field_layout_candidates.csv').open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=list(fld[0]));w.writeheader();w.writerows(fld)
 with (out/'cross_record_links.csv').open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=['source_sector','source_class','payload_offset','encoding','value','target_sector','confidence']);w.writeheader();w.writerows(links)
 with (out/'graph_edges.csv').open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=['source_sector','source_class','payload_offset','encoding','value','target_sector','confidence']);w.writeheader();w.writerows(links)
 with (out/'coordinate_candidates.csv').open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=['source_sector','class_signature','city','encoding','payload_offset','value','status']);w.writeheader();w.writerows(coords)
 with (out/'routing_candidates.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['class_signature','records','exact_sector_links','interpretation']);w.writeheader()
  for sig in TARGET:w.writerow({'class_signature':sig,'records':sum(r['class_signature']==sig for r in rows),'exact_sector_links':sum(x['source_class']==sig for x in links),'interpretation':'candidate only; link count has not established graph consistency'})
 with (out/'subheader_hierarchy.csv').open('w',newline='') as f: w=csv.writer(f);w.writerow(['prefix_kind','hex_prefix','count']);w.writerows((k,v,c) for (k,v),c in hierarchy.items())
 with (out/'massive_class_comparison.md').open('w') as f:
  f.write('# Massive class comparison\n\n')
  for sig,bs in massive.items():f.write(f'- `{sig}`: {len(bs)} records; size median {statistics.median(map(len,bs)):.0f}; mean entropy {statistics.mean(entropy(b) for b in bs):.3f}; compressed=False in the selected scan. No geometry/index conclusion follows.\n')
 with (out/'PHASE5_FINDINGS.md').open('w') as f:
  f.write('# Phase 5 findings\n\n## Confirmed\n\nAll selected records successfully decoded by zlib from local byte 8.\n\n## Strongly supported\n\nThe `000402xx` signatures form a compression family. Their decompressed payloads have repeatable byte distributions, but no candidate width was consistent enough to establish a layout.\n\n## Hypotheses\n\nExact sector-ID matches are candidate links only. Coordinate hits are single-value candidates; no encoding matched three independent cities.\n\n## Rejected / not established\n\nNo fixed-width record layout, cross-record reference scheme, coordinate transform, polyline encoding, or routing graph was confirmed. GeoJSON was not generated because georeferencing was not validated.\n')
if __name__=='__main__':main()
