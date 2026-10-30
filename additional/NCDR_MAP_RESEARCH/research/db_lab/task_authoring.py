"""Conservative pasted-task parser, compiler bridge, revisions, and lifecycle."""
from __future__ import annotations
import hashlib, json, re
import os
from datetime import datetime, timezone
from pathlib import Path

UNDEFINED="НЕ ВИЗНАЧЕНО"
COMPILER_SCHEMA_VERSION=2
COMPILER_VERSION=os.environ.get("NCDR_APP_VERSION","Unknown")
COMPILER_FINGERPRINT=hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name("generic_runner.py").read_bytes()+Path(__file__).with_name("strict_plan.py").read_bytes()).hexdigest()
ALIASES={
 "task_id":("task","task id","id"),"title":("title","назва"),
 "research_question":("research question","research goal","goal","мета","дослідницьке питання"),
 "inputs":("inputs","input","input artifacts","вхідні дані"),
 "known_facts":("known facts","facts","відомі факти"),
 "required_capabilities":("required capabilities","required capability","required modules","потрібні модулі","обов'язкові модулі"),
 "optional_capabilities":("optional capabilities","optional capability","optional modules","додаткові модулі","необов'язкові модулі"),
 "not_required":("not required","not required capabilities","excluded capabilities","не потрібно","не потрібні модулі"),
 "methods":("method","methods","methodology","метод","методи"),
 "stages":("stages","steps","етапи","кроки"),
 "stop_condition":("stop condition","stop conditions","умова завершення","умови завершення","умова автоматичного завершення"),
 "expected_outputs":("expected outputs","expected output","outputs","очікувані результати","очікувані виходи"),
 "report_questions":("report must answer","report questions","questions for report","питання до звіту","звіт має відповісти"),
 "finding_status":("finding status","статус висновку"),
}
CAPABILITY_NAMES={
 "SH4_DISASSEMBLY":("sh4 disassembly","sh4 дизасемб"),
 "SH4_XREF_ANALYSIS":("sh4 xref","cross reference","перехресні посилання"),
 "SH4_IMPORT_XREF":("sh4 import xref","import-call xref"),
 "COREDLL_ORDINAL_RESOLUTION":("coredll resolution","coredll ordinal"),
 "NK_BIN_ROM_PARSER":("nk.bin parser","nk_bin_rom_parser","nk.bin rom"),
 "NK_BIN_MODULE_EXTRACTION":("nk.bin module extraction","extract nk.bin module"),
 "WINCE_PE_ORDINAL_IMPORTS":("wince pe ordinal","ordinal imports"),
 "PE_IMPORT_ANALYSIS":("pe import analysis","pe imports"),
 "DB_AWARE_DIFF":("db-aware diff","database-aware diff"),
 "ARTIFACT_INVENTORY":("artifact inventory","inventory artifacts"),
}
CAP_ID_RE=re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")

def _norm(text): return re.sub(r"[^a-z0-9а-яіїєґ]+"," ",text.casefold()).strip()
def _items(raw):
    """Keep list entries and wrapped lines intact, stripping only list markers."""
    result=[]; current=[]
    for line in raw.splitlines():
        s=line.strip()
        if not s:
            if current: result.append(" ".join(current));current=[]
            continue
        m=re.match(r"^(?:[-*•]|\d+[.)])\s+(.*)$",s)
        if m:
            if current: result.append(" ".join(current))
            current=[m.group(1).strip()]
        elif current and (line[:1].isspace() or not re.match(r"^[A-ZА-ЯІЇЄҐ][A-ZА-ЯІЇЄҐ _-]{2,}:\s*$",s)):
            current.append(s)
        else:
            if current: result.append(" ".join(current))
            current=[s]
    if current: result.append(" ".join(current))
    return result

def _method_items(raw):
    """Keep numbered method stages whole, including their nested bullet lists."""
    rows=[];current=[]
    for line in raw.splitlines():
        s=line.strip()
        if not s:
            if current:current.append("")
            continue
        if re.match(r"^\d+[.)]\s+",s):
            if current:rows.append("\n".join(current).strip())
            current=[s]
        elif current:current.append(line.rstrip())
        elif s:current=[s]
    if current:rows.append("\n".join(current).strip())
    return [x for x in rows if x]

