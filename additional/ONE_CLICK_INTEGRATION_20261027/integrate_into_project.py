#!/usr/bin/env python3
"""Safe one-off import of previously verified NCDR1500 research into the LIVE project.

Does not write project SQLite, source optical media, original archive, or any running-worker file.
Refuses overwrite collisions. Requires Python 3.10+.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE=Path(__file__).resolve().parent
EXPECTED = json.loads((HERE/'BUNDLE_SHA256.json').read_text(encoding='utf-8'))
BUNDLE_FILES=['payload/geography.zip','payload/roadlinks.zip','payload/EUZ.CT.logical.bin', 'ncdr1500_search_index.py', 'test_ncdr1500_search_index.py']


def digest(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for buf in iter(lambda:f.read(1024*1024),b''):h.update(buf)
    return h.hexdigest()


def find_project():
    home=Path.home()
    candidates=[home/'Documents'/'Codex'/'2026-10-25'/'new-chat-2'/'work'/'NCDR_MAP_RESEARCH',
                home/'Desktop'/'crz'/'NCDR'/'1234',
                home/'Desktop'/'crz'/'NCDR']
    valid=[x for x in candidates if (x/'src'/'agent'/'autonomous_manager.py').is_file()]
    if len(valid)==1:return valid[0]
    # Explicit user choice instead of guessing which Codex checkout is the active workspace.
    print('Оберіть папку АКТИВНОГО проєкту, яка містить src\\agent\\autonomous_manager.py')
    try:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk();root.withdraw()
        result=filedialog.askdirectory(title='Оберіть NCDR_MAP_RESEARCH (активний проєкт)')
        root.destroy()
        if result and (Path(result)/'src'/'agent'/'autonomous_manager.py').is_file():return Path(result)
    except Exception:
        pass
    raise RuntimeError('Не вибрано папку активного проєкту NCDR_MAP_RESEARCH')


def checked_extract(archive, dest):
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist()
        for info in infos:
            p=Path(info.filename)
            if p.is_absolute() or '..' in p.parts or ':' in info.filename or '\\' in info.filename:
                raise ValueError(f'Небезпечний ZIP шлях: {info.filename}')
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Symlinks are not allowed')
            target=dest/p
            if info.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as src,target.open('xb') as dst:
                shutil.copyfileobj(src,dst)


def run_test(path):
    cp=subprocess.run([sys.executable,'-B',str(path)],cwd=str(path.parent),capture_output=True,text=True,timeout=90)
    if cp.returncode:
        raise RuntimeError(f'Не пройшов тест {path.name}:\n{cp.stdout}\n{cp.stderr}')
    return (cp.stdout+cp.stderr).strip()[-2000:]


def atomic_new_copy(src,dst):
    dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.exists():
        if digest(dst)==digest(src):return 'unchanged'
        raise FileExistsError(f'Інший файл уже існує, не перезаписую: {dst}')
    # Create exclusively so no writer is overwritten even if worker edits concurrently.
    with Path(src).open('rb') as inp,dst.open('xb') as out:
        shutil.copyfileobj(inp,out)
    return 'new'


def main():
    print('NCDR 1500 - інтеграція перевірених результатів у робоче дерево')
    for rel in BUNDLE_FILES:
        actual=digest(HERE/rel)
        if actual!=EXPECTED.get(rel):raise ValueError(f'Контрольна сума не збігається: {rel}')
    project=find_project().resolve()
    print('Проєкт:',project)
    if not (project/'src'/'readers').is_dir():
        raise ValueError('Немає src/readers; помилкова папка проєкту')
    ct_sha='552aaed46ec96cf5afc46af49d63d89bf989c675f6e4013514a269266dc9809e'
    if digest(HERE/'payload'/'EUZ.CT.logical.bin')!=ct_sha:
        raise ValueError('EUZ.CT.logical.bin не збігається з вихідним evidence')
    with tempfile.TemporaryDirectory(prefix='ncdr-merge-check-') as temporary:
        staged=Path(temporary)
        checked_extract(HERE/'payload'/'geography.zip',staged/'geography')
        checked_extract(HERE/'payload'/'roadlinks.zip',staged/'roadlinks')
        geo=json.loads((staged/'geography'/'OUTPUT_GEO'/'EVIDENCE_GEOGRAPHY.json').read_text('utf-8'))
        road=json.loads((staged/'roadlinks'/'NCDR1500_ROADLINK_RESEARCH_20261027'/'OUTPUT'/'EVIDENCE_ROADLINKS.json').read_text('utf-8'))
        if (geo['validated']['city_records'],geo['validated']['city_lookup_alias_entries'])!=(26525,26949):
            raise RuntimeError('Incompatible geography results')
        if (road['counts']['RL_records'],road['counts']['IOF_pointer_groups'],road['counts']['IL_variable_records'])!=(249750,3709,41172):
            raise RuntimeError('Incompatible roadlink results')
        print('Локальні тести:',run_test(HERE/'test_ncdr1500_search_index.py'))
        ct_test=subprocess.run([sys.executable,'-B',str(HERE/'ncdr1500_search_index.py'),'--ct',str(HERE/'payload'/'EUZ.CT.logical.bin'),'--cl-rows','26949'],capture_output=True,text=True,timeout=120)
        if ct_test.returncode:raise RuntimeError(ct_test.stderr)
        ct=json.loads(ct_test.stdout)
        if ct['status']!='PASS':raise RuntimeError('CT check was not PASS')
        # Install only into a new date-tagged destination. Repeated runs never overwrite evidence.
        research=project/'research'/'NCDR1500_VERIFIED_20261027'
        if research.exists():
            mf=research/'IMPORT_MANIFEST.json'
            if not mf.is_file() or json.loads(mf.read_text(encoding='utf-8')).get('bundle_sha256')!=EXPECTED:
                raise FileExistsError('Раніше існуюча папка дослідження відрізняється: '+str(research))
            print('Дослідження вже імпортовано раніше; повторні дані не перезаписано.')
        else:
            research.mkdir(parents=True,exist_ok=False)
            try:
                checked_extract(HERE/'payload'/'geography.zip',research/'geography')
                checked_extract(HERE/'payload'/'roadlinks.zip',research/'roadlinks')
                # Keeps a byte-for-byte sample for independent testing; does not alter original media.
                atomic_new_copy(HERE/'payload'/'EUZ.CT.logical.bin',research/'EUZ.CT.logical.bin')
                (research/'CT_EVIDENCE.json').write_text(json.dumps(ct,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                (research/'IMPORT_MANIFEST.json').write_text(json.dumps({'bundle_sha256':EXPECTED,'generated_utc':datetime.now(timezone.utc).isoformat(),'project':str(project),'claim':'Reader research, not disc'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            except Exception:
                # Only remove newly created research directory, never any user content in existing paths.
                shutil.rmtree(research,ignore_errors=True)
                raise
        copies=[]
        for src_name,dst in [('ncdr1500_search_index.py',project/'src'/'readers'/'ncdr1500_search_index.py'),
                             ('test_ncdr1500_search_index.py',project/'tests'/'unit'/'test_ncdr1500_search_index.py'),
                             ('ncdr1500_geography.py',project/'src'/'readers'/'ncdr1500_geography.py'),
                             ('ncdr1500_roadlinks.py',project/'src'/'readers'/'ncdr1500_roadlinks.py')]:
            src=HERE/src_name if src_name.startswith(('ncdr1500_search_','test_')) else None
            if src_name=='ncdr1500_geography.py':src=staged/'geography'/'decode_geography.py'
            if src_name=='ncdr1500_roadlinks.py':src=staged/'roadlinks'/'NCDR1500_ROADLINK_RESEARCH_20261027'/'verify_road_links.py'
            copies.append({'path':str(dst),'result':atomic_new_copy(src,dst)})
        # After install, run a real-source readback from the installed module.
        installed=subprocess.run([sys.executable,'-B',str(project/'src'/'readers'/'ncdr1500_search_index.py'), '--ct', str(research/'EUZ.CT.logical.bin'),'--cl-rows','26949'],capture_output=True,text=True,timeout=120)
        if installed.returncode:raise RuntimeError('Installed reader failed its full-data test: '+installed.stderr)
        if json.loads(installed.stdout).get('status')!='PASS':raise RuntimeError('Installed reader failed')
    handoff=research/'NEXT_ENGINEERING_STEP.md'
    handoff.write_text('''# NCDR1500 - наступна інженерна задача\n\n**Доведено на EU44420940.82:** CT з 47 251 записів по 14 байтів утворює вкладене дерево інтервалів над 26 949 індексами CL. Поле u16 +4 /256 дорівнює кількості безпосередніх дітей вузла на всьому файлі. Кожна позиція CL має рівно один термінальний вузол CT. Root має 45 дочірніх вузлів. RL -> IOF -> IL: 3709 коректних груп із загальною кількістю 41172 зв’язаних записів. Географічні межі CTY/CNY перевірені.\n\n**Наступна ціль (одна, а не сотні):** незалежно зіставити геометрію дорожніх сегментів MP0/MG1/MG2/MG3 з ідентифікаторами RL/IOF та населеними пунктами. Реалізувати Reader сегментів і тест із географічними координатами, підтвердженими зовнішньою картою. Без цього не видавати Writer за готовий.\n\n**Важливо:** Цей імпорт додає Reader та докази в робоче дерево, але наявний Manager сам не сканує цю папку. Він НЕ створює автоматично нову задачу і НЕ підтверджує сумісність диска. Для цього потрібна окрема інтеграція з планувальником. Не змінювати оригінальні диски.\n''',encoding='utf-8')
    print('\nIMPORT PASS')
    print('Результати:',research)
    print('Нові модулі:',json.dumps(copies,ensure_ascii=False,indent=2))
    print('Наступний інженерний крок:',handoff)
    print('SQLite, Worker, NCDR оригінали не змінено.')

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('\nІНТЕГРАЦІЮ НЕ ЗАВЕРШЕНО:',type(e).__name__,str(e),file=sys.stderr)
        raise SystemExit(1)
