"""Conservative inventory and comparative analysis for Opel NCDx discs."""
from __future__ import annotations
import csv, hashlib, json, math, os, re, shutil, sqlite3, struct, subprocess, time, uuid, zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from .db_concurrency import connect_database

VOLUMES=["CD_7178","cd_7182","CD_7183","CD_7184","CD_7185","CD_7186","CD_7187","CD_7188","CD_7190"]
TOKENS=[".ABC",".RD",".STT",".AFF",".ASC",".CL",".CNY",".CT",".CTY",".FEA",".IL",".IOF",".MG1",".MG2",".MG3",".MP0",".PDX",".PTI",".PTP",".RL",".RT",".TYP","ZONE.CFG"]
SEARCH=["DB","RD","FEA","MG1","MG2","MG3","MP0","RL","RT","CTY","CNY","ZONE.CFG","navigation","route","road","map","sector","read","open","file","NAV","NAVI"]
REGION_LABELS={"CD_7178":"Germany","cd_7182":"France","CD_7183":"Central Europe","CD_7184":"Benelux","CD_7185":"Italy","CD_7186":"Scandinavia","CD_7187":"Spain/Portugal","CD_7188":"UK/Ireland","CD_7190":"Europe/MRE + Update"}
STAGES=["Disc discovery","Hash/catalog","Text metadata extraction","Native map-family comparison","Firmware discovery","PE/SH4 inventory","Critical artifact copy","Cross-source correlation","Report","ChatGPT package"]

def sha_file(p):
    h=hashlib.sha256(); hist=[0]*256; total=0
    with open(p,"rb") as f:
        while True:
            b=f.read(4*1024*1024)
            if not b: break
            h.update(b); total+=len(b)
            for x,c in Counter(b).items(): hist[x]+=c
    entropy=-sum((n/total)*math.log2(n/total) for n in hist if n) if total else 0
    return h.hexdigest(),round(entropy,6),total