def _section_items(raw):
    if not raw:return []
    if re.search(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+",raw):return _items(raw)
    return [line.strip() for line in raw.splitlines() if line.strip()]

def parse_sections(prompt:str)->dict:
    aliases={_norm(alias):key for key,values in ALIASES.items() for alias in values}
    fields={key:[] for key in ALIASES}; active=None
    for line in prompt.splitlines():
        m=re.match(r"^\s*(?:#{1,6}\s*)?([^:]+?)\s*:\s*(.*)$",line)
        key=aliases.get(_norm(m.group(1))) if m else None
        if key:
            active=key
            if m.group(2): fields[key].append(m.group(2))
            continue
        if active is not None: fields[active].append(line)
    return {key:"\n".join(lines).strip() for key,lines in fields.items() if "\n".join(lines).strip()}

def _capabilities(raw):
    values=[]
    if not raw:return values
    for line in raw.splitlines():
        for cap in CAP_ID_RE.findall(line.upper()):
            if cap in CAPABILITY_NAMES and cap not in values: values.append(cap)
    return values

def _compile_plan(methods,expected_outputs,report_questions,stop_condition,explicit_required):
    from .generic_runner import compile_operations,OPERATION_REGISTRY,annotate_execution_plan
    instructions=list(methods)
    plan,unsupported,optional_unsupported=compile_operations(instructions,expected_outputs,report_questions,stop_condition)
    plan=annotate_execution_plan(plan,instructions)
    names=[x.get("operation") if isinstance(x,dict) else x for x in plan]
    corpus_impls={"cataloged raw-byte search","cataloged positive-control scan","validated PE section mapping","SH4 xrefs around catalog pattern hits","cataloged ASCII and UTF-16LE search","cataloged PE import/export symbol search","evidence relationship aggregation","weighted evidence ranking"}
    corpus_ops={op for op,row in OPERATION_REGISTRY.items() if row.get("implementation") in corpus_impls}
    # Single-file work uses the read-only loader; corpus operations resolve
    # their targets from the artifact catalog and need no manually named file.
    if not corpus_ops.intersection(names):plan.insert(0,{"operation":"LOAD_ARTIFACT","parameters":{"artifact_scope":{"kind":"input_artifacts"}},"source_method_item":None})
    return plan,unsupported,optional_unsupported

def parse_prompt(prompt:str,project_root:Path,language="uk")->dict:
    from .strict_plan import is_strict_plan,preview_text
    if is_strict_plan(prompt): return preview_text(prompt,project_root,language)
    from .tasks import CAPABILITY_REGISTRY
    sections=parse_sections(prompt)
    task_id_value=sections.get("task_id","")
    id_match=re.search(r"(?im)^\s*(?:TASK\s*ID|TASK|ID)\s*:\s*([A-Za-z0-9_-]+)",prompt)
    task_id=(id_match.group(1).upper() if id_match else "")
    title_items=_items(sections.get("title",""));title=title_items[0] if title_items else ""
    if not title: title=next((line.lstrip("# ").strip() for line in prompt.splitlines() if line.strip() and not line.strip().startswith("=")),UNDEFINED)
    task_id=task_id or (re.sub(r"[^A-Za-z0-9]+","_",title).strip("_").upper()[:42] or "PASTED_TASK")
    methods=_method_items(sections.get("methods",sections.get("stages","")))
    if not methods: methods=[]
    inputs=_items(sections.get("inputs",""));facts=_items(sections.get("known_facts",""))
    expected=_section_items(sections.get("expected_outputs",""));questions=_section_items(sections.get("report_questions",""))
    stop=_section_items(sections.get("stop_condition",""))
    required_explicit="required_capabilities" in sections
    any_explicit_capability_sections=any(k in sections for k in ("required_capabilities","optional_capabilities","not_required"))
    required=_capabilities(sections.get("required_capabilities",""))
    optional=_capabilities(sections.get("optional_capabilities",""))
    excluded=_capabilities(sections.get("not_required",""))
    if not any_explicit_capability_sections:
        lower_prompt=prompt.casefold()
        for cap,terms in CAPABILITY_NAMES.items():
            if cap in required:continue
            if CAPABILITY_REGISTRY.get(cap,{}).get("status")=="UNSUPPORTED" and any(term in lower_prompt for term in terms):optional.append(cap)
        if re.search(r"(?:not analyze|do not analyze|do not spend time on|не аналізувати|не досліджувати|не витрачати часу на)[^\n]{0,100}nk\.bin|nk\.bin[^\n]{0,100}(?:not analyze|do not analyze|не аналізувати|не досліджувати)",prompt,re.I):
            excluded.extend(["NK_BIN_ROM_PARSER","NK_BIN_MODULE_EXTRACTION"])
    # Explicit declarations are authoritative. Only infer from the METHOD body
    # when there is no REQUIRED CAPABILITIES section at all.
    if not required_explicit:
        mentioned=_capabilities("\n".join(methods))
        required=[cap for cap in mentioned if cap not in optional and cap not in excluded]
    required=[cap for cap in required if cap not in excluded]
    optional=[cap for cap in optional if cap not in required]
    plan,unsupported,optional_unsupported=_compile_plan(methods,expected,questions,stop,required_explicit)
    if not required_explicit:
        inferred={"SH4_DISASSEMBLE":"SH4_DISASSEMBLY","BUILD_CALL_GRAPH":"SH4_XREF_ANALYSIS","SH4_XREF":"SH4_XREF_ANALYSIS","STRING_XREF":"SH4_XREF_ANALYSIS","DATA_XREF":"SH4_XREF_ANALYSIS","IMPORT_XREF":"WINCE_PE_ORDINAL_IMPORTS","PE_ANALYZE":"PE_IMPORT_ANALYSIS"}
        operation_names=[x.get("operation") if isinstance(x,dict) else x for x in plan]
        required=list(dict.fromkeys(required+[inferred[x] for x in operation_names if x in inferred]))
    optional=[cap for cap in dict.fromkeys(optional) if cap not in required]
    from .tasks import CAPABILITY_REGISTRY,AVAILABLE_CAPABILITIES
    missing=[];partial=[];optional_missing=[]
    for cap in required:
        entry=CAPABILITY_REGISTRY.get(cap,{})
        if cap not in AVAILABLE_CAPABILITIES or entry.get("status")=="UNSUPPORTED": missing.append(cap)
        elif entry.get("status")=="PARTIAL": partial.append(cap)
    for cap in optional:
        if cap in excluded:continue
        entry=CAPABILITY_REGISTRY.get(cap,{})
        if cap not in AVAILABLE_CAPABILITIES or entry.get("status")=="UNSUPPORTED": optional_missing.append(cap)
    from .generic_runner import OPERATION_REGISTRY,compile_diagnostics,_method_fragments
    operation_capabilities=[]
    for entry in plan:
        operation=entry.get("operation") if isinstance(entry,dict) else entry
        for cap in OPERATION_REGISTRY.get(operation,{}).get("capabilities",[]):
            if cap not in operation_capabilities:operation_capabilities.append(cap)
            entry=CAPABILITY_REGISTRY.get(cap,{})
            if cap not in AVAILABLE_CAPABILITIES or entry.get("status")=="UNSUPPORTED":missing.append(cap)
            elif entry.get("status")=="PARTIAL":partial.append(cap)
    missing=list(dict.fromkeys(missing));partial=list(dict.fromkeys(partial))
    existing=Path(project_root)/"research"/"tasks"/task_id/"task.json"
    specialized=[]
    try:
        old=json.loads(existing.read_text(encoding="utf-8"))
        from .tasks import task_capability_status
        cap_status=task_capability_status(old)
        old_modules=list(old.get("analysis_modules",[]))
        if cap_status["can_run"] and "generic_research_runner" not in old_modules:specialized=old_modules
    except Exception: pass
    executor="SPECIALIZED_TASK_HANDLER" if specialized else "GENERIC_RESEARCH_RUNNER"
    if specialized:
        plan=[]
    status="SUPPORTED"
    if missing or unsupported: status="UNSUPPORTED"
    elif partial or optional_unsupported: status="PARTIAL"
    analysis_ops={op for op,row in OPERATION_REGISTRY.items() if row.get("implementation") not in {"csv.DictWriter","markdown_and_html_report","package_run","validated firmware/update corpus scope declaration","conditional SH4 evidence plan gate"}}
    operation_names=[x.get("operation") if isinstance(x,dict) else x for x in plan]
    if not specialized and not any(op in analysis_ops for op in operation_names) and not unsupported:unsupported=["No research instruction maps to a registered analysis operation."]
    can_run=bool(specialized or (any(op in analysis_ops for op in operation_names) and not missing and not unsupported))
    if not can_run: status="UNSUPPORTED"
    classifications=[]
    for block in methods:
        if not block or block==UNDEFINED:continue
        _,fragments=_method_fragments(block)
        classifications.extend({"instruction":x["text"],"classification":x["role"]} for x in fragments)
    classifications += [{"instruction":x,"classification":"STOP_CONDITION"} for x in stop]
    classifications += [{"instruction":x,"classification":"OUTPUT_FIELD"} for x in expected]
    diagnostics=compile_diagnostics(methods,plan,unsupported,missing)
    from .generic_runner import validate_execution_plan
    dry_run_validation=validate_execution_plan(plan,CAPABILITY_REGISTRY,AVAILABLE_CAPABILITIES)
    return {
      "task_id":task_id,"title":title,"research_question":_joined(_items(sections.get("research_question",""))),
      "inputs":inputs or [UNDEFINED],"known_facts":facts or [UNDEFINED],"methods":methods or [UNDEFINED],"stages":methods or _items(sections.get("stages","")) or [UNDEFINED],
      "required_capabilities":required,"optional_capabilities":optional,"not_required_capabilities":excluded,
      "missing_capabilities":missing,"partial_capabilities":partial,"optional_missing_capabilities":optional_missing,
      "unsupported_instructions":unsupported,"optional_unsupported_instructions":optional_unsupported,
      "unsupported_mandatory_instructions":unsupported,
      "instruction_classifications":classifications,
      "compile_diagnostics":diagnostics,"dry_run_validation":dry_run_validation,
      "execution_plan":plan,"executor":executor,"support_status":status,"can_run":can_run,
      "run_enabled":can_run,"application_version":COMPILER_VERSION,
      "analysis_modules":specialized or (["generic_research_runner"] if can_run else []),
      "stop_condition":stop or [UNDEFINED],"expected_outputs":expected or [UNDEFINED],"report_questions":questions or [UNDEFINED],
      "finding_status":_items(sections.get("finding_status","")) or [UNDEFINED],
      "estimated_workload":UNDEFINED,"required_capabilities_explicit":required_explicit,
      "compiler_schema_version":COMPILER_SCHEMA_VERSION,"compiler_version":COMPILER_VERSION,
      "compiler_fingerprint":COMPILER_FINGERPRINT,
      "application_version":COMPILER_VERSION,
      "original_prompt_sha256":hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    }

def _joined(items):return "\n".join(items) if items else UNDEFINED

def state_path(root):return Path(root)/"research"/"db_lab"/"task_lifecycle.json"
def read_state(root):
    try:return json.loads(state_path(root).read_text(encoding="utf-8"))
    except Exception:return {"auto_archive_mode":"after_success","tasks":{}}
def write_state(root,obj):
    p=state_path(root);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(".tmp");tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding="utf-8");tmp.replace(p)

