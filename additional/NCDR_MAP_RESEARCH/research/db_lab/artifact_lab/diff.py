"""Filesystem and byte-level comparison for read-only artifact copies."""
from __future__ import annotations
import bisect, json, mmap, os, sqlite3
from pathlib import Path
from .catalog import _file_fingerprint
from ..core.db_reader import DBReader

def compare_directories(catalog, baseline_id, experiment_id, max_ranges=10000, chunk_size=1024*1024):
    db=catalog.db
    base=db.execute("SELECT source_path FROM artifacts WHERE artifact_id=?",(baseline_id,)).fetchone()
    exp=db.execute("SELECT source_path FROM artifacts WHERE artifact_id=?",(experiment_id,)).fetchone()
    if not base or not exp: raise ValueError("Both baseline and experiment artifacts must be catalogued")
    base_files={r["relative_path"]:r for r in db.execute("SELECT * FROM files WHERE artifact_id=? AND is_directory=0",(baseline_id,))}
    exp_files={r["relative_path"]:r for r in db.execute("SELECT * FROM files WHERE artifact_id=? AND is_directory=0",(experiment_id,))}
    removed=set(base_files)-set(exp_files); added=set(exp_files)-set(base_files)
    # Identical hashes with different relative paths are classified as moves.
    moves=[]
    for old in list(removed):
        matches=[new for new in added if base_files[old]["sha256"]==exp_files[new]["sha256"]]
        if matches:
            new=sorted(matches)[0]; moves.append((old,new)); removed.remove(old); added.remove(new)
    rows=[]; ranges=0
    for old,new in moves:
        rows.append({"relative_path":old,"change_type":"MOVED","file_offset":None,"old_size":base_files[old]["size"],"new_size":exp_files[new]["size"],"old_sha256":base_files[old]["sha256"],"new_sha256":exp_files[new]["sha256"],"similarity":1.0,"details":{"new_path":new}})
    for rel in sorted(removed):
        r=base_files[rel]; rows.append({"relative_path":rel,"change_type":"REMOVED","file_offset":None,"old_size":r["size"],"new_size":0,"old_sha256":r["sha256"],"new_sha256":"","similarity":0.0,"details":{}})
    for rel in sorted(added):
        r=exp_files[rel]; rows.append({"relative_path":rel,"change_type":"ADDED","file_offset":None,"old_size":0,"new_size":r["size"],"old_sha256":"","new_sha256":r["sha256"],"similarity":0.0,"details":{}})
    identical=0
    for rel in sorted(set(base_files)&set(exp_files)):
        left,right=base_files[rel],exp_files[rel]
        if left["sha256"]==right["sha256"]:
            identical+=1; rows.append({"relative_path":rel,"change_type":"IDENTICAL","file_offset":None,"old_size":left["size"],"new_size":right["size"],"old_sha256":left["sha256"],"new_sha256":right["sha256"],"similarity":1.0,"details":{}}); continue
        diff_count=0; same=0; oldpath=Path(left["source_path"]); newpath=Path(right["source_path"]); size=max(left["size"],right["size"]); header_maps=(None,None)
        if Path(rel).name.upper()=="DB_0":
            header_maps=(_headers(oldpath),_headers(newpath))
        try:
            with oldpath.open("rb") as fa,newpath.open("rb") as fb,mmap.mmap(fa.fileno(),0,access=mmap.ACCESS_READ) as a,mmap.mmap(fb.fileno(),0,access=mmap.ACCESS_READ) as b:
                for offset in range(0,size,chunk_size):
                    aa=bytes(a[offset:min(offset+chunk_size,len(a))]); bb=bytes(b[offset:min(offset+chunk_size,len(b))])
                    if aa==bb: same+=len(aa); continue
                    n=max(len(aa),len(bb)); i=0
                    while i<n and ranges<max_ranges:
                        av=aa[i] if i<len(aa) else None; bv=bb[i] if i<len(bb) else None
                        if av==bv: same+=1; i+=1; continue
                        start=i; oldbytes=bytearray(); newbytes=bytearray()
                        while i<n:
                            av=aa[i] if i<len(aa) else None; bv=bb[i] if i<len(bb) else None
                            if av==bv: break
                            if av is not None: oldbytes.append(av)
                            if bv is not None: newbytes.append(bv)
                            diff_count+=1; i+=1
                        phys=offset+start; meta=_record_meta(phys,header_maps[0]) if header_maps[0] else {}
                        logical=(phys-meta["record_offset"]) if meta and meta.get("compression")==0 else None
                        rows.append({"relative_path":rel,"change_type":"CHANGED_RANGE","file_offset":phys,"old_size":len(oldbytes),"new_size":len(newbytes),"old_sha256":left["sha256"],"new_sha256":right["sha256"],"similarity":None,"details":{"sector":phys//512 if rel.upper().endswith("DB_0") else None,"record_sector":meta.get("sector"),"block_type":meta.get("block_type"),"compression":meta.get("compression"),"logical_offset":logical,"old_bytes":bytes(oldbytes[:32]).hex(),"new_bytes":bytes(newbytes[:32]).hex(),"truncated_bytes":max(0,len(oldbytes)-32)}})
                        ranges+=1
                    same+=max(0,n-diff_count)
                    if ranges>=max_ranges: break
        except OSError as e: rows.append({"relative_path":rel,"change_type":"DIFF_ERROR","file_offset":None,"old_size":left["size"],"new_size":right["size"],"old_sha256":left["sha256"],"new_sha256":right["sha256"],"similarity":None,"details":{"error":str(e)}})
        sim=round(max(0.0,1-diff_count/max(1,size)),8)
        for row in rows:
            if row["relative_path"]==rel and row["change_type"]=="CHANGED_RANGE": row["similarity"]=sim
        db.execute("INSERT INTO cross_source_matches(match_type,source_artifact,target_artifact,source_file,target_file,value,evidence,confidence) VALUES('changed_file',?,?,?,?,?,?,?)",(baseline_id,experiment_id,rel,rel,f"{diff_count} differing bytes","SHA256 mismatch plus byte scan","CONFIRMED"))
    db.execute("DELETE FROM binary_diffs WHERE baseline_artifact=? AND experiment_artifact=?",(baseline_id,experiment_id))
    for row in rows:
        detail=row["details"]
        db.execute("INSERT INTO binary_diffs(baseline_artifact,experiment_artifact,relative_path,change_type,file_offset,sector,record_sector,block_type,compression,logical_offset,old_bytes,new_bytes,old_size,new_size,similarity,details_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (baseline_id,experiment_id,row["relative_path"],row["change_type"],row["file_offset"],detail.get("sector"),detail.get("record_sector"),detail.get("block_type"),detail.get("compression"),detail.get("logical_offset"),detail.get("old_bytes"),detail.get("new_bytes"),row["old_size"],row["new_size"],row["similarity"],json.dumps(detail)))
    db.commit()
    counts={}
    for r in rows: counts[r["change_type"]]=counts.get(r["change_type"],0)+1
    return {"baseline":base["source_path"],"experiment":exp["source_path"],"files_identical":identical,"files_added":len(added),"files_removed":len(removed),"files_moved":len(moves),"diff_ranges":ranges,"change_counts":counts,"diffs":rows}

def _headers(path):
    try:
        with DBReader(path) as reader:
            return {b.offset:{"sector":b.sector,"record_offset":b.offset,"block_type":b.block_type,"compression":b.compression,"span":b.span} for b in reader.blocks}
    except Exception: return None

def _record_meta(offset,headers):
    if not headers: return {}
    # The DB_0 records are ordered; build a short sorted list as needed.
    starts=sorted(headers); ix=bisect.bisect_right(starts,offset)-1
    if ix<0:return {}
    h=headers[starts[ix]]
    return h if offset < h["record_offset"]+h["span"]*512 else {}
