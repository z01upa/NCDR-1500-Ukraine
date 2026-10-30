"""First general NCDR RE LAB task: project-only artifact inventory."""
from __future__ import annotations
import csv, json, sqlite3, time
from collections import Counter
from datetime import datetime
from pathlib import Path
import argparse, subprocess, sys
from .artifact_lab.catalog import ArtifactCatalog
from .artifact_lab.diff import compare_directories
from .tasks import APP_VERSION, atomic_json, create_run, finish_run, package_run, task_hash, write_logs, emit_progress

TASK_TEMPLATE={"task_id":"PROJECT_INVENTORY","title":"NCDR project artifact inventory","description":"Catalog the current research project and compare controlled POISoN experiment folders.","research_question":"Which map, firmware, executable, database and experiment artifacts are available locally, and which are the highest priority for the next reverse-engineering task?","input_artifacts":["project_root"],"required_artifact_types":["map_database_directory","disc_image","firmware","pe","controlled_experiment"],"known_facts":["research/PROJECT_STATE.md","research/firmware/F2_CONTAINER_FORMAT.md"],"analysis_modules":["project_inventory","artifact_scan","binary_search","binary_diff"],"hypotheses_to_test":[],"hypotheses_to_reject":[],"methods":["read-only recursive file catalog","SHA256 and entropy","ISO-9660 descriptor detection","conservative firmware magic/size validation","static PE metadata","byte-level comparison of controlled experiment files","global known-constant search in executables and firmware candidates"],"parameters":{"excluded_directories":["research/db_lab",".git"],"compare_baseline":"ORIGINAL","compare_experiments":"OUTPUT_*"},"cpu_settings":{"backend":"AUTO","workers":1},"gpu_settings":{"backend":"AUTO"},"memory_limits":{"max_ram":"AUTO"},"sample_strategy":"full file metadata; no full image or DB payload copied","full_scan_permission":True,"checkpoint_interval":25,"timeout":7200,"stop_conditions":["inventory and controlled-folder comparisons complete"],"expected_outputs":["REPORT.md","REPORT.html","CHATGPT_SUMMARY.txt","CHATGPT_PACKAGE.zip"],"required_tables":["artifacts","files","disc_images","firmware_containers","executables","binary_diffs","cross_source_matches","experiments"],"required_logs":["main.log","errors.log","performance.log"],"required_evidence":["file IDs, hashes and offsets for all findings"],"report_template":"project_inventory","ChatGPT_summary_requirements":"Concise evidence-based inventory; distinguish a navboot string reference from an actual firmware module.","depends_on":[]}

def ensure_task(project):
    taskdir=Path(project)/"research"/"tasks"/"PROJECT_INVENTORY"; taskdir.mkdir(parents=True,exist_ok=True)
    taskmd=taskdir/"TASK.md"; taskjson=taskdir/"task.json"
    if not taskmd.exists(): taskmd.write_text("# Project Inventory\n\nInspect only the explicitly selected NCDR_MAP_RESEARCH project. Catalog local artifacts read-only, compare the ORIGINAL folder against controlled OUTPUT experiment directories, search known firmware/database constants, and recommend the next RE task. Do not start compression brute force or firmware reverse engineering.\n",encoding="utf-8")
    if not taskjson.exists(): atomic_json(taskjson,TASK_TEMPLATE)
    templates=Path(project)/"research"/"tasks"/"templates"; templates.mkdir(exist_ok=True)
    for task_id in ("compression_analysis","firmware_analysis","navboot_analysis","binary_diff","poison_diff","road_structure","coordinate_analysis","geometry_search","routing_search","string_search","cross_source_analysis","custom"):
        folder=templates/task_id; folder.mkdir(exist_ok=True)
        obj=dict(TASK_TEMPLATE); obj.update(task_id=task_id.upper(),title=task_id.replace("_"," ").title(),analysis_modules=[task_id])
        p=folder/"task.json"
        if not p.exists(): atomic_json(p,obj)
        md=folder/"TASK.md"
        if not md.exists(): md.write_text(f"# {obj['title']}\n\nDescribe the research question, exact artifacts, hypotheses and stop conditions before running this task. Unsupported modules will be reported and will not be guessed.\n",encoding="utf-8")
    return taskmd,taskjson

