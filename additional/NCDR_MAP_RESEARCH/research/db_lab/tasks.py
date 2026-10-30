"""Task manifest validation and immutable run-directory utilities."""
from __future__ import annotations
import hashlib, json, os, platform, sqlite3, subprocess, sys, time, uuid, zipfile
from datetime import datetime
from pathlib import Path

APP_VERSION=os.environ.get("NCDR_APP_VERSION","Unknown")
TASK_KEYS={"task_id","title","description","research_question","input_artifacts","required_artifact_types","known_facts","analysis_modules","hypotheses_to_test","hypotheses_to_reject","methods","parameters","cpu_settings","gpu_settings","memory_limits","sample_strategy","full_scan_permission","checkpoint_interval","timeout","stop_conditions","expected_outputs","required_tables","required_logs","required_evidence","report_template","ChatGPT_summary_requirements","depends_on"}
SUPPORTED_MODULES={"project_inventory","artifact_scan","binary_search","binary_diff","db0_first_stage","foundation_audit","ui_audit","ncdx_native","map_reader_discovery","sh4_analysis_test","sh4_research_stack_test","generic_research_runner"}
EXECUTABLE_TASK_MODULES={"project_inventory","foundation_audit","ui_audit","ncdx_native","map_reader_discovery","sh4_analysis_test","sh4_research_stack_test","generic_research_runner"}
INVENTORY_COMPONENTS={"artifact_scan","binary_search","binary_diff"}
MODULE_CAPABILITIES={
    "project_inventory":["ARTIFACT_INVENTORY","SHA256_HASHING","BINARY_DIFF","REPORT_GENERATION","PACKAGE_VALIDATION"],
    "artifact_scan":["ARTIFACT_INVENTORY","SHA256_HASHING"],
    "binary_search":["BINARY_PATTERN_SEARCH"],
    "binary_diff":["BINARY_DIFF"],
    "db0_first_stage":["DB0_RECORD_VALIDATION","REPORT_GENERATION","PACKAGE_VALIDATION"],
    "foundation_audit":["DB0_RECORD_VALIDATION","DB_AWARE_DIFF","REPORT_GENERATION","PACKAGE_VALIDATION"],
    "ui_audit":["UI_BINDING_AUDIT","REPORT_GENERATION","PACKAGE_VALIDATION"],
    "ncdx_native":["ISO9660_READ","PE_HEADER_PARSE","FIRMWARE_INVENTORY","REPORT_GENERATION","PACKAGE_VALIDATION"],
    "map_reader_discovery":["PE_IMPORT_ANALYSIS","ASCII_UTF16_SCAN","FIRMWARE_BYTE_SCAN","DEPENDENCY_GRAPH","DB_HEADER_CORRELATION","REPORT_GENERATION","PACKAGE_VALIDATION","SH4_DISASSEMBLY","SH4_XREF_ANALYSIS","SH4_IMPORT_XREF","WINCE_PE_ORDINAL_IMPORTS","COREDLL_ORDINAL_RESOLUTION","NK_BIN_ROM_PARSER","NK_BIN_MODULE_EXTRACTION"],
    "sh4_analysis_test":["SH4_DISASSEMBLY","SH4_XREF_ANALYSIS","SH4_IMPORT_XREF","WINCE_PE_ORDINAL_IMPORTS","REPORT_GENERATION","PACKAGE_VALIDATION"],
    "sh4_research_stack_test":["SH4_DISASSEMBLY","SH4_XREF_ANALYSIS","SH4_IMPORT_XREF","WINCE_PE_ORDINAL_IMPORTS","NK_BIN_ROM_PARSER","REPORT_GENERATION","PACKAGE_VALIDATION"],
    "generic_research_runner":[],
}
CAPABILITY_REGISTRY={
    "CORPUS_BINARY_PATTERN_SEARCH":{"status":"SUPPORTED","implementation":"generic_runner catalog-backed streaming byte search","validation":"synthetic binary pattern fixtures; immutable catalog inputs"},
    "MULTI_ARTIFACT_SCOPE":{"status":"SUPPORTED","implementation":"generic_runner read-only SQLite artifact catalog resolver","validation":"scope filters catalog file rows by corpus, firmware, PE, folder or artifact class"},
    "POSITIVE_CONTROL_VALIDATION":{"status":"SUPPORTED","implementation":"generic_runner required-pattern control scan","validation":"dependent operations halt when a required cataloged control hit is absent"},
    "PE_FILE_OFFSET_MAPPING":{"status":"SUPPORTED","implementation":"artifact_lab.binary_analysis.pe_file_offset_to_rva","validation":"raw section boundaries checked before RVA/VA mapping"},
    "CORPUS_CODE_XREF_ANALYSIS":{"status":"SUPPORTED","implementation":"generic_runner with sh4_analysis.disassemble_module and normalized xrefs","validation":"SH4 PE hits retain xref/function/call/string evidence"},
    "CORPUS_STRING_SEARCH":{"status":"SUPPORTED","implementation":"generic_runner catalog-backed ASCII and UTF-16LE byte search","validation":"synthetic encoding fixtures"},
    "CORPUS_SYMBOL_SEARCH":{"status":"SUPPORTED","implementation":"artifact_lab.binary_analysis.pe_analyze imports/exports plus substring matching","validation":"synthetic PE import/export records"},
    "GUID_RELATIONSHIP_AGGREGATION":{"status":"SUPPORTED","implementation":"generic_runner BUILD_RELATIONSHIP_TABLE","validation":"aggregates source hits and related xref/string/symbol evidence"},
    "ARTIFACT_RANKING":{"status":"SUPPORTED","implementation":"generic_runner weighted evidence score","validation":"scores cite each evidence contribution"},
    "SH4_DISASSEMBLY":{"status":"SUPPORTED","implementation":"sh4_analysis.disassemble_module","validation":"NAVIMAIN.EXE entry-point decode"},
    "SH4_XREF_ANALYSIS":{"status":"SUPPORTED","implementation":"sh4_analysis direct and register-indirect xrefs, PC-relative literal resolution, delay-slot annotations and bounded recursive call graph","validation":"NAVIMAIN.EXE: three literal-backed JSR targets and delay slots resolve; graph traversal is bounded to four levels and reaches three active levels before the fourth frontier has no outgoing calls"},
    "SH4_WINCE_ABI_ANALYSIS":{"status":"SUPPORTED","implementation":"semantic_analysis.sh4_wince_abi","validation":"Bounded Windows CE SH4 model: R4 this pointer for member calls, R5-R7 remaining register arguments, stack spill area, R0 return"},
    "MSVC_DECORATED_SYMBOL_PARSE":{"status":"SUPPORTED","implementation":"semantic_analysis.parse_msvc_decorated_symbol","validation":"Common MSVC member symbol subset with class, method, member/static, return and parameter types"},
    "RVA_DATA_READ":{"status":"SUPPORTED","implementation":"semantic_analysis.read_rva_bytes","validation":"PE section mapping and strict raw-file bounds"},
    "GUID_INTERPRETATION":{"status":"SUPPORTED","implementation":"semantic_analysis.windows_guid_interpret","validation":"Windows GUID field byte ordering; format validity separated from semantic evidence"},
    "SH4_VALUE_FLOW_TRACE":{"status":"SUPPORTED","implementation":"semantic_analysis.trace_local_value_flow","validation":"Bounded local register copy/store/load patterns; unresolved flows remain explicit"},
    "SH4_IMPORT_XREF":{"status":"PARTIAL","implementation":"sh4_analysis.get_import_xrefs","validation":"IAT literal + JSR register tracking; other indirect forms remain unresolved"},
    "WINCE_PE_ORDINAL_IMPORTS":{"status":"SUPPORTED","implementation":"artifact_lab.binary_analysis.pe_analyze","validation":"ordinal, DLL and IAT records"},
    "COREDLL_ORDINAL_RESOLUTION":{"status":"UNSUPPORTED","implementation":"wince_rom.parse_nkbin","validation":"no structurally validated local COREDLL export table"},
    "NK_BIN_ROM_PARSER":{"status":"SUPPORTED","implementation":"wince_rom.parse_nkbin","validation":"validated ROMHDR/TOC/E32/O32 synthetic fixture; target firmware evaluated independently"},
    "NK_BIN_MODULE_EXTRACTION":{"status":"UNSUPPORTED","implementation":"wince_rom.safe_extract_module","validation":"fail-closed until boundaries and format validate"},
}
AVAILABLE_CAPABILITIES={"ARTIFACT_INVENTORY","SHA256_HASHING","BINARY_DIFF","REPORT_GENERATION","PACKAGE_VALIDATION","BINARY_PATTERN_SEARCH","DB0_RECORD_VALIDATION","DB_AWARE_DIFF","UI_BINDING_AUDIT","ISO9660_READ","PE_HEADER_PARSE","FIRMWARE_INVENTORY","PE_IMPORT_ANALYSIS","ASCII_UTF16_SCAN","FIRMWARE_BYTE_SCAN","DEPENDENCY_GRAPH","DB_HEADER_CORRELATION","SH4_DISASSEMBLY","SH4_XREF_ANALYSIS","SH4_IMPORT_XREF","WINCE_PE_ORDINAL_IMPORTS","NK_BIN_ROM_PARSER","SH4_WINCE_ABI_ANALYSIS","MSVC_DECORATED_SYMBOL_PARSE","RVA_DATA_READ","GUID_INTERPRETATION","SH4_VALUE_FLOW_TRACE","CORPUS_BINARY_PATTERN_SEARCH","MULTI_ARTIFACT_SCOPE","POSITIVE_CONTROL_VALIDATION","PE_FILE_OFFSET_MAPPING","CORPUS_CODE_XREF_ANALYSIS","CORPUS_STRING_SEARCH","CORPUS_SYMBOL_SEARCH","GUID_RELATIONSHIP_AGGREGATION","ARTIFACT_RANKING"}

