"""Provenance-preserving artifact catalog and static inventory."""
from __future__ import annotations
import hashlib, importlib.util, json, mmap, os, re, sqlite3, struct, time, uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from ..db_concurrency import connect_database
from .binary_analysis import KNOWN, find_all, pe_analyze, strings
from .disc_image import cue_layout, enumerate_iso
from .db_validation import db0_signature_hit, validate_db0

SCHEMA = """
CREATE TABLE IF NOT EXISTS artifacts(artifact_id TEXT PRIMARY KEY,parent_artifact TEXT,source_path TEXT NOT NULL,source_type TEXT NOT NULL,filename TEXT,size INTEGER,sha256 TEXT,magic TEXT,entropy REAL,created_at TEXT,imported_at TEXT,analysis_state TEXT,analysis_run TEXT,relationships_json TEXT,artifact_role TEXT,UNIQUE(source_path,source_type));
CREATE TABLE IF NOT EXISTS files(file_id INTEGER PRIMARY KEY,artifact_id TEXT,source_path TEXT,relative_path TEXT,filename TEXT,size INTEGER,sha256 TEXT,file_type TEXT,magic TEXT,entropy REAL,source_offset INTEGER,container_artifact TEXT,is_directory INTEGER DEFAULT 0,artifact_role TEXT,format_candidate TEXT,signature_hits_json TEXT,validated_format TEXT,validation_status TEXT,validation_evidence TEXT,mtime_ns INTEGER,UNIQUE(artifact_id,relative_path));
CREATE TABLE IF NOT EXISTS disc_images(artifact_id TEXT PRIMARY KEY,format TEXT,filesystem TEXT,status TEXT,track_sector_size INTEGER,track_data_offset INTEGER,file_count INTEGER,details_json TEXT);
CREATE TABLE IF NOT EXISTS firmware_containers(container_id INTEGER PRIMARY KEY,artifact_id TEXT,file_id INTEGER,magic TEXT,magic_offset INTEGER,record_size INTEGER,navboot_offsets TEXT,status TEXT,evidence TEXT);
CREATE TABLE IF NOT EXISTS firmware_modules(module_id INTEGER PRIMARY KEY,container_id INTEGER,name TEXT,offset INTEGER,size INTEGER,sha256 TEXT,extracted_path TEXT,status TEXT,evidence TEXT);
CREATE TABLE IF NOT EXISTS executables(artifact_id TEXT PRIMARY KEY,pe_offset INTEGER,machine TEXT,pe32_plus INTEGER,imports_count INTEGER,exports_count INTEGER,resources_count INTEGER,analysis_json TEXT);
CREATE TABLE IF NOT EXISTS pe_sections(id INTEGER PRIMARY KEY,artifact_id TEXT,name TEXT,virtual_address INTEGER,virtual_size INTEGER,raw_offset INTEGER,raw_size INTEGER,characteristics INTEGER);
CREATE TABLE IF NOT EXISTS executable_files(file_id INTEGER PRIMARY KEY,artifact_id TEXT,pe_offset INTEGER,machine TEXT,pe32_plus INTEGER,imports_count INTEGER,exports_count INTEGER,resources_count INTEGER,analysis_json TEXT);
CREATE TABLE IF NOT EXISTS pe_file_sections(id INTEGER PRIMARY KEY,file_id INTEGER,name TEXT,virtual_address INTEGER,virtual_size INTEGER,raw_offset INTEGER,raw_size INTEGER,characteristics INTEGER);
CREATE TABLE IF NOT EXISTS strings(id INTEGER PRIMARY KEY,artifact_id TEXT,file_id INTEGER,file_offset INTEGER,encoding TEXT,value TEXT);
CREATE INDEX IF NOT EXISTS strings_value ON strings(value);
CREATE TABLE IF NOT EXISTS binary_diffs(id INTEGER PRIMARY KEY,baseline_artifact TEXT,experiment_artifact TEXT,relative_path TEXT,change_type TEXT,file_offset INTEGER,sector INTEGER,record_sector INTEGER,block_type INTEGER,compression INTEGER,logical_offset INTEGER,old_bytes TEXT,new_bytes TEXT,old_size INTEGER,new_size INTEGER,similarity REAL,details_json TEXT);
CREATE TABLE IF NOT EXISTS cross_source_matches(id INTEGER PRIMARY KEY,match_type TEXT,source_artifact TEXT,target_artifact TEXT,source_file TEXT,target_file TEXT,source_offset INTEGER,target_offset INTEGER,value TEXT,evidence TEXT,confidence TEXT);
CREATE TABLE IF NOT EXISTS experiments(experiment_id TEXT PRIMARY KEY,name TEXT,artifact_id TEXT,baseline_artifact TEXT,created_at TEXT,parameters_json TEXT,run_id TEXT,status TEXT);
CREATE TABLE IF NOT EXISTS constants(id INTEGER PRIMARY KEY,artifact_id TEXT,file_id INTEGER,name TEXT,pattern_hex TEXT,offset INTEGER,context_hex TEXT);
CREATE TABLE IF NOT EXISTS run_tasks(run_id TEXT PRIMARY KEY,task_id TEXT,status TEXT,start_time TEXT,end_time TEXT,run_path TEXT,summary_json TEXT);
CREATE TABLE IF NOT EXISTS db0_parse_cache(sha256 TEXT PRIMARY KEY,size INTEGER,parse_version INTEGER,status TEXT,record_count INTEGER,source_run TEXT,cache_source TEXT,parsed_at TEXT,validation_json TEXT);
CREATE TABLE IF NOT EXISTS db0_records(sha256 TEXT,record_index INTEGER,sector INTEGER,offset INTEGER,span INTEGER,alignment INTEGER,block_type INTEGER,compression INTEGER,logical_units INTEGER,record_sha256 TEXT,PRIMARY KEY(sha256,sector));
CREATE INDEX IF NOT EXISTS db0_records_type ON db0_records(sha256,block_type,compression);
CREATE TABLE IF NOT EXISTS task_queue(task_id TEXT PRIMARY KEY,status TEXT,manifest_path TEXT,updated_at TEXT,run_id TEXT,detail TEXT);
"""
KB_SCHEMA="""
CREATE TABLE IF NOT EXISTS facts(fact_id INTEGER PRIMARY KEY,subject TEXT,property TEXT,value TEXT,status TEXT,evidence TEXT,artifact TEXT,offset_or_sector TEXT,experiment TEXT,confidence REAL,date TEXT,UNIQUE(subject,property,value,evidence));
CREATE TABLE IF NOT EXISTS artifact_registry(artifact_id TEXT PRIMARY KEY,source_path TEXT,source_type TEXT,sha256 TEXT,parent_artifact TEXT,analysis_run TEXT,first_seen TEXT);
"""
MAGIC_PATTERNS=[("firmware_4DAD0002",bytes.fromhex("4D AD 00 02")),("PE_MZ",b"MZ"),("ELF",b"\x7fELF"),("ISO_PVD",b"CD001")]
MAP_METADATA_NAMES={"ABSTRACT","BIBLIOGR","CARINET","COPYRIGH"}
KNOWN_FACTS=[
 ("DB_0","sector_size","512 bytes","CONFIRMED","research/PROJECT_STATE.md: physical framing"),
 ("DB_0","header_sector_id","uint24 big-endian at block +0","CONFIRMED","research/PROJECT_STATE.md: BL_HEAD fields"),
 ("DB_0","compression_0x02","zlib stream begins at local byte +8","CONFIRMED","research/PROJECT_STATE.md: compression"),
 ("DB_0","coordinate_scale","5555555","CONFIRMED","research/PROJECT_STATE.md: MULCOORD"),
 ("Firmware","container_magic","4D AD 00 02","STRONG_EVIDENCE","research/firmware/F2_CONTAINER_FORMAT.md: patch.exe code-supported magic check"),
 ("Firmware","module_name","navboot","CONFIRMED","research/firmware/F1_PATCH_TARGET.md: exact lower-case target string"),
 ("Roads","road_ownership","source ownership relationships parsed","CONFIRMED","research/roads/PROJECT_STATE.md: validated owned-road controls"),
 ("DB_0","compression_0x01","decoder not validated","UNKNOWN","Open research question; do not promote a statistical transform without validation"),
 ("Roads","geometry","field semantics unresolved","UNKNOWN","Open research question; use neutral anchor terminology"),
 ("Routing","graph_semantics","partially mapped","PARTIAL","Existing research has controls but does not establish complete routing semantics"),
 ("DB_0","writer","serialization symmetry not implemented","UNKNOWN","Open research question; original DB_0 remains read-only"),
]

