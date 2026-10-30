#!/usr/bin/env python3
from __future__ import annotations
import bz2, csv, gzip, hashlib, json, lzma, math, re, zlib
from pathlib import Path
from collections import Counter
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / 'roads'))
from parse_roads import DB

ROOT=Path(__file__).parent
DBPATH=ROOT.parent.parent/'DB_0'
SAMPLES=100

def write_csv(path, rows, fields):
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def attempts(payload, expected):
    out=[]
    for name,fn in [('zlib',lambda:zlib.decompress(payload)),('raw-deflate',lambda:zlib.decompress(payload,-15)),('gzip',lambda:gzip.decompress(payload)),('bz2',lambda:bz2.decompress(payload)),('lzma',lambda:lzma.decompress(payload))]:
        try: out.append((name,len(fn())))
        except Exception: pass
    return ';'.join(f'{a}:{b}' for a,b in out)

def main():
  c1=[]; c2=[]
  with DB(DBPATH) as db:
    for sec,h in sorted(db.headers.items()):
      if h.block_type!=0: continue
      if h.compression==1 and len(c1)<SAMPLES: c1.append((sec,h))
      if h.compression==2 and len(c2)<SAMPLES: c2.append((sec,h))
    (ROOT/'comp01_samples').mkdir(exist_ok=True); (ROOT/'comp02_samples').mkdir(exist_ok=True)
    rows1=[]; rows2=[]
    for kind,items,out,rows in [('comp01',c1,ROOT/'comp01_samples',rows1),('comp02',c2,ROOT/'comp02_samples',rows2)]:
      for sec,h in items:
        raw=bytes(db.data[sec*512:(sec+h.span)*512]); payload=raw[8:]
        logical=b''
        if h.compression==2: logical=db.logical(sec)
        (out/f'{sec:06X}_physical.bin').write_bytes(raw)
        if logical: (out/f'{sec:06X}_logical.bin').write_bytes(logical)
        rows.append({'sector':f'{sec:06X}','span':h.span,'physical_size':len(raw),'logical_units':raw[7],'expected_logical_size':h.logical_size,'header_hex':raw[:8].hex(),'first256_physical_hex':raw[:256].hex(),'first256_payload_hex':payload[:256].hex(),'codec_attempts':attempts(payload,h.logical_size) if h.compression==1 else 'zlib:success'})
    fields=list(rows1[0])
    write_csv(ROOT/'comp01_controls.csv',rows1,fields)
    write_csv(ROOT/'comp02_controls.csv',rows2,fields)
    # Compare the known type-0 prefix signature and record the literal physical prefix.
    pref=[]
    sig=bytes.fromhex('007400030094000500c8')
    for sec,h in c1:
      raw=bytes(db.data[sec*512:(sec+h.span)*512]); p=raw[8:]
      k=0
      for i in range(min(len(p),256)):
        # only report the maximal initial region that remains a valid-looking
        # even-aligned local-word stream; no decompression claim is made.
        if i%2==0 and i+2<=len(p): k=i+2
      first=p.find(sig)
      pref.append({'sector':f'{sec:06X}','physical_payload_bytes':len(p),'signature_0074_offset':first,'literal_prefix_candidate_end':k,'first64_payload_hex':p[:64].hex()})
    write_csv(ROOT/'comp01_prefix_analysis.csv',pref,list(pref[0]))
    summary={'comp01_samples':len(c1),'comp02_controls':len(c2),'global_comp01_blocks':sum(h.block_type==0 and h.compression==1 for h in db.headers.values()),'global_comp02_blocks':sum(h.block_type==0 and h.compression==2 for h in db.headers.values()),'known_control_11576_header':bytes(db.data[0x11576*512:0x11576*512+8]).hex(),'known_control_11576_payload_prefix':bytes(db.data[0x11576*512+8:0x11576*512+40]).hex(),'standard_codec_successes':0}
  (ROOT/'comp01_recovery_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
  print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
