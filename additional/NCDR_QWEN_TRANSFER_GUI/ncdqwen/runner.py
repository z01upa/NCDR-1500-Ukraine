from __future__ import annotations

import argparse
import bz2
import collections
import ctypes
import gzip
import hashlib
import json
import lzma
import os
import sqlite3
import statistics
import subprocess
import shutil
import sys
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

# Support both `python -m ncdqwen.runner` and direct execution by absolute path.
# The latter keeps Windows GUI and logon-task launches independent of CWD.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "ncdqwen"

from .db0 import DB0Reader, SECTOR_SIZE, sha256_file
from .ollama_client import OllamaClient, OllamaError

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/"work"
REPORTS=ROOT/"reports"
STATE_DB=WORK/"analysis.sqlite"
STATUS_PATH=WORK/"status.json"
LOG_PATH=WORK/"runner.log"
LOCK_PATH=WORK/"runner.lock"
MAX_PROBE_BYTES=512
STANDARD_CODECS={"zlib","raw_deflate","gzip","bz2","lzma"}
ALLOWED_TOOLS={"inspect_block","prefix_compare","codec_sweep","word_profile","find_hex","list_type0_targets","road_summary","stop"}
FINAL_STATUSES={"EXPERIMENTS_EXHAUSTED","BLOCKED_ORACLE","DECODER_CANDIDATE_REQUIRES_REVIEW"}
RESUMABLE_QWEN_STOP="The local model did not produce a valid allow-listed action after five bounded retries."

def utcnow()->str:
    return datetime.now(timezone.utc).isoformat()

def log(message:str)->None:
    WORK.mkdir(parents=True,exist_ok=True)
    line=f"{utcnow()} {message}"
    with LOG_PATH.open("a",encoding="utf-8") as handle: handle.write(line+"\n")
    print(line,flush=True)

def write_json(path:Path,value:dict)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    temp.replace(path)

def set_status(run_id:str|None,status:str,stage:str,detail:str="",progress:dict|None=None)->None:
    write_json(STATUS_PATH,{"run_id":run_id,"status":status,"stage":stage,"detail":detail,
                            "progress":progress or {},"updated_utc":utcnow()})