def task_capability_status(task):
    if task.get("executor_mode")=="STRICT_PLAN":
        required=list(task.get("required_capabilities") or [])
        missing=[x for x in required if x not in AVAILABLE_CAPABILITIES or CAPABILITY_REGISTRY.get(x,{}).get("status")=="UNSUPPORTED"]
        invalid=task.get("strict_validation",{}).get("status")=="FAIL" or task.get("scope_artifact_count",1)==0
        partial=[x for x in required if CAPABILITY_REGISTRY.get(x,{}).get("status")=="PARTIAL"]
        status="UNSUPPORTED" if invalid or missing else ("PARTIAL" if partial else "SUPPORTED")
        return {"status":status,"required":required,"available":[x for x in required if x in AVAILABLE_CAPABILITIES],"missing":missing,"partial":partial,"missing_modules":[],"optional":[],"optional_missing":[],"unsupported_instructions":[],"executor":"GENERIC_RESEARCH_RUNNER","can_run":not invalid and not missing}
    modules=list(task.get("analysis_modules") or [])
    required=list(task.get("required_capabilities") or [])
    if not required:
        for module in modules: required.extend(MODULE_CAPABILITIES.get(module,["MODULE:"+module]))
    required=list(dict.fromkeys(required))
    missing=[x for x in required if x not in AVAILABLE_CAPABILITIES or CAPABILITY_REGISTRY.get(x,{}).get("status")=="UNSUPPORTED"]
    partial=[x for x in required if CAPABILITY_REGISTRY.get(x,{}).get("status")=="PARTIAL"]
    missing_modules=[x for x in modules if x not in EXECUTABLE_TASK_MODULES and not ("project_inventory" in modules and x in INVENTORY_COMPONENTS)]
    runnable=any(x in EXECUTABLE_TASK_MODULES for x in modules)
    if not runnable or missing or missing_modules: status="UNSUPPORTED"
    elif partial: status="PARTIAL"
    else: status="SUPPORTED"
    return {"status":status,"required":required,"available":[x for x in required if x in AVAILABLE_CAPABILITIES],"missing":missing,"partial":partial,"missing_modules":missing_modules,"optional":list(task.get("optional_capabilities",[])),"optional_missing":list(task.get("optional_missing_capabilities",[])),"unsupported_instructions":list(task.get("unsupported_instructions",[])),"executor":"GENERIC_RESEARCH_RUNNER" if "generic_research_runner" in modules else (task.get("executor") or "SPECIALIZED_TASK_HANDLER"),"can_run":runnable and not missing_modules and not missing}

