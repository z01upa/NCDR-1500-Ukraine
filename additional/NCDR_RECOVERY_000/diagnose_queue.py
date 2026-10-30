"""Read-only task/mission diagnosis: stdlib only, does not mutate SQLite."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
from urllib.parse import quote
import argparse
import json
import sqlite3


def analyze(db: Path) -> dict:
    # URI explicitly enforces SQLite read-only mode (never runs migrations).
    uri = db.resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True, timeout=5) as con:
        con.row_factory = sqlite3.Row
        tasks = [dict(row) for row in con.execute('SELECT id,status,result_json FROM tasks')]
        missions = [dict(row) for row in con.execute(
            'SELECT canonical_id,status,dependencies_json FROM mission_tasks')]
    status_by_id = {row['canonical_id']: row['status'] for row in missions}
    actionable = []
    blocked = []
    for row in missions:
        if row['status'] not in ('PROPOSED', 'READY'):
            continue
        deps = json.loads(row['dependencies_json'] or '[]')
        waiting = [{'id': dep, 'status': status_by_id.get(dep, 'MISSING')}
                   for dep in deps if status_by_id.get(dep) != 'DONE']
        if waiting:
            blocked.append({'id': row['canonical_id'], 'waiting_for': waiting})
        else:
            actionable.append(row['canonical_id'])
    known_osm = [row for row in tasks if row['id'] == 'AUTO_OSM_NATIONAL_PUBLISHED_RECOVERY_01']
    osm_error = ''
    if known_osm:
        try:
            osm_error = str(json.loads(known_osm[0]['result_json'] or '{}').get('error', ''))[:500]
        except ValueError:
            osm_error = '<invalid JSON>'
    return {
        'runtime_statuses': dict(Counter(row['status'] for row in tasks)),
        'mission_statuses': dict(Counter(row['status'] for row in missions)),
        'ready_canonical_missions': actionable,
        'dependency_blocked_canonical_missions': blocked,
        'stale_osm_recovery': {'status': known_osm[0]['status'] if known_osm else 'NOT_FOUND',
                               'error': osm_error},
        'note': 'Read-only diagnostics: a PROPOSED mission is not necessarily dependency-ready.'
    }


def main() -> None:
    p = argparse.ArgumentParser(description='NCDR SQLite read-only queue diagnosis')
    p.add_argument('project_root', type=Path)
    args = p.parse_args()
    print(json.dumps(analyze(args.project_root / 'project_state.sqlite'),
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
