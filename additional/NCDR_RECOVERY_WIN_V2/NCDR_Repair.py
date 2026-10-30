#!/usr/bin/env python3
"""NCDR Qwen GUI import recovery. No modification of the original project.

Stdlib only, Windows 11 + Python 3.13. Creates diagnostics and an isolated launcher.
"""
from __future__ import annotations

import argparse
from collections import deque
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback
import zipfile

OMIT = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', 'site-packages', '.next',
        'DISCS', 'ORIGINAL_IMAGES', 'NK.BIN', '_TRANSFER_META',
        'WindowsApps', 'AppData', 'System Volume Information'}
GUI_NAMES = {'gui.py', 'gui.pyw', 'run_gui.py', 'run_gui.pyw', 'start_gui.py',
             'start_gui.pyw', 'main.py', 'main.pyw', 'app.py', 'app.pyw',
             'ncdqwen_gui.py', 'ncdqwen_gui.pyw'}


def find_packages(search_roots: list[Path], max_depth=7, max_directories=20000):
    queue = deque((p, 0) for p in search_roots if p.is_dir())
    seen = set()
    found = []
    total = 0
    while queue and total < max_directories:
        base, depth = queue.popleft()
        try:
            key = str(base.resolve()).lower()
        except (OSError, RuntimeError):
            key = str(base).lower()
        if key in seen:
            continue
        seen.add(key)
        total += 1
        if base.name.lower() == 'ncdqwen':
            found.append(base)
            continue
        if depth >= max_depth:
            continue
        try:
            dirs = [p for p in base.iterdir() if p.is_dir() and not p.is_symlink() and p.name not in OMIT]
        except (OSError, PermissionError):
            continue
        queue.extend((p, depth + 1) for p in dirs)
    return found, total, bool(queue)


def probe(root: Path, python: Path, work: Path, serial: int):
    """Actual subprocess test. Uses different cwd from project root to uncover path assumptions."""
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root) + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    # Avoid executing full runner CLI, which might start a long computation on import.
    code = r'''
import importlib, json, os, sys, traceback
info={'python':sys.executable,'cwd':os.getcwd(),'path':sys.path,'modules':{}}
try:
    from ncdqwen.db0 import DB0Reader, SECTOR_SIZE, sha256_file
    for name in ('ncdqwen.db0','ncdqwen.runner'):
        module=importlib.import_module(name)
        info['modules'][name]=getattr(module,'__file__',None)
    info['result']='IMPORTS_PASS'
except Exception:
    info['result']='IMPORTS_FAIL'
    info['traceback']=traceback.format_exc()
print(json.dumps(info, ensure_ascii=False))
sys.exit(0 if info['result']=='IMPORTS_PASS' else 17)
'''
    try:
        p = subprocess.run([str(python), '-c', code], cwd=str(Path.home()), env=env,
                           capture_output=True, text=True, timeout=25, encoding='utf-8', errors='replace')
        (work / f'probe_{serial:02d}.stdout.txt').write_text(p.stdout, encoding='utf-8')
        (work / f'probe_{serial:02d}.stderr.txt').write_text(p.stderr, encoding='utf-8')
        result = json.loads(p.stdout.strip().splitlines()[-1])
        return p.returncode == 0, result
    except subprocess.TimeoutExpired:
        return False, {'result':'TIMEOUT','error':'Module import did not finish in 25 seconds'}
    except (OSError, ValueError, IndexError) as e:
        return False, {'result':'ERROR', 'error':f'{type(e).__name__}: {e}'}


def entrypoints(root: Path):
    """Only consider roots adjacent to the ncdqwen package, avoiding random GUI files."""
    candidates = []
    checked = [root, root / 'ncdqwen', root.parent]
    for p in checked:
        if not p.is_dir():
            continue
        try:
            for f in p.iterdir():
                if f.is_file() and (f.name.lower() in GUI_NAMES or
                                    (f.suffix.lower() == '.exe' and ('ncd' in f.name.lower() or 'qwen' in f.name.lower()))):
                    candidates.append(f)
        except OSError:
            pass
    return sorted(set(candidates), key=lambda p: str(p).lower())


def cmd_quote(s):
    return '"' + s.replace('"', '') + '"'


def make_launcher(output: Path, root: Path, python: Path, entry: Path):
    # Generate .cmd launcher. A GUI-launched Python subprocess inherits PYTHONPATH unless GUI overwrites env.
    root_s = str(root)
    py_s = str(python)
    ent_s = str(entry)
    if any(c in root_s + py_s + ent_s for c in '\r\n%'):
        raise ValueError('Unsupported path characters in launcher')
    is_exe = entry.suffix.lower() == '.exe'
    launch_line = cmd_quote(ent_s) if is_exe else f'{cmd_quote(py_s)} {cmd_quote(ent_s)}'
    content = ('@echo off\n'
               'chcp 65001 >nul\n'
               'setlocal\n'
               'rem Sets search path for GUI and all inherited child Python processes.\n'
               f'set "PYTHONPATH={root_s};%PYTHONPATH%"\n'
               f'cd /d {cmd_quote(root_s)}\n'
               'echo NCDR package root: %CD%\n'
               f'{launch_line}\n'
               'set "NCDR_EXIT=%ERRORLEVEL%"\n'
               'echo NCDR exit code: %NCDR_EXIT%\n'
               'pause\n'
               'exit /b %NCDR_EXIT%\n')
    output.write_text(content, encoding='utf-8')


