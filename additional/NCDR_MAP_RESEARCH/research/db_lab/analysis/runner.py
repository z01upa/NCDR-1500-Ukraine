from __future__ import annotations
import csv, json, os, shutil, sqlite3, statistics, time, zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from ..config import APP_NAME, EXPECTED_DB_SIZE, EXPECTED_TYPE00_COMPRESSION_COUNTS, MOSCOW_CONTROL
from ..core.db_reader import DBReader, sha256_file
from ..acceleration.backend import Backend
from ..compression.comp01_lab import reference_profile, transforms, score

def _write_csv(path, rows, fields=None):
    fields = fields or (list(rows[0]) if rows else ["empty"])
    with path.open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def _checkpoint(run, stage):
    (run/"checkpoints").mkdir(exist_ok=True)
    (run/"checkpoints"/"state.json").write_text(json.dumps({"completed_stage":stage,"updated_at":datetime.now().astimezone().isoformat()},indent=2))

def _progress(run, stage, processed, total, block, started, candidate_count=0, best_score=None):
    elapsed=max(.001,time.time()-started); rate=processed/elapsed
    remaining=max(0,total-processed)/rate if rate else None
    (run/"progress.json").write_text(json.dumps({"stage":stage,"processed":processed,"total":total,"blocks_per_second":round(rate,2),"elapsed_seconds":round(elapsed,1),"remaining_seconds":round(remaining,1) if remaining is not None else None,"sector":block.sector if block else None,"block_type":block.block_type if block else None,"compression":block.compression if block else None,"candidate_count":candidate_count,"best_candidate_score":best_score},indent=2))

def _pause_stop(run):
    while (run/"pause.flag").exists(): time.sleep(.5)
    return (run/"stop.flag").exists()

