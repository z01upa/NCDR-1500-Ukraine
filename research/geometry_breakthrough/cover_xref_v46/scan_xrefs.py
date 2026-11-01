"""Full recovered executable-range reference inventory. No firmware writes."""
import json,gzip,struct,hashlib,argparse
from pathlib import Path

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--recovery',type=Path,default=Path(__file__).resolve().parent.parent/'module_recovery_v13');ap.add_argument('--out',type=Path,default=Path(__file__).resolve().parent);a=ap.parse_args()
 p=a.recovery/'modules/NavigationRem.dll';j=json.loads((p/'module.json').read_text());out=a.out;out.mkdir(exist_ok=True,parents=True)
 with gzip.open(p/'reachable.jsonl.gz','rt') as f: fs=[json.loads(x) for x in f]
 targets={0x2ffb92c,0x2ffbb00};allins={i['va']:i for f in fs for i in f['instructions']};rows=[];raw=[];pointers=[]
 for f in fs:
  ls=[x for x in f['literals'] if x['normalized'] in targets];cs=[c for c in f['calls'] if c['target'] in targets]
  if not ls and not cs:continue
  ins=sorted(f['instructions'],key=lambda i:i['va']);(out/('%08x.asm'%f['va'])).write_text('\n'.join('%08x %-8s %s'%(i['va'],i['mnem'],i['body']) for i in ins)+'\n')
  for l in ls:
   reg='r%d'%l['register'];site=None
   for i in ins:
    if i['va']<=l['instruction_va']:continue
    if i['va']>l['instruction_va']+32:break
    if i['mnem'] in ['jsr','jmp'] and i['body']=='@'+reg:site=i;break
    if i['body'].split(',')[-1]==reg:break
   rows.append(dict(function=hex(f['va']),load=hex(l['instruction_va']),literal=hex(l['literal_va']),target=hex(l['normalized']),call=hex(site['va']) if site else None,kind=site['mnem']+' literal-register' if site else 'UNRESOLVED literal use'))
  for c in cs:rows.append(dict(function=hex(f['va']),target=hex(c['target']),call=hex(c['va']),kind='direct'))
 for s in j['sections']:
  b=(p/('section_%d.bin'%s['index'])).read_bytes();assert hashlib.sha256(b).hexdigest()==s['sha256']
  for target in targets:
   for value in [target,target-0x2000000]:
    start=0
    while True:
     k=b.find(struct.pack('<I',value),start)
     if k<0:break
     pointers.append(dict(section=s['index'],address=hex(s['runtime_va']+k),value=hex(value)));start=k+1
  if not s['executable']:continue
  for k in range(0,len(b)-1,2):
   w=struct.unpack_from('<H',b,k)[0];va=s['runtime_va']+k
   if w>>12 in [10,11]:
    d=w&4095;d=d-4096 if d&2048 else d;t=va+4+2*d
    if t in targets:raw.append(dict(address=hex(va),target=hex(t),kind='bsr' if w>>12==11 else 'bra',reachable=va in allins))
   if w>>12==13:
    lit=(va&~3)+4+4*(w&255);o=lit-s['runtime_va']
    if 0<=o<=len(b)-4:
     value=struct.unpack_from('<I',b,o)[0]
     if value in targets or value+0x2000000 in targets:raw.append(dict(address=hex(va),literal=hex(lit),target=hex(value if value in targets else value+0x2000000),kind='mov.l literal',reachable=va in allins))
 report=dict(executable=[dict(start=hex(s['runtime_va']),end_exclusive=hex(s['runtime_va']+s['decoded_size']),sha256=s['sha256']) for s in j['sections'] if s['executable']],pdata_functions=len(fs),call_candidates=rows,full_range_raw_hits=raw,pointer_occurrences=pointers,limitations='Literal-register chains are local candidates; arbitrary computed indirect targets cannot be exhaustively resolved statically. Raw hits in unreachable words may be data.')
 (out/'xref_inventory.json').write_text(json.dumps(report,indent=2)+'\n')
 selected=[0x2fd676c,0x301f984,0x301fcd8,0x2ffb92c,0x2ffbb00,
           0x306f484,0x3060fa0,0x308c1f0,0x301efe4,0x3060d48]
 for f in fs:
  if f['va'] in selected:
   (out/('%08x.asm'%f['va'])).write_text('\n'.join('%08x %-8s %s'%(i['va'],i['mnem'],i['body']) for i in sorted(f['instructions'],key=lambda i:i['va']))+'\n')
 print(json.dumps({'executable':report['executable'],'calls':len(rows),'unresolved':sum(x['call'] is None for x in rows),'raw_hits':len(raw),'raw_unreachable':[x for x in raw if not x['reachable']],'pointers':len(pointers)},indent=2))
if __name__=='__main__':main()
