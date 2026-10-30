from pathlib import Path
import json,hashlib
p=Path(__file__).parent
files={str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in f.parts and f.name!='MANIFEST.json'}
(p/'MANIFEST.json').write_text(json.dumps({'algorithm':'sha256','files':files},indent=2))
print('Manifest files:',len(files));print('Evidence bytes:',sum(f.stat().st_size for f in (p/'evidence').iterdir()))
