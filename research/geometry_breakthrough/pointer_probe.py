from pathlib import Path
import os
import struct,zlib
r=Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[2])) / 'SW' / 'DB'
for ext in ['MP0','MG3']:
 d=(r/('EUZ.'+ext)).read_bytes();n=struct.unpack_from('<I',d,86)[0];base=114+28*n
 for j in range(3):
  at=114+24*j+16 if ext=='MP0' else 114+16*n+8*j
  p,a,b=struct.unpack_from('<IHH',d,at)
  print(ext,j,p,a,b)
  for off in [p,base+p]:
   try:
    z=zlib.decompressobj();out=z.decompress(d[off:],4000000); print('decoded',off,len(d)-off-len(z.unused_data),len(out),z.eof,out[:54].hex(' '))
   except zlib.error:pass