def _now(): return datetime.now(timezone.utc).astimezone().isoformat()
def _hash_bytes(data): return hashlib.sha256(data).hexdigest()
def _magic(data,name=""):
    if bytes(data[:2])==b"MZ": return "PE/MZ"
    if bytes(data[:6])[1:6]==b"CD001": return "ISO9660"
    for label,needle in MAGIC_PATTERNS:
        if len(needle)>2 and bytes(data[:len(needle)])==needle: return label
    return bytes(data[:16]).hex()

def _file_fingerprint(path,offset=0,length=None,chunk_size=4*1024*1024):
    h=hashlib.sha256(); counts=Counter(); total=0
    with Path(path).open("rb") as f:
        if offset: f.seek(offset)
        left=length
        while left is None or left>0:
            n=chunk_size if left is None else min(chunk_size,left)
            buf=f.read(n)
            if not buf: break
            h.update(buf); counts.update(buf); total+=len(buf)
            if left is not None: left-=len(buf)
    ent=-sum((n/total)*(n/total and __import__('math').log2(n/total)) for n in counts.values()) if total else 0.0
    return h.hexdigest(),round(ent,6),total

def _strings_from_path(path,offset=0,length=None,max_count=10000):
    # Bounded chunks make catalogue memory stable on multi-gigabyte disc images.
    pat=re.compile(rb"[\x20-\x7e]{5,}"); upat=re.compile(rb"(?:[\x20-\x7e]\x00){5,}")
    out=[]; seen=set(); chunk_size=2*1024*1024; position=0; carry=b""
    with Path(path).open("rb") as f:
        f.seek(offset); left=length
        while (left is None or left>0) and len(out)<max_count:
            n=chunk_size if left is None else min(chunk_size,left)
            chunk=f.read(n)
            if not chunk: break
            base=position-len(carry); buf=carry+chunk
            for enc,rx in (("ascii",pat),("utf16le",upat)):
                for m in rx.finditer(buf):
                    absolute=base+m.start(); key=(enc,absolute)
                    if key in seen or absolute<offset: continue
                    value=m.group().decode("ascii", "replace") if enc=="ascii" else m.group().decode("utf-16le","replace")
                    seen.add(key); out.append((absolute,enc,value[:2048]))
                    if len(out)>=max_count: break
            position+=len(chunk); carry=buf[-16:]
            if left is not None: left-=len(chunk)
    return sorted(out,key=lambda x:x[0])

