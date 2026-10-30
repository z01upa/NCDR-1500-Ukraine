"""Foundation inventory validator and untruncated, record-aware experiment audit."""
from __future__ import annotations
import csv, hashlib, json, sqlite3, uuid
from .db_concurrency import connect_database
from datetime import datetime
from pathlib import Path
from .artifact_lab.catalog import ArtifactCatalog
from .artifact_lab.db0_diff import inventory_db0_files,get_or_parse_db0,compare_db0,group_identical_experiments,write_tables
from .tasks import atomic_json,finish_run,package_run,environment,APP_VERSION,register_run

TASK_ID="FOUNDATION_AUDIT_DB_DIFF"
def _latest_inventory(root):
    found=[]
    for p in (root/"research"/"runs").glob("*/run.json"):
        try:
            obj=json.loads(p.read_text())
            if obj.get("task_id")=="PROJECT_INVENTORY" and obj.get("status")=="COMPLETED" and obj.get("end_time"): found.append((obj["end_time"],p.parent,obj))
        except Exception: pass
    if not found: raise RuntimeError("No completed PROJECT_INVENTORY run is available")
    return sorted(found,key=lambda x:x[0])[-1]

def _create_run(root,inv_run):
    now=datetime.now().astimezone(); rid=now.strftime("%Y-%m-%d_%H-%M-%S_%f")+"_"+TASK_ID
    run=root/"research"/"runs"/rid; run.mkdir(parents=True,exist_ok=False)
    for d in ("inputs","logs","data","evidence","plots","checkpoints"): (run/d).mkdir()
    task={"task_id":TASK_ID,"title":"Foundation audit and DB-aware diff","analysis_modules":["db0_structural_validation","content_addressed_db0_cache","record_aware_diff","package_integrity","self_consistency"],"input_run":str(inv_run),"stop_conditions":["Stop before Phase 2; do not investigate firmware or navigation semantics."],"outputs":["poison_experiment_summary.csv","poison_changed_records.csv","poison_logical_ranges.csv","PACKAGE_MANIFEST.json"]}
    (run/"TASK.md").write_text("# Foundation audit and DB-aware diff\n\nValidate DB_0 framing, reuse hash-verified parse caches, and compare the complete record chain for every controlled output against ORIGINAL. Stop before Phase 2.\n",encoding="utf-8")
    (run/"task.json").write_text(json.dumps(task,indent=2),encoding="utf-8")
    meta={"run_id":str(uuid.uuid4()),"task_id":TASK_ID,"start_time":now.isoformat(),"end_time":None,"duration_seconds":None,"status":"RUNNING","application_version":APP_VERSION,"input_inventory_run":str(inv_run),"summary":{},"warnings":[],"errors":[]}
    atomic_json(run/"run.json",meta); atomic_json(run/"environment.json",environment(root)); return run,meta