def _schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS blocks(sector INTEGER PRIMARY KEY, offset INTEGER, span INTEGER, alignment INTEGER, block_type INTEGER, compression INTEGER, logical_units INTEGER, logical_size INTEGER, header_hex TEXT, index_valid INTEGER, decode_status TEXT, decoded_size INTEGER, entropy REAL, zero_ratio REAL, unique_bytes INTEGER, payload_prefix TEXT);
    CREATE TABLE IF NOT EXISTS stage_status(name TEXT PRIMARY KEY, completed INTEGER, details TEXT);
    CREATE TABLE IF NOT EXISTS candidates(id INTEGER PRIMARY KEY, transform TEXT, score REAL, blocks_scored INTEGER, avg_entropy REAL, avg_zero_ratio REAL, sample_sector INTEGER, sample_hex TEXT);
    CREATE TABLE IF NOT EXISTS events(at TEXT, level TEXT, message TEXT);
    """)

def _event(conn, run, level, message):
    conn.execute("INSERT INTO events VALUES(?,?,?)",(datetime.now().astimezone().isoformat(),level,message)); conn.commit()
    with (run/"events.log").open("a",encoding="utf-8") as f: f.write(f"{datetime.now().astimezone().isoformat()} [{level}] {message}\n")

def _find_moscow(research_dir):
    result={"status":"NOT_RUN","confirmed_roads":None,"message":"Existing confirmed parser unavailable"}
    parser=research_dir/"roads"/"parse_roads.py"
    if not parser.exists(): return result
    import sys, importlib
    sys.path.insert(0,str(parser.parent))
    try:
        mod=importlib.import_module("parse_roads")
        with mod.DB(research_dir.parent/"DB_0") as db:
            roads=mod.parse_moscow_control(db)
            result={"status":"PASS" if len(roads)==MOSCOW_CONTROL["road_count"] else "DIFFERENCE",
                    "confirmed_roads":len(roads),"expected_roads":MOSCOW_CONTROL["road_count"],
                    "message":"Moscow type-0x0E control list parsed with existing confirmed parser"}
    except Exception as e: result={"status":"FAIL","confirmed_roads":None,"message":str(e)}
    finally:
        sys.path.remove(str(parser.parent)); sys.modules.pop("parse_roads",None)
    return result

def _make_html(run, summary, block_rows):
    types=summary["block_type_counts"]; comps=summary["compression_counts"]
    table="".join(f'<tr><td>0x{k}</td><td>{v:,}</td></tr>' for k,v in sorted(types.items()))
    ctable="".join(f'<tr><td>0x{k}</td><td>{v:,}</td></tr>' for k,v in sorted(comps.items()))
    candidates=summary.get("top_candidates",[])
    cand="".join(f'<tr><td>{x["transform"]}</td><td>{x["score"]}</td><td>{x["blocks_scored"]}</td></tr>' for x in candidates[:20])
    html=f'''<!doctype html><meta charset="utf-8"><title>NCDR DB Laboratory report</title>
<style>body{{font:15px system-ui;max-width:1100px;margin:32px auto;padding:0 18px;color:#17212b}}h1,h2{{color:#153b58}}table{{border-collapse:collapse;width:100%;margin:12px 0 28px}}td,th{{border:1px solid #cbd5df;padding:7px;text-align:left}}th{{background:#eef3f7}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}}.card{{background:#eef3f7;padding:12px;border-radius:8px}}</style>
<h1>NCDR DB Laboratory</h1><p>Offline deterministic analysis report. Candidate scores are heuristic evidence, not proof of decoding.</p>
<div class="grid"><div class="card">DB size<br><b>{summary['db_size']:,} bytes</b></div><div class="card">Indexed blocks<br><b>{summary['total_blocks']:,}</b></div><div class="card">DB SHA256<br><code>{summary['db_sha256']}</code></div><div class="card">Decode 0x00/0x02<br><b>{summary['known_decode_success']:,} successful</b></div></div>
<h2>Database overview</h2><p>Expected DB size: {EXPECTED_DB_SIZE:,}; observed {summary['db_size']:,}. Index records use the confirmed uint24 BE sector ID and one-byte physical span.</p>
<h2>Block type distribution</h2><table><tr><th>Type</th><th>Count</th></tr>{table}</table>
<h2>Compression distribution</h2><table><tr><th>Code</th><th>Count</th></tr>{ctable}</table>
<h2>Known structures and road parser status</h2><pre>{json.dumps(summary['moscow_control'],indent=2)}</pre>
<h2>Unknown structures</h2><p>Compression 0x01 decoding and several block type semantics remain unresolved. This application records observations without assigning unconfirmed meanings.</p>
<h2>Compression 0x01 statistics</h2><p>Blocks: {summary['compression_counts'].get('01',0)}. The pipeline summarizes entropy, byte frequencies, prefixes and cross-block similarities. Decoder status remains unresolved.</p><p>See <a href="../csv/compression01_statistics.csv">compression statistics</a> and the downloadable candidate samples.</p>
<h2>Top decoder candidates</h2><table><tr><th>Transform</th><th>Heuristic score</th><th>Blocks scored</th></tr>{cand}</table>
<h2>Reference validation</h2><p>Readable 0x00/0x02 blocks provide a statistical reference profile. Candidate scoring compares entropy, zero-byte ratio, and distinct-byte count only.</p>
<h2>Entropy distributions</h2><p>Entropy profiles are stored per block in <a href="../csv/block_statistics.csv">block statistics</a>; byte frequencies for compression 0x01 are in the <a href="../csv/compression01_byte_frequency.csv">frequency table</a>.</p>
<h2>Coordinate and anchor statistics</h2><p>This milestone does not reinterpret anchor coordinates. Existing research remains authoritative; no routing-node claim is made here.</p>
<h2>Errors and anomalies</h2><p>Invalid bounded decodes: {summary['decode_failures']}. See <a href="../csv/structural_anomalies.csv">structural anomalies</a> and <a href="../csv/block_statistics.csv">block statistics</a>.</p>
<h2>Recommended next experiment</h2><p>Use top candidates as hypotheses only; add validated structural features from the readable type-0x00 oracle before expanding transform combinations.</p>
<h2>Block inspector</h2><p>Search and select an indexed record for its header and payload preview.</p><label>Find by sector, type, or compression <input id="q" oninput="render()"></label><div style="height:300px;overflow:auto"><table><thead><tr><th>Sector</th><th>Type</th><th>Compression</th><th>Span</th></tr></thead><tbody id="rows"></tbody></table></div><pre id="detail">Select a row to inspect it.</pre>
<script>const blocks={json.dumps(block_rows,separators=(',',':'))};function render(){{const q=document.getElementById('q').value.toLowerCase();const body=document.getElementById('rows');body.innerHTML='';for(const b of blocks){{if(q&&!(`${{b.sector}} 0x${{b.sector.toString(16)}} 0x${{b.block_type.toString(16)}} 0x${{b.compression.toString(16)}}`.toLowerCase().includes(q)))continue;const tr=document.createElement('tr');tr.innerHTML=`<td>${{b.sector}}</td><td>0x${{b.block_type.toString(16).padStart(2,'0')}}</td><td>0x${{b.compression.toString(16).padStart(2,'0')}}</td><td>${{b.span}}</td>`;tr.onclick=()=>document.getElementById('detail').textContent=JSON.stringify(b,null,2);body.appendChild(tr);if(body.children.length>=300)break;}}}}render();</script>
<p>Created {summary['created_at']}</p>'''
    (run/"html"/"index.html").write_text(html,encoding="utf-8")

def _package(run, summary):
    dest=run.parent/f"NCDR_DB_LAB_REPORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    include=[run/"summary.md",run/"summary.json",run/"run_manifest.json",run/"events.log",run/"analysis.sqlite"]
    for p in (run/"csv").glob("*.csv"): include.append(p)
    for p in (run/"samples").glob("*"): include.append(p)
    with zipfile.ZipFile(dest,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in include:
            if p.exists(): z.write(p,p.relative_to(run))
    return str(dest)

def run_analysis(db_path, parent_dir, resume=False, modes="Standard", stop_after=None, cpu_load="50%", gpu_load="50%", max_ram="AUTO", requested_backend="AUTO"):
    db_path=Path(db_path).expanduser().resolve(); parent_dir=Path(parent_dir).expanduser().resolve()
    parent_dir.mkdir(parents=True,exist_ok=True)
    digest=sha256_file(db_path)
    if resume:
        runs=sorted(parent_dir.glob("NCDR_DB_LAB_*/run_manifest.json"),key=lambda p:p.parent.name,reverse=True)
        matching=[]
        for p in runs:
            try:
                m=json.loads(p.read_text())
                if m.get("db_sha256")==digest and m.get("db_path")==str(db_path): matching.append(p.parent)
            except Exception: pass
        if not matching: raise ValueError("No resumable run matches this DB path and SHA256")
        run=matching[0]
    else:
        run=parent_dir/("NCDR_DB_LAB_"+datetime.now().strftime("%Y%m%d_%H%M%S")); run.mkdir()
        for name in ("csv","html","candidates","samples","checkpoints"): (run/name).mkdir()
    for name in ("csv","html","candidates","samples","checkpoints"): (run/name).mkdir(exist_ok=True)
    print("RUN_FOLDER="+str(run),flush=True)
    dbfile=run/"analysis.sqlite"; conn=sqlite3.connect(dbfile); _schema(conn)
    manifest={"application":APP_NAME,"version":"0.1.0","db_path":str(db_path),"db_sha256":digest,"db_size":db_path.stat().st_size,"created_at":datetime.now().astimezone().isoformat(),"mode":modes,"requested_backend":requested_backend,"cpu_load":cpu_load,"gpu_load":gpu_load,"maximum_ram":max_ram,"original_open_mode":"read-only","checkpoint_resume":True}
    if resume:
        old=json.loads((run/"run_manifest.json").read_text())
        if old.get("db_sha256")!=digest: raise ValueError("REFUSED: DB SHA256 differs from the previous run")
    (run/"run_manifest.json").write_text(json.dumps(manifest,indent=2))
    backend=Backend(); manifest["backend"]=backend.report(); (run/"run_manifest.json").write_text(json.dumps(manifest,indent=2))
    _event(conn,run,"INFO",f"Backend selected: {backend.selected} (requested {requested_backend}); starting analysis ({modes}, CPU {cpu_load}, RAM {max_ram})")
    start=time.time()
    load=int(cpu_load.rstrip("%")); batch_started=time.perf_counter()
    def throttle(index):
        nonlocal batch_started
        if load>=100 or index==0 or index%128: return
        now=time.perf_counter(); elapsed=now-batch_started
        if load>0: time.sleep(elapsed*(100/load-1))
        batch_started=time.perf_counter()
    with DBReader(db_path) as db:
        blocks=db.blocks
        done=conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
        if done < len(blocks):
            existing={r[0] for r in conn.execute("SELECT sector FROM blocks")}
            for i,b in enumerate(blocks):
                throttle(i)
                if b.sector in existing: continue
                if _pause_stop(run): raise InterruptedError("Analysis stopped at checkpoint; resume with the same DB and folder")
                conn.execute("INSERT OR IGNORE INTO blocks(sector,offset,span,alignment,block_type,compression,logical_units,logical_size,header_hex,index_valid,decode_status,decoded_size,entropy,zero_ratio,unique_bytes,payload_prefix) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (b.sector,b.offset,b.span,b.alignment,b.block_type,b.compression,b.logical_units,b.logical_size,db.header_hex(b),1,"pending",None,None,None,None,bytes(db.raw(b)[8:72]).hex()))
                if (i%250)==0: conn.commit(); _checkpoint(run,"block_index")
                if (i%250)==0: _progress(run,"Indexing blocks",i+1,len(blocks),b,start)
            conn.commit(); _checkpoint(run,"block_index")
        _event(conn,run,"INFO",f"Indexed {len(blocks)} block headers")
        # Decode 0x00 and 0x02; save summary features, never decoded blobs.
        failures=0; profiles=[]; reference_profiles=[]; zero_one=[]; known_success=0
        for i,b in enumerate(blocks):
            throttle(i)
            if _pause_stop(run): raise InterruptedError("Analysis stopped at checkpoint; resume with the same DB and folder")
            prior=conn.execute("SELECT decode_status,decoded_size,entropy,zero_ratio,unique_bytes FROM blocks WHERE sector=?",(b.sector,)).fetchone()
            if prior and prior[0] in ("decoded","unknown_0x01"):
                if b.compression in (0,2) and prior[0]=="decoded":
                    known_success+=1
                    if b.block_type==0: reference_profiles.append({"entropy":prior[2],"zero_ratio":prior[3],"unique_bytes":prior[4]})
                elif b.compression==1: zero_one.append(b)
                continue
            if b.compression in (0,2):
                try:
                    logical=db.logical(b); p=logical[8:]
                    from ..analysis.entropy import profile
                    pr=profile(p); profiles.append(pr); known_success+=1
                    if b.block_type==0: reference_profiles.append(pr)
                    conn.execute("UPDATE blocks SET decode_status='decoded',decoded_size=?,entropy=?,zero_ratio=?,unique_bytes=? WHERE sector=?",(len(logical),pr["entropy"],pr["zero_ratio"],pr["unique_bytes"],b.sector))
                except Exception as e:
                    failures+=1; conn.execute("UPDATE blocks SET decode_status=?,decoded_size=NULL WHERE sector=?",("error: "+str(e)[:120],b.sector))
            elif b.compression==1:
                zero_one.append(b)
                raw=db.raw(b)
                from ..analysis.entropy import profile
                pr=profile(raw[8:]); conn.execute("UPDATE blocks SET decode_status='unknown_0x01',decoded_size=NULL,entropy=?,zero_ratio=?,unique_bytes=? WHERE sector=?",(pr["entropy"],pr["zero_ratio"],pr["unique_bytes"],b.sector))
            if i%250==0: conn.commit(); _checkpoint(run,"decode_known")
            if i%250==0: _progress(run,"Decoding known blocks",i+1,len(blocks),b,start)
        conn.commit(); _checkpoint(run,"decode_known")
        # Compression 0x01 corpus fingerprint before hypotheses. Keep only
        # metadata and aggregate profiles in RAM; payloads stay mmap-backed.
        ref={k:statistics.mean(p[k] for p in reference_profiles if p[k] is not None) if reference_profiles else 0.0 for k in ("entropy","zero_ratio","unique_bytes")}
        freq=Counter(); prefixes=Counter(); ent=[]; sizes=[]
        for b in zero_one:
            raw=db.raw(b)
            body=raw[8:]; freq.update(body); prefixes[body[:8].hex()] += 1
            from ..analysis.entropy import profile
            p=profile(body); ent.append(p["entropy"]); sizes.append(len(body))
        _write_csv(run/"csv"/"compression01_statistics.csv",[{"blocks":len(zero_one),"raw_body_bytes":sum(sizes),"mean_entropy":statistics.mean(ent) if ent else 0,"min_entropy":min(ent) if ent else 0,"max_entropy":max(ent) if ent else 0,"unique_prefixes_8":len(prefixes),"top_prefix":prefixes.most_common(1)[0][0] if prefixes else "","top_prefix_count":prefixes.most_common(1)[0][1] if prefixes else 0,"reference_entropy":ref.get("entropy",0),"reference_zero_ratio":ref.get("zero_ratio",0)}])
        _write_csv(run/"csv"/"compression01_byte_frequency.csv",[{"byte":f"0x{k:02x}","count":v} for k,v in sorted(freq.items())])
        if stop_after=="index":
            conn.close(); return str(run), None
        # Bounded sample and first-stage independent transforms; stage completions are resumable.
        existing_candidates=conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        if zero_one and not existing_candidates:
            sample_limit={"Quick":8,"Standard":24,"Deep":64,"Experimental":96}.get(modes,24)
            sample=sorted(zero_one,key=lambda x:(x.span,x.sector))
            sample=sample[::max(1,len(sample)//min(sample_limit,len(sample)))][:sample_limit]
            progress_path=run/"checkpoints"/"comp01_progress.json"
            progress=json.loads(progress_path.read_text()) if progress_path.exists() else {"processed":0,"accum":{}}
            accum=progress["accum"]
            for idx,b in enumerate(sample):
                throttle(idx)
                if idx < progress["processed"]: continue
                if _pause_stop(run): raise InterruptedError("Candidate search stopped at checkpoint; resume with the same DB and folder")
                body=db.raw(b)[8:]
                for name,out in transforms(body):
                    sc,p=score(out,ref); row=accum.setdefault(name,{"scores":[],"ent":[],"zero":[],"sample_sector":b.sector,"sample_hex":out[:32].hex()})
                    row["scores"].append(sc); row["ent"].append(p["entropy"]); row["zero"].append(p["zero_ratio"])
                if idx%4==0 or idx==len(sample)-1:
                    progress_path.write_text(json.dumps({"processed":idx+1,"accum":accum}))
                    _checkpoint(run,f"comp01_search_{idx+1}")
                    best_now=max((statistics.mean(row["scores"]) for row in accum.values()),default=None)
                    _progress(run,"Compression 0x01 hypotheses",idx+1,len(sample),b,start,len(accum),round(best_now,4) if best_now is not None else None)
            ranked=[]
            for name,row in accum.items(): ranked.append({"transform":name,"score":round(statistics.mean(row["scores"]),4),"blocks_scored":len(row["scores"]),"avg_entropy":round(statistics.mean(row["ent"]),6),"avg_zero_ratio":round(statistics.mean(row["zero"]),6),"sample_sector":row["sample_sector"],"sample_hex":row["sample_hex"]})
            ranked.sort(key=lambda x:x["score"],reverse=True)
            conn.executemany("INSERT INTO candidates(transform,score,blocks_scored,avg_entropy,avg_zero_ratio,sample_sector,sample_hex) VALUES(:transform,:score,:blocks_scored,:avg_entropy,:avg_zero_ratio,:sample_sector,:sample_hex)",ranked); conn.commit()
            progress_path.unlink(missing_ok=True)
            for ix,row in enumerate(ranked[:10],1):
                (run/"samples"/f"candidate_{ix:02d}_{row['transform'].replace('/','_')}.txt").write_text(json.dumps(row,indent=2))
            _event(conn,run,"INFO",f"Tested {len(ranked)} first-stage hypotheses across {len(sample)} representative blocks")
        _checkpoint(run,"complete")
        # Export tables and build report.
        block_rows=[dict(zip([x[0] for x in conn.execute("SELECT * FROM blocks LIMIT 0").description],r)) for r in conn.execute("SELECT * FROM blocks ORDER BY sector")]
        _write_csv(run/"csv"/"block_statistics.csv",block_rows)
        types=Counter(str(b.block_type) for b in blocks); comps=Counter(f"{b.compression:02x}" for b in blocks)
        count_comp=Counter(f"{b.compression:02x}" for b in blocks)
        type00_comp=Counter(b.compression for b in blocks if b.block_type==0)
        moscow=_find_moscow(db_path.parent/"research")
        if moscow["status"]=="NOT_RUN": moscow=_find_moscow(Path(__file__).resolve().parents[2])
        cand=[dict(zip([x[0] for x in conn.execute("SELECT * FROM candidates LIMIT 0").description],r)) for r in conn.execute("SELECT * FROM candidates ORDER BY score DESC")]
        observed_type00={k:type00_comp.get(k,0) for k in (0,1,2)}
        summary={"created_at":datetime.now().astimezone().isoformat(),"db_path":str(db_path),"db_sha256":digest,"db_size":db_path.stat().st_size,"total_blocks":len(blocks),"block_type_counts":dict(types),"compression_counts":dict(count_comp),"known_decode_success":known_success,"decode_failures":failures,"compression01_count":len(zero_one),"compression01_mean_entropy":statistics.mean(ent) if ent else 0,"compression01_unique_prefixes":len(prefixes),"reference_profile":ref,"backend":backend.report(),"mode":modes,"elapsed_seconds":round(time.time()-start,3),"moscow_control":moscow,"validation":{"db_size":{"expected":EXPECTED_DB_SIZE,"observed":db_path.stat().st_size,"status":"PASS" if db_path.stat().st_size==EXPECTED_DB_SIZE else "DIFFERENCE"},"type00_compression":{"expected":EXPECTED_TYPE00_COMPRESSION_COUNTS,"observed":observed_type00,"status":"PASS" if observed_type00==EXPECTED_TYPE00_COMPRESSION_COUNTS else "DIFFERENCE"}},"hypotheses_tested":conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],"top_candidates":cand}
        (run/"summary.json").write_text(json.dumps(summary,indent=2))
        md=["# NCDR DB Laboratory analysis",f"\n- DB: `{db_path}`",f"- SHA256: `{digest}`",f"- Size: {summary['db_size']:,} bytes",f"- Indexed blocks: {len(blocks):,}",f"- Known decode successes: {summary['known_decode_success']:,}",f"- Compression 0x01 blocks: {len(zero_one):,}",f"- Hypotheses tested: {summary['hypotheses_tested']:,}",f"- Highest heuristic score: {cand[0]['score'] if cand else 0}","\nCandidate scores compare coarse byte profiles and do not establish successful decompression.","\n## Validation\n"]
        for k,v in summary["validation"].items(): md.append(f"- {k}: {json.dumps(v)}")
        md.append(f"\n## Moscow control parser\n\n{json.dumps(moscow,indent=2)}")
        (run/"summary.md").write_text("\n".join(md),encoding="utf-8")
        (run/"README.txt").write_text("NCDR DB Laboratory run folder. Original DB_0 was opened read-only. Zip this folder or use Create ChatGPT analysis package.\n")
        _write_csv(run/"csv"/"top_candidates.csv",cand)
        _write_csv(run/"csv"/"structural_anomalies.csv",[{"sector":b.sector,"issue":conn.execute("SELECT decode_status FROM blocks WHERE sector=?",(b.sector,)).fetchone()[0]} for b in blocks if (conn.execute("SELECT decode_status FROM blocks WHERE sector=?",(b.sector,)).fetchone()[0] or "").startswith("error:")])
        block_details=[{"sector":r["sector"],"offset":r["offset"],"span":r["span"],"block_type":r["block_type"],"compression":r["compression"],"logical_size":r["logical_size"],"header_hex":r["header_hex"],"decode_status":r["decode_status"],"payload_prefix":r["payload_prefix"]} for r in block_rows]
        _make_html(run,summary,block_details)
        zippath=_package(run,summary); summary["chatgpt_zip"]=zippath; (run/"summary.json").write_text(json.dumps(summary,indent=2))
        _event(conn,run,"INFO",f"Analysis complete: {run}")
    conn.close()
    return str(run),zippath
