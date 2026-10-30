"""Evidence-bounded Windows CE flat XIP parser.

The parser accepts only the classic CE signature/pointer/ROMHDR/TOC layout.
It deliberately does not carve PE headers or infer modules from strings.
"""
from __future__ import annotations
import csv, hashlib, struct
from pathlib import Path

ROMHDR_SIZE = 84
TOC_ENTRY_SIZE = 32
FILES_ENTRY_SIZE = 32
E32_BASE_SIZE = 108
O32_SIZE = 24
IMAGE_SCN_COMPRESSED = 0x2000

def _name(data, offset, limit=260):
    if offset is None or offset < 0 or offset >= len(data): return None
    end=data.find(b"\0",offset,min(len(data),offset+limit))
    if end<0: return None
    raw=data[offset:end]
    if not raw or any(b<0x20 or b>0x7e for b in raw): return None
    return raw.decode("ascii")

def _parse_candidate(data, sig_off):
    size=len(data); region_start=sig_off-0x40
    if region_start<0 or sig_off%4 or data[sig_off:sig_off+4] not in (b"ECEC",b"CECE"):
        return None
    if sig_off+12>size: return None
    hdr_va,toc_va=struct.unpack_from("<II",data,sig_off+4)
    # Boot ROMs set pTOC to the ROMHDR; the fixed TOC-entry array follows it.
    if hdr_va==0 or hdr_va==0xffffffff or toc_va!=hdr_va: return None
    hdr_off=region_start+(hdr_va) # placeholder until physfirst is read
    # ROMHDR address is an image VA, so test possible byte-aligned headers and
    # require its physfirst to produce exactly the pointer's file mapping.
    candidates=[]
    for off in range(region_start, max(region_start,size-ROMHDR_SIZE+1), 4):
        vals=struct.unpack_from("<17IHHIII",data,off)
        physfirst,physlast,nummods=vals[2],vals[3],vals[4]
        mapped=region_start+(hdr_va-physfirst) if hdr_va>=physfirst else -1
        if mapped!=off: continue
        if physlast<=physfirst or physlast-physfirst>size-region_start: continue
        if not (1<=nummods<=4096) or vals[12]>32768: continue
        if vals[6] and vals[7] and not vals[6]<=vals[7]: continue
        if vals[5] and vals[7] and not vals[5]<=vals[6]<=vals[7]: continue
        candidates.append((off,vals))
    if len(candidates)!=1: return None
    hdr_off,vals=candidates[0]
    (dllfirst,dlllast,physfirst,physlast,nummods,ramstart,ramfree,ramend,
     copy_count,copy_va,profile_len,profile_va,numfiles,kernel_flags,
     fsram,drivglob_start,drivglob_len,cpu_type,misc_flags,extensions,
     tracking_start,tracking_len)=vals
    if not (physfirst<=hdr_va<physlast): return None
    image_base=physfirst
    def va_to_off(va,length=1):
        if va<image_base: return None
        off=region_start+(va-image_base)
        return off if length>=0 and off>=region_start and off+length<=size and va+length<=physlast else None
    if va_to_off(hdr_va,ROMHDR_SIZE)!=hdr_off: return None
    if va_to_off(toc_va,ROMHDR_SIZE)!=hdr_off: return None
    toc_off=hdr_off+ROMHDR_SIZE
    if toc_off+nummods*TOC_ENTRY_SIZE+numfiles*FILES_ENTRY_SIZE>size: return None
    modules=[]; files=[]; failures=[]; module_ranges=[]
    for idx in range(nummods):
        eoff=toc_off+idx*TOC_ENTRY_SIZE
        attrs,ftlo,fthi,filesize,name_va,e32_va,o32_va,load_va=struct.unpack_from("<8I",data,eoff)
        name_off=va_to_off(name_va,1); name=_name(data,name_off)
        e32_off=va_to_off(e32_va,E32_BASE_SIZE); e32=None; o32_rows=[]
        if e32_off is not None:
            objcnt,imageflags=struct.unpack_from("<HH",data,e32_off)
            if 0<objcnt<=128 and e32_off+E32_BASE_SIZE<=size:
                e32={"object_count":objcnt,"image_flags":imageflags,"entry_rva":struct.unpack_from("<I",data,e32_off+4)[0],"vbase":struct.unpack_from("<I",data,e32_off+8)[0],"virtual_size":struct.unpack_from("<I",data,e32_off+20)[0]}
                o32_off=va_to_off(o32_va,objcnt*O32_SIZE)
                if o32_off is not None:
                    valid=True
                    for oi in range(objcnt):
                        vsize,rva,psize,dataptr,realaddr,flags=struct.unpack_from("<6I",data,o32_off+oi*O32_SIZE)
                        data_off=va_to_off(dataptr,psize) if psize else va_to_off(dataptr,0)
                        if not vsize or psize>max(vsize,0x1000000) or data_off is None:
                            valid=False; break
                        if psize: module_ranges.append((data_off,data_off+psize,idx,oi))
                        o32_rows.append({"vsize":vsize,"rva":rva,"psize":psize,"dataptr":dataptr,"realaddr":realaddr,"flags":flags,"file_offset":data_off})
                    if not valid: o32_rows=[]
        valid=bool(name and e32 and len(o32_rows)==e32["object_count"] and filesize>0 and filesize<=size and (load_va==0 or va_to_off(load_va,0) is not None))
        modules.append({"module_name":name,"module_type":Path(name).suffix.lower().lstrip(".") or "module","virtual_address":load_va or (e32 or {}).get("vbase"),"file_offset":None,"size":filesize,"attributes":attrs,"compression_state":"COMPRESSED" if any(o["flags"]&IMAGE_SCN_COMPRESSED for o in o32_rows) else "UNCOMPRESSED_OR_UNMARKED","extraction_status":"NOT_EXTRACTED","sha256":None,"validation_status":"VALIDATED" if valid else "REJECTED","table_validated":valid,"e32":e32,"o32":o32_rows,"source_toc_offset":eoff})
        if not valid: failures.append({"entry":idx,"reason":"MODULE_NAME_OR_E32_O32_MAPPING_INVALID"})
    ranges=sorted(module_ranges)
    for a,b in zip(ranges,ranges[1:]):
        if b[0]<a[1]: failures.append({"entry":b[2],"reason":"OVERLAPPING_O32_DATA_RANGES"})
    if any(f["reason"]=="OVERLAPPING_O32_DATA_RANGES" for f in failures):
        for m in modules: m["validation_status"]="REJECTED";m["table_validated"]=False
    file_base=toc_off+nummods*TOC_ENTRY_SIZE
    for idx in range(numfiles):
        off=file_base+idx*FILES_ENTRY_SIZE
        attrs,ftlo,fthi,real_size,comp_size,name_va,load_va,reserved=struct.unpack_from("<8I",data,off)
        name=_name(data,va_to_off(name_va,1)); data_off=va_to_off(load_va,comp_size) if comp_size else va_to_off(load_va,0)
        valid=bool(name and real_size<=size and comp_size<=size and data_off is not None)
        files.append({"name":name,"attributes":attrs,"real_size":real_size,"compressed_size":comp_size,"compression_state":"COMPRESSED" if comp_size and comp_size!=real_size else "UNCOMPRESSED_OR_EMPTY","virtual_address":load_va,"file_offset":data_off,"validation_status":"VALIDATED" if valid else "REJECTED"})
    if failures or any(m["validation_status"]!="VALIDATED" for m in modules) or any(f["validation_status"]!="VALIDATED" for f in files):
        return {"header_offset":hdr_off,"partial":True,"failures":failures,"modules":modules,"files":files}
    hdr={"dll_first":dllfirst,"dll_last":dlllast,"physical_first":physfirst,"physical_last":physlast,"module_count":nummods,"file_count":numfiles,"ram_start":ramstart,"ram_free":ramfree,"ram_end":ramend,"copy_entry_count":copy_count,"copy_table_va":copy_va,"cpu_type":cpu_type,"extensions_va":extensions,"tracking_start":tracking_start,"tracking_length":tracking_len}
    return {"signature_offset":sig_off,"header_offset":hdr_off,"partial":False,"rom_header":hdr,"modules":modules,"files":files,"structures_validated":["ROM_SIGNATURE","ROMHDR","MODULE_TOC","FILES_TOC","E32","O32"]}

