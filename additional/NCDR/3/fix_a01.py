from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone
import traceback

MARKER = '# NCDR_A01_AVAILABLE_MODELS_BRIDGE_V1'
RECOVERY_MARKER = '# NCDR_A01_REQUEUE_V1'
MANAGER_IMPORT = 'from src.agent import autonomous_manager as manager\n'
FUNC_HEADER = 'def _known_recovery_reason(task_id: str, diagnostic: str) -> str | None:\n'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def report(root, status, **detail):
    d = {'status': status, 'utc': datetime.now(timezone.utc).isoformat(), 'project': str(root), **detail}
    out = root / 'reports' / 'A01_NAMEERROR_RESCUE_20261027.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(d, ensure_ascii=False, indent=2))
    return d

def find_root():
    if len(sys.argv) > 1:
        p = Path(sys.argv[1]).expanduser()
        if (p / 'src/agent/autonomous_manager.py').is_file():
            return p.resolve()
    home = Path.home()
    preferred = home / 'Documents/Codex/2026-10-25/new-chat-2/work/NCDR_MAP_RESEARCH'
    if (preferred / 'src/agent/autonomous_manager.py').is_file():
        return preferred.resolve()
    print('NOT FOUND: current NCDR_MAP_RESEARCH directory. Pass its path as first argument.')
    raise SystemExit(2)

def mutation(original):
    target = original / 'src/agent/project_director.py'
    manager = original / 'src/agent/autonomous_manager.py'
    if not (target.is_file() and manager.is_file()):
        raise RuntimeError('Missing project_director or autonomous_manager. No changes.')
    director_src = target.read_text('utf-8')
    manager_src = manager.read_text('utf-8')
    if MANAGER_IMPORT not in director_src or FUNC_HEADER not in manager_src:
        raise RuntimeError('Current code differs from validated version. Refusing unreviewed changes.')
    ast.parse(director_src, filename=str(target))
    ast.parse(manager_src, filename=str(manager))
    if not any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name=='available_models' for n in ast.parse(manager_src).body):
        raise RuntimeError('No available_models() function in autonomous_manager. No changes.')
    director_new = director_src
    if MARKER not in director_new:
        director_new = director_src.replace(MANAGER_IMPORT,
            MANAGER_IMPORT + '\n' + MARKER + '\navailable_models = manager.available_models\n', 1)
    manager_new = manager_src
    if RECOVERY_MARKER not in manager_new:
        # Insert after the function docstring, keeping the original matching logic untouched.
        start = FUNC_HEADER + '    """Return a recovery reason only for an exact error with a checked code fix."""\n'
        if start not in manager_new:
            raise RuntimeError('Recovery function changed shape: no safe insertion point. No changes.')
        branch = ("    " + RECOVERY_MARKER + "\n"
            "    if task_id.startswith('AUTO_MISSION_EXEC_A01_') and 'NameError' in diagnostic and 'available_models' in diagnostic:\n"
            "        from src.agent import project_director\n"
            "        if callable(getattr(project_director, 'available_models', None)):\n"
            "            return 'ncdr-a01-available-models-v1: validated model-discovery alias installed; retry only this A01 task once'\n")
        manager_new = manager_new.replace(start, start+branch, 1)
    ast.parse(director_new, filename=str(target))
    ast.parse(manager_new, filename=str(manager))
    return (target, director_src, director_new), (manager, manager_src, manager_new)

def run():
    root = find_root()
    paths = []
    try:
        files = mutation(root)
        if all(before == after for _, before, after in files):
            report(root, 'ALREADY_PATCHED', note='Files unchanged; worker restart may still be necessary.')
            return 0
        backup = root / 'backups' / ('A01_AVAILABLE_MODELS_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S'))
        backup.mkdir(parents=True, exist_ok=True)
        before_hash = {}
        for p, before, after in files:
            before_hash[str(p.relative_to(root))] = sha(p)
            backed = backup / p.relative_to(root)
            backed.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, backed)
            paths.append((p, backed))
        for p, before, after in files:
            if sha(p) != before_hash[str(p.relative_to(root))]:
                raise RuntimeError(f'Concurrent file change: {p}; no safe installation')
        for p, before, after in files:
            tmp = p.with_name(p.name + '.a01tmp')
            tmp.write_text(after, encoding='utf-8', newline='')
            tmp.replace(p)
        # Targeted check in a child process; no run of the worker, no SQLite writes.
        expr = ("from src.agent import project_director as p, autonomous_manager as m; "
                "assert p.available_models is p.manager.available_models; "
                "assert m._known_recovery_reason('AUTO_MISSION_EXEC_A01_TEST', "
                "\"RuntimeError: NameError: name 'available_models' is not defined\") is not None; "
                "print('A01 BRIDGE TEST: PASS')")
        check = subprocess.run([sys.executable, '-B', '-c', expr], cwd=root, capture_output=True,
                               text=True, encoding='utf-8', errors='replace', timeout=45)
        if check.returncode:
            raise RuntimeError('Targeted import/recovery test failed: '+(check.stderr or check.stdout)[-2000:])
        # Optional regression: if test exists, it must pass.
        test = root / 'tests/unit/test_empty_queue_replan.py'
        if test.is_file():
            cp = subprocess.run([sys.executable,'-B','-m','unittest','tests.unit.test_empty_queue_replan'],
                                cwd=root, capture_output=True, text=True, encoding='utf-8',errors='replace',timeout=90)
            if cp.returncode:
                raise RuntimeError('Queue regression failed: '+(cp.stderr or cp.stdout)[-2000:])
        report(root, 'PATCH_INSTALLED', backup=str(backup), before_hash=before_hash,
               after_hash={str(p.relative_to(root)):sha(p) for p,_,_ in files},
               test=check.stdout.strip(),
               next='Restart ONLY idle worker to load changed modules. Recovery logic retries the specific NameError A01 once.')
        return 0
    except Exception as exc:
        rolled=[]
        for p,bak in reversed(paths):
            if bak.is_file():
                shutil.copy2(bak,p)
                rolled.append(str(p))
        report(root,'NO_PATCH_OR_ROLLED_BACK',reason=f'{type(exc).__name__}: {exc}',rolled_back=rolled)
        return 1

if __name__ == '__main__':
    sys.exit(run())
