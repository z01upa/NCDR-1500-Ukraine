"""Content-addressed DB_0 record comparison for controlled POISoN experiments."""
from __future__ import annotations
import csv, hashlib, json, mmap, sqlite3, zlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .db_validation import SECTOR_SIZE, validate_db0

PARSE_VERSION=1


def inventory_db0_files(inventory_run: Path):
    rows=[]
    with (inventory_run/"data"/"db0_files.csv").open(newline="",encoding="utf-8") as f:
        for row in csv.DictReader(f):
            root=Path(row["source_path"])
            path=root if root.is_file() else root/row["relative_path"]
            rows.append({**row,"path":str(path.resolve()),"size":int(row["size"]),"sha256":row["sha256"]})
    return rows


def _cache_records(catalog, sha):
    return [dict(r) for r in catalog.db.execute("SELECT sector,offset,span,alignment,block_type,compression,logical_units,record_sha256 FROM db0_records WHERE sha256=? ORDER BY record_index",(sha,))]


def _save_records(catalog, sha, size, records, source_run, cache_source, validation):
    catalog.db.execute("DELETE FROM db0_records WHERE sha256=?",(sha,))
    catalog.db.executemany("INSERT INTO db0_records(sha256,record_index,sector,offset,span,alignment,block_type,compression,logical_units,record_sha256) VALUES(?,?,?,?,?,?,?,?,?,?)",
        [(sha,i,r["sector"],r["offset"],r["span"],r["alignment"],r["block_type"],r["compression"],r["logical_units"],r["record_sha256"]) for i,r in enumerate(records)])
    catalog.db.execute("INSERT OR REPLACE INTO db0_parse_cache(sha256,size,parse_version,status,record_count,source_run,cache_source,parsed_at,validation_json) VALUES(?,?,?,?,?,?,?,?,?)",
        (sha,size,PARSE_VERSION,"VALIDATED_DB_0",len(records),source_run,cache_source,datetime.now(timezone.utc).isoformat(),json.dumps(validation,sort_keys=True)))
    catalog.db.commit()


def _legacy_db0_records(path, expected_sha, expected_size, legacy_db, source_run):
    """Reuse the completed earlier DB_0 framing index when its SHA matches."""
    if not legacy_db.exists(): return None
    try:
        old=sqlite3.connect(legacy_db); old.row_factory=sqlite3.Row
        rows=old.execute("SELECT sector,offset,span,alignment,block_type,compression,logical_units FROM blocks ORDER BY offset").fetchall()
        old.close()
    except sqlite3.Error:
        return None
    if not rows or int(Path(path).stat().st_size)!=expected_size: return None
    records=[]; expected_offset=2*SECTOR_SIZE
    digest=hashlib.sha256()
    with Path(path).open("rb") as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as mm:
        digest.update(mm[:expected_offset])
        for i,row in enumerate(rows):
            r={k:int(row[k]) for k in ("sector","offset","span","alignment","block_type","compression","logical_units")}
            size=r["span"]*SECTOR_SIZE
            if r["offset"]!=expected_offset or r["sector"]!=expected_offset//SECTOR_SIZE or not (0<r["span"]<=255) or r["block_type"]>0x1f or r["compression"] not in (0,1,2):
                return None
            end=expected_offset+size
            if end>expected_size: return None
            raw=mm[expected_offset:end]
            r["record_sha256"]=hashlib.sha256(raw).hexdigest()
            digest.update(raw); records.append(r); expected_offset=end
        if expected_offset!=expected_size or digest.hexdigest()!=expected_sha: return None
    return {"records":records,"size":expected_size,"sha256":expected_sha,"record_count":len(records),"valid":True,
            "status":"VALIDATED_DB_0","source":"reused legacy completed DB_0 block index; verified chain and content SHA256",
            "errors":[]},source_run


