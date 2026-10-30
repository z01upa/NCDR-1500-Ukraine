#!/usr/bin/env python3
from __future__ import annotations
import csv, math, collections, json
from pathlib import Path
from parse_roads import DB

ROOT=Path(__file__).parent
DBPATH=ROOT.parent.parent/'DB_0'
CORPUS=ROOT/'authoritative_road_objects.csv'

def be16(b,o): return int.from_bytes(b[o:o+2],'big')
def be32(b,o): return int.from_bytes(b[o:o+4],'big')
def entropy(b):
    if not b:return 0.0
    c=collections.Counter(b); n=len(b)
    return -sum((v/n)*math.log2(v/n) for v in c.values())
def pctzero(b): return 100.0*b.count(0)/len(b) if b else 100.0
def cardinality(b,w):
    return len({b[i:i+w] for i in range(0,len(b)-w+1,w)}) if len(b)>=w else 0

def write(path, rows, fields=None):
    fields=fields or (list(rows[0]) if rows else ['empty'])
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def main():
    rows=list(csv.DictReader(CORPUS.open()))
    by=collections.defaultdict(list)
    for r in rows: by[int(r['target_sector'])].append(r)
    inv=[]; regions=[]; tables=[]; geom=[]
    with DB(DBPATH) as db:
      for sec, refs in sorted(by.items()):
        h=db.headers[sec]; raw=bytes(db.data[sec*512:(sec+h.span)*512])
        readable=h.compression in (0,2)
        logical=db.logical(sec) if readable else b''
        ptrs=sorted({int(r['ptr']) for r in refs if r['raw32'] and readable and int(r['ptr'])+32<=len(logical)})
        slots=[]
        if ptrs:
          residue=collections.Counter(p%32 for p in ptrs).most_common(1)[0][0]
          for p in ptrs:
            if p%32==residue: slots.append(p)
          start=min(slots); end=max(slots)+32
        else: residue=''; start=end=0
        occ=set()
        for p in slots: occ.update(range(p,p+32))
        lattice=set(range(start,end)) if slots else set()
        unknown=sorted(set(range(len(logical)))-lattice)
        # contiguous unknown regions
        if unknown:
          a=prev=unknown[0]
          for x in unknown[1:]+[None]:
            if x is None or x!=prev+1:
              b=prev+1; data=logical[a:b]
              regions.append({'sector':f'{sec:06X}','offset':f'{a:04X}','length':b-a,'zero_pct':round(pctzero(data),3),'entropy':round(entropy(data),5),'be16_cardinality':cardinality(data,2),'be32_cardinality':cardinality(data,4),'position':'before' if b<=start else ('after' if a>=end else 'split')})
              if x is not None:a=x
            prev=x if x is not None else prev
        inv.append({'sector':f'{sec:06X}','span':h.span,'compression':h.compression,'logical_size':len(logical),'object_occurrences':len(refs),'owned_readable':sum(bool(r['raw32']) for r in refs),'distinct_ptrs':len({int(r['ptr']) for r in refs if r['raw32']}),'first_slot':f'{start:04X}' if slots else '','last_slot':f'{end-32:04X}' if slots else '','descriptor_start':f'{start:04X}' if slots else '','descriptor_end':f'{end:04X}' if slots else '','descriptor_count':len(slots),'residue_mod32':residue,'referenced_descriptor_bytes':len(occ),'lattice_bytes':len(lattice),'outside_lattice_bytes':len(logical)-len(lattice)})
        if slots:
          for stride in (2,4,6,8,10,12,16):
            count=len(slots); tables.append({'sector':f'{sec:06X}','region':'lattice','stride':stride,'count':count,'length':count*stride,'supported':'NO'})
          # plausible index tests only against region counts; recorded as diagnostics
          descs=[r for r in refs if r['raw32']]
          for fld in ('W02','W14','W18','W1A','W1C','W1E'):
            for mode in ('value','low','high'):
              hits=0
              for r in descs:
                raw32=bytes.fromhex(r['raw32']); v=be16(raw32,int(fld[1:],16))
                idx=v if mode=='value' else (v&255 if mode=='low' else v>>8)
                hits += idx < len(slots)
              tables.append({'sector':f'{sec:06X}','region':'descriptor_index_test','stride':32,'count':len(slots),'length':len(slots)*32,'field':fld,'mode':mode,'hits':hits,'tested':len(descs),'supported':'NO'})
      # cross-block candidate region homologues: concise output is generated from regions
    write(ROOT/'type0_block_inventory.csv',inv)
    write(ROOT/'type0_byte_regions.csv',regions)
    write(ROOT/'type0_candidate_tables.csv',tables)
    write(ROOT/'type0_geometry_candidates.csv',geom or [{'result':'No geometry candidate accepted; readable blocks contain only confirmed descriptor lattice plus non-descriptor regions, requiring structural table support first.'}])
    summary={'blocks':len(inv),'by_compression':dict(collections.Counter(int(x['compression']) for x in inv)), 'objects_by_compression':dict(collections.Counter(int(r['target_compression']) for r in rows)), 'readable_blocks':sum(x['compression'] in (0,2) for x in inv), 'readable_bytes':sum(x['logical_size'] for x in inv), 'descriptor_bytes':sum(x['referenced_descriptor_bytes'] for x in inv), 'lattice_bytes':sum(x['lattice_bytes'] for x in inv), 'outside_lattice_bytes':sum(x['outside_lattice_bytes'] for x in inv)}
    (ROOT/'type0_structure_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
if __name__=='__main__': main()
