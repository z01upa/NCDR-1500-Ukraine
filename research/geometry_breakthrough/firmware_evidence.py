from pathlib import Path
import os
import hashlib,json
root=Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[2])) / 'SW';out=Path(__file__).parent/'evidence';rows=[]
for name in ['NAVIMAIN.EXE','NK.BIN']:
 p=next(root.rglob(name));d=p.read_bytes();offsets=[0x400,0x410,0x9cead3] if name=='NK.BIN' else [0x1224]
 rows.append({'source':str(p),'sha256':hashlib.sha256(d).hexdigest(),'size':len(d),'windows':[{'offset':o,'hex':d[o:o+64].hex()} for o in offsets]})
(out/'firmware_evidence.json').write_text(json.dumps(rows,indent=2))
