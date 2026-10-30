from pathlib import Path
import os
import struct,zlib
r=Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[2])) / 'SW' / 'DB'
for ext in ['MP0','MG1','MG2','MG3']:
 d=(r/('EUZ.'+ext)).read_bytes();n=struct.unpack_from('<I',d,86)[0];p=114+16*n
 print(ext,n,'table',p,'streambase',114+28*n)
 print([struct.unpack_from('<III',d,p+i*12) for i in range(8)])
 print('end',d[114+28*n-48:114+28*n+4].hex(' '))
