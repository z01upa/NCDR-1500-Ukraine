"""Safe, deterministic NCDR_TASK_PLAN_V1 parser and validator."""
from __future__ import annotations
import hashlib, json, re
from pathlib import Path

FORMAT="NCDR_TASK_PLAN_V1"
SCHEMA_VERSION=1
TOP_FIELDS={"format","task_id","title","description","scope","patterns","artifacts","known_facts","variables","steps","controls","outputs","report","stop","presentation"}
STEP_FIELDS={"id","op","params","input","where","condition"}
OUTPUT_TYPES={"csv","report_md","chatgpt_package"}
COND_OPS={"eq","ne","in","not_in","contains","exists"}
OUTPUT_FIELDS={"CORPUS_BINARY_PATTERN_SEARCH":{"hits"},"POSITIVE_CONTROL":{"hits"},"POSITIVE_CONTROL_VALIDATION":{"hits"},"PE_FILE_OFFSET_TO_RVA":{"mappings"},"PE_FILE_OFFSET_MAPPING":{"mappings"},"CORPUS_CODE_XREF_ANALYSIS":{"analyses"},"CORPUS_STRING_SEARCH":{"hits"},"CORPUS_SYMBOL_SEARCH":{"hits"},"BUILD_RELATIONSHIP_TABLE":{"rows"},"RANK_ARTIFACTS":{"rows"},"LOAD_ARTIFACT":{"artifact"},"PE_ANALYZE":{"analysis"},"READ_RVA_BYTES":{"bytes"}}
REF_RE=re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)\.([A-Za-z][A-Za-z0-9_-]*)$")

class PlanError(ValueError):
    def __init__(self,issues):
        self.issues=issues if isinstance(issues,list) else [issues]
        super().__init__("; ".join(self.issues))

def is_strict_plan(text):
    return bool(re.search(r"(?m)^\s*format\s*:\s*NCDR_TASK_PLAN_V1\s*(?:#.*)?$",text))

def _yaml_text(text):
    lines=text.splitlines()
    if lines and lines[0].lstrip().startswith("```"):lines=lines[1:]
    if lines and lines[-1].strip()=="```":lines=lines[:-1]
    return "\n".join(lines)

def _check_value(v,path="$",depth=0,count=None):
    if count is None:count=[0]
    count[0]+=1
    if depth>64 or count[0]>10000:raise PlanError("Plan exceeds YAML structure limits")
    if v is None or type(v) in (str,int,bool):return
    if isinstance(v,list):
        for i,x in enumerate(v):_check_value(x,f"{path}[{i}]",depth+1,count)
    elif isinstance(v,dict):
        for k,x in v.items():
            if not isinstance(k,str):raise PlanError(f"{path}: mapping keys must be strings")
            _check_value(x,f"{path}.{k}",depth+1,count)
    else:raise PlanError(f"{path}: unsupported YAML scalar type {type(v).__name__}")

def parse_yaml(text):
    if len(text.encode("utf-8"))>1024*1024:raise PlanError("Plan exceeds 1 MiB")
    from .vendor import yaml
    from .vendor.yaml.events import AliasEvent
    class Loader(yaml.SafeLoader):
        def compose_node(self,parent,index):
            if self.check_event(AliasEvent):raise PlanError("YAML aliases are not supported")
            return super().compose_node(parent,index)
        def construct_mapping(self,node,deep=False):
            out={}
            for kn,vn in node.value:
                k=self.construct_object(kn,deep=deep)
                if not isinstance(k,str):raise PlanError("Mapping keys must be strings")
                if k in out:raise PlanError(f"Duplicate key: {k}")
                out[k]=self.construct_object(vn,deep=deep)
            return out
    try:result=yaml.load(_yaml_text(text),Loader=Loader)
    except PlanError:raise
    except yaml.YAMLError as e:
        mark=getattr(e,"problem_mark",None);loc=f" at line {mark.line+1}, column {mark.column+1}" if mark else ""
        raise PlanError("Invalid YAML"+loc+": "+str(e).splitlines()[0]) from e
    _check_value(result)
    return result

def _i18n(value,path,required=False):
    if value is None and not required:return {}
    if isinstance(value,str):return {"en":value}
    if not isinstance(value,dict) or not value or set(value)-{"uk","en"} or any(not isinstance(x,str) for x in value.values()):raise PlanError(f"{path} must be text or a map of uk/en strings")
    return value