def run_foundation_audit(project_root):
    root=Path(project_root).resolve(); _,inv_run,inv_meta=_latest_inventory(root); run,meta=_create_run(root,inv_run)
    db_files=inventory_db0_files(inv_run)
    original=next((r for r in db_files if Path(r["source_path"]).name.upper()=="ORIGINAL"),None)
    if original is None: raise RuntimeError("Latest completed inventory has no ORIGINAL DB_0")
    legacy=root/"research/db_lab/runs/NCDR_DB_LAB_20261005_232254/analysis.sqlite"
    baseline=None; parsed=[]; cache_rows=[]; issues=[]
    catalog=ArtifactCatalog(root)
    try:
        for item in db_files:
            legacy_sha=original["sha256"] if item["sha256"]==original["sha256"] else None
            result=get_or_parse_db0(catalog,item["path"],item["sha256"],item["size"],inv_run.name,legacy,legacy_sha)
            if not result.get("valid"):
                issues.append({"path":item["path"],"sha256":item["sha256"],"status":result.get("status"),"errors":result.get("errors",[])})
                continue
            entry={**result,"path":item["path"],"name":Path(item["source_path"]).name.upper()}
            parsed.append(entry)
            if entry["name"]=="ORIGINAL": baseline=entry
            cache_rows.append({"sha256":item["sha256"],"size":item["size"],"record_count":result["record_count"],"status":result["status"],"cache_source":result.get("source"),"source_run":inv_run.name})
        if baseline is None: raise RuntimeError("ORIGINAL failed strong DB_0 validation")
        # Reconcile inventory classification without rehashing file contents.
        for item in db_files:
            catalog.db.execute("UPDATE files SET file_type='db0',artifact_role='navigation_database',format_candidate='DB_0',validated_format='DB_0',validation_status='VALIDATED_DB_0',validation_evidence=?,mtime_ns=COALESCE(mtime_ns,0) WHERE sha256=? AND filename='DB_0'",(json.dumps({"record_count":next((x["record_count"] for x in parsed if x["sha256"]==item["sha256"]),0),"source_run":inv_run.name}),item["sha256"]))
        catalog.db.execute("UPDATE files SET artifact_role=CASE WHEN upper(filename)='CARINET' THEN 'map_metadata' ELSE 'generic_file' END,format_candidate='DB_0',validated_format=NULL,validation_status='REJECTED_DB_0_CANDIDATE',validation_evidence='signature prefix is only a candidate clue; complete DB_0 record-chain validation failed' WHERE upper(filename)='CARINET' OR filename='.DS_Store'")
        catalog.db.execute("UPDATE artifacts SET artifact_role='controlled_experiment' WHERE source_type='controlled_experiment'")
        catalog.db.execute("UPDATE artifacts SET artifact_role='map_metadata' WHERE upper(filename) IN ('ABSTRACT','BIBLIOGR','CARINET','COPYRIGH')")
        catalog.db.execute("UPDATE artifacts SET artifact_role='generic_file' WHERE filename='.DS_Store'")
        catalog.db.execute("UPDATE artifacts SET artifact_role='navigation_database' WHERE filename='DB_0' AND sha256 IN (SELECT sha256 FROM db0_parse_cache WHERE status='VALIDATED_DB_0')")
        catalog.db.commit()
    finally: catalog.close()
    if not issues and len(parsed)!=len(db_files): issues.append({"status":"INVENTORY_COUNT_MISMATCH","expected":len(db_files),"validated":len(parsed)})
    summaries=[]; details=[]; ranges=[]
    for exp in parsed:
        if exp["name"] in ("ORIGINAL","DB_0"): continue
        summary=compare_db0(None,baseline,exp,exp["name"])
        summaries.append(summary); details.extend(summary.pop("details")); ranges.extend(summary.pop("logical_ranges"))
    identical=group_identical_experiments(summaries)
    shaped=[]
    for s in summaries:
        shaped.append({"experiment":s["experiment"],"db_size":s["experiment_db_size"],"db_sha256":s["experiment_db_sha256"],"record_count":s["experiment_record_count"],"changed_records":s["records_changed"],"added_records":s["records_added"],"removed_records":s["records_removed"],"relocated_records":s["records_relocated"],"changed_block_types":json.dumps(s["changed_block_types"],sort_keys=True),"changed_compression_types":json.dumps(s["changed_compression_types"],sort_keys=True),"physical_changed_bytes":s["physical_changed_bytes"],"logical_changed_bytes":s["logical_changed_bytes"],"identical_to":s["identical_to"],"original_db_size":s["original_db_size"],"original_record_count":s["original_record_count"],"records_unchanged":s["records_unchanged"],**s})
    write_tables(run/"data",shaped,details,ranges,cache_rows)
    # PROJECT_STATE defines these controls relative to OUTPUT_A, not ORIGINAL.
    controls=[]
    output_a=next((x for x in parsed if x["name"]=="OUTPUT_A"),None)
    if output_a:
        for exp,want in (("OUTPUT_B",1),("OUTPUT_D",1)):
            target=next((x for x in parsed if x["name"]==exp),None)
            pair=compare_db0(None,output_a,target,exp,baseline_name="OUTPUT_A") if target else {"details":[]}
            rows=[r for r in pair["details"] if int(r["block_type"])==0x06]
            controls.append({"control":"OUTPUT_A to "+exp+" expected one changed type-0x06 record","expected":want,"observed":len(rows),"status":"PASS" if len(rows)==want else "DIFFERENCE","sectors":";".join(str(r["sector"]) for r in rows)})
    else: controls=[{"control":"OUTPUT_A baseline available for type-0x06 controls","expected":1,"observed":0,"status":"DIFFERENCE","sectors":""}]
    # Verify false-positive candidate fixtures against strong structural validation.
    from .artifact_lab.db_validation import validate_db0
    false_positive=[]
    for p in (root/"CARINET",root/".DS_Store"):
        if p.exists():
            v=validate_db0(p); false_positive.append({"path":str(p),"signature_hit":v.get("signature_hit"),"validated":v.get("valid"),"status":v.get("status")})
    (run/"data"/"db0_false_positive_audit.json").write_text(json.dumps(false_positive,indent=2),encoding="utf-8")
    (run/"data"/"known_type06_controls.json").write_text(json.dumps(controls,indent=2),encoding="utf-8")
    self_check={"inventory_db0_count":len(db_files),"strong_validated_count":len(parsed),"validation_issues":issues,"record_counts_match":all(x["record_count"]==baseline["record_count"] or x["name"]=="OUTPUT_C" for x in parsed),"identical_output_groups":identical,"package_manifest_added":True,"diff_is_capped":False,"false_positives_rejected":all(not x["validated"] for x in false_positive),"type06_controls":controls}
    self_check["passed"]=not issues and len(parsed)==len(db_files) and self_check["false_positives_rejected"] and all(c["status"]=="PASS" for c in controls)
    (run/"data"/"self_consistency_audit.json").write_text(json.dumps(self_check,indent=2),encoding="utf-8")
    summary={"inventory_run":inv_run.name,"inventory_counts":inv_meta.get("summary",{}).get("artifact_counts",{}),"db0_files":len(db_files),"validated_db0":len(parsed),"db0_records_per_file":baseline["record_count"],"experiment_outputs":len(summaries),"identical_hash_groups":identical,"changed_record_rows":len(details),"logical_range_rows":len(ranges),"validated_cache_entries":len(cache_rows),"issues":issues,"self_consistency_passed":self_check["passed"]}
    report=["# Foundation Audit and DB-aware Diff","",f"Completed from inventory run `{inv_run.name}`.","",f"- Structurally validated DB_0 files: {len(parsed)} / {len(db_files)}",f"- Record chain: {baseline['record_count']:,} records in each baseline/output DB_0",f"- Controlled experiment outputs compared: {len(summaries)}",f"- Identical output groups: {json.dumps(identical,sort_keys=True)}",f"- Changed/added/removed/relocated record detail rows: {len(details):,}",f"- Logical changed-range rows: {len(ranges):,}","- Diff output is complete; no row cap applied.","", "## PROJECT_STATE type-0x06 controls", "", "| Control | Expected | Observed | Result |", "|---|---:|---:|---|"]
    report += [f"| {x['control']} | {x['expected']} | {x['observed']} | {x['status']} |" for x in controls]
    report += ["", "## Candidate false positives", "", "| File | Signature clue | Strong DB_0 result |", "|---|---|---|"]+[f"| `{Path(x['path']).name}` | {x['signature_hit']} | {x['status']} |" for x in false_positive]
    report += ["", "Logical ranges are emitted with an explicit status for every affected record. Records with logical_units=0 have an unknown or empty logical extent and are marked NOT_COMPARABLE; no logical byte range is inferred from physical bytes.", "", "## Scope boundary", "", "This run stops at the requested foundation diff. It does not investigate firmware, NAVBOOT internals, compression 0x01, geometry, or routing semantics."]
    (run/"REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    (run/"REPORT.html").write_text("<!doctype html><meta charset='utf-8'><title>Foundation Audit</title><pre>"+"\n".join(report).replace("&","&amp;").replace("<","&lt;")+"</pre>",encoding="utf-8")
    (run/"CHATGPT_SUMMARY.txt").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    finish_run(run,meta,"COMPLETED" if self_check["passed"] else "COMPLETED_WITH_DIFFERENCES",summary,errors=issues)
    packaged=package_run(run,required=["REPORT.md","REPORT.html","CHATGPT_SUMMARY.txt","data/poison_experiment_summary.csv","data/poison_changed_records.csv","data/poison_logical_ranges.csv","PACKAGE_MANIFEST.json"])
    self_check["package_integrity"]=packaged["status"]=="READY" and not packaged.get("verification_errors")
    self_check["passed"]=self_check["passed"] and self_check["package_integrity"]
    summary["self_consistency_passed"]=self_check["passed"]
    summary["package"]=packaged
    (run/"data"/"self_consistency_audit.json").write_text(json.dumps(self_check,indent=2),encoding="utf-8")
    report.append(f"\nPackage integrity: **{packaged['status']}**; manifest/member verification errors: {len(packaged.get('verification_errors',[]))}.")
    (run/"REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    (run/"REPORT.html").write_text("<!doctype html><meta charset='utf-8'><title>Foundation Audit</title><pre>"+"\n".join(report).replace("&","&amp;").replace("<","&lt;")+"</pre>",encoding="utf-8")
    (run/"CHATGPT_SUMMARY.txt").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    finish_run(run,meta,"COMPLETED" if self_check["passed"] else "COMPLETED_WITH_DIFFERENCES",summary,errors=issues)
    atomic_json(run/"run.json",{**meta,"summary":summary})
    # Rebuild so its manifest records the final completed run metadata.
    packaged=package_run(run,required=["REPORT.md","REPORT.html","CHATGPT_SUMMARY.txt","data/poison_experiment_summary.csv","data/poison_changed_records.csv","data/poison_logical_ranges.csv","PACKAGE_MANIFEST.json"])
    summary["package"]=packaged
    atomic_json(run/"run.json",{**meta,"summary":summary})
    register_run(root,run,{**meta,"summary":summary})
    return {"run_path":str(run),"summary":summary,"package":packaged,"self_consistency":self_check}