class ArtifactCatalog:
    def __init__(self, project_root, analysis_db=None, knowledge_db=None, output_dir=None):
        self.project=Path(project_root).resolve()
        base=self.project/"research"/"db_lab"
        base.mkdir(parents=True,exist_ok=True)
        self.analysis_path=Path(analysis_db or base/"analysis.sqlite")
        self.knowledge_path=Path(knowledge_db or base/"knowledge.sqlite")
        self.output_dir=Path(output_dir or base/"artifacts")
        self.analysis_path.parent.mkdir(parents=True,exist_ok=True); self.knowledge_path.parent.mkdir(parents=True,exist_ok=True)
        self.db=connect_database(self.analysis_path); self.db.row_factory=sqlite3.Row; self.db.executescript(SCHEMA); self._migrate_schema(); self.db.commit()
        self.kb=connect_database(self.knowledge_path); self.kb.executescript(KB_SCHEMA); self.kb.commit(); self._seed_facts()

    def close(self): self.db.close(); self.kb.close()
    def _migrate_schema(self):
        columns={"artifacts":{"artifact_role":"TEXT"},"files":{"artifact_role":"TEXT","format_candidate":"TEXT","signature_hits_json":"TEXT","validated_format":"TEXT","validation_status":"TEXT","validation_evidence":"TEXT","mtime_ns":"INTEGER"}}
        for table,needed in columns.items():
            existing={r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for name,kind in needed.items():
                if name not in existing: self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    def _seed_facts(self):
        for subject,prop,value,status,evidence in KNOWN_FACTS:
            self.kb.execute("INSERT OR IGNORE INTO facts(subject,property,value,status,evidence,confidence,date) VALUES(?,?,?,?,?,?,?)",(subject,prop,value,status,evidence,1.0 if status=="CONFIRMED" else .8,_now()))
        self.kb.commit()

    def _artifact(self,path,source_type,parent=None,sha=None,size=None,magic="",entropy=0.0,state="CATALOGUED",run_id=""):
        p=Path(path).resolve(); aid=_hash_bytes((str(p)+"\0"+source_type).encode())[:24]
        st=p.stat() if p.exists() else None
        role=self._role_for_path(p,source_type)
        self.db.execute("INSERT INTO artifacts(artifact_id,parent_artifact,source_path,source_type,filename,size,sha256,magic,entropy,created_at,imported_at,analysis_state,analysis_run,relationships_json,artifact_role) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_path,source_type) DO UPDATE SET size=excluded.size,sha256=excluded.sha256,magic=excluded.magic,entropy=excluded.entropy,imported_at=excluded.imported_at,analysis_state=excluded.analysis_state,analysis_run=excluded.analysis_run,artifact_role=excluded.artifact_role",
                        (aid,parent,str(p),source_type,p.name,size if size is not None else (st.st_size if st and p.is_file() else None),sha,magic,entropy,_now(),_now(),state,run_id,"{}",role))
        self.kb.execute("INSERT OR REPLACE INTO artifact_registry VALUES(?,?,?,?,?,?,?)",(aid,str(p),source_type,sha,parent,run_id,_now())); self.kb.commit()
        return aid

    @staticmethod
    def _role_for_path(path,source_type=""):
        p=Path(path); name=p.name.upper()
        if p.is_dir():
            if name=="ORIGINAL" or name.startswith("OUTPUT_"): return "controlled_experiment"
            if name in ("RESEARCH","TOOLS","POISON"): return "research_artifacts" if name=="RESEARCH" else "executable_tools"
            return "generic_directory"
        if name=="DB_0": return "navigation_database_candidate"
        if name in MAP_METADATA_NAMES or name==".DS_STORE": return "map_metadata" if name!=".DS_STORE" else "generic_file"
        if p.suffix.lower() in (".iso",".bin",".img",".cue"): return "disc_image_candidate"
        if p.suffix.lower() in (".exe",".dll"): return "executable_candidate"
        if source_type in ("firmware","firmware_candidate"): return "firmware_candidate"
        return "generic_file"

    def _insert_file(self,aid,source_path,relative,size,sha,ftype,magic,entropy,source_offset=0,container=None,isdir=0,classification=None):
        classification=classification or {}
        p=Path(source_path); stat=p.stat() if p.exists() else None
        role=classification.get("artifact_role",self._role_for_path(p))
        cur=self.db.execute("INSERT OR REPLACE INTO files(artifact_id,source_path,relative_path,filename,size,sha256,file_type,magic,entropy,source_offset,container_artifact,is_directory,artifact_role,format_candidate,signature_hits_json,validated_format,validation_status,validation_evidence,mtime_ns) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (aid,str(source_path),relative,Path(relative).name,size,sha,ftype,magic,entropy,source_offset,container,isdir,role,classification.get("format_candidate"),json.dumps(classification.get("signature_hits",[])),classification.get("validated_format"),classification.get("validation_status","NOT_TESTED"),classification.get("validation_evidence",""),stat.st_mtime_ns if stat else None))
        return cur.lastrowid

    def _clear_artifact_analysis(self, aid):
        """Drop derived rows before refreshing an artifact's indexed children."""
        predicate="file_id IN (SELECT file_id FROM files WHERE artifact_id=?)"
        self.db.execute(f"DELETE FROM strings WHERE {predicate}",(aid,))
        self.db.execute(f"DELETE FROM constants WHERE {predicate}",(aid,))
        self.db.execute(f"DELETE FROM executable_files WHERE {predicate}",(aid,))
        self.db.execute(f"DELETE FROM pe_file_sections WHERE {predicate}",(aid,))
        self.db.execute("DELETE FROM cross_source_matches WHERE match_type='known_constant' AND source_artifact=?",(aid,))
        self.db.execute("DELETE FROM pe_sections WHERE artifact_id=?",(aid,))
        self.db.execute("DELETE FROM executables WHERE artifact_id=?",(aid,))
        container_ids=[r[0] for r in self.db.execute("SELECT container_id FROM firmware_containers WHERE artifact_id=?",(aid,))]
        for cid in container_ids: self.db.execute("DELETE FROM firmware_modules WHERE container_id=?",(cid,))
        self.db.execute("DELETE FROM firmware_containers WHERE artifact_id=?",(aid,))
        self.db.execute("DELETE FROM files WHERE artifact_id=?",(aid,))

    def _analyze_file(self,aid,path,relative,source_offset=0,length=None,container=None,run_id=""):
        path=Path(path); size=path.stat().st_size if length is None else length
        sha,entropy,total=_file_fingerprint(path,source_offset,length)
        with path.open("rb") as f:
            f.seek(source_offset); prefix=f.read(65536)
        def read_segment():
            with path.open("rb") as f:
                f.seek(source_offset)
                return f.read(length if length is not None else size)
        magic=_magic(prefix,path.name); suffix=path.suffix.lower()
        signature_hits=[]
        if db0_signature_hit(prefix): signature_hits.append("DB0_HEADER_PREFIX_000000")
        if prefix[:2]==b"MZ": signature_hits.append("PE_MZ")
        if b"CD001" in prefix[:32768]: signature_hits.append("ISO9660_PVD_CANDIDATE")
        has_container_magic=False
        if size<=128*1024*1024 and suffix not in (".db",):
            try:
                with path.open("rb") as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as mm:
                    has_container_magic=mm.find(bytes.fromhex("4D AD 00 02"),source_offset,source_offset+size)>=0
            except (ValueError,OSError): pass
        db0_candidate=path.name.upper()=="DB_0" or bool(signature_hits and signature_hits[0]=="DB0_HEADER_PREFIX_000000")
        db0_validation=validate_db0(path,source_offset,length if length is not None else size) if db0_candidate else None
        if db0_candidate and db0_validation and db0_validation["signature_hit"] and "DB0_HEADER_PREFIX_000000" not in signature_hits:
            signature_hits.append("DB0_HEADER_PREFIX_000000")
        ftype=("db0" if db0_validation and db0_validation["valid"] else "pe" if prefix[:2]==b"MZ" else "iso" if b"CD001" in prefix else "firmware" if bytes.fromhex("4D AD 00 02") in prefix else suffix.lstrip(".") or "binary")
        if has_container_magic and ftype not in ("pe","db0"): ftype="firmware_candidate"
        role=("navigation_database" if ftype=="db0" else "executable" if ftype=="pe" else "disc_image" if ftype=="iso" else "firmware_candidate" if ftype.startswith("firmware") else self._role_for_path(path,ftype))
        candidate=("DB_0" if db0_candidate else "PE" if prefix[:2]==b"MZ" else "ISO9660" if "ISO9660_PVD_CANDIDATE" in signature_hits else "firmware_container" if has_container_magic else None)
        validated="DB_0" if db0_validation and db0_validation["valid"] else None
        validation_status=db0_validation["status"] if db0_validation else "NOT_TESTED"
        classification={"artifact_role":role,"format_candidate":candidate,"signature_hits":signature_hits,"validated_format":validated,"validation_status":validation_status,"validation_evidence":json.dumps({k:v for k,v in (db0_validation or {}).items() if k not in ("records",)},sort_keys=True) if db0_validation else ""}
        if path.resolve()==self.db.execute("SELECT source_path FROM artifacts WHERE artifact_id=?",(aid,)).fetchone()[0]:
            self.db.execute("UPDATE artifacts SET artifact_role=? WHERE artifact_id=?",(role,aid))
        fid=self._insert_file(aid,path,relative,size,sha,ftype,magic,entropy,source_offset,container,classification=classification)
        if ftype=="pe" or size<=32*1024*1024:
            ss=_strings_from_path(path,source_offset,length,5000)
            self.db.executemany("INSERT INTO strings(artifact_id,file_id,file_offset,encoding,value) VALUES(?,?,?,?,?)",[(aid,fid,o,e,v) for o,e,v in ss])
        # Static executable metadata and known-constant/string evidence.
        if ftype=="pe":
            data=read_segment()
            result=pe_analyze(data)
            if result:
                self.db.execute("INSERT OR REPLACE INTO executables VALUES(?,?,?,?,?,?,?,?)",(aid,result["pe_offset"],result["machine_hex"],int(result["pe32_plus"]),sum(len(x["symbols"]) for x in result["imports"]),len(result["exports"]),len(result["resources"]),json.dumps(result)))
                self.db.execute("INSERT OR REPLACE INTO executable_files VALUES(?,?,?,?,?,?,?,?,?)",(fid,aid,result["pe_offset"],result["machine_hex"],int(result["pe32_plus"]),sum(len(x["symbols"]) for x in result["imports"]),len(result["exports"]),len(result["resources"]),json.dumps(result)))
                self.db.execute("DELETE FROM pe_sections WHERE artifact_id=?",(aid,))
                self.db.executemany("INSERT INTO pe_sections(artifact_id,name,virtual_address,virtual_size,raw_offset,raw_size,characteristics) VALUES(?,?,?,?,?,?,?)",[(aid,s["name"],s["virtual_address"],s["virtual_size"],s["raw_offset"],s["raw_size"],s["characteristics"]) for s in result["sections"]])
                self.db.executemany("INSERT INTO pe_file_sections(file_id,name,virtual_address,virtual_size,raw_offset,raw_size,characteristics) VALUES(?,?,?,?,?,?,?)",[(fid,s["name"],s["virtual_address"],s["virtual_size"],s["raw_offset"],s["raw_size"],s["characteristics"]) for s in result["sections"]])
        if size and size<256*1024*1024 and (ftype in ("pe","firmware","firmware_candidate") or path.name.lower()=="navboot"):
            data=read_segment()
            for name,needle in KNOWN:
                if len(needle)<2 and ftype not in ("pe","firmware"): continue
                for off,n in find_all(data,[needle],200):
                    self.db.execute("INSERT INTO constants(artifact_id,file_id,name,pattern_hex,offset,context_hex) VALUES(?,?,?,?,?,?)",(aid,fid,name,needle.hex(),off,data[max(0,off-8):off+len(needle)+8].hex()))
                    if name in ("navboot","firmware_4DAD0002","MULCOORD_BE32_5555555","MULCOORD_LE32_5555555","5555555_ASCII","DB_0","CARINET","ABSTRACT"):
                        self.db.execute("INSERT INTO cross_source_matches(match_type,source_artifact,target_artifact,source_file,source_offset,value,evidence,confidence) VALUES('known_constant',?,?,?,?,?,?,?)",(aid,None,str(path),off,name,f"raw bytes {needle.hex()}","OBSERVED"))
        self._firmware(aid,fid,path,size,source_offset,length,run_id)
        return {"file_id":fid,"relative_path":relative,"size":size,"sha256":sha,"file_type":ftype,"magic":magic,"entropy":entropy,"artifact_role":role,"format_candidate":candidate,"signature_hits":signature_hits,"validated_format":validated,"validation_status":validation_status,"strings":self.db.execute("SELECT COUNT(*) FROM strings WHERE file_id=?",(fid,)).fetchone()[0]}

    def _firmware(self,aid,fid,path,size,source_offset,length,run_id):
        if size>128*1024*1024: return
        with path.open("rb") as f:
            f.seek(source_offset); data=f.read(length if length is not None else size)
        try:
            parser_path=self.project/"research"/"firmware"/"firmware_container.py"
            spec=importlib.util.spec_from_file_location("ncdr_existing_firmware_container",parser_path)
            mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            candidates=mod.candidates(data)
        except Exception: candidates=[]
        magic=data.find(bytes.fromhex("4D AD 00 02")); navboot=[m.start() for m in re.finditer(b"navboot",data,re.I)]
        if magic>=0 or candidates:
            status="VALIDATED_MAGIC_SIZE" if candidates else "MAGIC_OR_STRING_ONLY"
            for off,recsize in candidates or [(magic if magic>=0 else -1,size)]:
                cur=self.db.execute("INSERT INTO firmware_containers(artifact_id,file_id,magic,magic_offset,record_size,navboot_offsets,status,evidence) VALUES(?,?,?,?,?,?,?,?)",
                    (aid,fid,"4D AD 00 02" if magic>=0 else "",off if off>=0 else None,recsize,json.dumps(navboot),status,"Reused conservative research/firmware/firmware_container.py; outer header and payload boundary remain partially unresolved"))
                cid=cur.lastrowid
                if navboot:
                    for pos in navboot:
                        self.db.execute("INSERT INTO firmware_modules(container_id,name,offset,size,status,evidence) VALUES(?,?,?,?,?,?)",(cid,"navboot",pos,None,"STRING_HIT_NOT_EXTRACTED","Existing parser does not establish a safe payload boundary; no guessed extraction"))
        # A standalone exact module file can be safely copied as a file, without alteration.
        if path.name.lower()=="navboot" and source_offset==0 and length is None:
            self.output_dir.mkdir(parents=True,exist_ok=True); dest=self.output_dir/(hashlib.sha256(str(path).encode()).hexdigest()[:12]+"_navboot.copy")
            if not dest.exists():
                import shutil; shutil.copyfile(path,dest)
            self.db.execute("INSERT INTO firmware_modules(name,offset,size,sha256,extracted_path,status,evidence) VALUES(?,?,?,?,?,?,?)",("navboot",0,size,_hash_bytes(data),str(dest),"COPIED_STANDALONE_FILE","Byte-for-byte analysis copy; original untouched"))

    def add_file(self,path,source_type="generic_binary",parent=None,relative=None,run_id=""):
        path=Path(path).resolve(); sha,entropy,size=_file_fingerprint(path)
        with path.open("rb") as f: file_magic=_magic(f.read(64),path.name)
        aid=self._artifact(path,source_type,parent,sha,size,file_magic,entropy,run_id=run_id)
        self._clear_artifact_analysis(aid)
        result=self._analyze_file(aid,path,relative or path.name,run_id=run_id); self.db.commit()
        if path.suffix.lower() in (".iso",".bin",".img",".cue"):
            self.add_disc_image(aid,path,result,run_id)
        return aid,result

    def add_disc_image(self,aid,path,file_result,run_id=""):
        fmt=Path(path).suffix.lower().lstrip(".").upper(); layout=(2048,0); image=Path(path)
        if fmt=="CUE":
            try: image,layout=cue_layout(Path(path)); fmt="CUE/"+image.suffix.lstrip(".").upper()
            except Exception as e:
                self.db.execute("INSERT OR REPLACE INTO disc_images VALUES(?,?,?,?,?,?,?,?)",(aid,fmt,"UNKNOWN","UNREADABLE: "+str(e),None,None,0,"{}")); return
        size,base=layout; entries=[]; status="NO_FILESYSTEM"
        try:
            with image.open("rb") as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
                if size==2048 and (len(data)%2048): size,base=2352,16
                entries=enumerate_iso(data,size,base); status="ISO9660"
                for row in entries:
                    if row["is_directory"]: continue
                    info=self._analyze_file(aid,image,row["path"],row["image_offset"],row["size"],str(path),run_id)
                    row["sha256"]=info["sha256"]; row["magic"]=info["magic"]
                    if Path(row["path"]).name.lower()=="navboot":
                        # Extract an exact file extent to a COPY for later firmware analysis.
                        self.output_dir.mkdir(parents=True,exist_ok=True); out=self.output_dir/(info["sha256"][:12]+"_navboot.copy")
                        with out.open("wb") as w: w.write(data[row["image_offset"]:row["image_offset"]+row["size"]])
                        self.db.execute("INSERT INTO firmware_modules(name,offset,size,sha256,extracted_path,status,evidence) VALUES(?,?,?,?,?,?,?)",("navboot",row["image_offset"],row["size"],info["sha256"],str(out),"COPIED_FROM_ISO_FILE_EXTENT","Exact ISO file extent copied; image unchanged"))
        except Exception as e: status="UNREADABLE: "+str(e)
        self.db.execute("INSERT OR REPLACE INTO disc_images VALUES(?,?,?,?,?,?,?,?)",(aid,fmt,status,status,size,base,len(entries),json.dumps(entries[:5000])))
        self.db.commit()

    def add_directory(self,path,source_type="generic_directory",run_id="",exclude_db_lab=True):
        root=Path(path).resolve(); pfiles=[]
        for base,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=sorted(d for d in dirs if d not in (".git","__pycache__",".DS_Store") and not (exclude_db_lab and Path(base,d) in (self.project/"research"/"db_lab",self.project/"research"/"runs",self.project/"research"/"tasks")))
            for name in sorted(files):
                p=Path(base)/name
                if p.is_symlink(): continue
                try: pfiles.append((p,p.relative_to(root).as_posix()))
                except ValueError: continue
        manifest=hashlib.sha256()
        for p,rel in pfiles:
            if p.name==".DS_Store": continue
            filehash,_,size=_file_fingerprint(p); manifest.update(rel.encode()+b"\0"+filehash.encode()+b"\n")
        aid=self._artifact(root,source_type,sha=manifest.hexdigest(),size=sum(p.stat().st_size for p,_ in pfiles),magic="DIRECTORY",entropy=0.0,run_id=run_id)
        self._clear_artifact_analysis(aid); self.db.commit()
        rootinfo=self._insert_file(aid,root,".",sum(p.stat().st_size for p,_ in pfiles),manifest.hexdigest(),"directory","DIRECTORY",0,isdir=1)
        results=[]
        for i,(p,rel) in enumerate(pfiles):
            try: results.append(self._analyze_file(aid,p,rel,run_id=run_id))
            except (OSError,PermissionError) as e: results.append({"relative_path":rel,"error":str(e)})
            if i%25==0: self.db.commit()
        self.db.commit()
        if source_type=="controlled_experiment" or root.name.upper() in {"ORIGINAL","OUTPUT_A","OUTPUT_B","OUTPUT_C","OUTPUT_D","OUTPUT_E","OUTPUT_F","OUTPUT_G","OUTPUT_L1","OUTPUT_L2","OUTPUT_T1","OUTPUT_T2","OUTPUT_XCARRY","OUTPUT_YCARRY"}:
            baseline=None
            self.db.execute("INSERT OR REPLACE INTO experiments(experiment_id,name,artifact_id,baseline_artifact,created_at,parameters_json,status) VALUES(?,?,?,?,?,?,?)",(aid,root.name,aid,baseline,_now(),"{}","CATALOGUED")); self.db.commit()
        return aid,results

    def catalog_project(self,run_id="PROJECT_INVENTORY",progress=None):
        paths=[]
        for p in sorted(self.project.iterdir()):
            if p.name in ("research","tools"): continue
            if p.is_dir(): paths.append((p,"controlled_experiment" if p.name.upper() in {"ORIGINAL","OUTPUT_A","OUTPUT_B","OUTPUT_C","OUTPUT_D","OUTPUT_E","OUTPUT_F","OUTPUT_G","OUTPUT_L1","OUTPUT_L2","OUTPUT_T1","OUTPUT_T2","OUTPUT_XCARRY","OUTPUT_YCARRY"} else "generic_directory"))
            elif p.is_file(): paths.append((p,self._role_for_path(p)))
        # Existing reverse-engineering files and static tools are first-class artifact sources.
        for p in (self.project/"research",self.project/"tools"):
            if p.is_dir(): paths.append((p,"research_artifacts" if p.name=="research" else "executable_tools"))
        artifacts=[]; failures=[]
        for i,(p,kind) in enumerate(paths):
            if progress: progress(i,len(paths),p)
            try:
                aid,res=(self.add_directory(p,kind,run_id) if p.is_dir() else self.add_file(p,kind,run_id=run_id))
                artifacts.append({"artifact_id":aid,"path":str(p),"type":kind,"file_count":len(res) if isinstance(res,list) else 1})
            except Exception as e: failures.append({"path":str(p),"error":str(e)})
        self._correlate(); self.db.commit()
        return {"artifacts":artifacts,"failures":failures,"artifact_count":self.db.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0],"file_count":self.db.execute("SELECT COUNT(*) FROM files").fetchone()[0]}

    def _correlate(self):
        self.db.execute("DELETE FROM cross_source_matches WHERE match_type='identical_sha256'")
        rows=self.db.execute("SELECT f.sha256,a.artifact_id,a.source_path,f.relative_path FROM files f JOIN artifacts a USING(artifact_id) WHERE f.sha256 IS NOT NULL AND f.is_directory=0 GROUP BY f.sha256,a.artifact_id,f.relative_path HAVING COUNT(*)>=1 ORDER BY f.sha256").fetchall()
        byhash={}
        for r in rows: byhash.setdefault(r["sha256"],[]).append(r)
        for digest,group in byhash.items():
            for i,left in enumerate(group):
                for right in group[i+1:]:
                    if left["artifact_id"]==right["artifact_id"]: continue
                    self.db.execute("INSERT INTO cross_source_matches(match_type,source_artifact,target_artifact,source_file,target_file,value,evidence,confidence) VALUES('identical_sha256',?,?,?,?,?,?,?)",(left["artifact_id"],right["artifact_id"],left["relative_path"],right["relative_path"],digest,"SHA256 equality", "CONFIRMED"))

    def global_search(self,query,mode="auto",limit=1000):
        from .binary_analysis import representations
        needles=representations(query,mode); results=[]
        for row in self.db.execute("SELECT file_id,artifact_id,source_path,relative_path,size,source_offset,is_directory FROM files WHERE is_directory=0"):
            p=Path(row["source_path"]); base=row["source_offset"] or 0
            try:
                with p.open("rb") as f, mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as data:
                    end=base+row["size"]
                    for needle in needles:
                        pos=base
                        while len(results)<limit:
                            pos=data.find(needle,pos,end)
                            if pos<0: break
                            results.append({"artifact_id":row["artifact_id"],"file_id":row["file_id"],"file":row["relative_path"],"offset":pos-base,"pattern_hex":needle.hex()})
                            pos+=max(1,len(needle))
            except (OSError,ValueError): continue
        return results