def sample(p):
    size=p.stat().st_size
    with p.open("rb") as f:
        head=f.read(min(size,4096)); f.seek(max(0,size-4096)); tail=f.read(min(size,4096))
        chunks=[]
        for off in sorted(set((0,min(size//4,1024*1024),size//2,max(0,size-4096)))):
            f.seek(off); chunks.append({"offset":off,"sha256":hashlib.sha256(f.read(4096)).hexdigest()})
    return head.hex(),tail.hex(),chunks

def decode_text(b):
    candidates=[]
    if b.startswith(b"\xff\xfe"): candidates=[("utf-16le-bom","utf-16")]
    elif b.startswith(b"\xfe\xff"): candidates=[("utf-16be-bom","utf-16")]
    else:
        if len(b)>8 and b[1::2].count(0)>len(b)//8: candidates.append(("utf-16le-detected","utf-16le"))
        candidates.extend([("utf-8","utf-8-sig"),("iso-8859-1","latin-1")])
    for label,enc in candidates:
        try: return label,b.decode(enc)
        except UnicodeDecodeError: continue
    return "binary",b.decode("latin-1","replace")

def toc_fields(text):
    d={}
    for line in text.splitlines():
        m=re.match(r"\s*([^:]{1,48}):\s*(.*?)\s*$",line)
        if m and m.group(1).strip().lower() not in ("continental automotive gmbh",): d[m.group(1).strip()]=m.group(2).strip()
    return d

def log(run,idx,msg,started,done,total):
    elapsed=time.time()-started
    from .tasks import emit_progress
    emit_progress(f"stage_{idx}",STAGES[idx-1],idx,len(STAGES),done,total,"files",started)
    eta_text=""
    if elapsed>=3 and done>=2 and total>done:
        eta_text=f"; ETA ~{int((total-done)/(done/elapsed))}s"
    line=f"[{idx}/10] {STAGES[idx-1]} — {msg}; progress {done}/{total}; elapsed {int(elapsed)}s{eta_text}\n"
    with (run/"logs/main.log").open("a",encoding="utf-8") as f: f.write(line)
    print(line.rstrip(),flush=True)

def create_task(project):
    td=project/"research/tasks/NCDX_NATIVE_CORPUS_INVENTORY"; td.mkdir(parents=True,exist_ok=True)
    (td/"TASK.md").write_text("# NCDx Native Corpus Inventory\n\nInventory nine mounted original Opel NCDx 2010–2011 discs, validate identification from metadata, compare native database extensions and statically inspect update/firmware evidence. Stop after packaging. No mounted media is modified; no compression brute force is run.\n",encoding="utf-8")
    task={"task_id":"NCDX_NATIVE_CORPUS_INVENTORY","title":"NCDx Native Corpus Inventory","description":"Read-only native disc corpus and firmware discovery.","research_question":"What does the 2010–2011 NCDx corpus and its update media establish about data and firmware structure?","input_artifacts":[],"required_artifact_types":["OPEL_NCDX_DISC"],"known_facts":[],"analysis_modules":["ncdx_native"],"hypotheses_to_test":[],"hypotheses_to_reject":["NCDx equals DB_0"],"methods":["manifest","text extraction","sampled differential","static PE inspection"],"parameters":{"volumes":VOLUMES},"cpu_settings":{"backend":"CPU","workers":1},"gpu_settings":{},"memory_limits":{},"sample_strategy":"headers/tails and representative 4 KiB chunks","full_scan_permission":True,"checkpoint_interval":1,"timeout":"manual bounded run","stop_conditions":["Stop after ChatGPT package is verified"],"expected_outputs":["REPORT.md","CHATGPT_PACKAGE.zip"],"required_tables":[],"required_logs":["main.log"],"required_evidence":[],"report_template":"TASK.md","ChatGPT_summary_requirements":"All requested facts; unknowns explicitly limited","depends_on":[]}
    (td/"task.json").write_text(json.dumps(task,indent=2),encoding="utf-8")
    return td

def pe_info(data):
    if len(data)<0x40 or data[:2]!=b"MZ": return None
    off=int.from_bytes(data[0x3c:0x40],"little")
    if off+24>len(data) or data[off:off+4]!=b"PE\0\0": return None
    machine,nsec,_,_,_,optsz,_=struct.unpack_from("<HHIIIHH",data,off+4); op=off+24
    if op+optsz>len(data): return None
    entry=int.from_bytes(data[op+16:op+20],"little") if optsz>=20 else None
    sect=[]
    for i in range(min(nsec,96)):
        p=op+optsz+40*i
        if p+40>len(data): break
        name=data[p:p+8].split(b"\0")[0].decode("ascii","replace"); vs,va,rs,ro=struct.unpack_from("<IIII",data,p+8)
        sect.append({"name":name,"virtual_address":va,"virtual_size":vs,"raw_offset":ro,"raw_size":rs,"characteristics":int.from_bytes(data[p+36:p+40],"little")})
    machine_name={0x1a6:"Hitachi SH4",0x1a2:"Hitachi SH3",0x14c:"Intel 386",0x8664:"AMD64"}.get(machine,f"unknown 0x{machine:04x}")
    strings=[x.decode("ascii","ignore") for x in re.findall(rb"[\x20-\x7e]{5,}",data)]
    try:
        from .artifact_lab.binary_analysis import pe_analyze
        parsed=pe_analyze(data) or {}
    except Exception: parsed={}
    return {"machine":machine,"machine_name":machine_name,"pe_offset":off,"optional_header_magic":hex(int.from_bytes(data[op:op+2],"little")),"entry_point_rva":entry,"sections":sect,"imports":parsed.get("imports",[]),"exports":parsed.get("exports",[]),"resources":parsed.get("resources",[]),"strings":strings[:12000]}

def run_ncdx(project_root):
    project=Path(project_root); td=create_task(project); task_path=td/"TASK.md"
    from .tasks import create_run,finish_run,register_run,package_run,atomic_json
    run,meta,_=create_run(project,task_path,json.loads((td/"task.json").read_text()),[])
    started=time.time(); meta["status"]="RUNNING"; atomic_json(run/"run.json",meta)
    dirs={}; filepaths={}; manifests=[]; allrows=[]
    log(run,1,"checking all nine mounts and reading CDROM.TOC identity",started,1,1)
    for vol in VOLUMES:
        root=Path("/Volumes")/vol
        if not root.is_dir(): raise FileNotFoundError(root)
        fs="unknown"
        try:
            mountout=subprocess.check_output(["mount"],text=True,stderr=subprocess.DEVNULL)
            line=next((x for x in mountout.splitlines() if f" on {root} (" in x),"")
            fs=re.search(r"\(([^,]+),",line).group(1) if line else "unknown"
        except Exception: fs="unknown"
        files=sorted((p for p in root.rglob("*") if p.is_file()),key=lambda p:str(p).lower()); ds=sorted((p for p in root.rglob("*") if p.is_dir()),key=lambda p:str(p).lower()); dirs[vol]=ds; filepaths[vol]=files
        manifests.append({"volume":vol,"root":str(root),"file_system":fs,"probable_region":REGION_LABELS[vol],"directories":[p.relative_to(root).as_posix() for p in ds],"file_count":len(files),"directory_count":len(ds),"total_size":sum(p.stat().st_size for p in files)})
    total=sum(len(x) for x in filepaths.values()); done=0; t0=time.time()
    log(run,2,"streaming SHA256 and entropy across each regular file",started,0,total)
    allmeta=[]
    for disc in manifests:
        vol=disc["volume"]; root=Path(disc["root"]); records=[]
        cached=project/"research/ncdx/manifests"/(vol+".json")
        old=json.loads(cached.read_text()) if cached.exists() else None
        oldfiles={x["relative_path"]:x for x in old.get("files",[])} if old and old.get("volume")==vol else {}
        can_reuse=bool(oldfiles) and len(oldfiles)==len(filepaths[vol]) and all(x in oldfiles and oldfiles[x].get("size")==p.stat().st_size and oldfiles[x].get("mtime_ns")==p.stat().st_mtime_ns for p in filepaths[vol] for x in [p.relative_to(root).as_posix()])
        for p in filepaths[vol]:
            rel=p.relative_to(root).as_posix()
            if can_reuse: m=oldfiles[rel]
            else:
                sha,ent,size=sha_file(p); head,tail,chunks=sample(p)
                ext=p.suffix.lower() or "[no extension]"
                with p.open("rb") as f: prefix=f.read(16)
                m={"relative_path":rel,"size":size,"sha256":sha,"file_type":ext.lstrip("."),"magic":prefix.hex(),"entropy":ent,"header_4096_hex":head,"tail_4096_hex":tail,"sample_chunks":chunks,"mtime_ns":p.stat().st_mtime_ns}
            records.append(m); allmeta.append((vol,p,rel,m)); allrows.append((vol,p.suffix.lower() or "[no extension]",m)); done+=1
            if done%40==0: log(run,2,("reused verified manifest " if can_reuse else "hashed ")+f"{vol}; {done} files",started,done,total)
        disc["files"]=records
        raw=json.dumps(disc,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode(); disc["manifest_id"]=hashlib.sha256(raw).hexdigest()
        out=project/"research/ncdx/manifests"/(vol+".json"); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(disc,indent=2,ensure_ascii=False),encoding="utf-8")
        (run/"data"/(vol+"_manifest.json")).write_text(json.dumps(disc,indent=2,ensure_ascii=False),encoding="utf-8")
    log(run,2,f"all manifests complete; {done} files, {sum(x['total_size'] for x in manifests)} bytes; hash throughput ~{sum(x['total_size'] for x in manifests)/max(time.time()-t0,0.1)/1e6:.1f} MB/s",started,total,total)
    # Text metadata and decoded evidence.
    log(run,3,"decoding TOC, version and text/config/log files",started,0,1)
    texts=[]; extstats=defaultdict(Counter); textdir=run/"evidence/text"; textdir.mkdir(parents=True)
    for vol,p,rel,m in allmeta:
        ext=p.suffix.lower(); base=p.name.upper()
        extstats[vol][ext or "[no extension]"]+=1
        want=ext in (".txt",".cfg",".log") or base in ("CDROM.TOC","CREATE_CD") or "CREATE_CD" in base
        if not want or m["size"]>4*1024*1024: continue
        label,txt=decode_text(p.read_bytes()); dest=textdir/(vol+"__"+re.sub(r"[^A-Za-z0-9._-]+","_",rel.replace("/","__"))+".txt"); dest.write_text(txt,encoding="utf-8")
        texts.append({"volume":vol,"relative_path":rel,"encoding":label,"evidence_path":str(dest.relative_to(run)),"sha256":m["sha256"],"identity_fields":toc_fields(txt) if base=="CDROM.TOC" else {}})
    (run/"data/text_evidence.json").write_text(json.dumps(texts,indent=2,ensure_ascii=False),encoding="utf-8")
    log(run,3,f"saved {len(texts)} decoded text/config extracts",started,1,1)
    # Cross-disc structure via neutral extensions and bounded samples.
    log(run,4,"comparing neutral extensions, headers, tails and sampled chunks",started,0,1)
    rows=[]; perdisc={d["volume"]:d for d in manifests}
    for ext in sorted(set(e for _,e,_ in allrows)):
        by=defaultdict(list)
        for vol,e,m in allrows:
            if e==ext: by[vol].append(m)
        populated=[v for v in VOLUMES if by[v]]
        if True:
            rows.append({"extension":ext,"disc_count":len(populated),"discs":";".join(populated),"common_all_9":len(populated)==9,"file_count":sum(map(len,by.values())),"size_min":min(m["size"] for ms in by.values() for m in ms),"size_max":max(m["size"] for ms in by.values() for m in ms),"entropy_mean":round(sum(m["entropy"] for ms in by.values() for m in ms)/sum(map(len,by.values())),4),"unique_headers":len(set(m["header_4096_hex"][:128] for ms in by.values() for m in ms)),"unique_tails":len(set(m["tail_4096_hex"][-128:] for ms in by.values() for m in ms))})
    with (run/"data/extension_stats.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ["extension"]); w.writeheader(); w.writerows(rows)
    samepaths=defaultdict(list)
    for vol,p,rel,m in allmeta: samepaths[rel.lower()].append((vol,rel,m))
    comparisons=[]
    for entries in samepaths.values():
        for i,(va,ra,a) in enumerate(entries):
            for vb,rb,b in entries[i+1:]:
                ah={x["offset"]:x["sha256"] for x in a["sample_chunks"]}; bh={x["offset"]:x["sha256"] for x in b["sample_chunks"]}; common=set(ah)&set(bh)
                comparisons.append({"relative_path":ra,"disc_a":va,"disc_b":vb,"size_a":a["size"],"size_b":b["size"],"same_size":a["size"]==b["size"],"same_sha256":a["sha256"]==b["sha256"],"same_header_64B":a["header_4096_hex"][:128]==b["header_4096_hex"][:128],"same_tail_64B":a["tail_4096_hex"][-128:]==b["tail_4096_hex"][-128:],"equal_sample_chunks":sum(ah[x]==bh[x] for x in common),"sample_chunks_compared":len(common)})
    with (run/"data/cross_region_comparison.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(comparisons[0]) if comparisons else ["relative_path"]);w.writeheader();w.writerows(comparisons)
    # Selected high-value firmware inventory.
    log(run,5,"locating firmware/update evidence from names and static signatures",started,0,1)
    fw=[]
    for vol,p,rel,m in allmeta:
        u=rel.upper(); ext=p.suffix.upper()
        if vol!="CD_7190": continue
        if any(x in u for x in ("BOOTSECTOR.BIN","KERNELLOADER.BIN","NK.BIN","KERNELUPDATE","NAVIMAIN.EXE","MMIDIS.EXE","UPDATE")) or ext in (".HEX",".ABS",".DAT",".DLL",".EXE") or (u.startswith("SW/")):
            subsystem=next((x for x in ("KERNEL","A20","AUDIO","C161","LANGUAGE","MMIDIS","TMC","IDIS","SW") if x in u),"Other")
            fw.append({"volume":vol,"relative_path":rel,"subsystem":subsystem,"size":m["size"],"sha256":m["sha256"],"entropy":m["entropy"],"extension":ext})
    (run/"data/firmware_artifacts.json").write_text(json.dumps(fw,indent=2,ensure_ascii=False),encoding="utf-8")
    firmware_by_name={Path(x["relative_path"]).name.upper():x for v,p,rel,x in allmeta if v=="CD_7190"}
    update_pairs=[]
    for name,x in sorted(firmware_by_name.items()):
        if not name.endswith("01.DLL"): continue
        base=name[:-6]+".DLL"; y=firmware_by_name.get(base)
        if y: update_pairs.append({"base_file":base,"revision_file":name,"base_size":y["size"],"revision_size":x["size"],"same_sha256":y["sha256"]==x["sha256"],"base_entropy":y["entropy"],"revision_entropy":x["entropy"],"same_header_64B":y["header_4096_hex"][:128]==x["header_4096_hex"][:128],"same_tail_64B":y["tail_4096_hex"][-128:]==x["tail_4096_hex"][-128:],"interpretation":"Byte-level comparison only; semantics unassigned"})
    with (run/"data/update_dll_pairs.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(update_pairs[0]) if update_pairs else ["base_file"]);w.writeheader();w.writerows(update_pairs)
    swrows=[{"relative_path":rel,"size":m["size"],"sha256":m["sha256"],"entropy":m["entropy"],"header_64B":m["header_4096_hex"][:128],"tail_64B":m["tail_4096_hex"][-128:]} for v,p,rel,m in allmeta if v=="CD_7190" and rel.upper().startswith("SW/")]
    (run/"data/sw_subsystem.json").write_text(json.dumps(swrows,indent=2,ensure_ascii=False),encoding="utf-8")
    log(run,5,f"cataloged {len(fw)} firmware/update candidates by path and type",started,1,1)
    # PE analysis for actual EXE/DLL candidates; only files <=128MiB read wholly.
    log(run,6,"static PE signature and SH4 inspection",started,0,1)
    pe=[]; critical=[]
    for vol,p,rel,m in allmeta:
        u=rel.upper()
        if vol!="CD_7190" or p.suffix.lower() not in (".exe",".dll"): continue
        data=p.read_bytes() if m["size"]<=128*1024*1024 else p.read_bytes()[:1024*1024]
        pi=pe_info(data)
        if pi: pe.append({"path":rel,"sha256":m["sha256"],"size":m["size"],**pi})
    (run/"data/pe_inventory.json").write_text(json.dumps(pe,indent=2,ensure_ascii=False),encoding="utf-8")
    log(run,6,f"inspected {len(pe)} valid PE files; SH4={sum(p['machine']==0x1a6 for p in pe)}",started,1,1)
    # Copy priority evidence without map data; exclude NK.BIN from package.
    log(run,7,"copying only selected firmware/configuration evidence",started,0,1)
    copydir=run/"evidence/cd_7190"; copied=[]
    for vol,p,rel,m in allmeta:
        if vol!="CD_7190": continue
        u=rel.upper(); ext=p.suffix.lower(); name=p.name.upper()
        high=any(x in u for x in ("BOOTSECTOR.BIN","KERNELLOADER.BIN","NK.BIN","KERNELUPDATE","NAVIMAIN.EXE","MMIDIS.EXE")) or ("UPDATE" in name and ext==".dll") or (ext==".hex" and any(x in name for x in ("LOADER","APP","AUDIO"))) or u.startswith("IDIS/") and ("LOAD" in name or "SW01" in name or "SW02" in name or name in ("UPD_DAT.BIN","A20_UPD.DAT","IDISCONF.DAT")) or u.startswith("SW/") and ext in (".abs",".log") or name in ("VERSION.TXT","CREATE_CD","CDROM.TOC") or ext in (".cfg",".log") and ("LK841/" in u or u.startswith("IDIS/"))
        if not high or m["size"]>256*1024*1024: continue
        dest=copydir/rel; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(p,dest)
        if hashlib.sha256(dest.read_bytes()).hexdigest()!=m["sha256"]: raise IOError("copy integrity mismatch: "+rel)
        copied.append({"source":str(p),"relative_path":rel,"copy_path":str(dest.relative_to(run)),"size":m["size"],"sha256":m["sha256"],"included_in_package":not name.endswith("NK.BIN")})
    (run/"data/copied_evidence.json").write_text(json.dumps(copied,indent=2,ensure_ascii=False),encoding="utf-8")
    log(run,7,f"verified {len(copied)} evidence copies; NK.BIN retained outside package payload list",started,1,1)
    # Search target strings and DB_0 comparators. Conservative signal inventory only.
    log(run,8,"cross-source checks against DB_0 and scanned firmware strings",started,0,1)
    nav=next((r for r in pe if Path(r["path"]).name.upper()=="NAVIMAIN.EXE"),None)
    navpath=next((p for v,p,rel,m in allmeta if v=="CD_7190" and Path(rel).name.upper()=="NAVIMAIN.EXE"),None)
    navstrings=[]
    if navpath:
        nd=navpath.read_bytes(); printable=[x.decode("ascii","ignore") for x in re.findall(rb"[\x20-\x7e]{4,}",nd)]; navstrings=sorted(set(s for s in printable if any(t.lower() in s.lower() for t in SEARCH) or re.search(r"\.(DLL|EXE|DAT|BIN|ABC|RD|FEA|MG[123]|MP0|RL|RT)",s,re.I)))
    nk=next((p for v,p,rel,m in allmeta if v=="CD_7190" and Path(rel).name.upper()=="NK.BIN"),None)
    nkinfo={"found":bool(nk),"size":nk.stat().st_size if nk else None,"windows_ce_rom_signature_hits":[],"embedded_pe_candidates":[],"extraction_status":"NOT_VALIDATED"}
    if nk:
        sigs=[]
        with nk.open("rb") as f:
            raw=f.read()
        for sig in (b"ECEC","CE",b"MSFLSH50",b"ROMHDR",b"IMGFS",b"FATFS",b"NK"): 
            try:
                b=sig.encode() if isinstance(sig,str) else sig; pos=raw.find(b)
                if pos>=0: sigs.append({"signature":b.decode("ascii","replace"),"offset":pos})
            except Exception: pass
        nkinfo["windows_ce_rom_signature_hits"]=sigs
        # Embedded PE claims require full header and all raw section bounds.
        for mat in re.finditer(b"MZ",raw):
            off=mat.start()
            if off+0x40>len(raw): continue
            po=int.from_bytes(raw[off+0x3c:off+0x40],"little"); end=off+po
            if end+24>len(raw) or raw[end:end+4]!=b"PE\0\0": continue
            nsec=int.from_bytes(raw[end+6:end+8],"little"); optsz=int.from_bytes(raw[end+20:end+22],"little"); machine=int.from_bytes(raw[end+4:end+6],"little"); sp=end+24+optsz; bounds=True
            for i in range(nsec):
                q=sp+i*40
                if q+40>len(raw): bounds=False; break
                sz=int.from_bytes(raw[q+16:q+20],"little"); ptr=int.from_bytes(raw[q+20:q+24],"little")
                if ptr+sz>len(raw)-off: bounds=False; break
            if bounds:
                pi=pe_info(raw[off:]); nkinfo["embedded_pe_candidates"].append({"offset":off,"machine":machine,"machine_name":{0x1a6:"Hitachi SH4"}.get(machine,f"0x{machine:04x}"),"validated_bounds":True,"sha256":hashlib.sha256(raw[off:off+min(len(raw)-off,4096)]).hexdigest()})
        nkinfo["extraction_status"]="embedded PE candidates bounded; filesystem/image extraction not validated" if nkinfo["embedded_pe_candidates"] else "no bounded embedded PE; filesystem/image extraction not validated"
    db0=project/"DB_0"; db0hits=[]
    for needle,label in ((bytes.fromhex("0054c563"),"DB_0 coordinate constant 5555555 BE"),(b"5555555","ASCII constant"),(b"DB_0","DB_0 literal")):
        found=[]
        for ext in (".abc",".rd",".stt",".mg1",".mg2",".mg3",".mp0",".rl",".rt",".fea",".cty",".cny"):
            for v,p,rel,m in allmeta:
                if p.suffix.lower()!=ext: continue
                with p.open("rb") as f:
                    head=f.read(4*1024*1024); tail=b""
                    if m["size"]>4*1024*1024: f.seek(max(0,m["size"]-4*1024*1024)); tail=f.read(4*1024*1024)
                if needle in head or needle in tail: found.append({"volume":v,"path":rel,"sample":"header_or_tail_4MiB"})
        db0hits.append({"probe":label,"hits":found})
    correlation={"classification":"WEAK SIMILARITY" if any(x["hits"] for x in db0hits) else "NO EVIDENCE","method":"sampled first/last 4 MiB of native database candidates for existing DB_0 coordinate/string markers; no full structural equivalence test","db0_exists":db0.exists(),"probes":db0hits,"navimain_relevant_strings":navstrings}
    (run/"data/ncdx_vs_db0_comparison.json").write_text(json.dumps(correlation,indent=2,ensure_ascii=False),encoding="utf-8")
    (run/"data/nk_bin_analysis.json").write_text(json.dumps(nkinfo,indent=2,ensure_ascii=False),encoding="utf-8")
    log(run,8,f"relationship classified {correlation['classification']}; NK examined; strings captured",started,1,1)
    # Register in artifact catalog for UI and downstream database awareness.
    log(run,9,"writing report, immutable manifests and catalog records",started,0,1)
    db=connect_database(project/"research/db_lab/analysis.sqlite"); db.row_factory=sqlite3.Row
    firmware_rel={x["relative_path"] for x in fw if x["subsystem"]!="Other"}
    for d in manifests:
        vol=d["volume"]; root=Path(d["root"]); src=str(root); aid=hashlib.sha256(("OPEL_NCDX_DISC:"+vol).encode()).hexdigest()[:32]
        toc=next((x for x in texts if x["volume"]==vol and x["relative_path"].upper()=="CDROM.TOC"),None); ident={}
        if toc:
            try: ident=toc_fields((run/toc["evidence_path"]).read_text())
            except Exception: pass
        meta_json=json.dumps({"volume":vol,"probable_region":REGION_LABELS[vol],"file_count":d["file_count"],"directory_count":d["directory_count"],"identity_fields":ident,"manifest_id":d["manifest_id"],"firmware_present":vol=="CD_7190","software_present":vol=="CD_7190","family":"OPEL NCDx 2010-2011"},ensure_ascii=False)
        db.execute("INSERT OR REPLACE INTO artifacts(artifact_id,source_path,source_type,filename,size,sha256,magic,entropy,created_at,imported_at,analysis_state,analysis_run,relationships_json,artifact_role) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(aid,src,"OPEL_NCDX_DISC",vol,d["total_size"],d["manifest_id"],"ISO9660-mounted-file-tree",None,None,datetime.now().astimezone().isoformat(),"COMPLETE",str(run),meta_json,"native_ncdx_disc"))
        db.execute("DELETE FROM files WHERE artifact_id=?",(aid,))
        for m in d["files"]:
            p=root/m["relative_path"]; role="ncdx_firmware" if m["relative_path"] in firmware_rel else "ncdx_native_db" if Path(m["relative_path"]).suffix.lower() in (".abc",".rd",".stt",".mg1",".mg2",".mg3",".mp0",".rl",".rt",".fea",".cty",".cny",".cfg") else "ncdx_disc_file"; db.execute("INSERT OR REPLACE INTO files(artifact_id,source_path,relative_path,filename,size,sha256,file_type,magic,entropy,is_directory,artifact_role,validation_status,mtime_ns) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(aid,str(p),m["relative_path"],Path(m["relative_path"]).name,m["size"],m["sha256"],m["file_type"],m["magic"],m["entropy"],0,role,"HASHED",m["mtime_ns"]))
        for rel in d["directories"]:
            db.execute("INSERT OR REPLACE INTO files(artifact_id,source_path,relative_path,filename,size,file_type,magic,entropy,is_directory,artifact_role,validation_status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(aid,str(root/rel),rel,Path(rel).name,0,"directory","",0.0,1,"ncdx_directory","HASHED"))
    db.commit(); db.close()
    mapping=[]
    for d in manifests:
        toc=next((x for x in texts if x["volume"]==d["volume"] and x["relative_path"].upper()=="CDROM.TOC"),None); fields={}
        if toc: fields=toc_fields((run/toc["evidence_path"]).read_text())
        mapping.append({"volume":d["volume"],"region":fields.get("Area",REGION_LABELS[d["volume"]]),"database_prefix":fields.get("db",""),"version":fields.get("Version",""),"date":fields.get("Date",""),"confirmation":"CONFIRMED: CDROM.TOC fields Area/db/Version" if all(k in fields for k in ("Area","db","Version")) else "PROVISIONAL"})
    (run/"data/disc_region_mapping.json").write_text(json.dumps(mapping,indent=2,ensure_ascii=False),encoding="utf-8")
    # Key files for interpreting exact requested questions.
    navexists=bool(navpath); sh4=[x for x in pe if x["machine"]==0x1a6]
    dbextensions=sorted({e.upper() for _,e,_ in allrows if e.upper() in TOKENS or e.upper() in (".ABC",".RD",".STT",".CFG")})
    report=["# NCDx Native Corpus Inventory",f"\nStatus: **COMPLETE** · app {meta['application_version']} · run `{run.name}`","\n## Coverage",f"\nInventoried {len(manifests)} of {len(VOLUMES)} discs, {sum(x['file_count'] for x in manifests)} files, {sum(x['directory_count'] for x in manifests)} directories, {sum(x['total_size'] for x in manifests):,} bytes. Each persistent manifest includes full relative paths, size, SHA256, neutral extension type, first 16 bytes, entropy and directory structure.","\n## Disc identity from CDROM.TOC", "\n|Volume|Area|DB prefix|Version|Date|Validation|\n|---|---|---|---|---|---|"]
    for x in mapping: report.append(f"|{x['volume']}|{x['region']}|{x['database_prefix']}|{x['version']}|{x['date']}|{x['confirmation']}|")
    report += ["\n## Most important findings",f"\n- MRE/Update: **CD_7190** is confirmed as EU 2009Q4, version {next(x['version'] for x in mapping if x['volume']=='CD_7190')}; its `IDIS/`, `LK841/`, and `SW/` trees are present.",f"- PE executables/DLLs: {len(pe)} valid PE files; {len(sh4)} report machine 0x01A6 (Hitachi SH4). See `data/pe_inventory.json`.",f"- NAVIMAIN.EXE: {'present and statically scanned' if navexists else 'not located'}; matching relevant string/file-name hits: {len(navstrings)}. See its PE dependencies and strings in `data/pe_inventory.json`; imports alone do not prove a launch target.",f"- NK.BIN: {'present' if nk else 'not located'}; {nkinfo['extraction_status']}. No filesystem extraction is claimed.",f"- DB_0 relationship: **{correlation['classification']}** under the sampled probes in `data/ncdx_vs_db0_comparison.json`; this is not a full structural equivalence test.","- Native map database extensions remain neutral labels. All suffix counts appear in `data/extension_stats.csv`; no road geometry/routing semantics are assigned from suffixes.","- Candidate geometry/routing files: **not established** by this inventory; next work should compare matched regional file pairs at repeated-record/table level and corroborate against executable read paths.","- Most likely map reader: not proven. Highest-priority firmware target is `LK841/.../WINDOWS/NAVIMAIN.EXE` and its statically recorded dependencies; evidence does not yet establish which component contains the actual reader.","\n## Critical evidence copies",f"\nCopied and byte-verified {len(copied)} selected files from CD_7190 into `evidence/cd_7190/`. Full map files were not copied; NK.BIN is excluded from package membership.","\n## Outputs", "\n- `data/*_manifest.json`: per-disc immutable snapshot.","- `research/ncdx/manifests/*.json`: persistent manifests for disc recognition.","- `data/extension_stats.csv`, `data/disc_region_mapping.json`, `data/firmware_artifacts.json`, `data/pe_inventory.json`.","- `evidence/text/`: decoded text metadata.","- `data/nk_bin_analysis.json`, `data/ncdx_vs_db0_comparison.json`."]
    (run/"REPORT.md").write_text("\n".join(report)+"\n",encoding="utf-8")
    summary=f"NCDx native corpus: 9 discs imported; CD_7190 is EU/MRE + Update per CDROM.TOC. {len(pe)} PE files, {len(sh4)} SH4. NK.BIN: {nkinfo['extraction_status']}. DB_0 comparison: {correlation['classification']}. No next task started."
    (run/"CHATGPT_SUMMARY.txt").write_text(summary+"\n",encoding="utf-8")
    meta["status"]="COMPLETE"; meta["summary"]={"discs":len(manifests),"files":sum(x["file_count"] for x in manifests),"pe_files":len(pe),"sh4_files":len(sh4),"firmware_candidates":len(fw),"ncdx_vs_db0":correlation["classification"],"manifest_ids":{x["volume"]:x["manifest_id"] for x in manifests}}
    finish_run(run,meta,"COMPLETE",meta["summary"]); register_run(project,run,meta)
    log(run,9,"report and catalog complete",started,1,1)
    log(run,10,"creating verified ChatGPT package; large map data and NK.BIN excluded",started,0,1)
    # Extend standard packager filter by holding NK.BIN copies outside the package in a staging temporary directory.
    nkcopies=[x for x in copied if Path(x["relative_path"]).name.upper()=="NK.BIN"]
    withheld=[]
    for x in nkcopies:
        p=run/x["copy_path"]; tmp=run/".withheld"/Path(x["copy_path"]).name; tmp.parent.mkdir(exist_ok=True); p.replace(tmp); withheld.append((tmp,p))
    package=package_run(run)
    for tmp,p in withheld: p.parent.mkdir(parents=True,exist_ok=True); tmp.replace(p)
    package["status"]="READY" if package["status"]=="READY" else package["status"]
    meta=json.loads((run/"run.json").read_text()); meta["summary"]["package"]=package; meta["status"]="COMPLETE"; atomic_json(run/"run.json",meta); register_run(project,run,meta)
    with zipfile.ZipFile(package["path"]) as z:
        if any(Path(n).name.upper()=="NK.BIN" for n in z.namelist()): raise AssertionError("NK.BIN included in package")
    log(run,10,f"package {package['status']}: {package['path']}",started,1,1)
    return {"status":"COMPLETE","run_path":str(run),"package_path":package["path"],"package_status":package["status"],"application_version":meta["application_version"],"disc_count":len(manifests),"files":sum(x["file_count"] for x in manifests),"firmware_candidates":len(fw),"pe_files":len(pe),"sh4_files":len(sh4),"nk_bin":nkinfo["extraction_status"],"navimain_found":navexists,"db0_relationship":correlation["classification"],"extensions":dbextensions}