def _manifest_prompt(task):
    rows=[f"TASK: {task.get('task_id','PASTED_TASK')}",f"TITLE: {task.get('title','')}"]
    question=task.get("research_question") or task.get("description")
    if question:rows.append(f"RESEARCH QUESTION: {question}")
    for section,key in (("REQUIRED CAPABILITIES:","required_capabilities"),("OPTIONAL CAPABILITIES:","optional_capabilities"),("NOT REQUIRED:","not_required_capabilities")):
        values=task.get(key) or []
        if values:rows.extend([section,*[f"- {x}" for x in values]])
    rows.append("METHOD:")
    for i,method in enumerate(task.get("methods") or [],1):
        method=str(method)
        rows.append(method if re.match(r"^\s*\d+[.)]\s+",method) else f"{i}. {method}")
    for section,key in (("EXPECTED OUTPUTS:","expected_outputs"),("REPORT MUST ANSWER:","report_questions"),("STOP CONDITION:","stop_conditions")):
        values=task.get(key) or []
        if values:rows.extend([section,*[f"- {x}" for x in values]])
    return "\n".join(rows)+"\n"

def refresh_stale_task_compilation(root,task_path,task):
    """Recompile old pasted-task metadata before the native task list uses it."""
    if (task.get("compiler_schema_version")==COMPILER_SCHEMA_VERSION and task.get("compiler_version")==COMPILER_VERSION and task.get("compiler_fingerprint")==COMPILER_FINGERPRINT):return task
    path=Path(task_path);source=path.parent/"ORIGINAL_TASK.txt"
    if not source.is_file():source=path.parent/"TASK.md"
    prompt=source.read_text(encoding="utf-8",errors="replace") if source.is_file() else _manifest_prompt(task)
    # This migration targets generic/pasted definitions; known specialized
    # handlers keep their own manifest contract.
    is_pasted=(task.get("executor")=="GENERIC_RESEARCH_RUNNER" or "generic_research_runner" in task.get("analysis_modules",[]) or bool(task.get("original_prompt_sha256")))
    if not is_pasted:return task
    preview=parse_prompt(prompt,Path(root))
    keys=("methods","required_capabilities","optional_capabilities","not_required_capabilities","missing_capabilities","partial_capabilities","optional_missing_capabilities","unsupported_instructions","optional_unsupported_instructions","unsupported_mandatory_instructions","instruction_classifications","compile_diagnostics","analysis_modules","executor","executor_mode","execution_plan","support_status","can_run","run_enabled","application_version","original_prompt_sha256","compiler_schema_version","compiler_version","compiler_fingerprint","plan_format","plan_schema_version","plan_sha256","strict_validation","scope_artifact_count","scope","patterns_count","controls_preview","controls_validation","outputs_preview","plan_preview_steps","strict_plan","strict_steps","strict_controls","strict_outputs","strict_report")
    updated=dict(task)
    for key in keys:updated[key]=preview.get(key)
    from .tasks import atomic_json
    atomic_json(path,updated)
    return updated
