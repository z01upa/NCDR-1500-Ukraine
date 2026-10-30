from pathlib import Path
import os
import re,struct
p=next(Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[2])) / 'SW'.rglob('NK.BIN'));d=p.read_bytes()
o=next(i for i in range(32,len(d)) if d[i]!=255);print(hex(o));print(d[o:o+512].hex(' '))
print([(hex(m.start()),d[m.start():m.start()+24].hex(' ')) for m in list(re.finditer(b'CE',d))[:15]])
