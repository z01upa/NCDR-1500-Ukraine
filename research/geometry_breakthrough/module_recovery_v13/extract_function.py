#!/usr/bin/env python3
"""Export a previously scanned function, without rescanning any code."""
import argparse,gzip,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('address',type=lambda x:int(x,0));p.add_argument('--module',default='NavigationRem.dll');a=p.parse_args();root=Path(__file__).resolve().parent
with gzip.open(root/'modules'/a.module/'reachable.jsonl.gz','rt') as f:
 for line in f:
  row=json.loads(line)
  if row['va']!=a.address:continue
  literals={x['instruction_va']:x for x in row['literals']};out=[]
  for i in row['instructions']:
   line='%08x  %-8s %-28s'%(i['va'],i['mnem'],i['body'])
   if i['va'] in literals:
    l=literals[i['va']];line+=' ; literal[%08x]=%08x normalized=%08x'%(l['literal_va'],l['value'],l['normalized'])
   out.append(line)
  path=root/'routing'/('%08x.asm'%a.address);path.write_text('\n'.join(out)+'\n');print(path);break
 else:raise SystemExit('No complete PDATA record at that address')