def parse_nkbin(path):
    path=Path(path); data=path.read_bytes(); digest=hashlib.sha256(data).hexdigest(); size=len(data)
    sigs=[]
    for marker in (b"ECEC",b"CECE"):
        at=0
        while True:
            at=data.find(marker,at)
            if at<0: break
            sigs.append(at); at+=1
    sigs=sorted(set(sigs))
    candidates=[]
    for off in sigs:
        parsed=_parse_candidate(data,off)
        if parsed: candidates.append(parsed)
    if len(candidates)==1 and not candidates[0]["partial"]:
        parsed=candidates[0]
        x=parsed["signature_offset"]
        result={"status":"VALIDATED","ui_status":"VALIDATED","path":str(path),"size":size,"sha256":digest,"container":"Windows CE flat XIP","rom_header":parsed["rom_header"],"module_count":len(parsed["modules"]),"file_count":len(parsed["files"]),"modules":parsed["modules"],"files":parsed["files"],"coredll_present":any((m.get("module_name") or "").casefold()=="coredll.dll" for m in parsed["modules"]),"extracted_modules":[],"rom_structures_validated":parsed["structures_validated"],"signature_hits":[{"token":"ECEC","file_offset":x,"aligned":x%4==0,"fixed_offset_candidate":x>=0x40 and x-0x40==0}],"evidence":"Fixed CE signature and pointers resolve to a range-checked ROMHDR, TOC entries, module E32/O32 records, and file records."}
    else:
        aligned=[off for off in sigs if off%4==0 and off>=0x40 and off-0x40==0]
        partial=any(c.get("partial") for c in candidates)
        result={"status":"PARTIAL" if partial else "INCONCLUSIVE","ui_status":"PARTIAL" if partial else "INCONCLUSIVE","path":str(path),"size":size,"sha256":digest,"container":"OEM NK.BIN; Windows CE flat-XIP chain not fully validated","rom_header":None,"module_count":None,"file_count":None,"modules":[],"files":[],"coredll_present":None,"extracted_modules":[],"rom_structures_validated":[],"signature_hits":[{"token":"ECEC","file_offset":off,"aligned":off%4==0,"fixed_offset_candidate":off>=0x40 and off-0x40==0} for off in sigs],"candidate_failures":[c.get("failures",[]) for c in candidates],"evidence":"No ECEC signature/pointer/ROMHDR/TOC chain satisfied the fixed-position, VA mapping, count, table-boundary, module, and file checks. No MZ carving, module inventory, or extraction was performed."}
    return result

