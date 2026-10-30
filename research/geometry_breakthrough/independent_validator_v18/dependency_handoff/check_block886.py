"""Read only one indexed original block. No topology/NK/mask analysis."""
import argparse,hashlib,json,struct,zlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('mp0',type=Path);p.add_argument('--out',type=Path);a=p.parse_args()
if a.out and a.out.resolve()==a.mp0.resolve():p.error('Output must differ from input')
with a.mp0.open('rb') as f:
 header=f.read(114);assert header.startswith(b'(*$SIEMENS&^)')
 count=struct.unpack_from('<I',header,86)[0];assert count>886
 f.seek(114+24*886);entry=f.read(24);offset,size,packed=struct.unpack_from('<IHH',entry,16)
 f.seek(offset);encoded=f.read(packed)
z=zlib.decompressobj();raw=z.decompress(encoded,size+1)
assert z.eof and not z.unused_data and not z.unconsumed_tail and len(raw)==size
pairs=[struct.unpack_from('<HH',raw,i*4) for i in range(11)]
result={'block':886,'compressed_offset':offset,'compressed_size':packed,'decoded_size':size,'raw_sha256':hashlib.sha256(raw).hexdigest(),'sections':[{'section':i,'offset':s,'count':n,'bytes':(pairs[i+1][0] if i<10 else len(raw))-s} for i,(s,n) in enumerate(pairs)],'scope':'Original block header only; no new-edge or dependency validation'}
text=json.dumps(result,indent=2)
if a.out:a.out.write_text(text,encoding='utf-8')
print(text)
