from pathlib import Path
import os
import struct,zlib
r=Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[2])) / 'SW' / 'DB'
for ext in ['MP0','MG3']:
 d=(r/('EUZ.'+ext)).read_bytes();n=struct.unpack_from('<I',d,86)[0]
 for j in range(3):
  bo=114+24*j if ext=='MP0' else 114+16*j
  at=bo+16 if ext=='MP0' else 114+16*n+8*j
  p,u,c=struct.unpack_from('<IHH',d,at);out=zlib.decompress(d[p:p+c]);print(ext,j,'bbox',struct.unpack_from('<iiii',d,bo));print(list(struct.iter_unpack('<HH',out[:44])));print(out[44:100].hex(' '));
