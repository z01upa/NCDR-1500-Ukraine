from pathlib import Path
import hashlib,json
p=Path(__file__).parent
files={str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in f.parts and f.name!='MANIFEST.json'}
(p/'MANIFEST.json').write_text(json.dumps(files,indent=2));print(len(files),'files hashed')