def self_test_fixture():
    """Build a tiny internally consistent CE ROM fixture for parser validation."""
    import tempfile
    from pathlib import Path
    base=0x80000000; blob=bytearray(0x900)
    # Fixed boot signature and both pointers to the ROMHDR (pTOC).
    struct.pack_into("<4sII",blob,0x40,b"ECEC",base+0x100,base+0x100)
    struct.pack_into("<17IHHIII",blob,0x100,
      0,0,base,base+len(blob),1,base+0x800,base+0x810,base+0x880,
      0,0,0,0,0,0,0,0,0,0x01a6,0,0,0,0)
    # One MODULE TOC record followed by no FILES records.
    struct.pack_into("<8I",blob,0x154,0,0,0,0x20,base+0x700,base+0x300,base+0x400,base+0x500)
    blob[0x700:0x70b]=b"test.dll\0\0\0"
    # e32_rom object count and expected fields; one corresponding o32_rom.
    struct.pack_into("<HHIIHHII",blob,0x300,1,0,0x100,base,0,0,0x1000,0x20)
    struct.pack_into("<6I",blob,0x400,0x20,0,0x20,base+0x600,base+0x600,0x40000040)
    blob[0x600:0x620]=bytes(range(32))
    with tempfile.TemporaryDirectory(prefix="ncdr-rom-parser-fixture-") as tmp:
        sample=Path(tmp)/"fixture.bin";sample.write_bytes(blob)
        got=parse_nkbin(sample)
        return {"status":got["status"],"module_count":got["module_count"],"file_count":got["file_count"],"structures":got.get("rom_structures_validated",[]),"modules":got.get("modules",[])}

def write_module_inventory(result,csv_path):
    fields=["module_name","module_type","virtual_address","file_offset","size","attributes","compression_state","extraction_status","sha256","validation_status"]
    path=Path(csv_path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for row in result.get("modules",[]):w.writerow({k:row.get(k) for k in fields})
    return path

def safe_extract_module(image_path,module,output_dir):
    """Copy only a validated contiguous FILE payload (not reconstructed modules)."""
    if module.get("validation_status")!="VALIDATED" or not module.get("table_validated"): raise ValueError("NK_MODULE_BOUNDARIES_NOT_VALIDATED")
    off=module.get("file_offset");length=int(module.get("size") or 0)
    if off is None or length<=0: raise ValueError("NK_MODULE_HAS_NO_CONTIGUOUS_PAYLOAD")
    image=Path(image_path); data=image.read_bytes()
    if off<0 or off+length>len(data): raise ValueError("NK_MODULE_RANGE_INVALID")
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True);name=Path(module["module_name"]).name
    target=out/name;payload=data[off:off+length];target.write_bytes(payload)
    module["extraction_status"]="EXTRACTED";module["sha256"]=hashlib.sha256(payload).hexdigest()
    (out/(name+".provenance.json")).write_text(__import__("json").dumps({"source_path":str(image),"source_sha256":hashlib.sha256(data).hexdigest(),"source_offset":off,"virtual_address":module.get("virtual_address"),"size":length,"module_name":module["module_name"],"extracted_sha256":module["sha256"]},indent=2)+"\n",encoding="utf-8")
    return target
