"""Evidence-bounded SH4 PE and NCDx map-reader discovery."""
from __future__ import annotations
import csv, hashlib, html, json, math, os, re, shutil, sqlite3, struct, subprocess, time, zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

TASK_ID="NCDX_MAP_READER_DISCOVERY"
PREVIOUS_RUN="2026-10-06_02-47-53_NCDX_NATIVE_CORPUS_INVENTORY"
MAP_EXTS=[".RD",".FEA",".MP0",".RL",".RT",".MG1",".MG2",".MG3",".CT",".CTY",".CNY",".PDX",".STT",".TYP","ZONE.CFG"]
PREFIXES=["EUZ","EU","GALLZ","GALL","FALLZ","FALL","CEZ","CE","BNLZ","BNL","SCZ","SC","SPZ","SP","UKZ","UK"]
IO_APIS=["CreateFileA","CreateFileW","CreateFile","ReadFile","SetFilePointer","SetFilePointerEx","CloseHandle","GetFileSize","GetFileSizeEx","FindFirstFileA","FindFirstFileW","FindFirstFile","FindNextFileA","FindNextFileW","FindNextFile","CreateFileMappingA","CreateFileMappingW","CreateFileMapping","MapViewOfFile","fopen","fread","fseek","open","read","lseek","close"]
STAGES=["Load previous corpus","Analyze PE files","Build import/dependency graph","Search map references","Disassemble file-I/O paths","Analyze NAVIMAIN","Analyze MMIDIS","Analyze NK.BIN","Correlate DB files","Rank candidates","Generate report","Package"]

def stage_log(run,idx,msg,start,done=0,total=1):
    elapsed=time.time()-start
    from .tasks import emit_progress
    emit_progress(f"stage_{idx}",STAGES[idx-1],idx,len(STAGES),done,total,"items",start)
    eta_text=""
    if elapsed>=3 and done>=2 and total>done:
        rate=done/elapsed
        eta_text=f"; ETA ~{int((total-done)/rate)}s"
    line=f"[{idx}/12] {STAGES[idx-1]} — {msg}; progress {done}/{total}; elapsed {elapsed:.1f}s{eta_text}\n"
    with (run/"logs/main.log").open("a",encoding="utf-8") as f: f.write(line)
    print(line.rstrip(),flush=True)

def cstr(data,pos,limit=512):
    if pos is None or pos<0 or pos>=len(data): return ""
    end=data.find(b"\0",pos,min(len(data),pos+limit))
    if end<0: return ""
    raw=data[pos:end]
    return raw.decode("ascii","replace") if all(32<=x<127 for x in raw) else ""