def get_or_parse_db0(catalog,path,sha,size,source_run,legacy_db=None,legacy_sha=None):
    row=catalog.db.execute("SELECT * FROM db0_parse_cache WHERE sha256=? AND size=? AND parse_version=? AND status='VALIDATED_DB_0'",(sha,size,PARSE_VERSION)).fetchone()
    if row:
        records=_cache_records(catalog,sha)
        if len(records)==row["record_count"]: return {"records":records,"size":size,"sha256":sha,"record_count":len(records),"valid":True,"status":"VALIDATED_DB_0","source":"content-addressed cache","errors":[]}
    if legacy_sha and sha==legacy_sha and legacy_db:
        reused=_legacy_db0_records(path,sha,size,legacy_db,source_run)
        if reused:
            parsed,old_run=reused
            _save_records(catalog,sha,size,parsed["records"],old_run,"legacy completed DB_0 analysis.sqlite",parsed)
            return parsed
    validation=validate_db0(path)
    if validation.get("sha256")!=sha:
        validation.update(valid=False,status="INVENTORY_HASH_MISMATCH",errors=validation.get("errors",[])+["current input SHA256 differs from the latest inventory run"])
    if not validation.get("valid"):
        return validation
    _save_records(catalog,sha,size,validation["records"],source_run,"full structural parse",validation)
    return {**validation,"source":"full structural parse"}


def _logical_bytes(path, record):
    comp=int(record["compression"]); units=int(record["logical_units"]); expected=units*SECTOR_SIZE
    if comp not in (0,2): return None,"UNSUPPORTED_COMPRESSION_0x01"
    if expected<=0: return None,"UNKNOWN_OR_EMPTY_LOGICAL_EXTENT"
    start=int(record["offset"]); size=int(record["span"])*SECTOR_SIZE
    with Path(path).open("rb") as f:
        f.seek(start); raw=f.read(size)
    if len(raw)!=size: return None,"TRUNCATED_RECORD"
    if comp==0:
        if expected>len(raw): return None,"LOGICAL_EXTENT_EXCEEDS_PHYSICAL_RECORD"
        return raw[:expected],"READABLE_RAW"
    try:
        dec=zlib.decompressobj()
        payload=dec.decompress(raw[8:],expected+1)
        payload+=dec.flush()
        if not dec.eof or len(payload)+8!=expected: return None,"ZLIB_LOGICAL_SIZE_MISMATCH"
        return raw[:8]+payload,"READABLE_ZLIB"
    except (zlib.error,ValueError) as exc:
        return None,"ZLIB_ERROR: "+str(exc)


def _range_stats(a:bytes,b:bytes):
    common=min(len(a),len(b)); changed=[]; first=None; last=None; count=0; start=None
    for i in range(common):
        if a[i]!=b[i]:
            count+=1; first=i if first is None else first; last=i
            if start is None: start=i
        elif start is not None:
            changed.append((start,i-1,i-start)); start=None
    if start is not None: changed.append((start,common-1,common-start))
    if len(a)!=len(b):
        tail_start=common
        count+=abs(len(a)-len(b))
        if first is None: first=tail_start
        last=max(len(a),len(b))-1
        changed.append((tail_start,max(len(a),len(b))-1,abs(len(a)-len(b))))
    return {"first":first,"last":last,"count":count,"ranges":changed}


