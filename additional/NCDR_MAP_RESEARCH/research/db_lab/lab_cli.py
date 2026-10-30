"""Local command bridge used by the native SwiftUI application."""
from __future__ import annotations
import argparse,json,sqlite3,os,plistlib
from pathlib import Path
if not os.environ.get("NCDR_APP_VERSION"):
    _info=Path(__file__).resolve().parent/"macos"/"build"/"NCDR RE LAB.app"/"Contents"/"Info.plist"
    try:os.environ["NCDR_APP_VERSION"]=str(plistlib.loads(_info.read_bytes())["CFBundleShortVersionString"])
    except Exception:os.environ["NCDR_APP_VERSION"]="Unknown"
from .artifact_lab.catalog import ArtifactCatalog
from .artifact_lab.diff import compare_directories
from .project_inventory import ensure_task,run_project_inventory

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument("command",choices=("add","search","list","compare","inventory","task","new-task","task-author","rebuild-package","foundation-audit","ui-audit","ncdx-import","map-reader-discovery","sh4-analysis")); ap.add_argument("--language",choices=("uk","en"),default="uk"); ap.add_argument("--project-root",type=Path,required=True); ap.add_argument("--path",type=Path); ap.add_argument("--source-type",default="generic_binary"); ap.add_argument("--query",default=""); ap.add_argument("--mode",default="auto"); ap.add_argument("--baseline",default=""); ap.add_argument("--experiment",default=""); ap.add_argument("--task",type=Path); ap.add_argument("--task-id",default="CUSTOM"); ap.add_argument("--run-dir",type=Path); ap.add_argument("--operation",default="preview"); ap.add_argument("--state",default="active"); ap.add_argument("--revision-of",default=""); ap.add_argument("--archive-mode",default=""); ap.add_argument("--dry-run",action="store_true"); a=ap.parse_args(argv)
    project=a.project_root.resolve(); dbpath=project/"research"/"db_lab"/"analysis.sqlite"
    if a.command=="inventory":
        print(json.dumps(run_project_inventory(project),default=str)); return
    if a.command=="foundation-audit":
        from .foundation_audit import run_foundation_audit
        print(json.dumps(run_foundation_audit(project),default=str)); return
    if a.command=="ui-audit":
        from .ui_audit import run_ui_audit
        print(json.dumps(run_ui_audit(project),default=str)); return
    if a.command=="ncdx-import":
        from .ncdx_native import run_ncdx
        print(json.dumps(run_ncdx(project),default=str,ensure_ascii=False)); return
    if a.command=="map-reader-discovery":
        from .map_reader_discovery import run_map_reader_discovery
        print(json.dumps(run_map_reader_discovery(project),default=str,ensure_ascii=False)); return
    if a.command=="rebuild-package":
        if not a.run_dir: ap.error("--run-dir is required")
        from .tasks import package_run
        print(json.dumps(package_run(a.run_dir),default=str)); return
    if a.command=="task":
        if not a.task: ap.error("--task is required")
        task=json.loads(a.task.read_text())
        from .task_authoring import refresh_stale_task_compilation
        task=refresh_stale_task_compilation(project,a.task,task)
        if task.get("executor_mode")=="STRICT_PLAN":
            from .strict_plan import validate_plan,PlanError
            plan_file=a.task.parent/"TASK_PLAN.yaml"
            try:
                if not plan_file.is_file():raise PlanError("STRICT_PLAN_MISSING")
                strict=validate_plan(plan_file.read_text(encoding="utf-8"),project,a.language)
                if strict.get("scope_artifact_count",0)==0:raise PlanError("EMPTY_ARTIFACT_SCOPE: Не знайдено артефактів для заданої області пошуку.")
                if task.get("plan_sha256")!=__import__("hashlib").sha256(plan_file.read_bytes()).hexdigest():raise PlanError("STRICT_PLAN_SHA_MISMATCH")
            except PlanError as exc:
                print(json.dumps({"status":"VALIDATION_FAILED","validation_errors":exc.issues,"error_code":"EMPTY_ARTIFACT_SCOPE" if any("EMPTY_ARTIFACT_SCOPE" in x for x in exc.issues) else "STRICT_PLAN_INVALID"},ensure_ascii=False));return
        if a.dry_run:
            if task.get("executor_mode")=="STRICT_PLAN":
                from .generic_runner import validate_strict_task
                print(json.dumps(validate_strict_task(a.task,project,a.language),ensure_ascii=False));return
            print(json.dumps({"status":"FAIL","issues":["DRY_RUN_REQUIRES_STRICT_PLAN"]},ensure_ascii=False));return
        modules=task.get("analysis_modules",[])
        from .tasks import SUPPORTED_MODULES
        unsupported=[m for m in modules if m not in SUPPORTED_MODULES]
        if "generic_research_runner" in modules and not unsupported:
            from .generic_runner import run_generic_research_task
            print(json.dumps(run_generic_research_task(a.task,project),default=str,ensure_ascii=False));return
        if "project_inventory" in modules and not unsupported:
            print(json.dumps(run_project_inventory(project),default=str)); return
        if "foundation_audit" in modules and not unsupported:
            from .foundation_audit import run_foundation_audit
            print(json.dumps(run_foundation_audit(project),default=str)); return
        if "ui_audit" in modules and not unsupported:
            from .ui_audit import run_ui_audit
            print(json.dumps(run_ui_audit(project),default=str)); return
        if "ncdx_native" in modules and not unsupported:
            from .ncdx_native import run_ncdx
            print(json.dumps(run_ncdx(project),default=str,ensure_ascii=False)); return
        if "map_reader_discovery" in modules and not unsupported:
            from .map_reader_discovery import run_map_reader_discovery
            print(json.dumps(run_map_reader_discovery(project),default=str,ensure_ascii=False)); return
        if "sh4_analysis_test" in modules and not unsupported:
            from .tasks import run_sh4_analysis_capability_test
            roots=[project/"research"/"runs",project/"research"/"db_lab"/"runs"]
            navimain=next((p for base in roots if base.is_dir() for p in base.rglob("NAVIMAIN.EXE") if p.is_file()),None)
            nkbin=next((p for base in roots if base.is_dir() for p in base.rglob("NK.BIN") if p.is_file()),None)
            if not navimain: print(json.dumps({"status":"INPUT_MISSING","error_code":"NAVIMAIN_NOT_FOUND"}));return
            print(json.dumps(run_sh4_analysis_capability_test(a.task,project,navimain,nkbin),default=str,ensure_ascii=False));return
        if "sh4_research_stack_test" in modules and not unsupported:
            from .tasks import run_sh4_research_stack_test
            roots=[project/"research"/"runs",project/"research"/"db_lab"/"runs"]
            navimain=next((p for base in roots if base.is_dir() for p in base.rglob("NAVIMAIN.EXE") if p.is_file()),None)
            nkbin=next((p for base in roots if base.is_dir() for p in base.rglob("NK.BIN") if p.is_file()),None)
            if not navimain or not nkbin: print(json.dumps({"status":"INPUT_MISSING","error_code":"NAVIMAIN_OR_NKBIN_NOT_FOUND"}));return
            print(json.dumps(run_sh4_research_stack_test(a.task,project,navimain,nkbin),default=str,ensure_ascii=False));return
        print(json.dumps({"status":"UNSUPPORTED","task_id":task.get("task_id"),"unsupported_modules":unsupported,"message":"Unsupported task instructions were not reinterpreted or executed."})); return
    if a.command=="new-task":
        from .project_inventory import ensure_task
        ensure_task(project)
        import shutil
        task_id="".join(c if c.isalnum() or c in "-_" else "_" for c in a.task_id).strip("_").upper() or "CUSTOM"
        templates=project/"research"/"tasks"/"templates"; dest=project/"research"/"tasks"/task_id
        dest.mkdir(parents=True,exist_ok=False)
        obj=json.loads((templates/"custom"/"task.json").read_text()); obj.update(task_id=task_id,title=task_id.replace("_"," ").title())
        (dest/"task.json").write_text(json.dumps(obj,indent=2),encoding="utf-8")
        (dest/"TASK.md").write_text(f"# {obj['title']}\n\nDescribe the research question, inputs, methods, and stop conditions here.\n",encoding="utf-8")
        print(json.dumps({"task_id":task_id,"task_path":str(dest/"TASK.md"),"manifest_path":str(dest/"task.json")})); return
    if a.command=="task-author":
        from .task_authoring import parse_prompt,save_task,set_lifecycle,read_state,write_state
        if a.operation=="settings":
            state=read_state(project);state["auto_archive_mode"]=a.archive_mode or "after_success";write_state(project,state);print(json.dumps(state,ensure_ascii=False));return
        if a.operation in ("preview","save","revise"):
            if not a.path or not a.path.is_file(): ap.error("task-author requires --path to a UTF-8 text file")
            prompt=a.path.read_text(encoding="utf-8");preview=parse_prompt(prompt,project,a.language)
            if a.operation=="preview": print(json.dumps(preview,ensure_ascii=False));return
            if preview.get("plan_format")=="NCDR_TASK_PLAN_V1" and preview.get("strict_validation",{}).get("status")!="PASS":
                print(json.dumps({"status":"VALIDATION_FAILED","validation_errors":preview.get("validation_errors",[]),"strict_validation":preview.get("strict_validation")},ensure_ascii=False));return
            saved=save_task(project,preview,prompt,a.revision_of or None);print(json.dumps({**preview,**saved},ensure_ascii=False));return
        if a.operation in ("archive","restore","template","delete"):
            task_id=a.task_id
            if a.operation=="delete":
                import shutil
                folder=project/"research"/"tasks"/task_id
                if folder.exists(): shutil.rmtree(folder)
                state=read_state(project);state.get("tasks",{}).pop(task_id,None);write_state(project,state)
                print(json.dumps({"task_id":task_id,"deleted_definition":True,"history_preserved":True}));return
            set_lifecycle(project,task_id,{"restore":"active","archive":"archived","template":"template"}[a.operation]);print(json.dumps({"task_id":task_id,"state":a.operation}));return
        ap.error("unsupported task-author operation")
    if a.command=="list" and a.mode=="summary":
        from .project_summary import build_project_summary
        print(json.dumps(build_project_summary(project),ensure_ascii=False)); return
    if a.command=="list" and a.mode=="runs":
        from .tasks import build_run_history
        print(json.dumps(build_run_history(project),ensure_ascii=False)); return
    if a.command=="list" and a.mode=="tasks":
        from .tasks import task_capability_status,build_run_history
        history=build_run_history(project); latest={}
        for run in history: latest.setdefault(run["task_id"],run)
        rows=[]
        from .task_authoring import read_state,refresh_stale_task_compilation
        lifecycle=read_state(project).get("tasks",{})
        for p in sorted((project/"research"/"tasks").glob("*/task.json")):
            task=json.loads(p.read_text()); task=refresh_stale_task_compilation(project,p,task); capability=task_capability_status(task); tid=task.get("task_id"); last=latest.get(tid,{})
            all_runs=[r for r in history if r.get("task_id")==tid]; life=lifecycle.get(tid,{})
            task_state=life.get("state","template" if task.get("is_template") else "active")
            rows.append({"task_path":str(p.parent/"TASK.md"),"manifest_path":str(p),"task":task,"implementation_status":capability["status"],"capabilities":capability,"unsupported_modules":capability["missing_modules"],"enabled":capability["can_run"],"last_run":last,"last_result":last.get("main_result"),"lifecycle_state":task_state,"archived_at":life.get("archived_at"),"run_count":len(all_runs)})
        print(json.dumps(rows,ensure_ascii=False)); return
    if a.command=="list" and a.mode=="map-reader-discovery":
        from .map_reader_discovery import load_map_reader_page
        print(json.dumps(load_map_reader_page(project),ensure_ascii=False)); return
    if a.command=="list" and a.mode=="nkbin-status":
        from .wince_rom import parse_nkbin
        roots=[project/"research"/"runs",project/"research"/"db_lab"/"runs"]
        nkbin=next((p for base in roots if base.is_dir() for p in base.rglob("NK.BIN") if p.is_file()),None)
        print(json.dumps(parse_nkbin(nkbin) if nkbin else {"status":"UNSUPPORTED","ui_status":"INCONCLUSIVE","path":None,"size":None,"rom_header":None,"module_count":None,"file_count":None,"modules":[],"files":[],"coredll_present":None,"extracted_modules":[]},ensure_ascii=False));return
    if a.command=="sh4-analysis":
        if not a.path: ap.error("--path is required")
        from .sh4_analysis import disassemble_module
        result=disassemble_module(a.path)
        print(json.dumps({"status":result.get("status"),"module":result.get("module"),"machine":result.get("machine"),"image_base":result.get("image_base"),"entry_point_rva":result.get("entry_point_rva"),"entry_point_file_offset":result.get("entry_point_file_offset"),"imports":result.get("imports"),"ordinal_imports":result.get("ordinal_imports"),"entry_instructions":result.get("entry_instructions"),"functions":result.get("functions"),"xrefs":result.get("xrefs"),"strings":result.get("strings"),"backend":result.get("backend")},ensure_ascii=False)); return
    cat=ArtifactCatalog(project)
    try:
        if a.command=="add":
            if not a.path: ap.error("--path is required")
            p=a.path.resolve()
            aid,res=cat.add_directory(p,a.source_type) if p.is_dir() else cat.add_file(p,a.source_type)
            cat._correlate(); cat.db.commit(); print(json.dumps({"artifact_id":aid,"path":str(p),"files":len(res) if isinstance(res,list) else 1}))
        elif a.command=="search": print(json.dumps(cat.global_search(a.query,a.mode),ensure_ascii=False))
        elif a.command=="list":
            if a.mode=="summary":
                from .project_summary import build_project_summary
                rows=build_project_summary(project)
            elif a.mode=="runs": rows=[dict(r) for r in cat.db.execute("SELECT run_id,task_id,status,start_time,end_time,run_path,summary_json FROM run_tasks ORDER BY start_time DESC")]
            elif a.mode=="tasks":
                from .tasks import task_capability_status
                from .task_authoring import refresh_stale_task_compilation
                rows=[]
                for p in sorted((project/"research"/"tasks").glob("*/task.json")):
                    task=json.loads(p.read_text()); task=refresh_stale_task_compilation(project,p,task); capability=task_capability_status(task); modules=task.get("analysis_modules",[])
                    rows.append({"task_path":str(p.parent/"TASK.md"),"manifest_path":str(p),"task":task,"implementation_status":capability["status"],"capabilities":capability,"unsupported_modules":capability["missing_modules"],"enabled":capability["can_run"]})
            elif a.mode=="facts": rows=[dict(zip(("subject","property","value","status","evidence","confidence"),r)) for r in cat.kb.execute("SELECT subject,property,value,status,evidence,confidence FROM facts ORDER BY subject,property")]
            elif a.mode=="backend":
                from .acceleration.backend import Backend
                import multiprocessing
                rows={"logical_cores":multiprocessing.cpu_count(),"machine":__import__("platform").machine(),"backend":Backend().report()}
            elif a.mode=="artifacts":
                rows=[]
                for r in cat.db.execute("SELECT artifact_id,source_path,source_type,size,sha256,magic,analysis_state,relationships_json FROM artifacts a WHERE a.rowid=(SELECT MAX(b.rowid) FROM artifacts b WHERE b.source_path=a.source_path) ORDER BY source_path"):
                    item=dict(r); item["files"]=[dict(x) for x in cat.db.execute("SELECT relative_path,size,file_type,sha256,magic FROM files WHERE artifact_id=? AND is_directory=0 ORDER BY relative_path LIMIT 3000",(r["artifact_id"],))];
                    try: item.update(json.loads(item.get("relationships_json") or "{}"))
                    except Exception: pass
                    rows.append(item)
            else: rows=[dict(r) for r in cat.db.execute("SELECT run_id,task_id,status,start_time,end_time,run_path,summary_json FROM run_tasks ORDER BY start_time DESC")]
            print(json.dumps(rows,ensure_ascii=False))
        elif a.command=="compare":
            def id_for(value):
                row=cat.db.execute("SELECT artifact_id FROM artifacts WHERE source_path=?",(str(Path(value).resolve()),)).fetchone()
                if not row: raise ValueError("Import both directories before comparing")
                return row[0]
            print(json.dumps(compare_directories(cat,id_for(a.baseline),id_for(a.experiment)),ensure_ascii=False))
    finally: cat.close()

if __name__=="__main__": main()
