from pathlib import Path
import os
import zlib,struct
r=Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[2])) / 'SW'
d=(r/'DB/EUZ.MG3').read_bytes()
for o in range(80,350,16):print(hex(o), d[o:o+16].hex(' '))
for i in range(114,len(d)-2):
 if d[i]==120 and d[i+1] in (1,94,156,218):
  try:
   z=zlib.decompressobj();b=z.decompress(d[i:],4000000)
   if not z.eof:continue
   print('stream',i,'packed',len(d)-i-len(z.unused_data),'unpacked',len(b),'prefix',b[:160].hex(' '));break
  except zlib.error:pass