def implementation_status(modules):
    modules=list(modules or []); implemented=sum(1 for module in modules if module in SUPPORTED_MODULES)
    if modules and implemented==len(modules): return "SUPPORTED"
    if implemented: return "PARTIAL"
    return "UNSUPPORTED"

def atomic_json(path,obj):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True); temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding="utf-8"); temp.replace(path)

def task_hash(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def environment(project_root):
    import multiprocessing
    from .acceleration.backend import Backend
    def command(args):
        try: return subprocess.check_output(args,text=True,stderr=subprocess.DEVNULL).strip()
        except Exception: return "unavailable"
    mem=command(["sysctl","-n","hw.memsize"])
    logical=command(["sysctl","-n","hw.logicalcpu"])
    try: mem_gb=round(int(mem)/1024**3,2)
    except Exception: mem_gb=None
    git=command(["git","-C",str(project_root),"rev-parse","HEAD"])
    return {"os":platform.platform(),"machine":platform.machine(),"cpu":platform.processor() or platform.machine(),"logical_cores":int(logical) if logical.isdigit() else multiprocessing.cpu_count(),"ram_gb":mem_gb,"gpu_backend":Backend().report(),"python":sys.version,"git_commit":git if git!="unavailable" else None,"application_version":APP_VERSION}

def create_run(project_root,task_path,task,inputs):
    root=Path(project_root); runs=root/"research"/"runs"
    prefs=root/"research"/"db_lab"/"preferences.json"
    if prefs.exists():
        try:
            selected=json.loads(prefs.read_text()).get("runs_location")
            if selected: runs=Path(selected).expanduser()
        except Exception: pass
    start=datetime.now().astimezone(); run_id=os.environ.get("NCDR_RUN_ID") or str(uuid.uuid4())
    run=runs/(start.strftime("%Y-%m-%d_%H-%M-%S")+"_"+task.get("task_id","CUSTOM")); run.mkdir(parents=True,exist_ok=False)
    for d in ("inputs","logs","data","evidence","plots","checkpoints"): (run/d).mkdir()
    import shutil
    shutil.copyfile(task_path,run/"TASK.md")
    (run/"task.json").write_bytes(Path(task_path).with_name("task.json").read_bytes())
    plan_source=Path(task_path).parent/"TASK_PLAN.yaml"
    if task.get("executor_mode")=="STRICT_PLAN" and plan_source.is_file():shutil.copyfile(plan_source,run/"TASK_PLAN.yaml")
    try:
        task_revision=int(task.get("task_revision",1))
        original=Path(task_path).with_name("ORIGINAL_TASK.txt")
        if original.is_file(): shutil.copyfile(original,run/"ORIGINAL_TASK.txt")
    except Exception: task_revision=1
    env=environment(root); atomic_json(run/"environment.json",env)
    meta={"run_id":run_id,"task_id":task.get("task_id","CUSTOM"),"task_revision":task_revision,"plan_format":task.get("plan_format"),"plan_schema_version":task.get("plan_schema_version"),"plan_sha256":task.get("plan_sha256"),"project_root":str(root),"start_time":start.isoformat(),"end_time":None,"duration_seconds":None,"status":"QUEUED","application_version":APP_VERSION,"git_commit":env.get("git_commit"),"process":{"pid":os.getpid(),"run_id":run_id,"task_id":task.get("task_id","CUSTOM"),"start_time":start.isoformat(),"state":"RUNNING"},"input_artifacts":inputs,"input_hashes":{x.get("artifact_id"):x.get("sha256") for x in inputs},"task_sha256":task_hash(task_path),"parameters":task.get("parameters",{}),"backend":{"requested":task.get("cpu_settings",{}).get("backend","AUTO"),"selected":"CPU"},"workers":task.get("cpu_settings",{}).get("workers",1),"checkpoints":[],"warnings":[],"errors":[],"summary":{}}
    atomic_json(run/"run.json",meta)
    return run,meta,env

def finish_run(run,meta,status,summary,warnings=None,errors=None):
    end=datetime.now().astimezone(); start=datetime.fromisoformat(meta["start_time"])
    meta.update({"end_time":end.isoformat(),"duration_seconds":round((end-start).total_seconds(),3),"status":status,"summary":summary,"warnings":warnings or [],"errors":errors or []})
    if isinstance(meta.get("process"),dict): meta["process"].update({"state":status,"end_time":end.isoformat()})
    atomic_json(Path(run)/"run.json",meta)

def register_run(project_root,run_path,meta):
    """Index a completed immutable run for the native Runs page and summary."""
    from .db_concurrency import register_run_with_retry
    root=Path(project_root)
    register_run_with_retry(root/"research"/"db_lab"/"analysis.sqlite",(meta.get("run_id"),meta.get("task_id"),meta.get("status"),meta.get("start_time"),meta.get("end_time"),str(run_path),json.dumps(meta.get("summary",{}),ensure_ascii=False)))
    # A definition is archived only after the completed run has been durably registered.
    from .task_authoring import maybe_auto_archive
    maybe_auto_archive(root,meta.get("task_id",""),meta.get("status",""))

def build_run_history(project_root):
    root=Path(project_root); rows=[]
    runs=root/"research"/"runs"
    prefs=root/"research"/"db_lab"/"preferences.json"
    if prefs.is_file():
        try:
            selected=json.loads(prefs.read_text(encoding="utf-8")).get("runs_location")
            if selected: runs=Path(selected).expanduser()
        except Exception: pass
    if not runs.is_dir(): return rows
    # The run JSON is authoritative for process lifecycle. Older app versions
    # could update it to INTERRUPTED/FAILED without refreshing analysis.sqlite.
    # Find only registry rows still claiming an active state and reconcile
    # those rows as their run records are read below.
    stale_registry_ids=set(); db=root/"research"/"db_lab"/"analysis.sqlite"
    if db.is_file():
        try:
            from .db_concurrency import connect_database
            conn=connect_database(db,readonly=True)
            stale_registry_ids={r[0] for r in conn.execute("SELECT run_id FROM run_tasks WHERE status IN ('QUEUED','RUNNING','FINALIZING','PACKAGING')")}
            conn.close()
        except Exception: stale_registry_ids=set()
    for run in sorted(runs.glob("*"),key=lambda p:p.name,reverse=True):
        meta_path=run/"run.json"
        if not meta_path.is_file(): continue
        try: meta=json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception: continue
        if meta.get("status") in ("QUEUED","RUNNING","FINALIZING","PACKAGING"):
            proc=meta.get("process") if isinstance(meta.get("process"),dict) else {}
            pid=proc.get("pid"); alive=False
            try:
                if pid: os.kill(int(pid),0); alive=True
            except (ProcessLookupError,ValueError,TypeError): alive=False
            except PermissionError: alive=True
            if not alive:
                ended=datetime.now().astimezone().isoformat(); started=meta.get("start_time")
                meta.update({"status":"INTERRUPTED","end_time":ended,"errors":list(meta.get("errors",[]))+["PROCESS_EXITED_BEFORE_FINALIZATION"]})
                try:
                    if started: meta["duration_seconds"]=round((datetime.fromisoformat(ended)-datetime.fromisoformat(started)).total_seconds(),3)
                except Exception: pass
                proc.update({"state":"INTERRUPTED","end_time":ended});meta["process"]=proc
                atomic_json(meta_path,meta)
        if meta.get("run_id") in stale_registry_ids and meta.get("status") not in ("QUEUED","RUNNING","FINALIZING","PACKAGING"):
            try: register_run(root,run,meta)
            except Exception: pass
        summary=meta.get("summary") or {}; package=summary.get("package") or {}; local_pack=run/"CHATGPT_PACKAGE.zip"
        pack_path=Path(package.get("external_path") or package.get("path")) if (package.get("external_path") or package.get("path")) else local_pack
        pack_ready=bool(package.get("status")=="READY" or (pack_path.is_file() and pack_path.stat().st_size>0) or (local_pack.is_file() and local_pack.stat().st_size>0))
        if pack_ready and package.get("status") not in ("INCOMPLETE","SKIPPED"):
            package_state="READY"
            if meta.get("status") in ("RUNNING","FINALIZING","PACKAGING"):
                meta["status"]="COMPLETED"
        elif package.get("status")=="SKIPPED": package_state="SKIPPED"
        else: package_state="MISSING"
        result_status=meta.get("status","UNKNOWN")
        status=result_status
        if status=="COMPLETE" or (meta.get("end_time") and status not in ("FAILED","INTERRUPTED")):
            status="COMPLETED"
        duration=meta.get("duration_seconds")
        rows.append({"run_id":meta.get("run_id",run.name),"task_id":meta.get("task_id",run.name),"status":status,"result_status":result_status,"start_time":meta.get("start_time"),"end_time":meta.get("end_time"),"duration_seconds":duration,"run_path":str(run),"summary_json":json.dumps(summary,ensure_ascii=False),"main_result":summary.get("result") or summary.get("status") or result_status or summary.get("candidate",{}).get("module") or summary.get("artifact_counts",{}),"package_status":package_state,"package_path":str(pack_path) if pack_path.exists() else "","report_path":str(run/"REPORT.html") if (run/"REPORT.html").exists() else (str(run/"REPORT.md") if (run/"REPORT.md").exists() else ""),"task_path":str(run/"TASK.md") if (run/"TASK.md").exists() else ""})
    return rows

def capability_test(task_path,project_root,navimain_path,nkbin_path=None):
    """Short read-only capability check; does not invoke map-reader discovery."""
    from .sh4_analysis import disassemble_module,render_report
    from .wince_rom import parse_nkbin
    result=disassemble_module(navimain_path,entry_rva=0x1e24,instruction_limit=4096)
    if result.get("entry_point_file_offset")!=0x1224: raise RuntimeError("NAVIMAIN_ENTRY_MAPPING_FAILED")
    if not result.get("entry_instructions"): raise RuntimeError("SH4_ENTRY_DISASSEMBLY_EMPTY")
    if not result.get("entry_function"): raise RuntimeError("SH4_ENTRY_CODE_REGION_NOT_IDENTIFIED")
    pe_imports=result.get("imports",[])
    if not pe_imports: raise RuntimeError("PE_IMPORTS_MISSING")
    if any(x.get("ordinal") is not None and (x.get("name") is not None or x.get("status")!="UNRESOLVED" or not x.get("dll") or not x.get("iat_rva")) for x in result.get("ordinal_imports",[])): raise RuntimeError("ORDINAL_IMPORT_MODEL_INVALID")
    if not any(x.get("xref_type")=="import_call" for x in result.get("xrefs",[])): raise RuntimeError("SH4_IMPORT_XREF_EMPTY")
    if not any(x.get("xref_type")=="string" for x in result.get("xrefs",[])): raise RuntimeError("SH4_STRING_XREF_EMPTY")
    import tempfile,threading
    from .db_concurrency import connect_database,register_run_with_retry
    with tempfile.TemporaryDirectory(prefix="ncdr-sqlite-concurrency-") as tmp:
        db=Path(tmp)/"analysis.sqlite"
        writer=connect_database(db); writer.execute("CREATE TABLE run_tasks(run_id TEXT PRIMARY KEY,task_id TEXT,status TEXT,start_time TEXT,end_time TEXT,run_path TEXT,summary_json TEXT)");writer.execute("INSERT INTO run_tasks VALUES('seed','SEED','COMPLETED','now','now',?,'{}')",(tmp,));writer.commit();writer.close()
        reader=connect_database(db,readonly=True);reader.execute("BEGIN");reader.execute("SELECT * FROM run_tasks").fetchall()
        registered=register_run_with_retry(db,("capability-test","SH4_ANALYSIS_CAPABILITY_TEST","COMPLETED","now","now",tmp,"{}"));reader.commit();reader.close()
        if not registered: raise RuntimeError("SQLITE_CONCURRENT_REGISTRATION_FAILED")
    report=render_report(result)
    target=Path(project_root)/"research"/"db_lab"/"capability-tests"/"SH4_ANALYSIS_CAPABILITY_TEST"
    target.mkdir(parents=True,exist_ok=True)
    rom=parse_nkbin(nkbin_path) if nkbin_path else None
    metrics={"module":result["module"],"entry_rva":result["entry_point_rva"],"entry_file_offset":result["entry_point_file_offset"],"instruction_count":len(result["instructions"]),"entry_instruction_count":len(result["entry_instructions"]),"import_count":len(pe_imports),"ordinal_import_count":len(result["ordinal_imports"]),"direct_call_xrefs":sum(x.get("xref_type")=="call" for x in result["xrefs"]),"branch_xrefs":sum(x.get("xref_type")=="branch" for x in result["xrefs"]),"import_xrefs":len([x for x in result["xrefs"] if x.get("xref_type")=="import_call"]),"string_xrefs":len([x for x in result["xrefs"] if x.get("xref_type")=="string"]),"sqlite_concurrent_registration":"PASS","backend":result["backend"],"nkbin":rom}
    (target/"REPORT.md").write_text(report+f"\n## SQLite concurrency\n\nRead-only transaction active during writer registration: PASS.\n",encoding="utf-8")
    (target/"analysis.json").write_text(json.dumps(metrics,indent=2),encoding="utf-8")
    import zipfile
    package=target/"CHATGPT_PACKAGE.zip"
    with zipfile.ZipFile(package,"w",zipfile.ZIP_DEFLATED) as z:
        z.write(target/"REPORT.md","REPORT.md");z.write(target/"analysis.json","analysis.json")
    return {"status":"PASS","report_path":str(target/"REPORT.md"),"analysis_path":str(target/"analysis.json"),"package_path":str(package),"analysis":metrics,"nkbin":rom}

def run_sh4_analysis_capability_test(task_path,project_root,navimain_path,nkbin_path=None):
    """Run the short SH4 validation as a normal, registered, packageable task."""
    task=json.loads(Path(task_path).read_text(encoding="utf-8"))
    run,meta,_=create_run(project_root,task_path,task,[]);meta["status"]="RUNNING";atomic_json(run/"run.json",meta);register_run(project_root,run,meta)
    try:
        result=capability_test(task_path,project_root,navimain_path,nkbin_path)
        import shutil
        shutil.copyfile(result["report_path"],run/"REPORT.md")
        shutil.copyfile(result["analysis_path"],run/"data"/"analysis.json")
        summary={"status":"PASS","module":result["analysis"]["module"],"entry_rva":result["analysis"]["entry_rva"],"entry_file_offset":result["analysis"]["entry_file_offset"],"instruction_count":result["analysis"]["instruction_count"],"import_count":result["analysis"]["import_count"],"ordinal_import_count":result["analysis"]["ordinal_import_count"],"import_xrefs":result["analysis"]["import_xrefs"],"string_xrefs":result["analysis"]["string_xrefs"],"sqlite_concurrent_registration":result["analysis"]["sqlite_concurrent_registration"],"nkbin_status":(result.get("nkbin") or {}).get("status"),"capability_test_report":result["report_path"]}
        (run/"CHATGPT_SUMMARY.txt").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        finish_run(run,meta,"COMPLETED",summary)
        register_run(project_root,run,meta)
        package=package_run(run)
        summary["package"]={"status":package.get("status"),"path":str(run/"CHATGPT_PACKAGE.zip") if package.get("status")=="READY" else ""}
        finish_run(run,meta,"COMPLETED",summary)
        register_run(project_root,run,meta)
        package=package_run(run)
        summary["package"]={"status":package.get("status"),"path":str(run/"CHATGPT_PACKAGE.zip") if package.get("status")=="READY" else ""}
        finish_run(run,meta,"COMPLETED",summary);register_run(project_root,run,meta)
        return {"status":"COMPLETED","run_path":str(run),"report_path":str(run/"REPORT.md"),"package_path":summary["package"]["path"],"summary":summary}
    except Exception as exc:
        finish_run(run,meta,"FAILED",{},errors=[str(exc)])
        try: register_run(project_root,run,meta)
        except Exception: pass
        raise

def run_sh4_research_stack_test(task_path,project_root,navimain_path,nkbin_path):
    """Registered short validation of SH4 xrefs and structural NK.BIN parsing."""
    import csv,hashlib,shutil
    from .sh4_analysis import (disassemble_module,get_function_at,get_callers,
        get_callees,get_code_xrefs_to,get_data_xrefs_to,get_string_xrefs,
        get_import_xrefs,render_report)
    from .wince_rom import parse_nkbin,self_test_fixture,write_module_inventory
    task=json.loads(Path(task_path).read_text(encoding="utf-8")); root=Path(project_root)
    inputs=[]
    for p,kind in ((Path(navimain_path),"pe_executable"),(Path(nkbin_path),"firmware_image")):
        h=hashlib.sha256(p.read_bytes()).hexdigest();inputs.append({"artifact_id":h[:24],"source_path":str(p),"source_type":kind,"sha256":h,"size":p.stat().st_size})
    run,meta,_=create_run(root,task_path,task,inputs);meta["status"]="RUNNING";atomic_json(run/"run.json",meta);register_run(root,run,meta)
    try:
        analysis=disassemble_module(navimain_path,entry_rva=0x1e24,instruction_limit=4096)
        if analysis.get("status")!="SUPPORTED" or analysis.get("entry_point_file_offset")!=0x1224 or not analysis.get("entry_instructions"):
            raise RuntimeError("NAVIMAIN_ENTRY_DISASSEMBLY_FAILED")
        calls=[x for x in analysis["normalized_xrefs"] if x["xref_type"]=="CALL"]
        branches=[x for x in analysis["normalized_xrefs"] if x["xref_type"]=="BRANCH"]
        imports=get_import_xrefs(analysis);strings=get_string_xrefs(analysis)
        entry_fn=get_function_at(analysis,0x1e24)
        callers=get_callers(analysis,0x1e24);callees=get_callees(analysis,0x1e24)
        code_targets=get_code_xrefs_to(analysis,0x1e24)
        data_refs=[x for x in analysis["normalized_xrefs"] if x["xref_type"]=="DATA"]
        data_targets=[ref for target in {x.get("target_rva") for x in data_refs} for ref in get_data_xrefs_to(analysis,target)]
        string_to_function=all(x.get("function_rva") is not None for x in strings)
        import_to_function=all(x.get("function_rva") is not None for x in imports)
        if not calls and not branches: raise RuntimeError("SH4_CODE_XREFS_NOT_RECOVERED")
        if not imports: raise RuntimeError("SH4_IMPORT_XREFS_NOT_RECOVERED")
        if not strings: raise RuntimeError("SH4_STRING_XREFS_NOT_RECOVERED")
        rom_fixture=self_test_fixture()
        if rom_fixture.get("status")!="VALIDATED" or "ROMHDR" not in rom_fixture.get("structures",[]):
            raise RuntimeError("NK_BIN_PARSER_FIXTURE_FAILED")
        rom=parse_nkbin(nkbin_path)
        if rom.get("status")=="VALIDATED" and any(m.get("validation_status")!="VALIDATED" for m in rom.get("modules",[])):
            raise RuntimeError("NK_BIN_VALIDATED_RESULT_CONTAINS_INVALID_MODULE")
        write_module_inventory(rom,run/"data"/"nk_modules.csv")
        with (run/"data"/"coredll_ordinal_map.csv").open("w",newline="",encoding="utf-8") as f:
            csv.DictWriter(f,fieldnames=["ordinal","name","RVA","source","confidence"]).writeheader()
        report=["# SH4 research stack test","", "Status: PASS", "",f"NAVIMAIN.EXE SHA256: `{inputs[0]['sha256']}`",f"NK.BIN SHA256: `{inputs[1]['sha256']}`",f"Entry RVA `0x1E24` maps to file offset `0x{analysis['entry_point_file_offset']:X}`; decoded {len(analysis['entry_instructions'])} entry-region instructions.","", "## SH4 cross-references", f"- Direct calls: {len(calls)}",f"- Branches: {len(branches)}",f"- Import references: {len(imports)} ({'all' if import_to_function else 'some'} mapped to candidate code regions; boundary confidence LOW)",f"- String references: {len(strings)} ({'all' if string_to_function else 'some'} mapped to candidate code regions; boundary confidence LOW)",f"- Candidate entry code region: `{entry_fn['start_rva']:#x}..{entry_fn['end_rva']:#x}` ({entry_fn['confidence']})" if entry_fn else "- Entry code region: no function boundary claimed; instruction-level xrefs retained.",f"- API checks: callers={len(callers)}, callees={len(callees)}, code-to-entry={len(code_targets)}, data references={len(data_targets)}", "", "## NK.BIN parser", "- Parser capability fixture: PASS; validated ROM signature, ROMHDR, MODULE/FILES TOC, E32 and O32 boundaries.",f"- This firmware image result: {rom.get('status')}.",f"- Validated modules: {rom.get('module_count') if rom.get('module_count') is not None else 0}; files: {rom.get('file_count') if rom.get('file_count') is not None else 0}.",f"- Structures validated in this image: {', '.join(rom.get('rom_structures_validated',[])) or 'none'}.","- COREDLL recovered: YES" if rom.get("coredll_present") else "- COREDLL recovered: NO.","- No modules extracted; image tables did not establish extractable module boundaries." if not rom.get("modules") else "- Module sections inventoried; no PE reconstruction was attempted.",rom.get("evidence", ""),"", "No MZ carving or generic ordinal mapping was used."]
        (run/"REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
        analysis_out={"entry_point":analysis["entry_point_rva"],"entry_file_offset":analysis["entry_point_file_offset"],"entry_instruction_count":len(analysis["entry_instructions"]),"entry_function":entry_fn,"normalized_xrefs":analysis["normalized_xrefs"],"xref_counts":{"calls":len(calls),"branches":len(branches),"imports":len(imports),"strings":len(strings),"data":len(data_targets)},"xref_api_checks":{"callers":len(callers),"callees":len(callees),"code_xrefs_to_entry":len(code_targets),"data_xrefs_to":len(data_targets),"string_xrefs_linked_to_functions":string_to_function,"import_xrefs_linked_to_functions":import_to_function},"rom_parser_fixture":rom_fixture,"nkbin":rom}
        atomic_json(run/"data"/"analysis.json",analysis_out)
        summary={"status":"PASS","navimain_xref_validation":"PASS","entry_rva":analysis["entry_point_rva"],"entry_file_offset":analysis["entry_point_file_offset"],"xref_counts":analysis_out["xref_counts"],"nk_parser_capability":"SUPPORTED","nkbin_image_result":rom.get("status"),"rom_structures_validated":rom.get("rom_structures_validated",[]),"modules_identified":len(rom.get("modules",[])),"modules_extracted":len(rom.get("extracted_modules",[])),"coredll_found":bool(rom.get("coredll_present")),"coredll_ordinals_resolved":0,"parser_fixture":"PASS"}
        (run/"CHATGPT_SUMMARY.txt").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        finish_run(run,meta,"COMPLETED",summary);register_run(root,run,meta)
        package=package_run(run)
        summary["package"]={"status":package.get("status"),"path":str(run/"CHATGPT_PACKAGE.zip") if package.get("status")=="READY" else ""}
        if package.get("status")!="READY": raise RuntimeError("CHATGPT_PACKAGE_NOT_READY")
        finish_run(run,meta,"COMPLETED",summary);register_run(root,run,meta)
        package=package_run(run)
        return {"status":"PASS","run_path":str(run),"report_path":str(run/"REPORT.md"),"package_path":str(run/"CHATGPT_PACKAGE.zip"),"summary":summary,"package_validation":package}
    except Exception as exc:
        finish_run(run,meta,"FAILED",{},errors=[str(exc)])
        try: register_run(root,run,meta)
        except Exception: pass
        raise

def emit_progress(stage_id,stage_name,stage_index,stage_count,units_completed,units_total,unit_name,started_at):
    elapsed=max(0.0,time.time()-started_at); fraction=(units_completed/units_total) if units_total else None
    rate=(units_completed/elapsed) if elapsed>=1 and units_completed>0 else None
    eta=(max(0.0,(units_total-units_completed)/rate) if rate and units_total and units_total>units_completed else None)
    confidence="MEDIUM" if eta is not None and elapsed>=3 and units_completed>=2 else "INSUFFICIENT_DATA"
    event={"stage_id":stage_id,"stage_name":stage_name,"stage_index":stage_index,"stage_count":stage_count,"units_completed":units_completed,"units_total":units_total,"unit_name":unit_name,"progress_fraction":fraction,"elapsed_seconds":round(elapsed,2),"processing_rate":round(rate,3) if rate is not None else None,"eta_seconds":round(eta) if eta is not None else None,"eta_confidence":confidence}
    print("[PROGRESS]"+json.dumps(event,ensure_ascii=False,separators=(",",":")),flush=True)
    return event

def write_logs(run,main="",error="",performance=""):
    for name,text in (("main.log",main),("errors.log",error),("performance.log",performance)):
        p=Path(run)/"logs"/name
        with p.open("a",encoding="utf-8") as f: f.write(text)

def package_run(run,required=None):
    run=Path(run); package=run/"CHATGPT_PACKAGE.zip"
    try: recorded=json.loads((run/"run.json").read_text(encoding="utf-8")).get("project_root")
    except Exception: recorded=None
    project=Path(recorded).expanduser() if recorded else run.parent.parent.parent
    prefs=project/"research"/"db_lab"/"preferences.json"
    if prefs.exists():
        try:
            settings=json.loads(prefs.read_text(encoding="utf-8"))
            if settings.get("auto_package") is False:
                return {"path":"","status":"SKIPPED","missing":[],"verification_errors":[],"members":0}
        except Exception: pass
    required=required or ["TASK.md","task.json","run.json","REPORT.md","CHATGPT_SUMMARY.txt","PACKAGE_MANIFEST.json"]
    required_set=set(required)
    include=["TASK.md","task.json","run.json","environment.json","REPORT.md","REPORT.html","CHATGPT_SUMMARY.txt"]
    for folder in ("data","evidence","plots","logs"):
        for p in (run/folder).rglob("*"):
            if p.is_file() and p.name.upper()!="NK.BIN" and (p.stat().st_size<=4*1024*1024 or str(p.relative_to(run)) in required_set): include.append(str(p.relative_to(run)))
    include=list(dict.fromkeys(rel for rel in include if (run/rel).is_file() and rel!="PACKAGE_MANIFEST.json"))
    metadata={}
    try:
        meta=json.loads((run/"run.json").read_text(encoding="utf-8"))
        metadata={"run_id":meta.get("run_id"),"task_id":meta.get("task_id"),"start_time":meta.get("start_time"),"end_time":meta.get("end_time"),"status":meta.get("status"),"application_version":meta.get("application_version"),"task_sha256":meta.get("task_sha256")}
    except Exception: pass
    members=[]
    for rel in include:
        p=run/rel; h=hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda:f.read(4*1024*1024),b""): h.update(chunk)
        members.append({"path":rel,"size":p.stat().st_size,"sha256":h.hexdigest()})
    manifest={"format":"NCDR_PACKAGE_MANIFEST_V1","created_at":datetime.now().astimezone().isoformat(),"run":metadata,"members":members,"manifest_note":"The manifest excludes itself; its SHA256 is recorded in the ZIP comment."}
    manifest_bytes=json.dumps(manifest,indent=2,ensure_ascii=False).encode("utf-8")
    manifest_sha=hashlib.sha256(manifest_bytes).hexdigest()
    with zipfile.ZipFile(package,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        z.comment=("NCDR-PACKAGE-MANIFEST-SHA256:"+manifest_sha).encode("ascii")
        for rel in include: z.write(run/rel,rel)
        z.writestr("PACKAGE_MANIFEST.json",manifest_bytes)
    verification_errors=[]
    with zipfile.ZipFile(package,"r") as z:
        bad=z.testzip(); names=set(z.namelist())
        try:
            packed=z.read("PACKAGE_MANIFEST.json"); loaded=json.loads(packed)
            if hashlib.sha256(packed).hexdigest()!=manifest_sha: verification_errors.append("manifest digest mismatch")
            if z.comment.decode("ascii","replace")!="NCDR-PACKAGE-MANIFEST-SHA256:"+manifest_sha: verification_errors.append("zip comment manifest digest mismatch")
            for item in loaded["members"]:
                payload=z.read(item["path"])
                if len(payload)!=item["size"] or hashlib.sha256(payload).hexdigest()!=item["sha256"]: verification_errors.append("member integrity failure: "+item["path"])
        except Exception as exc: verification_errors.append("manifest validation failed: "+str(exc))
    missing=[p for p in required if p not in names]
    status="READY" if package.exists() and package.stat().st_size>0 and not bad and not missing and not verification_errors else "INCOMPLETE"
    result={"path":str(package),"size":package.stat().st_size if package.exists() else 0,"status":status,"bad_member":bad,"missing":missing,"verification_errors":verification_errors,"manifest_sha256":manifest_sha,"members":len(members)}
    if prefs.exists():
        try:
            destination=json.loads(prefs.read_text(encoding="utf-8")).get("packages_location")
            if destination and status=="READY":
                import shutil
                folder=Path(destination).expanduser(); folder.mkdir(parents=True,exist_ok=True); external=folder/(run.name+"_CHATGPT_PACKAGE.zip"); shutil.copy2(package,external); result["external_path"]=str(external)
        except Exception as exc: result["external_copy_warning"]=str(exc)
    return result