def compare_db0(catalog,baseline,experiment,experiment_name,baseline_name="ORIGINAL"):
    a=baseline["records"]; b=experiment["records"]
    am={int(r["sector"]):r for r in a}; bm={int(r["sector"]):r for r in b}
    same=[]; changed=[]; old_only=set(am)-set(bm); new_only=set(bm)-set(am)
    for sector in sorted(set(am)&set(bm)):
        if am[sector]["record_sha256"]==bm[sector]["record_sha256"]: same.append(sector)
        else: changed.append(sector)
    # Detect exact relocations by one-to-one raw-record digest matching.
    old_by_hash=defaultdict(list); new_by_hash=defaultdict(list)
    for sector in old_only: old_by_hash[am[sector]["record_sha256"]].append(sector)
    for sector in new_only: new_by_hash[bm[sector]["record_sha256"]].append(sector)
    moved=[]
    for digest in sorted(set(old_by_hash)&set(new_by_hash)):
        for old_sector,new_sector in zip(sorted(old_by_hash[digest]),sorted(new_by_hash[digest])):
            moved.append((old_sector,new_sector)); old_only.remove(old_sector); new_only.remove(new_sector)
    detail_rows=[]; logical_rows=[]; affected_types=Counter(); affected_compressions=Counter(); physical_total=logical_total=0
    path_a=Path(baseline["path"]); path_b=Path(experiment["path"])

    def emit(kind,old,new):
        nonlocal physical_total,logical_total
        row= new or old
        sector=int(row["sector"]); block_type=int(row["block_type"]); comp=int(row["compression"]); span=int(row["span"]); physical_size=span*SECTOR_SIZE
        phys={"first":None,"last":None,"count":0}
        old_raw=b""; new_raw=b""
        if old is not None:
            with path_a.open("rb") as f: f.seek(int(old["offset"])); old_raw=f.read(int(old["span"])*SECTOR_SIZE)
        if new is not None:
            with path_b.open("rb") as f: f.seek(int(new["offset"])); new_raw=f.read(int(new["span"])*SECTOR_SIZE)
        if kind=="CHANGED":
            phys=_range_stats(old_raw,new_raw)
            base=int(old["offset"])
            phys["ranges"]=[(base+s,base+e,count) for s,e,count in phys["ranges"]]
            if phys["first"] is not None: phys["first"]+=base; phys["last"]+=base
        elif kind=="ADDED":
            first=int(new["offset"]); last=first+len(new_raw)-1
            phys={"first":first,"last":last,"count":len(new_raw),"ranges":[(first,last,len(new_raw))]}
        elif kind=="REMOVED":
            first=int(old["offset"]); last=first+len(old_raw)-1
            phys={"first":first,"last":last,"count":len(old_raw),"ranges":[(first,last,len(old_raw))]}
        elif kind=="RELOCATED":
            ranges=[(int(old["offset"]),int(old["offset"])+len(old_raw)-1,0),(int(new["offset"]),int(new["offset"])+len(new_raw)-1,0)]
            phys={"first":min(x[0] for x in ranges),"last":max(x[1] for x in ranges),"count":0,"ranges":ranges}
        old_log,old_status=_logical_bytes(path_a,old) if old is not None else (None,"MISSING")
        new_log,new_status=_logical_bytes(path_b,new) if new is not None else (None,"MISSING")
        logical={"first":None,"last":None,"count":0,"ranges":[]}; logical_status="NOT_COMPARABLE"
        if old_log is not None and new_log is not None:
            logical=_range_stats(old_log,new_log); logical_status="COMPARED"
        elif old_log is not None and new is None:
            logical={"first":0,"last":len(old_log)-1,"count":len(old_log),"ranges":[(0,len(old_log)-1,len(old_log))]}; logical_status="REMOVED_READABLE_BLOCK"
        elif new_log is not None and old is None:
            logical={"first":0,"last":len(new_log)-1,"count":len(new_log),"ranges":[(0,len(new_log)-1,len(new_log))]}; logical_status="ADDED_READABLE_BLOCK"
        physical_total+=phys["count"]; logical_total+=logical["count"]
        affected_types[str(block_type)]+=1; affected_compressions[str(comp)]+=1
        old_units=int(old["logical_units"]) if old else None; new_units=int(new["logical_units"]) if new else None
        detail_rows.append({"experiment":experiment_name,"change_kind":kind,"sector":sector,"old_sector":old["sector"] if old else "","new_sector":new["sector"] if new else "","block_type":block_type,"compression":comp,"span":span,"physical_size":physical_size,"logical_size":new_units*SECTOR_SIZE if new else old_units*SECTOR_SIZE,"original_span":old["span"] if old else "","experiment_span":new["span"] if new else "","original_physical_size":len(old_raw),"experiment_physical_size":len(new_raw),"original_logical_size":old_units*SECTOR_SIZE if old else "","experiment_logical_size":new_units*SECTOR_SIZE if new else "","physical_changed_bytes":phys["count"],"physical_changed_ranges":json.dumps(phys["ranges"],separators=(",",":")),"logical_changed_bytes":logical["count"],"first_physical_change":phys["first"] if phys["first"] is not None else "","last_physical_change":phys["last"] if phys["last"] is not None else "","first_logical_change":logical["first"] if logical["first"] is not None else "","last_logical_change":logical["last"] if logical["last"] is not None else "","logical_status":logical_status,"original_logical_status":old_status,"experiment_logical_status":new_status})
        for start,end,count in logical["ranges"]:
            logical_rows.append({"experiment":experiment_name,"change_kind":kind,"sector":sector,"block_type":block_type,"compression":comp,"first_logical_change":start,"last_logical_change":end,"logical_changed_bytes":count,"original_logical_size":old_units*SECTOR_SIZE if old else "","experiment_logical_size":new_units*SECTOR_SIZE if new else "","logical_status":logical_status})
        if not logical["ranges"]:
            # Retain a per-record logical interpretation even when the format's
            # zero logical-unit field makes a byte range unknowable.
            logical_rows.append({"experiment":experiment_name,"change_kind":kind,"sector":sector,"block_type":block_type,"compression":comp,"first_logical_change":"","last_logical_change":"","logical_changed_bytes":0,"original_logical_size":old_units*SECTOR_SIZE if old else "","experiment_logical_size":new_units*SECTOR_SIZE if new else "","logical_status":logical_status})

    for sector in changed: emit("CHANGED",am[sector],bm[sector])
    for old_sector,new_sector in moved: emit("RELOCATED",am[old_sector],bm[new_sector])
    for sector in sorted(old_only): emit("REMOVED",am[sector],None)
    for sector in sorted(new_only): emit("ADDED",None,bm[sector])
    return {"experiment":experiment_name,"baseline":baseline_name,"original_db_size":baseline["size"],"experiment_db_size":experiment["size"],"original_db_sha256":baseline["sha256"],"experiment_db_sha256":experiment["sha256"],"original_record_count":len(a),"experiment_record_count":len(b),"records_unchanged":len(same),"records_changed":len(changed),"records_added":len(new_only),"records_removed":len(old_only),"records_relocated":len(moved),"changed_block_types":dict(sorted(affected_types.items())),"changed_compression_types":dict(sorted(affected_compressions.items())),"physical_changed_bytes":physical_total,"logical_changed_bytes":logical_total,"identical_to":"","details":detail_rows,"logical_ranges":logical_rows}


