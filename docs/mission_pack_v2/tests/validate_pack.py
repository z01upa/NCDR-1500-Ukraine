from pathlib import Path
import json
root = Path(__file__).resolve().parents[1]
backlog = json.loads((root / 'plans/task_backlog.json').read_text(encoding='utf-8'))
tasks = backlog['tasks']; ids = {t['id'] for t in tasks}
assert len(ids) == len(tasks) == backlog['task_count']
for t in tasks:
    assert t['id'] not in t['dependencies']
    assert all(d in ids for d in t['dependencies']), t['id']
    assert t['acceptance_criteria'] and t['expected_artifacts']
    assert t['allowed_source_access'] == 'READ_ONLY'
for path in (root / 'schemas').glob('*.json'):
    json.loads(path.read_text(encoding='utf-8'))
for p in (root / 'plans').glob('*.json'):
    json.loads(p.read_text(encoding='utf-8'))
for p in (root / 'policies').glob('*.json'):
    json.loads(p.read_text(encoding='utf-8'))
try:
    import jsonschema
    schema = json.loads((root / 'schemas/task.schema.json').read_text(encoding='utf-8'))
    for t in tasks: jsonschema.validate(t, schema)
except ImportError:
    print('WARN: jsonschema absent, only structural checks run')
print(f'PASS: {len(tasks)} task definitions; all dependencies/schema files parse')