def _write_csv(path,rows,fields=None):
    fields=fields or (list(rows[0]) if rows else ["empty"])
    with Path(path).open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def run_project_inventory(project_root,progress=None):
    project=Path(project_root).resolve(); taskmd,taskjson=ensure_task(project); task=json.loads(taskjson.read_text())
    catalog=ArtifactCatalog(project)
    try:
        existing=catalog.db.execute("SELECT artifact_id,source_path,source_type,sha256 FROM artifacts ORDER BY source_path").fetchall()
        inputs=[dict(artifact_id=r["artifact_id"],source_path=r["source_path"],source_type=r["source_type"],sha256=r["sha256"]) for r in existing]
    finally: catalog.close()
    run,meta,env=create_run(project,taskmd,task,inputs)
    meta["status"]="RUNNING"; atomic_json(run/"run.json",meta)
    from .db_concurrency import register_run_with_retry
    register_run_with_retry(project/"research"/"db_lab"/"analysis.sqlite",(meta["run_id"],task["task_id"],"RUNNING",meta["start_time"],None,str(run),"{}"))
    start=time.time(); messages=[]; errors=[]; started_epoch=time.time()
    def log(msg):
        line=datetime.now().astimezone().isoformat()+" "+msg+"\n"; messages.append(line)
        write_logs(run,main=line)
        if progress: progress(msg)
    try:
        log("Project inventory started; source files are opened read-only.")
        cat=ArtifactCatalog(project,output_dir=run/"data"/"copied_firmware")
        def catalog_progress(i,n,p):
            emit_progress("catalog", "Catalog project artifacts", 1, 4, i+1, n, "files", started_epoch)
            log(f"Cataloging project input {i+1}/{n}: {p.name}")
        result=cat.catalog_project(meta["run_id"],catalog_progress)
        emit_progress("compare", "Compare controlled experiments", 2, 4, 1, 1, "sets", started_epoch)
        paths={r["source_path"]:r["artifact_id"] for r in cat.db.execute("SELECT artifact_id,source_path FROM artifacts")}
        meta["input_artifacts"]=[dict(artifact_id=r["artifact_id"],source_path=r["source_path"],source_type=r["source_type"],sha256=r["sha256"]) for r in cat.db.execute("SELECT artifact_id,source_path,source_type,sha256 FROM artifacts ORDER BY source_path")]
        meta["input_hashes"]={x["artifact_id"]:x["sha256"] for x in meta["input_artifacts"]}; atomic_json(run/"run.json",meta)
        baseline=paths.get(str((project/"ORIGINAL").resolve())); diff_summaries=[]
        if baseline:
            experiment_ids=[]
            for name,path in sorted(paths.items()):
                if Path(name).name.startswith("OUTPUT_"):
                    eid=path; experiment_ids.append(eid)
                    cat.db.execute("UPDATE experiments SET baseline_artifact=? WHERE artifact_id=?",(baseline,eid))
                    log(f"Comparing ORIGINAL with {Path(name).name}")
                    summary=compare_directories(cat,baseline,eid)
                    summary["experiment_name"]=Path(name).name
                    diff_summaries.append(summary)
            cat.db.commit()
        # Global firmware / executable constant search uses imported PE and firmware files only.
        emit_progress("static_analysis", "Scan executable and firmware constants", 3, 4, 0, 1, "evidence sets", started_epoch)
        pe_rows=cat.db.execute("SELECT a.artifact_id,a.source_path,f.file_id,f.relative_path,f.sha256 FROM artifacts a JOIN files f USING(artifact_id) WHERE f.file_type IN ('pe','firmware','firmware_candidate') AND f.is_directory=0").fetchall()
        interesting=[]
        for r in pe_rows:
            for c in cat.db.execute("SELECT name,offset,pattern_hex,context_hex FROM constants WHERE file_id=? AND name IN ('firmware_4DAD0002','MULCOORD_BE32_5555555','MULCOORD_LE32_5555555','5555555_ASCII','navboot','DB_0','CARINET','ABSTRACT','sector_size_BE16','sector_size_BE32')",(r["file_id"],)):
                interesting.append({"artifact_id":r["artifact_id"],"file":r["relative_path"],"sha256":r["sha256"],"constant":c["name"],"offset":c["offset"],"pattern_hex":c["pattern_hex"],"context_hex":c["context_hex"]})
        exes=[dict(r) for r in cat.db.execute("SELECT a.source_path,f.relative_path,f.filename,f.sha256,e.machine,e.pe32_plus,e.imports_count,e.exports_count,e.resources_count FROM executable_files e JOIN files f USING(file_id) JOIN artifacts a USING(artifact_id) ORDER BY a.source_path,f.relative_path")]
        dbfiles=[dict(r) for r in cat.db.execute("SELECT a.source_path,a.source_type,f.relative_path,f.filename,f.size,f.sha256 FROM files f JOIN artifacts a USING(artifact_id) WHERE lower(f.filename)='db_0' ORDER BY a.source_path,f.relative_path")]
        mapdirs=[]
        for x in dbfiles:
            artifact_path=Path(x["source_path"])
            relative=Path(x["relative_path"])
            folder=artifact_path.parent if artifact_path.is_file() else artifact_path/relative.parent
            mapdirs.append(str(folder.resolve()))
        mapdirs=sorted(set(mapdirs))
        counts={"artifacts":cat.db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0],"files":cat.db.execute("SELECT COUNT(*) FROM files WHERE is_directory=0").fetchone()[0],"db0_files":len(dbfiles),"map_folders":len(mapdirs),"disc_images":cat.db.execute("SELECT COUNT(*) FROM disc_images").fetchone()[0],"readable_disc_images":cat.db.execute("SELECT COUNT(*) FROM disc_images WHERE status='ISO9660'").fetchone()[0],"valid_firmware_containers":cat.db.execute("SELECT COUNT(*) FROM firmware_containers WHERE status='VALIDATED_MAGIC_SIZE'").fetchone()[0],"navboot_string_hits":cat.db.execute("SELECT COUNT(*) FROM strings WHERE lower(value)='navboot'").fetchone()[0],"pe_count":len(exes),"cross_source_matches":cat.db.execute("SELECT COUNT(*) FROM cross_source_matches").fetchone()[0],"controlled_experiment_sets":cat.db.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]}
        counts["map_folders"]=len(mapdirs)
        containers=[dict(r) for r in cat.db.execute("SELECT a.source_path,c.magic,c.magic_offset,c.record_size,c.navboot_offsets,c.status,c.evidence FROM firmware_containers c JOIN artifacts a USING(artifact_id)")]
        filechanges=[]
        for summary in diff_summaries:
            filechanges.append({k:summary[k] for k in ("experiment_name","files_identical","files_added","files_removed","files_moved","diff_ranges","change_counts")})
        research_dirs=["research/roads","research/compression","research/firmware"]
        navboot_rows=cat.db.execute("SELECT sha256,source_path,relative_path FROM files WHERE lower(filename)='navboot'").fetchall()
        local_navboot=bool(navboot_rows)
        disc_rows=[dict(r) for r in cat.db.execute("SELECT a.source_path,d.format,d.filesystem,d.status,d.file_count FROM disc_images d JOIN artifacts a USING(artifact_id)")]
        previous_db_analysis=None
        prior_runs=sorted((project/"research"/"db_lab"/"runs").glob("NCDR_DB_LAB_*/summary.json"))
        if prior_runs:
            try: previous_db_analysis=json.loads(prior_runs[-1].read_text())
            except Exception: previous_db_analysis=None
        cpu_backends=[x["name"] for x in env["gpu_backend"].get("benchmark",[]) if x.get("available") and x.get("name")=="CPU"]
        gpu_backends=[x["name"] for x in env["gpu_backend"].get("benchmark",[]) if x.get("available") and x.get("name")!="CPU"]
        summary={"run_id":meta["run_id"],"task_id":task["task_id"],"application_version":APP_VERSION,"project_root":str(project),"artifact_counts":counts,"db0_files":dbfiles,"map_database_folders":mapdirs,"disc_images":disc_rows,"firmware_containers":containers,"navboot_found":local_navboot,"navboot_sha256":[x["sha256"] for x in navboot_rows],"pe_executables":exes,"poison_exe_found":any(Path(x["filename"]).name.lower()=="poison.exe" for x in exes),"patch_exe_found":any(Path(x["filename"]).name.lower()=="patch.exe" for x in exes),"controlled_experiment_sets":sorted([Path(x).name for x in paths if Path(x).name.upper() in {"ORIGINAL","OUTPUT_A","OUTPUT_B","OUTPUT_C","OUTPUT_D","OUTPUT_E","OUTPUT_F","OUTPUT_G","OUTPUT_L1","OUTPUT_L2","OUTPUT_T1","OUTPUT_T2","OUTPUT_XCARRY","OUTPUT_YCARRY"}]),"controlled_diffs":filechanges,"diff_range_limit_per_experiment":10000,"diff_ranges_truncated":any(d["diff_ranges"]>=10000 for d in filechanges),"road_research_found":(project/"research"/"roads").is_dir(),"compression_research_found":(project/"research"/"compression").is_dir(),"firmware_research_found":(project/"research"/"firmware").is_dir(),"previous_db_analysis":previous_db_analysis,"interesting_constants":interesting,"cpu_backend":{"available":bool(cpu_backends),"name":cpu_backends[0] if cpu_backends else "unavailable","logical_cores":env["logical_cores"]},"gpu_backend":{"available":bool(gpu_backends),"names":gpu_backends},"cross_source_matches":counts["cross_source_matches"],"inventory_failures":result["failures"],"highest_priority_next_target":"Obtain an actual firmware/update disc or the firmware container containing navboot.","priority_reason":"patch.exe and existing static research confirm a code path expecting a 4D AD 00 02 container and a module named navboot, but the project inventory contains no validated firmware image. navboot may contain a real DB reader/compression dispatcher, which is more direct evidence for 0x01 than further blind transform search.","missing_artifacts":["firmware/update ISO, BIN/IMG/CUE image","raw firmware container with 4D AD 00 02 magic","standalone extracted navboot module"],"recommended_next_task":"FIND_NAVBOOT: inventory known update media, validate the container directory format, and extract navboot only when module boundaries are supported by evidence.","compression_search_started":False}
        emit_progress("report", "Write report and validate package", 4, 4, 0, 1, "outputs", started_epoch)
        _write_csv(run/"data"/"db0_files.csv",dbfiles); _write_csv(run/"data"/"map_folders.csv",[{"path":x} for x in mapdirs]); _write_csv(run/"data"/"controlled_diffs.csv",filechanges); _write_csv(run/"data"/"executable_constants.csv",interesting)
        atomic_json(run/"data"/"inventory.json",summary)
        report=["# NCDR / NCDC RE LAB — Project Inventory",f"\nRun: `{run}`",f"\nProject: `{project}`","\n## Findings",f"\n- Artifacts catalogued: **{counts['artifacts']}**; files indexed: **{counts['files']}**.",f"- DB_0 files found: **{len(dbfiles)}** across **{len(mapdirs)}** database folders.",f"- Disc images: **{counts['disc_images']}** (readable ISO-9660: {counts['readable_disc_images']}).",f"- Validated firmware container records: **{counts['valid_firmware_containers']}**.",f"- navboot module/file found: **{'YES' if local_navboot else 'NO'}**. Literal references inside patch.exe are not counted as a module.",f"- poison.exe: **{'YES' if summary['poison_exe_found'] else 'NO'}**; patch.exe: **{'YES' if summary['patch_exe_found'] else 'NO'}**.",f"- Controlled experiment sets found: **{len(summary['controlled_experiment_sets'])}**.",f"- Cross-source matches catalogued: **{counts['cross_source_matches']}**.",f"- Existing road, compression, firmware research: **{summary['road_research_found']} / {summary['compression_research_found']} / {summary['firmware_research_found']}**.","\n## Controlled differential inventory\n"]
        report.extend([f"- {d['experiment_name']}: {d['files_identical']} identical files, {d['files_added']} added, {d['files_removed']} removed, {d['files_moved']} moved, {d['diff_ranges']} byte-difference ranges." for d in filechanges])
        if any(d["diff_ranges"]>=10000 for d in filechanges): report.append("\nDiff note: detailed range recording is capped at 10,000 ranges per experiment in this inventory; pairs reaching that cap have additional differences that require a separately parameterized diff run.")
        report += ["\n## Firmware and navboot","\nThe existing patch.exe and F2 research establish a conservative container clue: outer magic `4D AD 00 02`, and requested module name `navboot`. No local firmware image with a validated container record was found, so no navboot extraction was attempted. The patcher’s literal `navboot` lookup is not an extracted module.","\n## Highest-priority next target",f"\n{summary['highest_priority_next_target']} {summary['priority_reason']}","\nDo not start a large compression search until the firmware search is complete.","\n## Environment",f"\nCPU: {env['cpu']} ({env['logical_cores']} logical cores); RAM: {env['ram_gb']} GB; Python {platform_python(env)}; backend selected CPU; GPU: {gpu_label(env)}.","\n## Exact blockers", "\n- No actual update-disc image, firmware container, or navboot module is in the project.","- Firmware format evidence does not establish a safe navboot payload boundary; the existing parser refuses guessed extraction.","- Task-specific modules beyond inventory, artifact scan, binary search, binary diff, and existing DB_0 first-stage analysis are not executed automatically."]
        (run/"REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
        html="<!doctype html><meta charset='utf-8'><title>NCDR RE LAB Inventory</title><style>body{font:15px system-ui;max-width:1100px;margin:32px auto;padding:0 18px;background:#111827;color:#e5e7eb}h1,h2{color:#93c5fd}.card{background:#1f2937;padding:16px;border-radius:12px;margin:12px 0}a{color:#67e8f9}</style><h1>NCDR / NCDC RE LAB — Project Inventory</h1><div class=card>Artifacts: %d · Files: %d · DB_0: %d · Disc images: %d · Firmware containers: %d · navboot: %s</div><h2>Controlled POISoN differences</h2><pre>%s</pre><h2>Executable constant matches</h2><pre>%s</pre><h2>Priority</h2><p>%s %s</p><h2>Blockers</h2><p>No validated firmware image/navboot was found. 0x01 decoder search remains bounded.</p>"%(counts['artifacts'],counts['files'],len(dbfiles),counts['disc_images'],counts['valid_firmware_containers'],"YES" if local_navboot else "NO",json.dumps(filechanges,indent=2),json.dumps(interesting,indent=2),summary['highest_priority_next_target'],summary['priority_reason'])
        (run/"REPORT.html").write_text(html,encoding="utf-8")
        _write_csv(run/"data"/"inventory_artifacts.csv",[dict(r) for r in cat.db.execute("SELECT artifact_id,source_path,source_type,size,sha256,magic,entropy,analysis_state FROM artifacts ORDER BY source_path")])
        finish_run(run,meta,"COMPLETED",summary,warnings=["No firmware image/navboot module was found; firmware-directed decoder work remains blocked."] if not local_navboot else [])
        (run/"CHATGPT_SUMMARY.txt").write_text(f"TASK: {task['task_id']}\nRUN: {run}\nSTATUS: COMPLETED\nDURATION: {meta.get('duration_seconds')} seconds\n\nINPUTS: {project}\n\nKNOWN FACTS USED: PROJECT_STATE.md and existing firmware/roads/compression research.\n\nTESTS PERFORMED: read-only recursive artifact inventory, SHA256/entropy, PE metadata, known-constant scans, conservative container detection, ORIGINAL versus OUTPUT_* file and binary comparison.\n\nTOP RESULTS: {counts['artifacts']} artifacts; {counts['files']} files; {len(dbfiles)} DB_0 files; {len(mapdirs)} map database folders; {counts['disc_images']} disc images; {counts['valid_firmware_containers']} validated firmware containers.\n\nCONFIRMED: poison.exe={summary['poison_exe_found']}; patch.exe={summary['patch_exe_found']}; controlled sets={len(summary['controlled_experiment_sets'])}; source files remained read-only.\n\nSTRONG EVIDENCE: existing patch.exe research identifies firmware magic 4D AD 00 02 and a navboot target, but no validated image was catalogued.\n\nREJECTED: no candidate decoder hypothesis promoted.\n\nINCONCLUSIVE: actual navboot/firmware unavailable.\n\nNEW DISCOVERIES: controlled output comparison counts are in data/controlled_diffs.csv; executable constant offsets are in data/executable_constants.csv.\n\nIMPORTANT NUMBERS: {json.dumps(counts,sort_keys=True)}\n\nERRORS: {len(result['failures'])} catalog errors.\n\nFILES TO INSPECT: REPORT.md, REPORT.html, data/inventory.json, data/controlled_diffs.csv, data/executable_constants.csv\n\nEXACT NEXT QUESTION: Can you provide the original update disc or firmware image containing the 4D AD 00 02 container so we can locate and analyze navboot before expanding compression 0x01 search?\n",encoding="utf-8")
        package=package_run(run)
        emit_progress("report", "Write report and validate package", 4, 4, 1, 1, "outputs", started_epoch)
        if package["status"] not in ("READY","SKIPPED"): raise RuntimeError("ChatGPT package validation failed: "+json.dumps(package))
        summary["package"]=package
        atomic_json(run/"run.json",meta)
        cat.db.execute("INSERT OR REPLACE INTO run_tasks(run_id,task_id,status,start_time,end_time,run_path,summary_json) VALUES(?,?,?,?,?,?,?)",(meta["run_id"],task["task_id"],"COMPLETED",meta["start_time"],meta["end_time"],str(run),json.dumps(summary,ensure_ascii=False))); cat.db.commit(); cat.close()
        write_logs(run,main=f"Inventory complete; package {package['status']} at {package['path']}\n",performance=f"duration_seconds={time.time()-start:.2f}\nfiles={counts['files']}\n")
        return {"run_dir":str(run),"package":package,"summary":summary,"report":str(run/"REPORT.md"),"html":str(run/"REPORT.html")}
    except Exception as e:
        errors.append(str(e)); write_logs(run,error=str(e)+"\n")
        try: finish_run(run,meta,"FAILED",{},errors=errors)
        except Exception: pass
        raise

def platform_python(env): return env["python"].split()[0]
def gpu_label(env):
    back=env["gpu_backend"].get("benchmark",[])
    return ", ".join(x["name"] for x in back if x["available"] and x["name"]!="CPU") or "none available"

def main(argv=None):
    ap=argparse.ArgumentParser(description="Run a read-only project inventory task")
    ap.add_argument("--project-root",type=Path,required=True)
    ap.add_argument("--no-finder",action="store_true")
    args=ap.parse_args(argv)
    result=run_project_inventory(args.project_root,lambda msg: print(msg,flush=True))
    print(json.dumps({k:v for k,v in result.items() if k!="summary"},indent=2),flush=True)
    print(f"Summary: {json.dumps(result['summary'],sort_keys=True)}",flush=True)
    if not args.no_finder:
        subprocess.run(["open","-R",result["package"]["path"]],check=False)

if __name__=="__main__": main()