def _scope(root,scope):
    if scope is None:return {"kind":"all_corpus"},[],[]
    if not isinstance(scope,dict) or set(scope)-{"corpus","extensions","artifacts"}:raise PlanError("scope contains unknown fields")
    if "artifacts" in scope:
        names=scope["artifacts"]
        if not isinstance(names,list) or not names or any(not isinstance(x,str) or not x for x in names):raise PlanError("scope.artifacts must be a non-empty list of filenames")
        internal={"kind":"all_corpus","artifacts":names}
    else:
        corpus=scope.get("corpus")
        kinds={"firmware":"firmware","pe":"pe","all":"all_corpus"}
        if corpus not in kinds:raise PlanError("scope.corpus must be firmware, pe, or all")
        internal={"kind":kinds[corpus]}
    exts=scope.get("extensions",[])
    if not isinstance(exts,list) or any(not isinstance(x,str) or not re.fullmatch(r"[A-Za-z0-9]{1,8}",x) for x in exts):raise PlanError("scope.extensions must be a list of file extensions")
    if exts:internal["extensions"]=[x.upper().lstrip(".") for x in exts]
    from .generic_runner import _catalog_artifacts
    rows,missing=_catalog_artifacts(root,internal,exts)
    if "artifacts" in scope:
        wanted={x.casefold() for x in scope["artifacts"]}
        rows=[x for x in rows if Path(x["source_path"]).name.casefold() in wanted]
        found={Path(x["source_path"]).name.casefold() for x in rows}
        absent=sorted(wanted-found)
    else:absent=[]
    return internal,rows,absent

def _condition(node,path):
    if not isinstance(node,dict) or len(node)!=1 or next(iter(node)) not in ("all","any"):raise PlanError(f"{path} must contain exactly one of all or any")
    group=next(iter(node));rows=node[group]
    if not isinstance(rows,list) or not rows:raise PlanError(f"{path}.{group} must be a non-empty list")
    for i,row in enumerate(rows):
        if not isinstance(row,dict) or set(row)!={"field","op","value"}:raise PlanError(f"{path}.{group}[{i}] requires field, op, and value")
        if not isinstance(row["field"],str) or not re.fullmatch(r"[A-Za-z0-9_.]+",row["field"]):raise PlanError(f"{path}.{group}[{i}].field is invalid")
        if row["op"] not in COND_OPS:raise PlanError(f"{path}.{group}[{i}].op is unsupported: {row['op']}")

def condition_matches(row,node):
    if not node:return True
    group,clauses=next(iter(node.items()))
    def check(c):
        got=row
        for part in c["field"].split("."):got=got.get(part) if isinstance(got,dict) else None
        want=c["value"];op=c["op"]
        if op=="eq":return got==want
        if op=="ne":return got!=want
        if op=="in":return got in want if isinstance(want,list) else False
        if op=="not_in":return got not in want if isinstance(want,list) else False
        if op=="contains":return want in got if isinstance(got,(str,list,dict)) else False
        if op=="exists":return (got is not None)==bool(want)
        return False
    result=[check(x) for x in clauses]
    return all(result) if group=="all" else any(result)

def _safe_filename(name):
    return isinstance(name,str) and bool(name) and len(name)<=180 and name not in (".","..") and not name.startswith(".") and not re.search(r"[/\\\x00]",name)

def _refs(value):
    if isinstance(value,str):
        m=REF_RE.fullmatch(value)
        return [m.groups()] if m else []
    if isinstance(value,list):return sum((_refs(x) for x in value),[])
    if isinstance(value,dict):return sum((_refs(x) for x in value.values()),[])
    return []