def group_identical_experiments(summaries):
    groups=defaultdict(list)
    for s in summaries: groups[s["experiment_db_sha256"]].append(s["experiment"])
    for s in summaries:
        peers=sorted(n for n in groups[s["experiment_db_sha256"]] if n!=s["experiment"])
        s["identical_to"]=",".join(peers)
    return {sha:sorted(names) for sha,names in groups.items() if len(names)>1}


def write_csv(path,rows,fields):
    with Path(path).open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); writer.writeheader(); writer.writerows(rows)


def write_tables(outdir,summaries,details,logical_ranges,cache_rows):
    summary_fields=["experiment","db_size","db_sha256","record_count","changed_records","added_records","removed_records","relocated_records","changed_block_types","changed_compression_types","physical_changed_bytes","logical_changed_bytes","identical_to","original_db_size","original_record_count","records_unchanged"]
    write_csv(outdir/"poison_experiment_summary.csv",summaries,summary_fields)
    detail_fields=["experiment","change_kind","sector","old_sector","new_sector","block_type","compression","span","physical_size","logical_size","original_span","experiment_span","original_physical_size","experiment_physical_size","original_logical_size","experiment_logical_size","physical_changed_bytes","physical_changed_ranges","logical_changed_bytes","first_physical_change","last_physical_change","first_logical_change","last_logical_change","logical_status","original_logical_status","experiment_logical_status"]
    write_csv(outdir/"poison_changed_records.csv",details,detail_fields)
    logical_fields=["experiment","change_kind","sector","block_type","compression","first_logical_change","last_logical_change","logical_changed_bytes","original_logical_size","experiment_logical_size","logical_status"]
    write_csv(outdir/"poison_logical_ranges.csv",logical_ranges,logical_fields)
    write_csv(outdir/"db0_parse_cache.csv",cache_rows,["sha256","size","record_count","status","cache_source","source_run"])
