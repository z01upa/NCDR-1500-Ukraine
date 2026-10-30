from pathlib import Path
import os
import struct,re
root=Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[2])) / 'SW'
for ext in ['MP0','MG1','MG2','MG3']:
 d=(root/'DB'/('EUZ.'+ext)).read_bytes(); print(ext,len(d),d[:128].hex(' '), 'zip',d.find(b'zip\1'))
d=next(root.rglob('NK.BIN')).read_bytes(); o=d.find(b'ECEC'); print('ECEC',hex(o),d[o-64:o+100].hex(' '))
for m in re.finditer(rb'[ -~]{5,}',d):
 if any(t in m[0].lower() for t in [b'.mp0',b'.mg1',b'geometry',b'dbaccess',b'mapread',b'.pdb']): print(hex(m.start()),m[0][:180])