def pack_source_zip(work: Path, packages: list[Path], report: dict):
    target = work / 'NCDR_SOURCE_FOR_FIX.zip'
    limit = 3 * 1024 * 1024
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('REPORT.json', json.dumps(report, ensure_ascii=False, indent=2))
        for idx, pkg in enumerate(packages, 1):
            root = pkg.parent
            for p in list(pkg.rglob('*.py'))[:150]:
                try:
                    if p.is_file() and p.stat().st_size < limit:
                        archive.write(p, f'candidate_{idx:02d}/ncdqwen/{p.relative_to(pkg).as_posix()}')
                except OSError:
                    pass
            for p in entrypoints(root):
                if p.suffix.lower() not in {'.py', '.pyw'}:
                    continue
                try:
                    if p.stat().st_size < limit:
                        archive.write(p, f'candidate_{idx:02d}/entrypoints/{p.name}')
                except OSError:
                    pass
    return target


def main():
    ap = argparse.ArgumentParser(description='Check ncdqwen.runner and db0; create correct GUI launcher')
    ap.add_argument('--root', type=Path, help='Optional exact project root containing ncdqwen/')
    ap.add_argument('--gui', type=Path, help='Optional exact existing GUI .exe or .py path')
    args = ap.parse_args()

    desktop = Path(os.environ.get('USERPROFILE', str(Path.home()))) / 'Desktop'
    out = desktop / ('NCDR_REPAIR_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S'))
    out.mkdir(parents=True, exist_ok=True)
    log = []
    def say(x):
        print(x, flush=True)
        log.append(x)

    python = Path(sys.executable)
    say('NCDR Research - Windows Python recovery')
    say(f'Python: {python}')
    say(f'Outputs: {out}')
    starts = ([args.root] if args.root else [desktop, Path.home() / 'Documents',
              Path.home() / 'Downloads', Path.home() / 'OneDrive' / 'Desktop',
              desktop / 'crz', desktop / 'crz' / 'NCDR_QWEN_TRANSFER_GUI',
              desktop / 'NCDR_QWEN_TRANSFER_GUI',
              Path.cwd()])
    pkg_paths, inspected, truncated = find_packages(starts)
    if args.root:
        p = args.root / 'ncdqwen'
        if p.is_dir() and p not in pkg_paths:
            pkg_paths.append(p)
    say(f'Folders scanned: {inspected}; search truncated: {truncated}')
    say(f'ncdqwen folders: {len(pkg_paths)}')
    summaries = []
    successes = []
    for i, pkg in enumerate(pkg_paths, 1):
        root = pkg.parent
        facts = {f: (pkg / f).is_file() for f in ('__init__.py', 'db0.py', 'runner.py')}
        say(f'[{i}] {pkg} - {facts}')
        row = {'package':str(pkg),'root':str(root),'files':facts,'gui_candidates':[str(p) for p in entrypoints(root)]}
        if facts['runner.py'] and facts['db0.py']:
            ok, test = probe(root, python, out, i)
            row['import_ok'], row['import_test'] = ok, test
            say('    import test: ' + ('PASS' if ok else 'FAIL: ' + str(test.get('result'))))
            if ok:
                successes.append(row)
        else:
            row['import_ok'] = False
            say('    BLOCKED: missing source modules')
        summaries.append(row)

    report = {'python':str(python), 'cwd':os.getcwd(), 'searched_directories':inspected,
              'search_truncated':truncated,'candidates':summaries,'status':'NO_COMPLETE_PACKAGE'}
    if len(successes) == 1:
        candidate = successes[0]
        entry_list = candidate['gui_candidates']
        if args.gui:
            entry = args.gui.resolve()
            if not entry.is_file():
                say(f'BLOCKED: GUI path does not exist: {entry}')
                report['status'] = 'GUI_NOT_FOUND'
            else:
                make_launcher(out / 'START_NCDR_WITH_FIXED_PATH.cmd', Path(candidate['root']), python, entry)
                say('CREATED: START_NCDR_WITH_FIXED_PATH.cmd')
                report['status'] = 'IMPORTS_PASS_LAUNCHER_READY'
        elif len(entry_list) == 1:
            make_launcher(out / 'START_NCDR_WITH_FIXED_PATH.cmd', Path(candidate['root']), python, Path(entry_list[0]))
            say('CREATED: START_NCDR_WITH_FIXED_PATH.cmd')
            report['status'] = 'IMPORTS_PASS_LAUNCHER_READY'
        else:
            say('IMPORTS_PASS but ambiguous/missing GUI entrypoint; run with --gui C:\\path\\to\\NCDR.exe')
            report['status'] = 'IMPORTS_PASS_GUI_SELECTION_REQUIRED'
    elif len(successes) > 1:
        say('Multiple importable package copies. Choose exact root with --root C:\\path\\to\\project')
        report['status'] = 'MULTIPLE_PACKAGE_COPIES'
    else:
        say('BLOCKED: ncdqwen.runner/db0 unavailable or their imports fail.')
        say('Do not create empty modules: recover the real files or repair dependencies from saved code.')

    (out / 'REPORT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'RUN_LOG.txt').write_text('\n'.join(log) + '\n', encoding='utf-8')
    zipout = pack_source_zip(out, pkg_paths, report)
    say(f'Code evidence ZIP: {zipout}')
    say('IMPORTANT: Review ZIP for personal data before sharing. No source files were modified.')
    say('Actual GUI analysis and DB_0/Ollama smoke test require a runnable project on this computer.')
    return 0 if report['status'].startswith('IMPORTS_PASS') else 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print(traceback.format_exc(), file=sys.stderr)
        sys.exit(3)
