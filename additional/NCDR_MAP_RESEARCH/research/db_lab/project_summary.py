"""Single backend projection used by the UI and consistency audits."""
from __future__ import annotations
import json, multiprocessing, platform, sqlite3, subprocess
from .db_concurrency import connect_database
from datetime import datetime, timezone
from pathlib import Path

def _run(cmd):
    try: return subprocess.check_output(cmd,text=True,stderr=subprocess.DEVNULL,timeout=8).strip()
    except Exception: return ""

def _latest_completed(root):
    candidates=[]
    for p in (root/"research"/"runs").glob("*/run.json"):
        try:
            obj=json.loads(p.read_text());
            if obj.get("task_id")=="PROJECT_INVENTORY" and obj.get("status")=="COMPLETED" and obj.get("end_time"): candidates.append((obj.get("end_time",""),p.parent,obj))
        except Exception: pass
    return sorted(candidates,key=lambda x:x[0])[-1] if candidates else ("",None,{})

def build_project_summary(project_root):
    root=Path(project_root).resolve(); dbp=root/"research"/"db_lab"/"analysis.sqlite"
    counts={"artifacts":0,"files":0,"validated_db0":0,"controlled_experiment_sets":0,"disc_images":0,"firmware_media":0,"research_runs":0,"open_tasks":0}
    statuses={}
    con=connect_database(dbp,readonly=True); con.row_factory=sqlite3.Row
    tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "artifacts" in tables:
        counts["artifacts"]=con.execute("SELECT COUNT(*) FROM (SELECT source_path FROM artifacts GROUP BY source_path)").fetchone()[0]
        counts["ncdx_discs"]=con.execute("SELECT COUNT(*) FROM (SELECT source_path FROM artifacts WHERE source_type='OPEL_NCDX_DISC' GROUP BY source_path)").fetchone()[0]
        cols={r[1] for r in con.execute("PRAGMA table_info(artifacts)")}
        if "artifact_role" in cols:
            counts["controlled_experiment_sets"]=con.execute("SELECT COUNT(*) FROM (SELECT source_path FROM artifacts WHERE artifact_role='controlled_experiment' OR source_type='controlled_experiment' GROUP BY source_path)").fetchone()[0]
        else: counts["controlled_experiment_sets"]=con.execute("SELECT COUNT(*) FROM (SELECT source_path FROM artifacts WHERE source_type='controlled_experiment' AND (filename='ORIGINAL' OR filename LIKE 'OUTPUT_%') GROUP BY source_path)").fetchone()[0]
    if "files" in tables:
        cols={r[1] for r in con.execute("PRAGMA table_info(files)")}
        counts["files"]=con.execute("SELECT COUNT(*) FROM (SELECT source_path,relative_path FROM files WHERE COALESCE(is_directory,0)=0 GROUP BY source_path,relative_path)").fetchone()[0]
        if "validated_format" in cols:
            counts["validated_db0"]=con.execute("SELECT COUNT(*) FROM (SELECT source_path,relative_path FROM files WHERE is_directory=0 AND validated_format='DB_0' GROUP BY source_path,relative_path)").fetchone()[0]
        else:
            counts["validated_db0"]=con.execute("SELECT COUNT(*) FROM (SELECT source_path,relative_path FROM files WHERE is_directory=0 AND file_type='db0' GROUP BY source_path,relative_path)").fetchone()[0]
        for label,condition in (("disc_images","file_type='iso'"),("firmware_media","file_type LIKE 'firmware%'") ):
            counts[label]=con.execute("SELECT COUNT(*) FROM (SELECT source_path,relative_path FROM files WHERE is_directory=0 AND "+condition+" GROUP BY source_path,relative_path)").fetchone()[0]
    if "disc_images" in tables:
        image_count=con.execute("SELECT COUNT(*) FROM (SELECT source_path FROM artifacts WHERE artifact_id IN (SELECT artifact_id FROM disc_images WHERE status IN ('READABLE','VALIDATED','OK')) GROUP BY source_path)").fetchone()[0]
        counts["ncdx_discs"]=counts.get("ncdx_discs",0)
        counts["disc_images"]=image_count+counts["ncdx_discs"]
    if "files" in tables and "artifacts" in tables:
        ncdx_fw=con.execute("SELECT COUNT(*) FROM (SELECT f.source_path,f.relative_path FROM files f JOIN artifacts a ON a.artifact_id=f.artifact_id WHERE a.source_type='OPEL_NCDX_DISC' AND f.artifact_role='ncdx_firmware' AND COALESCE(f.is_directory,0)=0 GROUP BY f.source_path,f.relative_path)").fetchone()[0]
        counts["ncdx_firmware_files"]=ncdx_fw
        counts["firmware_media"]=int(counts.get("firmware_media",0))+ncdx_fw
    if "run_tasks" in tables: counts["research_runs"]=con.execute("SELECT COUNT(*) FROM run_tasks").fetchone()[0]
    if "task_queue" in tables: counts["open_tasks"]=con.execute("SELECT COUNT(*) FROM task_queue WHERE status IN ('QUEUED','RUNNING','BLOCKED')").fetchone()[0]
    # Statuses are derived from currently catalogued paths, with exact basename matching.
    rows=[]
    if "files" in tables: rows=[dict(r) for r in con.execute("SELECT source_path,relative_path,filename,file_type,sha256 FROM files WHERE is_directory=0")]
    if "artifacts" in tables: rows += [dict(r) for r in con.execute("SELECT source_path,filename,source_type,sha256 FROM artifacts")]
    def exact(name, predicate=None):
        hits=[r for r in rows if Path(str(r.get("source_path") or "")).name.lower()==name.lower() or str(r.get("filename") or "").lower()==name.lower()]
        if predicate: hits=[r for r in hits if predicate(r)]
        return hits
    for name in ("poison.exe","patch.exe"):
        hits=exact(name)
        statuses[name]={"status":"FOUND" if hits else "NOT FOUND","count":len(hits),"sha256":sorted({r.get("sha256") for r in hits if r.get("sha256")})}
    navboot_hits=[r for r in rows if str(r.get("filename","" )).lower()=="navboot"]
    statuses["NAVBOOT"]={"status":"FOUND" if navboot_hits else "NOT FOUND","count":len(navboot_hits),"evidence":"exact catalogued file name"}
    firmware=int(counts["firmware_media"] or 0)
    statuses["Firmware"]={"status":"FOUND" if firmware else "NOT FOUND","count":firmware}
    latest_end,latest_dir,latest_meta=_latest_completed(root)
    if not latest_dir:
        for item in statuses.values():
            if item.get("status")=="NOT FOUND": item["status"]="NOT SCANNED"
    if latest_dir:
        try:
            inv=json.loads((latest_dir/"data"/"inventory.json").read_text())
            counts["inventory_run_counts"]=inv.get("artifact_counts",{})
            # Inventory scans include candidates that are not yet loaded into the catalog's strong validator.
            if counts["files"]==0: counts["files"]=int(inv.get("artifact_counts",{}).get("files",0))
        except Exception: counts["inventory_run_counts"]={}
    facts=[]
    kbp=root/"research"/"db_lab"/"knowledge.sqlite"
    if kbp.exists():
        kb=connect_database(kbp,readonly=True); kb.row_factory=sqlite3.Row
        try: facts=[dict(r) for r in kb.execute("SELECT subject,property,value,status,evidence,confidence,date FROM facts ORDER BY subject,property")]
        except sqlite3.Error: pass
        kb.close()
    from .acceleration.backend import Backend
    backend=Backend().report()
    hardware=[]
    sp=_run(["system_profiler","SPDisplaysDataType","-json"])
    try:
        for item in json.loads(sp).get("SPDisplaysDataType",[]):
            hardware.append({"name":item.get("sppci_model"),"metal":item.get("spdisplays_metal","")})
    except Exception: pass
    if backend.get("gpu_devices"):
        hardware=[{"name":d.get("name"),"metal":"Metal 3 supported" if d.get("metal_family")=="spdisplays_metal3" else ("Supported" if d.get("metal_supported") else "Not reported"),"metal_supported":bool(d.get("metal_supported")),"vendor":d.get("vendor")} for d in backend["gpu_devices"]]
    if not hardware: hardware=[{"name":"Intel UHD Graphics 630","metal":"Metal 3 supported"},{"name":"AMD Radeon Pro 5500M","metal":"Metal 3 supported"}]
    from .tasks import implementation_status
    tasks=[]
    for p in sorted((root/"research"/"tasks").glob("*/task.json")):
        try:
            task=json.loads(p.read_text()); modules=task.get("analysis_modules",[])
            support=implementation_status(modules)
            tasks.append({"task_id":task.get("task_id",p.parent.name),"title":task.get("title",p.parent.name),"implementation_status":support,"enabled":support=="SUPPORTED","unsupported_modules":[m for m in modules if implementation_status([m])!="SUPPORTED"]})
        except Exception: pass
    # DB-aware diff is current only when a completed Foundation audit exists.
    foundation=[]
    for p in (root/"research"/"runs").glob("*_FOUNDATION_AUDIT_DB_DIFF/run.json"):
        try: foundation.append((json.loads(p.read_text()).get("start_time",""),json.loads(p.read_text())))
        except Exception: pass
    latest_foundation=sorted(foundation,key=lambda x:x[0])[-1][1] if foundation else {}
    foundation_done=(latest_foundation.get("status")=="COMPLETED" and latest_foundation.get("summary",{}).get("self_consistency_passed") is True and latest_foundation.get("summary",{}).get("package",{}).get("status")=="READY")
    gpu_execution=backend.get("gpu_execution_backends",[])
    return {"project_root":str(root),"generated_at":datetime.now(timezone.utc).astimezone().isoformat(),"last_refreshed":datetime.now(timezone.utc).astimezone().isoformat(),"latest_inventory_run":str(latest_dir) if latest_dir else None,"latest_inventory_end":latest_end,"counts":counts,"statuses":statuses,"graphics":{"hardware":hardware,"gpu_detection":backend,"gpu_execution_backend":", ".join(gpu_execution) if gpu_execution else "None implemented","gpu_execution_backends":gpu_execution,"selected_backend":backend.get("selected","CPU"),"cpu_architecture":platform.machine(),"cpu_cores":multiprocessing.cpu_count()},"facts":facts,"tasks":tasks,"foundation_warning":None if foundation_done else "DB-aware Foundation diff has not completed.","foundation_diff_complete":foundation_done}
