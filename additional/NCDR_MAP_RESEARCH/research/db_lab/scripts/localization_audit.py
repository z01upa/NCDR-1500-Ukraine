#!/usr/bin/env python3
"""Audit Ukrainian/English UI strings and installed task presentation metadata."""
import json,re,sys
from pathlib import Path
project=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[3]
lab=project/'research/db_lab'
swift=lab/'macos/Sources/NCDRRELabApp/App.swift'
strings={lang:lab/f'macos/Resources/{lang}.lproj/Localizable.strings' for lang in ('en','uk')}
pattern=re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*=\s*"((?:[^"\\]|\\.)*)"\s*;',re.M)
parsed={k:{a for a,b in pattern.findall(p.read_text())} for k,p in strings.items()}
source=swift.read_text()
# Collect every string passed to tr(), including conditional-key calls.
keys=set()
for match in re.finditer(r'(?:model\.)?tr\(',source):
    i=match.end();depth=1;quoted=False;escaped=False;buf=[]
    while i<len(source) and depth:
        ch=source[i]
        if quoted:
            if escaped: escaped=False
            elif ch=='\\': escaped=True
            elif ch=='"': quoted=False;keys.add(''.join(buf));buf=[]
            else: buf.append(ch)
        elif ch=='"': quoted=True;buf=[]
        elif ch=='(': depth+=1
        elif ch==')': depth-=1
        i+=1
# Detect visible literal labels passed directly to SwiftUI controls.
visible=[]
for rx in (r'Text\(\s*"([^"]+)"\s*\)',r'Button\(\s*"([^"]+)"',r'Label\(\s*"([^"]+)"',r'Picker\(\s*"([^"]+)"',r'Toggle\(\s*"([^"]+)"',r'Section\(\s*"([^"]+)"',r'TextField\(\s*"([^"]+)"',r'LabeledContent\(\s*"([^"]+)"'):
    visible += re.findall(rx,source)
non_translation_fields={'implementation_status','package_status','status','ui_status','source_type','confidence',''}
allowed={'NCDR RE LAB','DB_0','NCDx','POISoN','NAVBOOT','SH4','PE32','Windows CE','SHA256','Metal','CPU','GPU','RVA','AUTO','English','Українська','System','Dark','Light'}
raw=sorted({x for x in visible if x not in allowed and not x.startswith('\\(') and not x.startswith('%') and re.search(r'[A-Za-z]{3}',x)})
tasks=[];missing=[];localized_stages=0
for p in sorted((project/'research/tasks').glob('*/task.json')):
    try:o=json.loads(p.read_text())
    except Exception:continue
    if 'task_id' not in o:continue
    tasks.append(o['task_id']);uk=o.get('presentation',{}).get('uk',{})
    if not uk.get('title') or not uk.get('description') or not uk.get('inputs_label'):missing.append(o['task_id'])
    elif uk.get('stage_names'):localized_stages+=1
    else:missing.append(o['task_id']+':stages')
result={'localized_keys':len(parsed['en']&parsed['uk']),'missing_ukrainian_keys':len(parsed['en']-parsed['uk']),'hard_coded_english_ui_literals':raw,'tasks_localized':len(tasks)-len([x for x in missing if ':stages' in x]),'task_stages_localized':localized_stages,'tasks_missing_localization':missing,'missing_callsite_keys':sorted((keys-parsed['uk'])-non_translation_fields),'source':str(swift)}
print(json.dumps(result,ensure_ascii=False,indent=2))