def validate_runtime(db0:Path)->None:
    required={
        "DB_0":db0,
        "schema.sql":ROOT/"schema.sql",
        "prompts/system_prompt.txt":ROOT/"prompts"/"system_prompt.txt",
        "research/roads/build_authoritative_corpus.py":ROOT/"research"/"roads"/"build_authoritative_corpus.py",
    }
    missing=[f"{label}: {path}" for label,path in required.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Research preflight failed; required file(s) missing:\n"+"\n".join(missing))

def init_store()->sqlite3.Connection:
    WORK.mkdir(parents=True,exist_ok=True); REPORTS.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(STATE_DB,timeout=60)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript((ROOT/"schema.sql").read_text(encoding="utf-8"))
    conn.commit()
    return conn

def acquire_lock()->None:
    WORK.mkdir(parents=True,exist_ok=True)
    for _ in range(2):
        try:
            fd=os.open(LOCK_PATH,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            with os.fdopen(fd,"w",encoding="utf-8") as handle:
                handle.write(json.dumps({"pid":os.getpid(),"started_utc":utcnow()}))
            return
        except FileExistsError:
            try:
                old=json.loads(LOCK_PATH.read_text(encoding="utf-8")); pid=int(old.get("pid",-1))
                if os.name=="nt":
                    kernel=ctypes.windll.kernel32
                    kernel.OpenProcess.restype=ctypes.c_void_p
                    handle=kernel.OpenProcess(0x1000,False,pid)
                    if not handle:
                        raise ProcessLookupError(pid)
                    kernel.CloseHandle(ctypes.c_void_p(handle))
                else:
                    os.kill(pid,0)
                raise RuntimeError(f"A runner appears active with PID {pid}; see work/status.json")
            except ProcessLookupError:
                LOCK_PATH.unlink(missing_ok=True)
            except (ValueError,KeyError,json.JSONDecodeError,OSError):
                LOCK_PATH.unlink(missing_ok=True)
    raise RuntimeError("Could not acquire work/runner.lock")

def hold_awake():
    if os.name!="nt": return None
    try:
        kernel=ctypes.windll.kernel32
        keep=kernel.SetThreadExecutionState(0x80000000|0x00000001)
        return (kernel,keep)
    except Exception as exc:
        log(f"Sleep-prevention request unavailable: {exc}")
        return None

def release_awake(state)->None:
    if state:
        try: state[0].SetThreadExecutionState(0x80000000)
        except Exception: pass

def ensure_run(conn:sqlite3.Connection,db0:Path,source_hash:str,size:int)->str:
    row=conn.execute("SELECT run_id,status FROM runs WHERE source_sha256=? ORDER BY started_utc DESC LIMIT 1",(source_hash,)).fetchone()
    if row:
        return row["run_id"]
    run_id=f"{source_hash[:12]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    conn.execute("INSERT INTO runs(run_id,source_path,source_sha256,source_size,started_utc,status,stage) VALUES(?,?,?,?,?,?,?)",
                 (run_id,str(db0),source_hash,size,utcnow(),"RUNNING","START"))
    templates=conn.execute("SELECT task_id FROM task_templates ORDER BY priority").fetchall()
    conn.executemany("INSERT INTO tasks(run_id,task_id,status,updated_utc) VALUES(?,?,?,?)",
                     [(run_id,row[0],"PENDING",utcnow()) for row in templates])
    conn.commit(); return run_id

def update_run(conn,run_id,status=None,stage=None,note=None,finished=False):
    parts=[]; values=[]
    if status is not None: parts.append("status=?"); values.append(status)
    if stage is not None: parts.append("stage=?"); values.append(stage)
    if note is not None: parts.append("note=?"); values.append(note)
    if finished: parts.append("finished_utc=?"); values.append(utcnow())
    if parts:
        values.append(run_id); conn.execute(f"UPDATE runs SET {','.join(parts)} WHERE run_id=?",values); conn.commit()

def mark_task(conn,run_id,task_id,status,detail=None):
    conn.execute("INSERT INTO tasks(run_id,task_id,status,attempts,updated_utc,detail_json) VALUES(?,?,?,?,?,?) "
                 "ON CONFLICT(run_id,task_id) DO UPDATE SET status=excluded.status, attempts=tasks.attempts+1, updated_utc=excluded.updated_utc, detail_json=excluded.detail_json",
                 (run_id,task_id,status,1,utcnow(),json.dumps(detail or {},ensure_ascii=False)))
    conn.commit()

def insert_records(conn,run_id,reader:DB0Reader)->dict:
    existing=conn.execute("SELECT count(*) FROM records WHERE run_id=?",(run_id,)).fetchone()[0]
    if existing==len(reader.records):
        counts=collections.Counter((r["block_type"],r["compression"]) for r in reader.records)
        return {"record_count":len(reader.records),"counts":{f"type_{t:02x}_comp_{c:02x}":n for (t,c),n in counts.items()},"reused":True}
    conn.execute("DELETE FROM records WHERE run_id=?",(run_id,)); conn.commit()
    rows=[]; counts=collections.Counter(); valid_zlib=0; zlib_errors=[]
    for idx,row in enumerate(reader.records,1):
        zvalid=None
        if row["compression"]==2:
            try:
                reader.logical(row["sector"]); zvalid=1; valid_zlib+=1
            except Exception as exc:
                zvalid=0; zlib_errors.append({"sector":row["sector"],"error":str(exc)})
        rows.append((run_id,row["sector"],row["span"],row["block_type"],row["compression"],row["logical_size"],zvalid))
        counts[(row["block_type"],row["compression"])]+=1
        if len(rows)>=1000:
            conn.executemany("INSERT INTO records VALUES(?,?,?,?,?,?,?)",rows); conn.commit(); rows.clear()
        if idx%5000==0:
            set_status(run_id,"RUNNING","INDEX_DB0",f"Indexed {idx} records",{"records":idx,"total":len(reader.records)})
    if rows: conn.executemany("INSERT INTO records VALUES(?,?,?,?,?,?,?)",rows); conn.commit()
    return {"record_count":len(reader.records),"counts":{f"type_{t:02x}_comp_{c:02x}":n for (t,c),n in counts.items()},
            "compression02_valid":valid_zlib,"compression02_errors":zlib_errors,"reused":False}

def run_road_corpus(db0:Path)->dict:
    script=ROOT/"research"/"roads"/"build_authoritative_corpus.py"
    out=WORK/"authoritative_road_corpus"
    summary=out/"authoritative_summary.json"
    if summary.is_file():
        try: return json.loads(summary.read_text(encoding="utf-8"))|{"reused":True}
        except Exception: pass
    if not script.is_file(): return {"status":"MISSING_SCRIPT","script":str(script)}
    out.mkdir(parents=True,exist_ok=True)
    cmd=[sys.executable,str(script),str(db0),"--output",str(out)]
    completed=subprocess.run(cmd,cwd=script.parent,capture_output=True,text=True,timeout=3600)
    (WORK/"road_corpus.stdout.log").write_text(completed.stdout,encoding="utf-8")
    (WORK/"road_corpus.stderr.log").write_text(completed.stderr,encoding="utf-8")
    if completed.returncode!=0:
        return {"status":"FAILED","returncode":completed.returncode,"stderr_tail":completed.stderr[-3000:]}
    if summary.is_file(): return json.loads(summary.read_text(encoding="utf-8"))|{"status":"BUILT"}
    return {"status":"NO_SUMMARY","stdout_tail":completed.stdout[-3000:]}

def parse_sector(value)->int:
    if isinstance(value,int): return value
    if not isinstance(value,str) or len(value)>16: raise ValueError("sector must be an integer or short decimal/0x string")
    return int(value,0)

def sample_rows(reader:DB0Reader,block_type:int|None=None,compression:int|None=None,limit:int=16)->list[dict]:
    rows=[r for r in reader.records if (block_type is None or r["block_type"]==block_type) and (compression is None or r["compression"]==compression)]
    if len(rows)<=limit:return rows
    # Deterministic coverage across the ordered population.
    positions=[round(i*(len(rows)-1)/(limit-1)) for i in range(limit)] if limit>1 else [len(rows)//2]
    return [rows[i] for i in positions]

def inspect_block(reader:DB0Reader,args:dict)->dict:
    sector=parse_sector(args.get("sector")); row=reader.by_sector.get(sector)
    if not row: raise ValueError("sector is not in validated record chain")
    offset=int(args.get("offset",0)); length=int(args.get("length",128))
    if offset<0 or length<1 or length>MAX_PROBE_BYTES: raise ValueError("offset must be nonnegative and length must be 1..512")
    data,view=reader.logical_or_stored(sector)
    if offset>=len(data): raise ValueError("offset is outside available view")
    chunk=data[offset:min(len(data),offset+length)]
    return {"sector":f"0x{sector:06X}","type":f"0x{row['block_type']:02X}","compression":f"0x{row['compression']:02X}","span":row["span"],"logical_size_header":row["logical_size"],"view":view,"offset":offset,"returned":len(chunk),"hex":chunk.hex(),"u16_be":[int.from_bytes(chunk[i:i+2],"big") for i in range(0,len(chunk)-1,2)],"u32_be":[int.from_bytes(chunk[i:i+4],"big") for i in range(0,len(chunk)-3,4)]}

def entropy(data:bytes)->float:
    if not data:return 0.0
    n=len(data); return -sum((c/n)*__import__("math").log2(c/n) for c in collections.Counter(data).values())

def prefix_compare(reader:DB0Reader,args:dict)->dict:
    block_type=int(args.get("block_type",0)); length=max(8,min(int(args.get("length",32)),64)); limit=max(2,min(int(args.get("count",6)),8))
    groups={}
    for comp in (0,1,2):
        rows=sample_rows(reader,block_type,comp,limit)
        groups[str(comp)]=[]
        for r in rows:
            raw=reader.stored(r["sector"]); part=raw[8:8+length]
            groups[str(comp)].append({"sector":f"0x{r['sector']:06X}","span":r["span"],"logical_size":r["logical_size"],"bytes":len(part),"hex":part.hex(),"entropy":round(entropy(part),4)})
    return {"block_type":f"0x{block_type:02X}","payload_prefix_bytes":length,"samples":groups}

def _attempt_codec(name:str,payload:bytes,max_output:int)->tuple[bool,int|None,str]:
    try:
        if name=="zlib":
            obj=zlib.decompressobj(); out=obj.decompress(payload,max_output+1)
            if len(out)>max_output or obj.unconsumed_tail:return False,None,"output_limit"
            out+=obj.flush(max_output+1-len(out))
        elif name=="raw_deflate":
            obj=zlib.decompressobj(-15); out=obj.decompress(payload,max_output+1)
            if len(out)>max_output or obj.unconsumed_tail:return False,None,"output_limit"
            out+=obj.flush(max_output+1-len(out))
        elif name=="gzip":
            obj=zlib.decompressobj(31); out=obj.decompress(payload,max_output+1)
            if len(out)>max_output or obj.unconsumed_tail:return False,None,"output_limit"
            out+=obj.flush(max_output+1-len(out))
        elif name=="bz2":
            obj=bz2.BZ2Decompressor(); out=obj.decompress(payload,max_length=max_output+1)
            if len(out)>max_output:return False,None,"output_limit"
        elif name=="lzma":
            obj=lzma.LZMADecompressor(); out=obj.decompress(payload,max_length=max_output+1)
            if len(out)>max_output:return False,None,"output_limit"
        else: return False,None,"codec_not_allowlisted"
        return True,len(out),"ok"
    except Exception as exc:
        return False,None,type(exc).__name__

def codec_sweep(reader:DB0Reader,args:dict)->dict:
    sectors=args.get("sectors")
    if not isinstance(sectors,list) or not 1<=len(sectors)<=8: raise ValueError("sectors must contain 1..8 entries")
    offsets=args.get("offsets",list(range(8,33)))
    if not isinstance(offsets,list) or not 1<=len(offsets)<=8: raise ValueError("offsets must contain 1..8 entries")
    offsets=[int(x) for x in offsets]
    if any(x<8 or x>64 for x in offsets): raise ValueError("candidate offsets must be 8..64")
    codecs=args.get("codecs",sorted(STANDARD_CODECS))
    if not isinstance(codecs,list) or any(x not in STANDARD_CODECS for x in codecs): raise ValueError("codec is not allow-listed")
    results=[]
    for value in sectors:
        sector=parse_sector(value); row=reader.by_sector.get(sector)
        if row is None or row["compression"]!=1: raise ValueError(f"sector {sector:#x} is not a validated compression-0x01 record")
        raw=reader.stored(sector); successes=[]; attempts=0
        for offset in offsets:
            if offset>=len(raw): continue
            for codec in codecs:
                attempts+=1; ok,size,reason=_attempt_codec(codec,raw[offset:],min(1024*1024,row["logical_size"]))
                if ok and size+8==row["logical_size"]:
                    successes.append({"codec":codec,"offset":offset,"decoded_payload_size":size,"logical_size_valid":True})
        results.append({"sector":f"0x{sector:06X}","attempts":attempts,"valid_size_candidates":successes})
    return {"sectors":results,"tested_codecs":codecs,"offsets":offsets,"size_rule":"decoded payload + 8 == advertised logical size"}

def word_profile(reader:DB0Reader,args:dict)->dict:
    block_type=int(args.get("block_type",0)); compression=int(args.get("compression",1)); width=int(args.get("width",2))
    if width not in (2,4): raise ValueError("width must be 2 or 4")
    start=int(args.get("offset_start",8)); end=int(args.get("offset_end",256)); step=int(args.get("step",2)); limit=max(4,min(int(args.get("sample_limit",64)),128))
    if start<8 or end<=start or end>8192 or step not in (1,2,4,8): raise ValueError("profile offsets must be bounded inside 8..8192")
    rows=sample_rows(reader,block_type,compression,limit); per_offset={}
    for offset in range(start,end,step):
        values=[]
        for row in rows:
            raw=reader.stored(row["sector"])
            if offset+width<=len(raw): values.append(int.from_bytes(raw[offset:offset+width],"big"))
        counts=collections.Counter(values)
        per_offset[str(offset)]={"observed":len(values),"distinct":len(counts),"top_values":[{"value":f"0x{v:0{width*2}X}","count":n} for v,n in counts.most_common(6)]}
    return {"block_type":f"0x{block_type:02X}","compression":f"0x{compression:02X}","sample_sectors":[f"0x{r['sector']:06X}" for r in rows],"width_bytes":width,"offset_stats":per_offset}

def find_hex(reader:DB0Reader,args:dict)->dict:
    try: pattern=bytes.fromhex(str(args.get("hex","")))
    except ValueError as exc: raise ValueError("hex must contain even-length hexadecimal bytes") from exc
    if not 1<=len(pattern)<=16: raise ValueError("pattern must be 1..16 bytes")
    limit=max(1,min(int(args.get("sample_limit",16)),16)); max_bytes=max(64,min(int(args.get("max_bytes",2048)),4096)); comp=int(args.get("compression",1))
    matches=[]
    for row in sample_rows(reader,args.get("block_type",0),comp,limit):
        raw=reader.stored(row["sector"]); segment=raw[8:min(len(raw),8+max_bytes)]; offset=segment.find(pattern)
        if offset>=0: matches.append({"sector":f"0x{row['sector']:06X}","physical_offset":8+offset})
    return {"pattern":pattern.hex(),"samples":limit,"searched_payload_bytes_each":max_bytes,"matches":matches}

def list_type0_targets(reader:DB0Reader,args:dict)->dict:
    compression=int(args.get("compression",1)); limit=max(1,min(int(args.get("limit",20)),32))
    rows=[r for r in reader.records if r["block_type"]==0 and r["compression"]==compression]
    selected=sample_rows(reader,0,compression,limit)
    return {"count":len(rows),"compression":compression,"samples":[{"sector":f"0x{r['sector']:06X}","span":r["span"],"logical_size":r["logical_size"],"physical_size":r["span"]*SECTOR_SIZE} for r in selected]}

def road_summary()->dict:
    path=WORK/"authoritative_road_corpus"/"authoritative_summary.json"
    if not path.is_file(): return {"status":"NOT_BUILT"}
    return json.loads(path.read_text(encoding="utf-8"))

def execute_tool(reader:DB0Reader,tool:str,args:dict)->dict:
    if tool=="inspect_block": return inspect_block(reader,args)
    if tool=="prefix_compare": return prefix_compare(reader,args)
    if tool=="codec_sweep": return codec_sweep(reader,args)
    if tool=="word_profile": return word_profile(reader,args)
    if tool=="find_hex": return find_hex(reader,args)
    if tool=="list_type0_targets": return list_type0_targets(reader,args)
    if tool=="road_summary": return road_summary()
    raise ValueError(f"tool {tool!r} is not allow-listed")

def action_fingerprint(tool:str,args:dict)->str:
    payload=json.dumps({"tool":tool,"args":args},sort_keys=True,separators=(",",":"))
    return hashlib.sha256(payload.encode()).hexdigest()

def record_experiment(conn,run_id,round_no,tool,args,result,fingerprint):
    conn.execute("INSERT OR IGNORE INTO experiments(run_id,round_no,tool,params_json,fingerprint,result_json,created_utc) VALUES(?,?,?,?,?,?,?)",
                 (run_id,round_no,tool,json.dumps(args,sort_keys=True),fingerprint,json.dumps(result,ensure_ascii=False),utcnow()))
    conn.commit()

def action_schema_text()->str:
    return json.dumps({
      "inspect_block":{"sector":"validated sector decimal or 0xHEX","offset":"0..physical/logical view length","length":"1..512"},
      "prefix_compare":{"block_type":"integer, default 0","length":"8..64","count":"2..8"},
      "codec_sweep":{"sectors":"1..8 compression-0x01 sectors","offsets":"1..8 integers in 8..64","codecs":"subset of zlib/raw_deflate/gzip/bz2/lzma"},
      "word_profile":{"block_type":"integer","compression":"integer","width":"2 or 4","offset_start":"8..8192","offset_end":"start..8192","step":"1,2,4,8","sample_limit":"4..128"},
      "find_hex":{"hex":"1..16 bytes as hex","sample_limit":"1..16","max_bytes":"64..4096","compression":"integer"},
      "list_type0_targets":{"compression":"integer","limit":"1..32"},
      "road_summary":{},
      "stop":{"reason":"no_more_safe_tests or external_oracle_required","details":"short factual explanation"}
    },ensure_ascii=False)

def compact_context()->str:
    docs=[ROOT/"research"/"PROJECT_STATE.md",ROOT/"research"/"compression"/"COMP01_DECODER_RE.md",ROOT/"research"/"roads"/"TYPE0_BLOCK_STRUCTURE.md",ROOT/"research"/"roads"/"RAW32_FINAL_ATTRIBUTE_MODEL.md",ROOT/"research"/"roads"/"RUN_ARC_GRAMMAR.md",ROOT/"research"/"roads"/"HALFEDGE_N_TEST.md"]
    chunks=[]; remaining=14000
    for path in docs:
        if not path.is_file(): continue
        body=path.read_text(encoding="utf-8",errors="replace")
        part=f"\n## {path.relative_to(ROOT)}\n{body}\n"
        if len(part)>remaining: part=part[:remaining]
        chunks.append(part); remaining-=len(part)
        if remaining<=0: break
    return "".join(chunks)

def model_decision(client,system_prompt,inventory,road,history,round_no):
    allow=action_schema_text()
    recent=history[-8:]
    user_prompt=(
      "Continue the local DB_0 research without asking the user anything.\n"
      f"Round {round_no}.\n\nPROJECT CHECKPOINTS:\n{compact_context()}\n\n"
      f"DETERMINISTIC INVENTORY:\n{json.dumps(inventory,ensure_ascii=False)[:6000]}\n\n"
      f"AUTHORITATIVE ROAD SUMMARY:\n{json.dumps(road,ensure_ascii=False)[:4000]}\n\n"
      f"RECENT EXPERIMENTS:\n{json.dumps(recent,ensure_ascii=False)[:6000]}\n\n"
      f"ALLOWED ACTIONS AND ARGUMENT LIMITS:\n{allow}\n\n"
      "Return JSON with exactly these keys: hypothesis, expected_if_true, falsifier, confidence, action. "
      "hypothesis/expected_if_true/falsifier must be short strings. confidence must be CONFIRMED, CANDIDATE, or UNRESOLVED; use CANDIDATE for any new claim. "
      "action must be {tool, args}; choose one allow-listed tool. For stop use tool=stop and args.reason/details. "
      "Choose one new action fingerprint; do not repeat a prior experiment. Do not claim decoder success unless a valid expected-size output and independent structure validation are already present."
    )
    return user_prompt,client.chat_json(system_prompt,user_prompt)

def validate_decision(value)->tuple[str,dict,str,str,str,str]:
    if not isinstance(value,dict): raise ValueError("response must be a JSON object")
    expected={"hypothesis","expected_if_true","falsifier","confidence","action"}
    if set(value.keys())!=expected: raise ValueError(f"response keys must be exactly {sorted(expected)}")
    for field in ("hypothesis","expected_if_true","falsifier"):
        if not isinstance(value[field],str) or len(value[field])>1200: raise ValueError(f"{field} must be a short string")
    if value["confidence"] not in ("CONFIRMED","CANDIDATE","UNRESOLVED"): raise ValueError("invalid confidence label")
    action=value["action"]
    if not isinstance(action,dict) or set(action.keys())!={"tool","args"} or not isinstance(action["args"],dict): raise ValueError("action must contain tool and args")
    if action["tool"] not in ALLOWED_TOOLS: raise ValueError("tool is not allow-listed")
    return value["hypothesis"],action["args"],value["expected_if_true"],value["falsifier"],value["confidence"],action["tool"]

def add_hypothesis(conn,run_id,round_no,claim,expected,falsifier):
    conn.execute("INSERT INTO hypotheses(run_id,round_no,claim,expected_if_true,falsifier,status,created_utc) VALUES(?,?,?,?,?,?,?)",
                 (run_id,round_no,claim,expected,falsifier,"CANDIDATE",utcnow())); conn.commit()

def write_final_report(run_id,status,inventory,road,conn,oracle_reason=""):
    experiments=conn.execute("SELECT round_no,tool,params_json,result_json FROM experiments WHERE run_id=? ORDER BY round_no",(run_id,)).fetchall()
    hypotheses=conn.execute("SELECT round_no,claim,expected_if_true,falsifier,status FROM hypotheses WHERE run_id=? ORDER BY round_no",(run_id,)).fetchall()
    path=REPORTS/"FINAL_REPORT.md"
    lines=["# NCDR DB_0 — local Qwen run report","",f"- Run: `{run_id}`",f"- Status: **{status}**",f"- Created (UTC): {utcnow()}","- DB_0 access: read-only","- Model endpoint: local Ollama API","", "## Deterministic inventory", "",f"- Validated chain records: {inventory.get('record_count','unknown')}",f"- Compression 0x02 records validated: {inventory.get('compression02_valid','reused/unknown')}",f"- Type/compression counts: `{json.dumps(inventory.get('counts',{}),sort_keys=True)}`", "", "## Road corpus", "",f"`{json.dumps(road,ensure_ascii=False,sort_keys=True)}`", "", "## Experiments", ""]
    if not experiments: lines.append("No model-proposed probe completed.")
    for row in experiments:
        result=json.loads(row["result_json"])
        lines.extend([f"### Round {row['round_no']}: `{row['tool']}`","",f"Parameters: `{row['params_json']}`","",f"Result: `{json.dumps(result,ensure_ascii=False)[:2500]}`",""])
    lines.extend(["## Model hypotheses (candidates only)",""])
    for row in hypotheses:
        lines.extend([f"- Round {row['round_no']}: **{row['status']}** — {row['claim']}",f"  - Expected if true: {row['expected_if_true']}",f"  - Falsifier: {row['falsifier']}"])
    lines.extend(["","## Conclusion","", "No candidate decoder is promoted to confirmed by statistical similarity alone. The runner does not execute model-written code or alter parser behavior."])
    if status=="BLOCKED_ORACLE":
        lines.extend(["", "### Exact external dependency", "", oracle_reason or "A trusted logical-buffer output for a known compression-0x01 record is required. The current package intentionally does not run POISoN or patch to produce it."])
    elif status=="EXPERIMENTS_EXHAUSTED":
        lines.extend(["", "### Remaining status", "", "The bounded, unique probe queue is exhausted. Compression-0x01 decoding and detailed road geometry remain unresolved unless new independent evidence is supplied."])
    path.write_text("\n".join(lines)+"\n",encoding="utf-8")
    return path

def run(db0:Path,model:str,max_rounds:int,resume_final:bool=False)->int:
    db0=db0.resolve()
    validate_runtime(db0)
    acquire_lock(); awake=hold_awake(); conn=init_store(); run_id=None
    try:
        set_status(None,"STARTING","HASH_DB0","Hashing source in read-only mode")
        source_hash=sha256_file(db0); source_size=db0.stat().st_size
        manifest_path=ROOT/"transfer_manifest.json"
        if manifest_path.is_file():
            transfer=json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_hash=transfer.get("db0",{}).get("sha256")
            if expected_hash and source_hash!=expected_hash:
                raise ValueError("DB_0 SHA-256 does not match transfer_manifest.json; the transfer may be incomplete")
        run_id=ensure_run(conn,db0,source_hash,source_size)
        run_row=conn.execute("SELECT status,note FROM runs WHERE run_id=?",(run_id,)).fetchone()
        previous=run_row["status"]
        run_note=run_row["note"] or ""
        resumable=(
            resume_final and previous=="BLOCKED_ORACLE" and
            RESUMABLE_QWEN_STOP in run_note
        )
        if previous in FINAL_STATUSES and not resumable:
            detail=run_note or "Existing completed run found; use its report."
            set_status(run_id,previous,"FINISHED",detail)
            log(f"Existing run {run_id} has final status {previous}; nothing was rerun.")
            return 0
        if resumable:
            old_report=REPORTS/"FINAL_REPORT.md"
            if old_report.is_file():
                backup=REPORTS/f"FINAL_REPORT_PRE_RESUME_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                shutil.copy2(old_report,backup)
                log(f"Preserved the previous report at {backup}")
            conn.execute(
                "UPDATE runs SET status='RUNNING',stage='RESUMING',note=?,finished_utc=NULL WHERE run_id=?",
                ("User resumed the saved run after bounded invalid Qwen responses.",run_id),
            )
            conn.commit()
            log(f"Explicitly resumed saved run {run_id} after the prior Qwen output stop.")
        update_run(conn,run_id,status="RUNNING",stage="INDEX_DB0")
        set_status(run_id,"RUNNING","INDEX_DB0","Scanning validated record chain and verifying compression 0x02")
        with DB0Reader(db0) as reader:
            inventory=insert_records(conn,run_id,reader)
            inventory.update({"source_sha256":source_hash,"source_size":source_size,
                              "compression02_errors":inventory.get("compression02_errors",[])})
            (WORK/"inventory_summary.json").write_text(json.dumps(inventory,indent=2)+"\n",encoding="utf-8")
            mark_task(conn,run_id,"INDEX_DB0","COMPLETE",inventory)
            update_run(conn,run_id,stage="AUTHORITATIVE_ROADS")
            set_status(run_id,"RUNNING","AUTHORITATIVE_ROADS","Rebuilding the confirmed road corpus into work/")
            road=run_road_corpus(db0)
            (WORK/"road_summary.json").write_text(json.dumps(road,indent=2)+"\n",encoding="utf-8")
            mark_task(conn,run_id,"AUTHORITATIVE_ROADS","COMPLETE",road)
            # Fixed baseline probes are finite and run before the model loop.
            baseline=[
                ("inspect_block",{"sector":"0x11576","offset":8,"length":128}),
                ("codec_sweep",{"sectors":["0x11576"],"offsets":list(range(8,32,3)),"codecs":sorted(STANDARD_CODECS)}),
                ("prefix_compare",{"block_type":0,"length":32,"count":6}),
                ("word_profile",{"block_type":0,"compression":1,"width":2,"offset_start":8,"offset_end":136,"step":2,"sample_limit":64}),
                ("list_type0_targets",{"compression":1,"limit":24}),
                ("road_summary",{}),
            ]
            history=[]
            prior=conn.execute("SELECT round_no,tool,params_json,result_json FROM experiments WHERE run_id=? ORDER BY round_no DESC LIMIT 8",(run_id,)).fetchall()
            for saved in reversed(prior):
                history.append({"round":saved["round_no"],"tool":saved["tool"],
                                "args":json.loads(saved["params_json"]),
                                "result":json.loads(saved["result_json"]),"resumed":True})
            done={row[0] for row in conn.execute("SELECT fingerprint FROM experiments WHERE run_id=?",(run_id,)).fetchall()}
            round_no=conn.execute("SELECT coalesce(max(round_no),0) FROM experiments WHERE run_id=?",(run_id,)).fetchone()[0]
            for tool,args in baseline:
                fp=action_fingerprint(tool,args)
                if fp in done: continue
                round_no+=1
                try: result=execute_tool(reader,tool,args)
                except Exception as exc: result={"error":type(exc).__name__,"detail":str(exc)}
                record_experiment(conn,run_id,round_no,tool,args,result,fp);done.add(fp)
                history.append({"round":round_no,"tool":tool,"args":args,"result":result})
                set_status(run_id,"RUNNING","BASELINE_PROBES",f"Completed fixed probe {round_no}/6",{"round":round_no,"unique_actions":len(done)})
                log(f"Completed baseline action {round_no}: {tool}")
            system_prompt=(ROOT/"prompts"/"system_prompt.txt").read_text(encoding="utf-8")
            client=OllamaClient(model)
            if not client.model_available():
                update_run(conn,run_id,status="WAITING_OLLAMA",stage="MODEL_LOOP",note=f"Model {model} or local Ollama API unavailable")
                set_status(run_id,"WAITING_OLLAMA","MODEL_LOOP",f"Local Ollama model {model} is unavailable; install/pull it and resume.")
                return 2
            invalid_count=0; duplicate_count=0; unique_model_actions=0; oracle_reason=""
            update_run(conn,run_id,status="RUNNING",stage="QWEN_RESEARCH")
            for _ in range(max_rounds):
                round_no+=1
                set_status(run_id,"RUNNING","QWEN_RESEARCH",f"Local analysis round {round_no}; no user input is requested",{"round":round_no,"max_rounds":max_rounds,"unique_actions":len(done)})
                try:
                    user_prompt,(raw_response,value)=model_decision(client,system_prompt,inventory,road,history,round_no)
                    prompt_hash=hashlib.sha256(user_prompt.encode()).hexdigest()
                    conn.execute("INSERT INTO model_calls(run_id,round_no,model,prompt_sha256,response_json,parse_status,created_utc) VALUES(?,?,?,?,?,?,?)",
                                 (run_id,round_no,model,prompt_hash,raw_response,"JSON_OK",utcnow()));conn.commit()
                    hypothesis,args,expected,falsifier,confidence,tool=validate_decision(value)
                    if tool!="stop": add_hypothesis(conn,run_id,round_no,hypothesis,expected,falsifier)
                except (OllamaError,ValueError,TypeError,KeyError) as exc:
                    invalid_count+=1
                    message={"round":round_no,"error":str(exc),"result":"No experiment executed; bounded repair prompt will be used."}
                    history.append(message); log(f"Rejected model response round {round_no}: {exc}")
                    if invalid_count>=5:
                        oracle_reason="The local model did not produce a valid allow-listed action after five bounded retries. No user prompt was shown."
                        break
                    continue
                if tool=="stop":
                    reason=args.get("reason",""); details=str(args.get("details", ""))[:1000]
                    if reason=="external_oracle_required":
                        oracle_reason=details or "A validated type-0x01 logical buffer is required."
                        break
                    if reason=="no_more_safe_tests" and unique_model_actions>=20:
                        break
                    history.append({"round":round_no,"tool":"stop","rejected":"minimum breadth not reached","unique_model_actions":unique_model_actions})
                    continue
                if tool not in ALLOWED_TOOLS-{"stop"}:
                    invalid_count+=1; history.append({"round":round_no,"error":"invalid allow-listed tool"});continue
                fp=action_fingerprint(tool,args)
                if fp in done:
                    duplicate_count+=1
                    history.append({"round":round_no,"tool":tool,"args":args,"duplicate":True,"instruction":"Choose a different action."})
                    if duplicate_count>=10:
                        oracle_reason="The model repeated already executed probes ten times; the unique safe action queue was exhausted."
                        break
                    continue
                try: result=execute_tool(reader,tool,args)
                except Exception as exc:
                    result={"error":type(exc).__name__,"detail":str(exc)}
                record_experiment(conn,run_id,round_no,tool,args,result,fp);done.add(fp);unique_model_actions+=1
                history.append({"round":round_no,"tool":tool,"args":args,"result":result})
                log(f"Completed model-proposed safe action {round_no}: {tool}")
            else:
                oracle_reason=f"The configured {max_rounds}-round local research budget was exhausted. The run was saved and can be resumed by increasing the round limit; no user input was requested."
            status="BLOCKED_ORACLE" if oracle_reason else "EXPERIMENTS_EXHAUSTED"
            report=write_final_report(run_id,status,inventory,road,conn,oracle_reason)
            update_run(conn,run_id,status=status,stage="FINISHED",note=oracle_reason or "Unique bounded action budget exhausted",finished=True)
            mark_task(conn,run_id,"BOUNDED_QWEN_RESEARCH",status,{"unique_actions":len(done),"model_actions":unique_model_actions,"report":str(report.relative_to(ROOT))})
            mark_task(conn,run_id,"FINAL_REPORT","COMPLETE",{"path":str(report.relative_to(ROOT))})
            set_status(run_id,status,"FINISHED",oracle_reason or "Bounded research queue exhausted; see reports/FINAL_REPORT.md",{"unique_actions":len(done),"model_actions":unique_model_actions,"report":str(report.relative_to(ROOT))})
            log(f"Run finished with {status}. Report: {report}")
            return 0
    except Exception as exc:
        if run_id:
            update_run(conn,run_id,status="FAILED",stage="ERROR",note=str(exc),finished=True)
        set_status(run_id,"FAILED","ERROR",f"{type(exc).__name__}: {exc}")
        log(f"Fatal error: {type(exc).__name__}: {exc}")
        raise
    finally:
        release_awake(awake)
        try: conn.close()
        except Exception: pass
        LOCK_PATH.unlink(missing_ok=True)

def main()->int:
    parser=argparse.ArgumentParser(description="Read-only DB_0 local research runner with local Ollama/Qwen")
    parser.add_argument("--db0",type=Path,default=ROOT/"DB_0")
    parser.add_argument("--model",default=os.environ.get("NCDR_QWEN_MODEL","qwen3.5:4b"))
    parser.add_argument("--max-rounds",type=int,default=80)
    parser.add_argument("--resume-final",action="store_true",
                        help="Resume a saved BLOCKED_ORACLE run only when its recorded cause is bounded invalid Qwen output.")
    parser.add_argument("--status",action="store_true")
    args=parser.parse_args()
    if args.status:
        print(STATUS_PATH.read_text(encoding="utf-8") if STATUS_PATH.exists() else "No run has started.")
        return 0
    if not 1<=args.max_rounds<=200: parser.error("--max-rounds must be 1..200")
    try: validate_runtime(args.db0)
    except Exception as exc:
        print(f"Research preflight failed: {type(exc).__name__}: {exc}",file=sys.stderr)
        return 2
    try: return run(args.db0,args.model,args.max_rounds,resume_final=args.resume_final)
    except Exception: return 1

if __name__=="__main__": raise SystemExit(main())