def validate_plan(text,root,language="uk"):
    plan=parse_yaml(text);issues=[]
    if not isinstance(plan,dict):raise PlanError("Plan root must be a mapping")
    for field in sorted(set(plan)-TOP_FIELDS):issues.append("Unknown field: "+field)
    for field in ("format","task_id","title","steps"):
        if field not in plan:issues.append("Missing field: "+field)
    if plan.get("format")!=FORMAT:issues.append("format must be "+FORMAT)
    tid=plan.get("task_id")
    if tid is not None and (not isinstance(tid,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",tid)):issues.append("task_id must contain 1-64 letters, digits, underscores or hyphens")
    try:title=_i18n(plan.get("title"),"title",True)
    except PlanError as e:issues.extend(e.issues);title={}
    try:description=_i18n(plan.get("description"),"description")
    except PlanError as e:issues.extend(e.issues);description={}
    steps=plan.get("steps") if isinstance(plan.get("steps"),list) else []
    if not steps:issues.append("steps must be a non-empty list")
    patterns=plan.get("patterns",{})
    if not isinstance(patterns,dict):issues.append("patterns must be a mapping");patterns={}
    compiled={}
    for name,spec in patterns.items():
        if not isinstance(name,str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}",name):issues.append(f"Invalid pattern name: {name}");continue
        if not isinstance(spec,dict) or set(spec)!={"type","value"}:issues.append(f"Pattern {name} requires type and value");continue
        kind,value=spec.get("type"),spec.get("value")
        if kind not in {"hex","ascii","utf16le"} or not isinstance(value,str) or not value:issues.append(f"Pattern {name} must be a non-empty hex/ascii/utf16le string");continue
        try:
            if kind=="hex":
                if len(value)%2 or not re.fullmatch(r"[0-9A-Fa-f]+",value):raise ValueError()
                raw=bytes.fromhex(value)
            else:raw=value.encode("ascii" if kind=="ascii" else "utf-16le")
        except (ValueError,UnicodeEncodeError):issues.append(f"Pattern {name} contains invalid {kind}");continue
        compiled[name]={"type":kind,"value":value,"raw_hex":raw.hex()}
    from .generic_runner import OPERATION_REGISTRY
    from .tasks import CAPABILITY_REGISTRY,AVAILABLE_CAPABILITIES
    normalized=[];byid={};caps=[]
    for i,step in enumerate(steps):
        p=f"steps[{i}]"
        if not isinstance(step,dict):issues.append(f"{p} must be a mapping");continue
        for field in sorted(set(step)-STEP_FIELDS):issues.append(f"Unknown field: {p}.{field}")
        sid,op=step.get("id"),step.get("op")
        if not isinstance(sid,str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}",sid):issues.append(f"{p}.id is invalid");continue
        if sid in byid:issues.append("Duplicate step id: "+sid)
        byid[sid]=i
        if not isinstance(op,str) or op not in OPERATION_REGISTRY:issues.append("Unknown operation: "+str(op));continue
        if not OPERATION_REGISTRY[op].get("implementation"):issues.append("Operation has no registered implementation: "+op)
        params=step.get("params",{})
        if not isinstance(params,dict):issues.append(f"{p}.params must be a mapping");params={}
        pats=params.get("patterns",[])
        if isinstance(pats,str):pats=[pats]
        if not isinstance(pats,list):issues.append(f"{p}.params.patterns must be a list")
        else:
            for pat in pats:
                if pat not in compiled:issues.append("Unknown pattern: "+str(pat))
        for refstep,field in _refs(params):
            if refstep not in byid:issues.append("Unknown dependency: "+refstep)
            elif field not in OUTPUT_FIELDS.get(steps[byid[refstep]].get("op"),set()):issues.append(f"Unknown output: {refstep}.{field}")
            elif byid[refstep]>=i:issues.append(f"Dependency must refer to an earlier step: {refstep}.{field}")
        inputref=step.get("input")
        if inputref is not None:
            match=REF_RE.fullmatch(inputref) if isinstance(inputref,str) else None
            if not match:issues.append(f"{p}.input must be a step.output reference")
            else:
                refstep,field=match.groups()
                if refstep not in byid:issues.append("Unknown dependency: "+refstep)
                elif field not in OUTPUT_FIELDS.get(steps[byid[refstep]].get("op"),set()):issues.append("Unknown output: "+inputref)
                elif byid[refstep]>=i:issues.append(f"Dependency must refer to an earlier step: {inputref}")
        for fld in ("where","condition"):
            if fld in step:
                try:_condition(step[fld],f"{p}.{fld}")
                except PlanError as e:issues.extend(e.issues)
        for c in OPERATION_REGISTRY[op].get("capabilities",[]):
            if c not in caps:caps.append(c)
        normalized.append({"id":sid,"op":op,"params":dict(params),"input":inputref,"where":step.get("where"),"condition":step.get("condition")})
    controls=plan.get("controls",[])
    if not isinstance(controls,list):issues.append("controls must be a list");controls=[]
    clean_controls=[]
    for i,c in enumerate(controls):
        if not isinstance(c,dict) or set(c)-{"op","artifact","patterns","on_fail"}:issues.append(f"controls[{i}] has invalid fields");continue
        if c.get("op")!="PATTERN_PRESENT":issues.append("Unknown control operation: "+str(c.get("op")));continue
        if c.get("on_fail","STOP_INVALID")!="STOP_INVALID":issues.append(f"controls[{i}].on_fail must be STOP_INVALID")
        if not isinstance(c.get("artifact"),str) or not c.get("artifact"):issues.append(f"controls[{i}].artifact is required")
        pats=c.get("patterns")
        if not isinstance(pats,list) or not pats:issues.append(f"controls[{i}].patterns must be a non-empty list")
        else:
            for pat in pats:
                if pat not in compiled:issues.append("Unknown pattern: "+str(pat))
        clean_controls.append(dict(c))
    try:scope,scope_rows,scope_missing=_scope(root,plan.get("scope"))
    except PlanError as e:issues.extend(e.issues);scope={"kind":"all_corpus"};scope_rows=[];scope_missing=[]
    if plan.get("scope") and not scope_rows:issues.append("EMPTY_ARTIFACT_SCOPE: Не знайдено артефактів для заданої області пошуку.")
    for name in scope_missing:issues.append("Required artifact not found: "+name)
    if any(x.get("op")=="CORPUS_BINARY_PATTERN_SEARCH" for x in normalized) and not clean_controls:issues.append("Positive controls are required for corpus binary searches")
    for c in clean_controls:
        if c.get("artifact"):
            try:_,found,_=_scope(root,{"artifacts":[c["artifact"]]})
            except PlanError:found=[]
            if not found:issues.append("Required artifact not found: "+c["artifact"])
    controls_validation=[]
    if clean_controls:
        from .generic_runner import _catalog_artifacts,_scan_patterns
        for control in clean_controls:
            rows,_=_catalog_artifacts(root,{"kind":"all_corpus","artifacts":[control["artifact"]]})
            required=set(control.get("patterns",[]));found=set()
            raw_patterns=[(pid,bytes.fromhex(compiled[pid]["raw_hex"])) for pid in required if pid in compiled]
            for row in rows:
                _,hits=_scan_patterns(row["source_path"],raw_patterns)
                found.update(hit["pattern_id"] for hit in hits)
            passed=bool(required) and required.issubset(found)
            controls_validation.append({"artifact":control["artifact"],"required_patterns":sorted(required),"found_patterns":sorted(found),"status":"PASS" if passed else "FAIL"})
            if not passed:issues.append("POSITIVE_CONTROL_FAILED: "+control["artifact"]+" missing "+", ".join(sorted(required-found)))
    for s in plan.get("stop",[]) if isinstance(plan.get("stop",[]),list) else []:
        if not isinstance(s,(str,dict)):issues.append("stop entries must be text or maps")
    outputs=plan.get("outputs",[])
    if not isinstance(outputs,list):issues.append("outputs must be a list");outputs=[]
    output_ids=set()
    for i,o in enumerate(outputs):
        if not isinstance(o,dict) or set(o)-{"id","type","source","filename"}:issues.append(f"outputs[{i}] has invalid fields");continue
        if o.get("type") not in OUTPUT_TYPES:issues.append("Unsupported output type: "+str(o.get("type")));continue
        if not _safe_filename(o.get("filename")):issues.append("Invalid output filename: "+str(o.get("filename")))
        if o.get("id"):
            if o["id"] in output_ids:issues.append("Duplicate output id: "+o["id"])
            output_ids.add(o["id"])
        if o.get("type")=="csv":
            m=REF_RE.fullmatch(o.get("source","")) if isinstance(o.get("source"),str) else None
            if not m:issues.append("Invalid output source: "+str(o.get("source")))
            else:
                sid,field=m.groups()
                if sid not in byid:issues.append("Unknown dependency: "+sid)
                elif field not in OUTPUT_FIELDS.get(steps[byid[sid]].get("op"),set()):issues.append("Unknown output: "+o["source"])
    report=plan.get("report",{}) or {}
    if not isinstance(report,dict) or set(report)-{"questions"}:issues.append("report may contain only questions")
    questions=report.get("questions",[]) if isinstance(report,dict) else []
    if not isinstance(questions,list):issues.append("report.questions must be a list");questions=[]
    for i,q in enumerate(questions):
        if not isinstance(q,dict) or set(q)-{"id","text","source"}:issues.append(f"report.questions[{i}] has invalid fields");continue
        try:_i18n(q.get("text"),f"report.questions[{i}].text",True)
        except PlanError as e:issues.extend(e.issues)
        src=q.get("source",{});sid=src.get("step") if isinstance(src,dict) else None
        if sid not in byid:issues.append("Unknown dependency: "+str(sid))
        else:
            field=(src.get("filter") or {}).get("output","hits")
            if field not in OUTPUT_FIELDS.get(steps[byid[sid]].get("op"),set()):issues.append(f"Unknown output: {sid}.{field}")
    if not plan.get("scope") and any(s.get("op") in {"CORPUS_BINARY_PATTERN_SEARCH","CORPUS_STRING_SEARCH","CORPUS_SYMBOL_SEARCH"} for s in normalized):issues.append("Missing field: scope")
    if any(o.get("type")=="report_md" for o in outputs) and "REPORT_GENERATION" not in caps:caps.append("REPORT_GENERATION")
    if any(o.get("type")=="chatgpt_package" for o in outputs) and "PACKAGE_VALIDATION" not in caps:caps.append("PACKAGE_VALIDATION")
    missing=[c for c in caps if c not in AVAILABLE_CAPABILITIES or CAPABILITY_REGISTRY.get(c,{}).get("status")=="UNSUPPORTED"]
    for c in missing:issues.append("Missing required capability: "+c)
    if issues:raise PlanError(issues)
    title_text=title.get(language) or title.get("en") or next(iter(title.values()))
    desc_text=description.get(language) or description.get("en") or next(iter(description.values()),"")
    partial=any(CAPABILITY_REGISTRY.get(c,{}).get("status")=="PARTIAL" for c in caps)
    authoring=__import__(__package__+".task_authoring",fromlist=["COMPILER_SCHEMA_VERSION","COMPILER_VERSION","COMPILER_FINGERPRINT"])
    preview={"plan":plan,"plan_format":FORMAT,"plan_schema_version":SCHEMA_VERSION,"task_id":plan["task_id"].upper(),"title":title_text,"title_i18n":title,"description":desc_text,"description_i18n":description,"scope":scope,"scope_artifact_count":len(scope_rows),"scope_artifacts":[{"filename":x.get("filename"),"source_path":x.get("source_path")} for x in scope_rows[:50]],"patterns_count":len(compiled),"controls_preview":clean_controls,"controls_validation":controls_validation,"outputs_preview":outputs,"plan_preview_steps":normalized,"patterns":compiled,"steps":normalized,"controls":clean_controls,"outputs":outputs,"report":report,"required_capabilities":caps,"missing_capabilities":[],"support_status":"PARTIAL" if partial else "SUPPORTED","executor":"GENERIC_RESEARCH_RUNNER","executor_mode":"STRICT_PLAN","analysis_modules":["generic_research_runner"],"can_run":bool(normalized),"run_enabled":bool(normalized),"strict_validation":{"status":"PASS","issues":[]},"unsupported_instructions":[],"original_prompt_sha256":hashlib.sha256(text.encode("utf-8")).hexdigest(),"plan_sha256":hashlib.sha256(text.encode("utf-8")).hexdigest(),"compiler_schema_version":authoring.COMPILER_SCHEMA_VERSION,"compiler_version":authoring.COMPILER_VERSION,"compiler_fingerprint":authoring.COMPILER_FINGERPRINT}
    preview["execution_plan"]=to_task(preview,text)["execution_plan"]
    return preview

def to_task(preview,text):
    p=preview["patterns"];strict=preview["plan"];ops=[]
    for c in preview["controls"]:
        ids=c["patterns"]
        ops.append({"operation":"POSITIVE_CONTROL","parameters":{"pattern_ids":ids,"patterns":[{"pattern_id":x,"raw_hex":p[x]["raw_hex"]} for x in ids],"control_artifact":c["artifact"],"artifact_scope":{"kind":"all_corpus","artifacts":[c["artifact"]]}},"control":True})
    for s in preview["steps"]:
        params=dict(s["params"]);ids=params.pop("patterns",None)
        if ids is not None:
            if isinstance(ids,str):ids=[ids]
            params["pattern_ids"]=ids;params["patterns"]=[{"pattern_id":x,"raw_hex":p[x]["raw_hex"]} for x in ids]
        params.setdefault("artifact_scope",preview["scope"])
        if preview["scope"].get("extensions"):params.setdefault("file_type_filters",preview["scope"]["extensions"])
        ops.append({"operation":s["op"],"parameters":params,"strict_step_id":s["id"],"strict_input":s.get("input"),"strict_where":s.get("where"),"strict_condition":s.get("condition"),"strict_original_params":s["params"]})
    if any(o["type"]=="report_md" for o in preview["outputs"]) or preview["report"].get("questions"):ops.append({"operation":"GENERATE_REPORT","parameters":{"strict":True}})
    if any(o["type"]=="chatgpt_package" for o in preview["outputs"]):ops.append({"operation":"PACKAGE_RESULTS","parameters":{}})
    digest=hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {"task_id":preview["task_id"],"title":preview["title"],"description":preview["description"],"presentation":{"uk":{"title":preview["title_i18n"].get("uk",preview["title_i18n"].get("en","")),"description":preview["description_i18n"].get("uk",preview["description_i18n"].get("en",""))},"en":{"title":preview["title_i18n"].get("en",preview["title_i18n"].get("uk","")),"description":preview["description_i18n"].get("en",preview["description_i18n"].get("uk",""))}},"research_question":preview["description"],"input_artifacts":[],"known_facts":strict.get("known_facts",[]),"methods":[],"parameters":{"patterns":[{"pattern_id":k,"raw_hex":v["raw_hex"]} for k,v in p.items()]},"expected_outputs":[o.get("filename",o["type"]) for o in preview["outputs"]],"report_questions":[],"analysis_modules":["generic_research_runner"],"executor":"GENERIC_RESEARCH_RUNNER","executor_mode":"STRICT_PLAN","plan_format":FORMAT,"plan_schema_version":SCHEMA_VERSION,"compiler_schema_version":preview["compiler_schema_version"],"compiler_version":preview["compiler_version"],"compiler_fingerprint":preview["compiler_fingerprint"],"plan_sha256":digest,"strict_plan":strict,"strict_plan_yaml":text,"strict_scope":preview["scope"],"strict_steps":preview["steps"],"strict_controls":preview["controls"],"controls_validation":preview.get("controls_validation",[]),"strict_outputs":preview["outputs"],"strict_report":preview["report"],"required_capabilities":preview["required_capabilities"],"execution_plan":ops,"task_revision":1,"original_prompt_sha256":digest}

def preview_text(text,root,language="uk"):
    try:return validate_plan(text,Path(root),language)
    except PlanError as e:return {"plan_format":FORMAT,"plan_schema_version":SCHEMA_VERSION,"executor":"GENERIC_RESEARCH_RUNNER","executor_mode":"STRICT_PLAN","support_status":"UNSUPPORTED","can_run":False,"run_enabled":False,"strict_validation":{"status":"FAIL","issues":e.issues},"validation_errors":e.issues,"unsupported_instructions":[],"required_capabilities":[],"missing_capabilities":[]}

def save_strict_task(root,preview,text,revision_of=None):
    root=Path(root);tasks=root/"research"/"tasks";base=(revision_of or preview["task_id"]).upper();task_id=base;dest=tasks/task_id
    if dest.exists() and not revision_of:
        n=2
        while (tasks/f"{base}_{n}").exists():n+=1
        task_id=f"{base}_{n}";dest=tasks/task_id
    old={}
    if revision_of and (dest/"task.json").is_file():
        try:old=json.loads((dest/"task.json").read_text(encoding="utf-8"))
        except Exception:old={}
    rev=int(old.get("task_revision",0))+1 if old else 1
    task=to_task(preview,text);task["task_id"]=task_id;task["task_revision"]=rev
    dest.mkdir(parents=True,exist_ok=True);revdir=dest/"revisions";revdir.mkdir(exist_ok=True)
    (dest/"TASK_PLAN.yaml").write_text(text,encoding="utf-8");(dest/"ORIGINAL_TASK.txt").write_text(text,encoding="utf-8")
    (dest/"TASK.md").write_text(f"# {preview['title']}\n\nStrict plan format: {FORMAT}. See TASK_PLAN.yaml for the exact plan.\n",encoding="utf-8")
    (dest/"task.json").write_text(json.dumps(task,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    (revdir/f"TASK_PLAN_v{rev}.yaml").write_text(text,encoding="utf-8");(revdir/f"task_v{rev}.json").write_text(json.dumps(task,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");(revdir/f"ORIGINAL_TASK_v{rev}.txt").write_text(text,encoding="utf-8")
    from .task_authoring import read_state,write_state
    state=read_state(root);state.setdefault("tasks",{}).setdefault(task_id,{})["state"]="active";write_state(root,state)
    return {"task_id":task_id,"task_revision":rev,"task_path":str(dest/"TASK.md"),"manifest_path":str(dest/"task.json"),"plan_path":str(dest/"TASK_PLAN.yaml"),"plan_sha256":task["plan_sha256"],"support_status":preview["support_status"],"can_run":preview["can_run"]}