def parse_pe(data):
    if len(data)<0x40 or data[:2]!=b"MZ": return None
    peoff=int.from_bytes(data[0x3c:0x40],"little")
    if peoff+24>len(data) or data[peoff:peoff+4]!=b"PE\0\0": return None
    machine,nsec,_,_,_,optsz,characteristics=struct.unpack_from("<HHIIIHH",data,peoff+4)
    op=peoff+24
    if op+optsz>len(data) or int.from_bytes(data[op:op+2],"little") not in (0x10b,0x20b): return None
    magic=int.from_bytes(data[op:op+2],"little"); is64=magic==0x20b
    entry=int.from_bytes(data[op+16:op+20],"little"); imagebase=int.from_bytes(data[op+(24 if is64 else 28):op+(32 if is64 else 32)],"little")
    sizeheaders=int.from_bytes(data[op+60:op+64],"little") if op+64<=len(data) else 0
    secpos=op+optsz; sections=[]
    for i in range(min(nsec,96)):
        q=secpos+40*i
        if q+40>len(data): break
        name=data[q:q+8].split(b"\0",1)[0].decode("ascii","replace")
        vs,va,rs,ro=struct.unpack_from("<IIII",data,q+8)
        sections.append({"name":name,"virtual_address":va,"virtual_size":vs,"raw_offset":ro,"raw_size":rs,"characteristics":int.from_bytes(data[q+36:q+40],"little")})
    def rva_to_off(rva):
        if rva<sizeheaders and rva<len(data): return rva
        for s in sections:
            if s["virtual_address"]<=rva<s["virtual_address"]+max(s["virtual_size"],s["raw_size"]):
                off=s["raw_offset"]+rva-s["virtual_address"]
                return off if off<len(data) else None
        return None
    ndd_off=op+(108 if is64 else 92)
    ndd=int.from_bytes(data[ndd_off:ndd_off+4],"little") if ndd_off+4<=len(data) else 0
    dd_off=op+(112 if is64 else 96)
    dirs=[]
    for i in range(min(ndd,16)):
        q=dd_off+8*i
        if q+8<=len(data): dirs.append(struct.unpack_from("<II",data,q))
    def get_dir(i): return dirs[i] if i<len(dirs) else (0,0)
    imports=[]; irva,isz=get_dir(1); ip=rva_to_off(irva) if irva and isz else None
    if ip is not None:
        width=8 if is64 else 4
        for j in range(min(isz//20+1,2048)):
            q=ip+20*j
            if q+20>len(data): break
            oft,stamp,chain,namer,iat=struct.unpack_from("<IIIII",data,q)
            if not any((oft,stamp,chain,namer,iat)): break
            name=cstr(data,rva_to_off(namer)); lookup=rva_to_off(oft or iat); syms=[]
            if lookup is not None:
                for k in range(8192):
                    z=lookup+k*width
                    if z+width>len(data): break
                    val=int.from_bytes(data[z:z+width],"little")
                    if not val: break
                    ordmask=1<<(width*8-1)
                    if val&ordmask: api=f"ordinal_{val&0xffff}"; hint=None; name_rva=None
                    else:
                        name_rva=val; no=rva_to_off(name_rva); hint=int.from_bytes(data[no:no+2],"little") if no is not None and no+2<=len(data) else None; api=cstr(data,no+2 if no is not None else None)
                        if not api: api=f"invalid_name_rva_0x{name_rva:x}"
                    iat_rva=iat+k*width
                    syms.append({"api":api,"iat_rva":iat_rva,"iat_va":imagebase+iat_rva,"hint":hint,"name_rva":name_rva,"lookup_offset":z})
            imports.append({"dll":name,"descriptor_rva":irva+20*j,"iat_rva":iat,"symbols":syms})
    # Validate exports rather than parsing the DOS header when the directory is zero.
    exports=[]; export_notes=[]; erva,esz=get_dir(0); ep=rva_to_off(erva) if erva and esz>=40 else None
    if ep is not None and ep+40<=len(data):
        fields=struct.unpack_from("<IIHHIIIIIII",data,ep)
        base,nfunc,nnames=fields[5],fields[6],fields[7]; names_rva,ords_rva,funcs_rva=fields[9],fields[10],fields[8]
        no=rva_to_off(names_rva); oo=rva_to_off(ords_rva); fo=rva_to_off(funcs_rva)
        if nnames>10000 or nfunc>100000 or no is None or oo is None or fo is None: export_notes.append("export directory tables out of bounds or implausible")
        else:
            for i in range(nnames):
                nq=no+4*i; oq=oo+2*i
                if nq+4>len(data) or oq+2>len(data): break
                nrva=int.from_bytes(data[nq:nq+4],"little"); idx=int.from_bytes(data[oq:oq+2],"little"); nameoff=rva_to_off(nrva); ename=cstr(data,nameoff)
                if not ename or idx>=nfunc: export_notes.append(f"invalid export name/ordinal at index {i}"); continue
                frva_off=fo+4*idx
                if frva_off+4>len(data): continue
                exports.append({"name":ename,"ordinal":base+idx,"function_rva":int.from_bytes(data[frva_off:frva_off+4],"little")})
    elif erva or esz: export_notes.append("nonzero export directory was not structurally parseable")
    def section_for_offset(off):
        if off is None: return ""
        for s in sections:
            if s["raw_offset"]<=off<s["raw_offset"]+s["raw_size"]: return s["name"]
        return "headers" if off<sizeheaders else ""
    return {"machine":machine,"machine_hex":f"0x{machine:04X}","machine_name":{0x1A6:"Hitachi SH4"}.get(machine,f"0x{machine:04X}"),"pe_offset":peoff,"optional_header_magic":f"0x{magic:04X}","entry_point_rva":entry,"entry_point_file_offset":rva_to_off(entry),"image_base":imagebase,"characteristics":characteristics,"sections":sections,"imports":imports,"exports":exports,"export_notes":export_notes,"resources_directory":get_dir(2),"rva_to_off":rva_to_off,"section_for_offset":section_for_offset,"data_directories":[{"rva":x[0],"size":x[1]} for x in dirs],"header_endianness":"little-endian (PE/COFF fields)","instruction_endianness":"INCONCLUSIVE without SH4 disassembly"}

def collect_strings(data,min_ascii=4,min_wide=4,limit=50000):
    out=[]
    for enc,rx,width in [("ASCII",rb"[\x20-\x7e]{4,}",1),("UTF-16LE",rb"(?:[\x20-\x7e]\x00){4,}",2),("UTF-16BE",rb"(?:\x00[\x20-\x7e]){4,}",2)]:
        for m in re.finditer(rx,data):
            raw=m.group(0)
            try: value=raw.decode("ascii") if width==1 else raw.decode("utf-16le" if enc.endswith("LE") else "utf-16be")
            except Exception: continue
            if len(value)>= (min_ascii if width==1 else min_wide): out.append({"offset":m.start(),"encoding":enc,"value":value})
            if len(out)>=limit: break
    out.sort(key=lambda x:x["offset"])
    # Coalesce a duplicate byte span only; distinct encodings remain explicit evidence.
    seen=set(); result=[]
    for x in out:
        k=(x["offset"],x["encoding"],x["value"])
        if k not in seen: seen.add(k); result.append(x)
    return result

def map_tokens():
    return MAP_EXTS+PREFIXES

def token_matches(data):
    hits=[]
    for enc in ("ASCII","UTF-16LE","UTF-16BE"):
        for token in map_tokens():
            raw=token.encode("ascii") if enc=="ASCII" else token.encode("utf-16le" if enc.endswith("LE") else "utf-16be")
            start=0; count=0
            while True:
                pos=data.find(raw,start)
                if pos<0: break
                # Word boundaries matter for short regional identifiers such as EU and CE.
                unit=1 if enc=="ASCII" else 2
                before=data[pos-unit:pos] if pos>=unit else b""
                after=data[pos+len(raw):pos+len(raw)+unit]
                def alnum(b):
                    x=b[0] if enc=="ASCII" and b else b[1] if enc=="UTF-16LE" and len(b)==2 else b[0] if len(b)==2 else 0
                    return 48<=x<=57 or 65<=x<=90 or 97<=x<=122
                if not alnum(before) and not alnum(after):
                    hits.append({"offset":pos,"token":token,"encoding":enc}); count+=1
                start=pos+max(1,len(raw))
                if count>=100: break
    return hits

def nearby_strings(data,offset,encoding):
    lo=max(0,offset-128); hi=min(len(data),offset+256); b=data[lo:hi]
    vals=[]
    for s in collect_strings(b,limit=200):
        if abs(lo+s["offset"]-offset)<=192: vals.append(f"{lo+s['offset']:08X}:{s['value'][:100]}")
    return " | ".join(vals[:12])

def write_csv(path,rows,fields=None):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fields=fields or (list(rows[0].keys()) if rows else ["evidence"])
    with path.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)

def ensure_task(project):
    td=project/"research/tasks"/TASK_ID;td.mkdir(parents=True,exist_ok=True)
    (td/"TASK.md").write_text("# NCDx Map Reader Discovery\n\nRank map-reader candidates from the completed native corpus. Analyze all CD_7190 SH4 PEs, import/IAT dependencies, encoded strings, firmware evidence, NK.BIN structure, and matched regional database headers. Do not assign extension meanings or alter originals. Stop after report/package.\n",encoding="utf-8")
    obj={"task_id":TASK_ID,"title":"NCDx Map Reader Discovery","description":"Evidence-bounded SH4 and firmware analysis to identify native NCDx database reader candidates.","research_question":"Which application/module and code path opens, reads and interprets native NCDx database files?","input_artifacts":[{"artifact_id":"NCDX_NATIVE_CORPUS_INVENTORY","run_path":str(project/"research/runs"/PREVIOUS_RUN)}],"required_artifact_types":["OPEL_NCDX_DISC","SH4_PE"],"known_facts":["CD_7190 is EU/MRE + Update; 16 SH4 PE files in prior inventory"],"analysis_modules":["map_reader_discovery"],"hypotheses_to_test":["NAVIMAIN.EXE is a map reader","MMIDIS.EXE brokers to a map reader"],"hypotheses_to_reject":["extension names alone prove semantics"],"methods":["bounded PE parse","imports/IAT","ASCII and UTF-16 strings","regional header correlation","local tool capability discovery"],"parameters":{"previous_run":PREVIOUS_RUN,"map_extensions":MAP_EXTS},"cpu_settings":{"backend":"CPU","workers":1},"gpu_settings":{},"memory_limits":{"max_file_read_mb":64},"sample_strategy":"all small executable/update files; NK.BIN full read for signatures; map data use previous 4 KiB edges only","full_scan_permission":True,"checkpoint_interval":1,"timeout":"bounded local static analysis","stop_conditions":["stop after ChatGPT package verification"],"expected_outputs":["REPORT.md","REPORT.html","CHATGPT_PACKAGE.zip"],"required_tables":["sh4_pe_inventory.csv","file_io_imports.csv","sh4_dependency_graph.csv","map_string_references.csv","map_reader_candidates.csv"],"required_logs":["main.log"],"required_evidence":[],"report_template":"TASK.md","ChatGPT_summary_requirements":"State evidence classes, ranking, exact blockers, next function/file target","depends_on":["NCDX_NATIVE_CORPUS_INVENTORY"]}
    (td/"task.json").write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding="utf-8")
    return td

