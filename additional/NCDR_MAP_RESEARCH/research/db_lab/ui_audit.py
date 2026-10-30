"""Persisted UI-to-backend consistency audit."""
from __future__ import annotations
import json, sqlite3, uuid
from .db_concurrency import connect_database
from datetime import datetime
from pathlib import Path
from .project_summary import build_project_summary
from .tasks import atomic_json,finish_run,package_run,environment,APP_VERSION,register_run

TASK_ID="UI_FOUNDATION_AUDIT"
def run_ui_audit(project_root):
    root=Path(project_root).resolve()
    now=datetime.now().astimezone(); run=root/"research"/"runs"/(now.strftime("%Y-%m-%d_%H-%M-%S_%f")+"_"+TASK_ID); run.mkdir(parents=True,exist_ok=False)
    for d in ("inputs","logs","data","evidence","plots","checkpoints"): (run/d).mkdir()
    task={"task_id":TASK_ID,"title":"UI data binding and foundation consistency audit","summary_source":"project_summary.build_project_summary","metrics":["artifacts","files","validated_db0","controlled_experiment_sets","disc_images","firmware_media","research_runs","open_tasks","artifact statuses","graphics capability","selected backend"],"scope":"Backend-to-Overview consistency; no Phase 2 research."}
    (run/"TASK.md").write_text("# UI data binding and foundation consistency\n\nVerify the native Overview projection against the authoritative SQLite inventory and knowledge databases.\n",encoding="utf-8")
    (run/"task.json").write_text(json.dumps(task,indent=2),encoding="utf-8")
    meta={"run_id":str(uuid.uuid4()),"task_id":TASK_ID,"start_time":now.isoformat(),"end_time":None,"duration_seconds":None,"status":"RUNNING","application_version":APP_VERSION,"summary":{},"warnings":[],"errors":[]}; atomic_json(run/"run.json",meta); atomic_json(run/"environment.json",environment(root))
    register_run(root,run,meta)
    summary=build_project_summary(root)
    db=connect_database(root/"research/db_lab/analysis.sqlite",readonly=True); db.row_factory=sqlite3.Row
    checks=[]
    expected={"artifacts":"SELECT COUNT(*) FROM (SELECT source_path FROM artifacts GROUP BY source_path)","files":"SELECT COUNT(*) FROM (SELECT source_path,relative_path FROM files WHERE COALESCE(is_directory,0)=0 GROUP BY source_path,relative_path)","validated_db0":"SELECT COUNT(*) FROM (SELECT source_path,relative_path FROM files WHERE file_type='db0' OR validated_format='DB_0' GROUP BY source_path,relative_path)","controlled_experiment_sets":"SELECT COUNT(*) FROM (SELECT source_path FROM artifacts WHERE source_type='controlled_experiment' AND (filename='ORIGINAL' OR filename LIKE 'OUTPUT_%') GROUP BY source_path)","disc_images":"SELECT COUNT(*) FROM (SELECT a.source_path FROM artifacts a JOIN disc_images d USING(artifact_id) WHERE d.status IN ('READABLE','VALIDATED','OK') GROUP BY a.source_path)","firmware_media":"SELECT COUNT(*) FROM (SELECT source_path,relative_path FROM files WHERE is_directory=0 AND file_type LIKE 'firmware%' GROUP BY source_path,relative_path)","research_runs":"SELECT COUNT(*) FROM run_tasks","open_tasks":"SELECT COUNT(*) FROM task_queue WHERE status IN ('QUEUED','RUNNING','BLOCKED')"}
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for key,sql in expected.items():
        try: authoritative=db.execute(sql).fetchone()[0]
        except sqlite3.Error: authoritative=0
        displayed=summary["counts"].get(key,0)
        checks.append({"metric":key,"backend_value":displayed,"authoritative_value":authoritative,"status":"PASS" if int(displayed or 0)==int(authoritative or 0) else "DIFFERENCE","source_query":sql})
    # Distinct executable and firmware states are checked against current source paths.
    for name in ("poison.exe","patch.exe","NAVBOOT","Firmware"):
        expected_status=summary["statuses"].get(name,{"status":"NOT FOUND"})["status"]
        if name=="Firmware" and "files" in tables:
            q=db.execute("SELECT COUNT(*) FROM files WHERE is_directory=0 AND file_type LIKE 'firmware%'").fetchone()[0]
            source="files.file_type firmware media count"
        elif "files" in tables:
            q=db.execute("SELECT COUNT(*) FROM files WHERE is_directory=0 AND lower(filename)=lower(?)",(name,)).fetchone()[0]
            source="files.filename exact match"
        else: q=0; source="files table unavailable"
        observed="FOUND" if q else "NOT FOUND"
        checks.append({"metric":"status:"+name,"backend_value":expected_status,"authoritative_value":observed,"authoritative_count":q,"status":"PASS" if expected_status==observed else "DIFFERENCE","source_query":source})
    db.close()
    graphics=summary["graphics"]
    gpu=graphics.get("gpu_detection",{})
    binding_checks=[
        ("gpu_hardware",graphics.get("hardware",[]),gpu.get("gpu_devices",[]),[d.get("name") for d in graphics.get("hardware",[])],[d.get("name") for d in gpu.get("gpu_devices",[])]),
        ("metal_capability",[d.get("metal") for d in graphics.get("hardware",[])],[d.get("metal_supported") for d in gpu.get("gpu_devices",[])],[d.get("metal_supported") for d in graphics.get("hardware",[])],[d.get("metal_supported") for d in gpu.get("gpu_devices",[])]),
        ("gpu_execution_backend",graphics.get("gpu_execution_backend"),gpu.get("gpu_execution_backends",[]),graphics.get("gpu_execution_backends",[]),gpu.get("gpu_execution_backends",[])),
        ("selected_backend",graphics.get("selected_backend"),gpu.get("selected"),graphics.get("selected_backend"),gpu.get("selected")),
    ]
    for name,display,authoritative,left,right in binding_checks:
        checks.append({"metric":name,"backend_value":authoritative,"gui_value":display,"authoritative_value":authoritative,"status":"PASS" if left==right else "DIFFERENCE","source":"platform compute discovery / shared project-summary binding"})
    for item in checks: item.setdefault("gui_value",item["backend_value"])
    status="PASS" if all(x["status"]=="PASS" for x in checks) else "DIFFERENCE"
    def csvq(value): return '"'+str(value).replace('"','""')+'"'
    csvtext="metric,backend_value,gui_value,authoritative_value,status,source\n"+"".join(",".join(csvq(x.get(k,"")) for k in ("metric","backend_value","gui_value","authoritative_value","status","source_query" if "source_query" in x else "source"))+"\n" for x in checks)
    (run/"data"/"ui_backend_comparison.csv").write_text(csvtext,encoding="utf-8")
    audit={"result":status,"checked_at":summary["last_refreshed"],"counts":summary["counts"],"statuses":summary["statuses"],"graphics":summary["graphics"],"checks":checks,"check_count":len(checks),"passed":sum(x["status"]=="PASS" for x in checks),"foundation_warning":summary["foundation_warning"]}
    atomic_json(run/"data"/"ui_foundation_audit.json",audit)
    report=["# UI Data Binding and Foundation Consistency", "",f"Result: **{status}**", "", "## Overview values", "", "| Metric | Backend projection | Overview binding | Authoritative source | Result |", "|---|---|---|---|---|"]
    report += [f"| {x['metric']} | {x['backend_value']} | {x['gui_value']} | {x['authoritative_value']} | {x['status']} |" for x in checks]
    report += ["", "## Separate status and compute facts", "", "```json",json.dumps({"statuses":summary["statuses"],"graphics":summary["graphics"],"foundation_warning":summary["foundation_warning"]},indent=2),"```", "", "This run audits data binding only. It does not begin Phase 2 research."]
    (run/"REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    (run/"REPORT.html").write_text("<!doctype html><meta charset='utf-8'><title>UI Foundation Audit</title><pre>"+"\n".join(report).replace("&","&amp;").replace("<","&lt;")+"</pre>",encoding="utf-8")
    (run/"CHATGPT_SUMMARY.txt").write_text(json.dumps(audit,indent=2),encoding="utf-8")
    finish_run(run,meta,"COMPLETED" if status=="PASS" else "COMPLETED_WITH_DIFFERENCES",audit)
    package=package_run(run,required=["REPORT.md","REPORT.html","CHATGPT_SUMMARY.txt","data/ui_backend_comparison.csv","data/ui_foundation_audit.json","PACKAGE_MANIFEST.json"])
    atomic_json(run/"run.json",{**meta,"summary":{**audit,"package":package}})
    package=package_run(run,required=["REPORT.md","REPORT.html","CHATGPT_SUMMARY.txt","data/ui_backend_comparison.csv","data/ui_foundation_audit.json","PACKAGE_MANIFEST.json"])
    register_run(root,run,{**meta,"summary":{**audit,"package":package}})
    return {"run_path":str(run),"audit":audit,"package":package}