def set_lifecycle(root,task_id,state):
    obj=read_state(root);row=obj.setdefault("tasks",{}).setdefault(task_id,{})
    row["state"]=state;row["archived_at"]=datetime.now(timezone.utc).isoformat() if state=="archived" else None
    write_state(root,obj);return row
def maybe_auto_archive(root,task_id,status):
    obj=read_state(root);mode=obj.get("auto_archive_mode","after_success");status=(status or "").upper()
    if (mode=="after_success" and status in ("COMPLETE","COMPLETED")) or (mode=="after_terminal" and status in ("COMPLETE","COMPLETED","FAILED","CANCELLED","INTERRUPTED")):set_lifecycle(root,task_id,"archived")

def save_task(root,preview,prompt,revision_of=None):
    if preview.get("plan_format")=="NCDR_TASK_PLAN_V1":
        if preview.get("strict_validation",{}).get("status")!="PASS": raise ValueError("Strict plan validation failed: "+"; ".join(preview.get("validation_errors",[])))
        from .strict_plan import save_strict_task
        return save_strict_task(root,preview,prompt,revision_of)
    root=Path(root);tasks=root/"research"/"tasks";task_id=(revision_of or preview["task_id"]).upper();dest=tasks/task_id
    if dest.exists() and not revision_of:
        base=task_id;idx=2
        while (tasks/f"{base}_{idx}").exists():idx+=1
        task_id=f"{base}_{idx}";dest=tasks/task_id
    old=json.loads((dest/"task.json").read_text(encoding="utf-8")) if revision_of and (dest/"task.json").exists() else {}
    rev=int(old.get("task_revision",0))+1 if old else 1;dest.mkdir(parents=True,exist_ok=True)
    revdir=dest/"revisions";revdir.mkdir(exist_ok=True)
    template=root/"research"/"tasks"/"templates"/"custom"/"task.json"
    if not old and template.exists():old=json.loads(template.read_text(encoding="utf-8"))
    old.update({"task_id":task_id,"title":preview["title"],"description":preview["research_question"],"research_question":preview["research_question"],"input_artifacts":preview["inputs"],"known_facts":preview["known_facts"],"methods":preview["methods"],"stop_conditions":preview["stop_condition"],"expected_outputs":preview["expected_outputs"],"report_questions":preview["report_questions"],"required_capabilities":preview["required_capabilities"],"optional_capabilities":preview["optional_capabilities"],"not_required_capabilities":preview["not_required_capabilities"],"instruction_classifications":preview["instruction_classifications"],"compile_diagnostics":preview.get("compile_diagnostics",[]),"compiler_schema_version":preview["compiler_schema_version"],"compiler_version":preview["compiler_version"],"compiler_fingerprint":preview["compiler_fingerprint"],"analysis_modules":["generic_research_runner"] if preview["executor"]=="GENERIC_RESEARCH_RUNNER" and preview["can_run"] else preview.get("analysis_modules",[]),"executor":preview["executor"],"execution_plan":preview["execution_plan"],"unsupported_instructions":preview["unsupported_instructions"],"task_revision":rev,"original_prompt_sha256":preview["original_prompt_sha256"]})
    (dest/"TASK.md").write_text(f"# {preview['title']}\n\n{prompt}\n",encoding="utf-8")
    (dest/"ORIGINAL_TASK.txt").write_text(prompt,encoding="utf-8")
    manifest=dest/"task.json";manifest.write_text(json.dumps(old,indent=2,ensure_ascii=False),encoding="utf-8")
    (revdir/f"TASK_v{rev}.md").write_text((dest/"TASK.md").read_text(encoding="utf-8"),encoding="utf-8")
    (revdir/f"task_v{rev}.json").write_text(manifest.read_text(encoding="utf-8"),encoding="utf-8")
    (revdir/f"ORIGINAL_TASK_v{rev}.txt").write_text(prompt,encoding="utf-8")
    state=read_state(root);state.setdefault("tasks",{}).setdefault(task_id,{})["state"]="active";write_state(root,state)
    return {"task_id":task_id,"task_revision":rev,"task_path":str(dest/"TASK.md"),"manifest_path":str(manifest),"support_status":preview["support_status"],"can_run":preview["can_run"]}