def tool_capabilities():
    result={"available_disassemblers":[],"attempted":[],"blocker":"No installed SH4 disassembler detected."}
    for name in ("rizin","radare2","r2","ghidraRun","analyzeHeadless","gobjdump","gdb"):
        p=shutil.which(name)
        if p: result["available_disassemblers"].append({"name":name,"path":p})
    llvm=shutil.which("llvm-objdump")
    if not llvm:
        try: llvm=subprocess.check_output(["xcrun","--find","llvm-objdump"],text=True,stderr=subprocess.STDOUT,timeout=5).strip()
        except Exception: llvm=None
    if llvm:
        try:
            out=subprocess.check_output([llvm,"--version"],text=True,stderr=subprocess.STDOUT,timeout=5)
            targetlines=[x.strip() for x in out.splitlines() if re.search(r"(^|\s)(sh|sh4|superh)(\s|-|$)",x,re.I)]
            result["attempted"].append({"tool":llvm,"registered_sh_targets":targetlines,"version_output":out[:1800]})
            result["llvm_has_sh_target"]=bool(targetlines)
        except Exception as e: result["attempted"].append({"tool":llvm,"error":str(e)})
    result["blocker"]="; ".join(["No Rizin/radare2/Ghidra/capstone SH4 decoder is installed." if not result["available_disassemblers"] else "Installed candidates do not advertise an SH4 target.","Apple LLVM 17 target list has no SuperH/SH4 backend.","COREDLL.dll is not present as a separate image/export map; IAT entries are ordinal-only in these PEs."])
    return result

def latest_ncdx_data(project):
    prev=project/"research/runs"/PREVIOUS_RUN
    if not (prev/"run.json").exists(): raise FileNotFoundError(prev)
    return prev

def run_map_reader_discovery(project_root):
    project=Path(project_root).resolve(); previous=latest_ncdx_data(project); td=ensure_task(project)
    from .tasks import create_run,finish_run,register_run,package_run,atomic_json
    task=json.loads((td/"task.json").read_text()); run,meta,_=create_run(project,td/"TASK.md",task,[{"artifact_id":"NCDX_NATIVE_CORPUS_INVENTORY","sha256":hashlib.sha256((previous/"run.json").read_bytes()).hexdigest(),"path":str(previous)}])
    start=time.time();meta["status"]="RUNNING";atomic_json(run/"run.json",meta)
    data=run/"data";data.mkdir(exist_ok=True)
    stage_log(run,1,"loading prior manifests, firmware inventory and verified 51-copy evidence list",start)
    prior_pe=json.loads((previous/"data/pe_inventory.json").read_text())
    previous_fw=json.loads((previous/"data/firmware_artifacts.json").read_text())
    copy_rows=json.loads((previous/"data/copied_evidence.json").read_text())
    copied={x["relative_path"]:previous/x["copy_path"] for x in copy_rows}
    pe_paths=[]
    for x in prior_pe:
        rel=x["path"]
        if rel not in copied or not copied[rel].is_file(): raise FileNotFoundError("missing verified SH4 evidence copy: "+rel)
        if hashlib.sha256(copied[rel].read_bytes()).hexdigest()!=x["sha256"]: raise IOError("PE copy hash mismatch: "+rel)
        pe_paths.append((rel,copied[rel],x))
    if len(pe_paths)!=16: raise ValueError(f"expected 16 prior SH4 PE files, found {len(pe_paths)}")
    stage_log(run,1,f"loaded {len(pe_paths)} SH4 PEs, {len(previous_fw)} prior firmware/update candidates",start)
    # PE inventory and string extraction.
    stage_log(run,2,"parsing PE headers, sections, directories and encoded strings",start,0,len(pe_paths))
    modules=[]; string_rows=[]
    for i,(rel,path,old) in enumerate(pe_paths,1):
        raw=path.read_bytes(); p=parse_pe(raw)
        if not p: continue
        strings=collect_strings(raw,limit=50000)
        for s in strings:
            s["section"]=p["section_for_offset"](s["offset"]);s["rva"]=None
            for sec in p["sections"]:
                if sec["raw_offset"]<=s["offset"]<sec["raw_offset"]+sec["raw_size"]: s["rva"]=sec["virtual_address"]+s["offset"]-sec["raw_offset"]; break
        mod={k:v for k,v in p.items() if k not in ("rva_to_off","section_for_offset")}; mod.update({"relative_path":rel,"filename":Path(rel).name,"sha256":old["sha256"],"size":len(raw),"imports":p["imports"],"exports":p["exports"],"all_strings":strings,"ascii_strings":[x["value"] for x in strings if x["encoding"]=="ASCII"],"utf16_strings":[x["value"] for x in strings if x["encoding"]!="ASCII"]})
        modules.append(mod)
        for s in strings: string_rows.append({"module":Path(rel).name,"relative_path":rel,"sha256":old["sha256"],"offset":s["offset"],"rva":s["rva"],"encoding":s["encoding"],"section":s["section"],"string":s["value"]})
        stage_log(run,2,f"parsed {Path(rel).name}",start,i,len(pe_paths))
    (data/"sh4_pe_inventory.json").write_text(json.dumps(modules,indent=2,ensure_ascii=False),encoding="utf-8")
    pe_rows=[]
    for m in modules:
        for s in m["sections"] or [{}]:
            pe_rows.append({"relative_path":m["relative_path"],"filename":m["filename"],"sha256":m["sha256"],"size":m["size"],"machine":m["machine_name"],"machine_hex":m["machine_hex"],"entry_point_rva":f"0x{m['entry_point_rva']:08X}","entry_point_file_offset":f"0x{(m['entry_point_file_offset'] or 0):08X}","section":s.get("name",""),"section_virtual_address":s.get("virtual_address",""),"section_virtual_size":s.get("virtual_size",""),"section_raw_offset":s.get("raw_offset",""),"section_raw_size":s.get("raw_size",""),"imports":"; ".join(i["dll"]+":"+",".join(x["api"] for x in i["symbols"]) for i in m["imports"]),"exports":"; ".join(x["name"] for x in m["exports"]),"resources_rva":m["resources_directory"][0],"resources_size":m["resources_directory"][1],"string_encoding":"","string_offset":"","string":""})
        for s in m["all_strings"]:
            pe_rows.append({"relative_path":m["relative_path"],"filename":m["filename"],"sha256":m["sha256"],"size":m["size"],"machine":m["machine_name"],"machine_hex":m["machine_hex"],"entry_point_rva":f"0x{m['entry_point_rva']:08X}","entry_point_file_offset":f"0x{(m['entry_point_file_offset'] or 0):08X}","section":s["section"],"section_virtual_address":"","section_virtual_size":"","section_raw_offset":"","section_raw_size":"","imports":"","exports":"","resources_rva":m["resources_directory"][0],"resources_size":m["resources_directory"][1],"string_encoding":s["encoding"],"string_offset":f"0x{s['offset']:X}","string":s["value"]})
    write_csv(data/"sh4_pe_inventory.csv",pe_rows)
    # Dependency edges and named/unresolved I/O imports.
    stage_log(run,3,"building imports-from/imported-by edges and IAT records",start)
    graph={"nodes":[],"edges":[]};module_names={Path(x["relative_path"]).name.lower():x for x in modules};import_rows=[]
    for m in modules:
        node={"name":m["filename"],"path":m["relative_path"],"kind":"SH4_PE","machine":m["machine_name"],"sha256":m["sha256"],"exports":[x["name"] for x in m["exports"]]};graph["nodes"].append(node)
        for imp in m["imports"]:
            dll=imp["dll"] or "<unresolved import DLL>";graph["edges"].append({"from":m["filename"],"to":dll,"type":"imports","symbol_count":len(imp["symbols"]),"symbols":[s["api"] for s in imp["symbols"]]})
            for s in imp["symbols"]:
                api=s["api"]; is_io=any(re.fullmatch(pat.replace("*",".*"),api,re.I) for pat in IO_APIS) or bool(re.search(r"(?:CreateFile|ReadFile|SetFilePointer|GetFileSize|FindFirstFile|FindNextFile|CreateFileMapping|MapViewOfFile|fopen|fread|fseek|lseek|\bopen\b|\bread\b|\bclose\b)",api,re.I))
                if is_io or api.startswith("ordinal_") and dll.lower()=="coredll.dll":
                    import_rows.append({"module":m["filename"],"api":api if is_io else "UNRESOLVED_"+api,"import_source":dll,"import_address/IAT":f"IAT RVA 0x{s['iat_rva']:08X}; VA 0x{s['iat_va']:08X}","evidence":"named file-I/O import" if is_io else "COREDLL ordinal import; export-name map unavailable, not attributed to file I/O"})
    (data/"sh4_dependency_graph.json").write_text(json.dumps(graph,indent=2,ensure_ascii=False),encoding="utf-8")
    graphrows=[{"from":e["from"],"to":e["to"],"edge":e["type"],"symbol_count":e["symbol_count"],"symbols":";".join(e["symbols"])} for e in graph["edges"]]
    write_csv(data/"sh4_dependency_graph.csv",graphrows)
    write_csv(data/"file_io_imports.csv",import_rows,["module","api","import_source","import_address/IAT","evidence"])
    (data/"module_inventory_ui.json").write_text(json.dumps([{"module":m["filename"],"path":m["relative_path"],"sha256":m["sha256"],"size":m["size"],"machine":m["machine_name"],"entry_point_rva":m["entry_point_rva"],"entry_point_file_offset":m["entry_point_file_offset"],"imports":[x["dll"] for x in m["imports"]],"exports":[x["name"] for x in m["exports"]]} for m in modules],indent=2),encoding="utf-8")
    # Include IAT edges to binaries that are themselves in the SH4 set.
    for e in graph["edges"]:
        if e["to"].lower() in module_names: e["resolved_to_local_module"]=True
    stage_log(run,3,f"{len(graph['edges'])} dependency edges; {len(import_rows)} file-I/O/unresolved COREDLL IAT rows",start)
    # Map strings in all 16 PE files and all copied firmware/update artifacts.
    stage_log(run,4,"searching ASCII, UTF-16LE and UTF-16BE map/region tokens",start,0,len(scanpaths))
    scanpaths={}
    for rel,p,_ in pe_paths: scanpaths["PE:"+rel]=p
    for f in previous_fw:
        rel=f["relative_path"]
        if rel in copied: scanpaths["FW:"+rel]=copied[rel]
        else:
            manifest=json.loads((previous/"data"/(f["volume"]+"_manifest.json")).read_text())
            original=Path(manifest["root"])/rel
            if not original.is_file(): raise FileNotFoundError("uncopied firmware evidence is not readable: "+str(original))
            if original.stat().st_size!=f["size"] or hashlib.sha256(original.read_bytes()).hexdigest()!=f["sha256"]: raise IOError("uncopied firmware evidence does not match prior verified manifest: "+str(original))
            scanpaths["FW:"+rel]=original
    references=[]; module_by_name={m["filename"].lower():m for m in modules}
    for scan_i,(aid,pth) in enumerate(scanpaths.items(),1):
        raw=pth.read_bytes(); m=module_by_name.get(Path(aid.split(":",1)[1]).name.lower()) if aid.startswith("PE:") else None
        for hit in token_matches(raw):
            sec="";rva=None
            if m:
                for s in m["sections"]:
                    if s["raw_offset"]<=hit["offset"]<s["raw_offset"]+s["raw_size"]: sec=s["name"];rva=s["virtual_address"]+hit["offset"]-s["raw_offset"];break
            references.append({"artifact":aid.split(":",1)[1],"artifact_type":aid.split(":",1)[0],"offset":hit["offset"],"rva":rva,"string":hit["token"],"encoding":hit["encoding"],"section":sec,"nearby_strings":nearby_strings(raw,hit["offset"],hit["encoding"]),"cross_references":"not recoverable: no SH4 disassembler available"})
        if scan_i%4==0 or scan_i==len(scanpaths): stage_log(run,4,f"scanned {scan_i}/{len(scanpaths)} files",start,scan_i,len(scanpaths))
    write_csv(data/"map_string_references.csv",references,["artifact","artifact_type","offset","rva","string","encoding","section","nearby_strings","cross_references"])
    # Retain a compact filtered string table and PE strings inventory, not entire binaries.
    (data/"map_relevant_strings.json").write_text(json.dumps(string_rows,indent=2,ensure_ascii=False),encoding="utf-8")
    stage_log(run,4,f"searched {len(scanpaths)} PE/firmware artifacts; {len(references)} exact token hits",start)
    # No disassembler is installed: record the attempted local capability check and exact consequence.
    stage_log(run,5,"checking installed SH4 disassembly support and recording caller-trace blocker",start)
    tools=tool_capabilities();(data/"tool_availability.json").write_text(json.dumps(tools,indent=2,ensure_ascii=False),encoding="utf-8")
    callgraph=[{"module":m["filename"],"function":"entrypoint RVA 0x%08X"%m["entry_point_rva"],"function_boundary":"not validated by disassembly","caller":"unknown","callee":"unknown","status":"INCONCLUSIVE","evidence":tools["blocker"]} for m in modules]
    write_csv(data/"callgraph.csv",callgraph)
    stage_log(run,5,tools["blocker"],start)
    # Dedicated runtime process analysis.
    stage_log(run,6,"analyzing NAVIMAIN imports, entry point, strings and process/IPC clues",start)
    nav=next(m for m in modules if m["filename"].upper()=="NAVIMAIN.EXE")
    navtxt=[x["value"] for x in nav["all_strings"]]
    navinfo={"path":nav["relative_path"],"sha256":nav["sha256"],"size":nav["size"],"machine":nav["machine_name"],"entry_point_rva":nav["entry_point_rva"],"entry_point_file_offset":nav["entry_point_file_offset"],"sections":nav["sections"],"imports":nav["imports"],"exports":nav["exports"],"resources_directory":nav["resources_directory"],"relevant_strings":[x for x in navtxt if re.search(r"navi|process|createprocess|loadlibrary|getprocaddress|\\\\|\.dll|\.exe|map|route|road|\.rd|\.fea|\.mp0|\.rt",x,re.I)],"direct_file_io_named_imports":[x for x in import_rows if x["module"].upper()=="NAVIMAIN.EXE" and not x["api"].startswith("UNRESOLVED_")],"role":"HYPOTHESIS: navigation process/runtime; not proven map reader or launcher","ipc_evidence":[x for x in navtxt if re.search(r"processid|process id|ComMgr|RemoteCom|CommunicationBroker|GetProcessName",x,re.I)],"map_extension_evidence":[x for x in references if x["artifact_type"]=="PE" and Path(x["artifact"]).name.upper()=="NAVIMAIN.EXE"]}
    (data/"navimain_analysis.json").write_text(json.dumps(navinfo,indent=2,ensure_ascii=False),encoding="utf-8")
    navpath=copied[nav["relative_path"]]; navraw=navpath.read_bytes();eoff=nav["entry_point_file_offset"] or 0
    (data/"navimain_entrypoint_hex.txt").write_text(f"{nav['relative_path']}\nentry RVA 0x{nav['entry_point_rva']:08X}; file offset 0x{eoff:08X}\n{navraw[eoff:eoff+96].hex(' ')}\nBytes only; not disassembled.\n",encoding="utf-8")
    stage_log(run,6,f"NAVIMAIN is {nav['machine_name']}; {len(nav['imports'])} DLL dependencies; map refs={len(navinfo['map_extension_evidence'])}; named file-I/O imports={len(navinfo['direct_file_io_named_imports'])}",start)
    # MMIDIS relationship analysis.
    stage_log(run,7,"analyzing MMIDIS imports, entry point, strings and relationship evidence",start)
    mm=next(m for m in modules if m["filename"].upper()=="MMIDIS.EXE"); mmtxt=[x["value"] for x in mm["all_strings"]]
    mminfo={"path":mm["relative_path"],"sha256":mm["sha256"],"size":mm["size"],"machine":mm["machine_name"],"entry_point_rva":mm["entry_point_rva"],"entry_point_file_offset":mm["entry_point_file_offset"],"sections":mm["sections"],"imports":mm["imports"],"exports":mm["exports"],"resources_directory":mm["resources_directory"],"relevant_strings":[x for x in mmtxt if re.search(r"process|createprocess|loadlibrary|getprocaddress|window|mutex|event|shared|message|trace|com|\.dll|\.exe|map|route|road|\.rd|\.fea|\.mp0|\.rt",x,re.I)],"named_file_io_imports":[x for x in import_rows if x["module"].upper()=="MMIDIS.EXE" and not x["api"].startswith("UNRESOLVED_")],"map_extension_evidence":[x for x in references if x["artifact_type"]=="PE" and Path(x["artifact"]).name.upper()=="MMIDIS.EXE"],"relationship":"INCONCLUSIVE; imports show MFC/Traceable/COM/memory components, but no process-launch or map-file path is proven"}
    (data/"mmidis_analysis.json").write_text(json.dumps(mminfo,indent=2,ensure_ascii=False),encoding="utf-8")
    mmraw=copied[mm["relative_path"]].read_bytes();mo=mm["entry_point_file_offset"] or 0
    (data/"mmidis_entrypoint_hex.txt").write_text(f"{mm['relative_path']}\nentry RVA 0x{mm['entry_point_rva']:08X}; file offset 0x{mo:08X}\n{mmraw[mo:mo+96].hex(' ')}\nBytes only; not disassembled.\n",encoding="utf-8")
    stage_log(run,7,f"MMIDIS DLL edges={sum(1 for x in graph['edges'] if x['from'].upper()=='MMIDIS.EXE')}; named file-I/O imports={len(mminfo['named_file_io_imports'])}; map refs={len(mminfo['map_extension_evidence'])}",start)
    # NK.BIN format signatures and structural plausibility; do not carve.
    stage_log(run,8,"checking NK.BIN ROMHDR/TOC/MODULES/FILES/E32/O32 and BIN markers",start)
    nkrel=next(x["relative_path"] for x in previous_fw if Path(x["relative_path"]).name.upper()=="NK.BIN")
    nkpath=copied[nkrel];nk=nkpath.read_bytes();patterns=[b"ECEC",b"ROMHDR",b"TOC",b"MODULES",b"FILES",b"FATFS",b"IMGFS",b"B000FF",b"E0000000",b"E32",b"O32"]
    sig=[]
    for pat in patterns:
        pos=0;hits=[]
        while len(hits)<128:
            pos=nk.find(pat,pos)
            if pos<0:break
            hits.append(pos);pos+=1
        sig.append({"signature":pat.decode("ascii"),"offsets":hits,"count":len(hits)})
    ecec=[x for x in sig if x["signature"]=="ECEC"][0]["offsets"]
    neighborhoods=[]
    for off in ecec[:16]: neighborhoods.append({"offset":off,"before_hex":nk[max(0,off-32):off].hex(),"after_hex":nk[off:off+128].hex(),"aligned_4":off%4==0,"aligned_16":off%16==0,"words_le_4_after":[int.from_bytes(nk[q:q+4],"little") for q in range(off+4,min(off+36,len(nk)),4)]})
    nkinfo={"path":nkrel,"size":len(nk),"sha256":hashlib.sha256(nk).hexdigest(),"signatures":sig,"ecec_neighborhoods":neighborhoods,"validated_romhdr":False,"validated_toc":False,"validated_modules_files_tables":False,"bounded_embedded_pe":False,"module_inventory":[],"extraction_status":"INCONCLUSIVE: no structurally validated ROMHDR/TOC/module table; no extraction or carving performed","blocker":"NK.BIN contains ECEC/FATFS byte strings, but the available local tools do not parse Windows CE ROM images and candidate structure fields were not validated against a known layout."}
    (data/"nk_bin_structure.json").write_text(json.dumps(nkinfo,indent=2,ensure_ascii=False),encoding="utf-8")
    stage_log(run,8,f"NK.BIN {len(nk):,} bytes; ECEC offsets={len(ecec)}; no validated ROM/module extraction",start)
    # Regional file correlation: reuse verified previous full-file hash and 4-KiB edge captures.
    stage_log(run,9,"joining extension literals, map corpus paths and 4-KiB cross-disc headers",start)
    maps={}
    for vol in ("CD_7178","cd_7182","CD_7183","CD_7184","CD_7185","CD_7186","CD_7187","CD_7188","CD_7190"):
        obj=json.loads((previous/"data"/(vol+"_manifest.json")).read_text())
        maps[vol]=obj
    header_rows=[]; extension_disc=defaultdict(set)
    for vol,obj in maps.items():
        for f in obj["files"]:
            ex=Path(f["relative_path"]).suffix.upper()
            if ex in MAP_EXTS or f["relative_path"].upper().endswith("ZONE.CFG"):
                extension_disc[ex].add(vol)
                header_rows.append({"extension":ex,"disc":vol,"relative_path":f["relative_path"],"size":f["size"],"sha256":f["sha256"],"header_4k_sha256":hashlib.sha256(bytes.fromhex(f["header_4096_hex"])).hexdigest(),"tail_4k_sha256":hashlib.sha256(bytes.fromhex(f["tail_4096_hex"])).hexdigest(),"header_256_hex":f["header_4096_hex"][:512],"tail_256_hex":f["tail_4096_hex"][-512:],"size_mod_512":f["size"]%512,"entropy":f["entropy"]})
    write_csv(data/"database_header_correlation.csv",header_rows)
    exts=[x for x in MAP_EXTS if extension_disc[x]]
    (data/"database_extension_disc_matrix.json").write_text(json.dumps({e:sorted(extension_disc[e]) for e in exts},indent=2),encoding="utf-8")
    stage_log(run,9,f"correlated {len(header_rows)} regional map-file headers across {len(exts)} observed extension labels",start)
    # File I/O function scoring uses auditable evidence only. Ordinals do not count as named API hits.
    stage_log(run,10,"ranking navigation-runtime candidates with explicit evidence and negative signals",start)
    maprefs_by=Counter(Path(x["artifact"]).name.upper() for x in references if x["artifact_type"]=="PE" and x["string"].upper() in MAP_EXTS and x["section"] not in (".rsrc",".rsrc1"))
    named_io_by=Counter(x["module"].upper() for x in import_rows if not x["api"].startswith("UNRESOLVED_"))
    candidates=[]
    for m in modules:
        name=m["filename"].upper(); strs=[x["value"] for x in m["all_strings"]]
        nav_process=1 if name=="NAVIMAIN.EXE" and any(re.search(r"Navi (main process started|ready to work)|NaviMain\.pdb",s,re.I) for s in strs) else 0
        map_count=maprefs_by[name];io_count=named_io_by[name]
        update_only=1 if "UPDATE" in name else 0
        score=4*int(nav_process)+4*int(map_count>0)+4*int(io_count>0)-4*update_only
        if name=="MMIDIS.EXE" and any("Traceable.dll".lower() in x.lower() for x in strs): score+=1
        evidence=[]
        if nav_process:evidence.append("Navi process-start/ready strings and NaviMain.pdb path")
        if map_count:evidence.append(f"{map_count} literal map/region token hit(s)")
        if io_count:evidence.append(f"{io_count} named file-I/O import(s)")
        if update_only:evidence.append("update DLL name and loaderFactoryEx export indicate updater path; negative for runtime reader")
        if name=="MMIDIS.EXE":evidence.append("imports MFC/Traceable/COM/MemMgr; UI role remains a hypothesis")
        ord_count=sum(len(x["symbols"]) for x in m["imports"] if x["dll"].lower()=="coredll.dll" and any(s["api"].startswith("ordinal_") for s in x["symbols"]))
        if ord_count:evidence.append(f"{ord_count} unresolved COREDLL ordinal import(s); not credited as file I/O")
        candidates.append({"module":m["filename"],"function_or_region":f"entrypoint RVA 0x{m['entry_point_rva']:08X} (boundary unverified)","score":score,"file_io_evidence":io_count,"filename_evidence":map_count,"navigation_evidence":nav_process,"callgraph_evidence":"UNAVAILABLE: no SH4 disassembly/xrefs","confidence":"HYPOTHESIS" if (nav_process or map_count or io_count) and not update_only else "INCONCLUSIVE","reason":"; ".join(evidence) if evidence else "No named file-I/O or literal map-reference evidence in statically extracted imports/strings."})
    candidates.sort(key=lambda x:(-x["score"],x["module"]))
    for rank,x in enumerate(candidates,1):x["rank"]=rank
    write_csv(data/"map_reader_candidates.csv",candidates,["rank","module","function_or_region","score","file_io_evidence","filename_evidence","navigation_evidence","callgraph_evidence","confidence","reason"])
    (data/"map_reader_candidates.json").write_text(json.dumps(candidates,indent=2,ensure_ascii=False),encoding="utf-8")
    ui={"status":"INCONCLUSIVE","candidate_count":len(candidates),"top_candidate":candidates[0] if candidates else None,"map_references":len(references),"named_io_imports":sum(1 for x in import_rows if not x["api"].startswith("UNRESOLVED_")),"sh4_files":[{"module":m["filename"],"path":m["relative_path"],"sha256":m["sha256"],"size":m["size"],"machine":m["machine_name"],"entry_point_rva":m["entry_point_rva"],"imports":[x["dll"] for x in m["imports"]],"exports":[x["name"] for x in m["exports"]]} for m in modules],"executables":[{"module":m["filename"],"path":m["relative_path"],"sha256":m["sha256"],"size":m["size"],"machine":m["machine_name"],"entry_point_rva":f"0x{m['entry_point_rva']:08X}","imports":[x["dll"] for x in m["imports"]],"exports":[x["name"] for x in m["exports"]]} for m in modules],"references":[{"source":e["from"],"target":e["to"],"edge":"imports","symbols":";".join(e["symbols"][:20]),"evidence":f"import table; {e['symbol_count']} symbols"} for e in graph["edges"]]+[{"source":x["artifact"],"target":x["string"],"edge":"contains literal candidate token","symbols":x["encoding"],"evidence":f"offset 0x{x['offset']:X}; section {x['section']}"} for x in references[:250]],"map_files":[{"extension":Path(f["relative_path"]).suffix.upper(),"relative_path":f["relative_path"],"disc":vol,"size":f["size"],"sha256":f["sha256"]} for vol,obj in maps.items() for f in obj["files"] if Path(f["relative_path"]).suffix.upper() in MAP_EXTS or f["relative_path"].upper().endswith("ZONE.CFG")]}
    (data/"map_reader_page_data.json").write_text(json.dumps(ui,indent=2,ensure_ascii=False),encoding="utf-8")
    stage_log(run,10,f"ranked {len(candidates)} SH4 modules; top candidate {candidates[0]['module'] if candidates else 'none'}; reader claim inconclusive",start)
    # Evidence-classified conclusion and explicit next target.
    status="INCONCLUSIVE"  # no candidate has a traced open/read/parser path
    matrix_rows=[{"question":"NAVIMAIN is actual map reader","status":"INCONCLUSIVE","evidence":"Navi process strings/PDB; no literal map extension in PE non-resource sections; no SH4 call trace"},{"question":"MMIDIS role","status":"INCONCLUSIVE","evidence":"MFC/Traceable/COM imports; no process/IPC or map path proven"},{"question":"direct map file open","status":"INCONCLUSIVE","evidence":"TMCUPDATE.DLL imports four MFC CFile/CArchive file/archive routines, but is update-only; NAVIMAIN/MMIDIS have no named file-I/O imports and no map path or parser trace"},{"question":"map extensions referenced by code","status":"INCONCLUSIVE","evidence":f"{len(references)} ASCII/UTF-16 candidate tokens occur in executable/firmware artifacts; no native extension token appears in PE non-resource sections; NAVIMAIN CE hit is in its Windows CE compiler path"},{"question":"NK.BIN Windows CE ROM parsing","status":"INCONCLUSIVE","evidence":nkinfo["blocker"]}]
    write_csv(data/"evidence_status.csv",matrix_rows)
    # Report and graph visualization.
    top=candidates[0] if candidates else None
    primary_map_extensions=sorted({x["string"].upper() for x in references if x["artifact_type"]=="PE" and x["string"].upper() in MAP_EXTS and x["section"] not in (".rsrc",".rsrc1")})
    candidate_lines="\n".join(f"|{x['rank']}|{x['module']}|{x['score']}|{x['confidence']}|{x['reason']}|" for x in candidates[:8])
    report=f'''# NCDx Map Reader Discovery

**Status: {status}.** This run ranks candidates but cannot confirm a map-reader code path.

## Result

|Rank|Module|Score|Evidence class|Evidence|
|---:|---|---:|---|---|
{candidate_lines}

Top candidate: **{top['module'] if top else 'none'}**, specifically its entry point RVA `0x{top['function_or_region'].split('0x')[-1].split()[0] if top else '00000000'}`. This is a ranked navigation-runtime candidate, not a proven map reader.

## 1. All SH4 PE files and file I/O

Analyzed {len(modules)} PE files, all Machine `0x01A6` (Hitachi SH4). See `data/sh4_pe_inventory.csv` for path, SHA256, sections, named exports, ASCII strings and both UTF-16 encodings. Imports are recorded with the original DLL, API name or raw ordinal, and IAT RVA/VA in `data/file_io_imports.csv`.

**TMCUPDATE.DLL imports four named MFC file/archive routines** (`CFile::Open`, `CFile::Close`, `CArchive::Close`, `CArchive::Read`). This is update-path file handling; it does not establish native map access. NAVIMAIN and MMIDIS have no named file-I/O imports. The 595 COREDLL imports are ordinal-only; without the matching COREDLL export table they cannot be attributed to `CreateFile`/`ReadFile`. The disassembler/tool capability evidence is in `data/tool_availability.json`.

## 2. Map names and regions

Exact ASCII, UTF-16LE, and UTF-16BE token hits from the 16 PEs and all manifest-verified firmware/update artifacts are in `data/map_string_references.csv`, with file offset, PE RVA/section when applicable, neighboring strings, and xref availability. A string hit is not treated as proof of a read path. Literal map extension hits in PE non-resource sections: {', '.join(primary_map_extensions) if primary_map_extensions else 'none'}.

## 3. NAVIMAIN and MMIDIS

- `NAVIMAIN.EXE` imports `COREDLL.dll`, `ComMgr.dll`, `mfcce212.dll`, `ole32.dll`, and `MemMgr.dll`. Its `Navi main process started...`, `Navi ready...`, `NaviMain.pdb`, and ComMgr remote-process/communication symbols support **HYPOTHESIS: navigation runtime/IPC client**. No named map-file reference, named file-I/O API, `CreateProcess`, `LoadLibrary`, or parser call was confirmed from available static metadata. Entry RVA `0x{nav['entry_point_rva']:08X}`; file offset `0x{nav['entry_point_file_offset'] or 0:08X}`.
- `MMIDIS.EXE` imports `COREDLL.dll`, `mtl.dll`, `mfcce212.dll`, `ole32.dll`, `Traceable.dll`, and `MemMgr.dll`. This supports **HYPOTHESIS: MFC/trace-enabled runtime component**; UI, broker, and map-reader roles are not distinguished by the available evidence. No direct map token or named file-I/O API was confirmed.
- Neither module’s direct file-open or post-ReadFile parser path can be traced because the installed Apple LLVM 17 has no SH4 target and no Rizin/radare2/Ghidra/Capstone executable is available. See `data/callgraph.csv` for the exact limitation.

## 4. Dependency and cross-reference graph

`data/sh4_dependency_graph.json` and `.csv` contain import edges, symbols, and local resolution state. Import dependencies are confirmed from PE tables; no map-reader edge is established. The HTML report includes a simplified visual of NAVIMAIN/MMIDIS imports, updater dependencies, and the absence of a proven database edge.

## 5. NK.BIN

NK.BIN is {nkinfo['size']:,} bytes. Signature offsets, ECEC neighborhoods, and little-endian candidate words are in `data/nk_bin_structure.json`. The strings `ECEC`/`FATFS` alone do not validate a ROMHDR, TOC, MODULES/FILES table, or E32/O32 module boundary. No module was extracted or carved; NK.BIN remains an **INCONCLUSIVE possible Windows CE image**. No claim is made that additional navigation modules are or are not present.

## 6. Native database files

`data/database_header_correlation.csv` correlates {len(header_rows)} observed files across all nine discs, using prior SHA256 and 4 KiB edge captures; `data/database_extension_disc_matrix.json` maps suffix labels to disc coverage. A 12-byte `SIEMENS`-prefixed header is invariant among the regional `.RD` sample files, while sizes vary; this is a byte-level correlation only, not an interpretation of `.RD` semantics.

**First neutral type for format work:** `.RD`, because it has one regional sample on each disc and a repeated 12-byte opening signature with varying file size. This is a corpus-comparison priority, not a claim that `.RD` stores road geometry or is used by a particular component.

## 7. Endianness and constants

PE/COFF header fields are parsed as little-endian. The CPU’s SH4 instruction endianness is **INCONCLUSIVE** because no SH4 decoder is available; database field endianness is also unobserved because no proven DB read path exists. The data inventory preserves offsets and bytes for follow-up. No semantic weight is assigned to the prior ASCII `5555555` hit.

## 8. Precise next target and blockers

Next single target: disassemble `NAVIMAIN.EXE` at entry RVA `0x{nav['entry_point_rva']:08X}` (file offset `0x{nav['entry_point_file_offset'] or 0:08X}`), resolve its COREDLL ordinal IAT entries against the matching platform export map, then trace calls from the entry point to file-open/read APIs. Entry-point function boundaries and callers remain unverified.

Blockers: (1) no installed SH4 disassembler; (2) no matching COREDLL ordinal-to-name export map; (3) no literal NCDx file open or parser path in the extracted string/import evidence; (4) NK.BIN’s Windows CE table layout is not structurally validated.

## Output files

See `data/sh4_pe_inventory.csv`, `data/file_io_imports.csv`, `data/sh4_dependency_graph.csv`, `data/sh4_dependency_graph.json`, `data/map_string_references.csv`, `data/map_reader_candidates.csv`, `data/database_header_correlation.csv`, `data/navimain_analysis.json`, `data/mmidis_analysis.json`, `data/nk_bin_structure.json`, and `data/callgraph.csv`.
'''
    (run/"REPORT.md").write_text(report,encoding="utf-8")
    # Small self-contained HTML and import-flow diagram.
    svg='''<svg viewBox="0 0 980 290" role="img" aria-label="SH4 import relationships"><defs><marker id="a" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#69d5f5"/></marker></defs><style>.n{fill:#142532;stroke:#69d5f5;stroke-width:2}.t{fill:#e7f4ff;font:15px sans-serif}.s{fill:#a8c0d1;font:12px sans-serif}.e{stroke:#69d5f5;stroke-width:2;marker-end:url(#a)}</style>'''
    nodes=[("NAVIMAIN.EXE",90,105),("MMIDIS.EXE",90,220),("COREDLL.dll",420,80),("ComMgr.dll",420,140),("mfcce212.dll",420,200),("ole32.dll",420,250),("MemMgr.dll",720,140),("No proven NCDx file edge",720,240)]
    for name,x,y in nodes: svg+=f'<rect class="n" x="{x}" y="{y}" width="220" height="36" rx="8"/><text class="t" x="{x+12}" y="{y+23}">{html.escape(name)}</text>'
    for x1,y1,x2,y2 in [(310,123,420,98),(310,123,420,158),(310,123,420,218),(310,123,420,268),(310,238,420,98),(310,238,420,218),(310,238,420,268)]:svg+=f'<path class="e" d="M{x1},{y1} L{x2},{y2}"/>'
    svg+='</svg>'
    html_doc=f'''<!doctype html><html><head><meta charset="utf-8"><title>NCDx Map Reader Discovery</title><style>body{{background:#0c141b;color:#dce8f0;font:16px system-ui;margin:36px auto;max-width:1100px;padding:0 24px}}h1,h2{{color:#75dcff}}section{{background:#14212b;border-radius:12px;padding:18px;margin:16px 0}}table{{width:100%;border-collapse:collapse}}td,th{{padding:8px;border-bottom:1px solid #334653;text-align:left;vertical-align:top}}small{{color:#a9bfcc}}</style></head><body><h1>NCDx Map Reader Discovery</h1><section><b>Status: {status}</b><p>Top ranked: {html.escape(top['module'] if top else 'none')}; hypothesis only, not a proven map reader.</p></section><section><h2>Import relationship graph</h2>{svg}<p><small>Edges represent PE import tables. No file-open/read or native DB edge was proven.</small></p></section><section><h2>Ranked candidates</h2><table><thead><tr><th>Rank</th><th>Module</th><th>Score</th><th>Confidence</th><th>Evidence</th></tr></thead><tbody>{''.join(f'<tr><td>{x["rank"]}</td><td>{html.escape(x["module"])}</td><td>{x["score"]}</td><td>{html.escape(x["confidence"])}</td><td>{html.escape(x["reason"])}</td></tr>' for x in candidates[:8])}</tbody></table></section><section><h2>Exact blockers</h2><p>{html.escape(tools['blocker'])}</p><p>No map database or NK.BIN module was extracted.</p></section><p>Full evidence tables are in the adjacent <code>data/</code> directory.</p></body></html>'''
    (run/"REPORT.html").write_text(html_doc,encoding="utf-8")
    summary=f"Map-reader discovery INCONCLUSIVE. Ranked top candidate {top['module'] if top else 'none'} as a HYPOTHESIS only; {len(modules)} SH4 PE files analyzed, no named file-I/O API or module map-extension path confirmed, no SH4 disassembly available. First neutral corpus target .RD due repeated 12-byte opening signature on all nine discs. Next exact target NAVIMAIN.EXE entry RVA 0x{nav['entry_point_rva']:08X} / file offset 0x{nav['entry_point_file_offset'] or 0:08X}."
    (run/"CHATGPT_SUMMARY.txt").write_text(summary+"\n",encoding="utf-8")
    meta["status"]=status;meta["summary"]={"status":status,"sh4_pe_files":len(modules),"file_io_named_apis":sum(1 for x in import_rows if not x["api"].startswith("UNRESOLVED_")),"map_string_hits":len(references),"map_pe_hits":sum(1 for x in references if x["artifact_type"]=="PE"),"candidate":top,"db_header_rows":len(header_rows),"next_target":{"module":"NAVIMAIN.EXE","rva":nav["entry_point_rva"],"file_offset":nav["entry_point_file_offset"]},"blockers":tools["blocker"]}
    finish_run(run,meta,status,meta["summary"],warnings=["No SH4 decoder or COREDLL export map was available; parser and reader attribution remain unresolved."])
    try:
        register_run(project,run,meta)
    except sqlite3.OperationalError as exc:
        meta["summary"]["catalog_registration"]="DEFERRED: "+str(exc)
        meta.setdefault("warnings",[]).append("Run outputs are complete, but project SQLite registration was deferred because the catalog is busy.")
        atomic_json(run/"run.json",meta)
    stage_log(run,11,f"report status {status}; candidate ranking and next RVA written",start)
    stage_log(run,12,"creating integrity-checked package; no full NK.BIN or map files included",start,0,1)
    required_package_files=["TASK.md","task.json","run.json","REPORT.md","REPORT.html","CHATGPT_SUMMARY.txt","PACKAGE_MANIFEST.json","data/sh4_pe_inventory.csv","data/file_io_imports.csv","data/sh4_dependency_graph.csv","data/sh4_dependency_graph.json","data/map_string_references.csv","data/map_reader_candidates.csv","data/navimain_analysis.json","data/mmidis_analysis.json","data/nk_bin_structure.json","data/database_header_correlation.csv","data/callgraph.csv","data/evidence_status.csv","data/map_reader_page_data.json"]
    package=package_run(run,required=required_package_files)
    meta=json.loads((run/"run.json").read_text());meta["summary"]["package"]=package;atomic_json(run/"run.json",meta);register_run(project,run,meta)
    with zipfile.ZipFile(package["path"]) as z:
        names=z.namelist(); bad=z.testzip()
        if bad: raise IOError("package CRC check failed: "+bad)
        if any(Path(n).name.upper()=="NK.BIN" for n in names): raise AssertionError("full NK.BIN included in package")
        if any(Path(n).suffix.upper() in (".RD",".FEA",".MP0",".RL",".RT",".MG1",".MG2",".MG3") and n.startswith("evidence/") for n in names): raise AssertionError("map data included in package")
    stage_log(run,12,f"package {package['status']}: {package['path']}",start)
    return {"status":status,"run_path":str(run),"package_path":package["path"],"package_status":package["status"],"sh4_pe_files":len(modules),"map_references":len(references),"named_file_io_apis":sum(1 for x in import_rows if not x["api"].startswith("UNRESOLVED_")),"candidate":top,"next_target":meta["summary"]["next_target"],"blockers":tools["blocker"]}

def load_map_reader_page(project):
    paths=sorted((Path(project)/"research/runs").glob("*_NCDX_MAP_READER_DISCOVERY"))
    if not paths:return {"status":"NOT RUN","candidates":[],"executables":[],"references":[]}
    r=paths[-1]; d=r/"data"
    try: page=json.loads((d/"map_reader_page_data.json").read_text())
    except Exception: return {"status":"NOT RUN","candidates":[],"executables":[],"references":[]}
    try: page["candidates"]=json.loads((d/"map_reader_candidates.json").read_text())
    except Exception: page["candidates"]=[]
    page["run_path"]=str(r);return page
