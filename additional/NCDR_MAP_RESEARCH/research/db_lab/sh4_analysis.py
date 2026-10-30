"""Evidence-bounded Windows CE SH4 PE analysis using the vendored Miasm decoder."""
from __future__ import annotations
import struct, sys
from pathlib import Path

_VENDOR = Path(__file__).with_name("vendor")
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from .artifact_lab.binary_analysis import pe_analyze, strings

BACKEND = {"tool":"Miasm SH4 instruction decoder", "version":"0.1.5", "architecture_support":"Hitachi SH-4 target; host Python/x86_64", "command":"python3 -m research.db_lab.lab_cli sh4-analysis --path NAVIMAIN.EXE --project-root PROJECT_ROOT", "installation_source":"https://github.com/cea-sec/miasm; vendored Python source at commit 3671fc24d6e625c2d75f3311724eb6b0c97664f8 (GPL-2.0-only)"}

def _decoder():
    from miasm.arch.sh4.arch import mn_sh4
    from miasm.core.bin_stream import bin_stream_str
    return mn_sh4, bin_stream_str

def _offset_for_rva(pe, rva):
    if rva < 0x1000: return rva
    for s in pe["sections"]:
        if s["virtual_address"] <= rva < s["virtual_address"] + max(s["virtual_size"], s["raw_size"]):
            off=s["raw_offset"]+rva-s["virtual_address"]
            return off if off < s["raw_offset"]+s["raw_size"] else None
    return None

def _signed(value, bits): return value-(1<<bits) if value & (1<<(bits-1)) else value

def _branch(word, rva):
    op=word & 0xF000
    if op==0xB000: return ("call", rva+4+_signed(word&0x0fff,12)*2)
    if op==0xA000: return ("branch", rva+4+_signed(word&0x0fff,12)*2)
    if (word&0xff00) in (0x8900,0x8b00,0x8d00,0x8f00): return ("branch",rva+4+_signed(word&0xff,8)*2)
    return (None,None)

def _target_info(value, pe, imports, functions):
    """Classify a resolved SH4 address without guessing its semantics."""
    image_base=int(pe["image_base"])
    imp=next((x for x in imports if int(x.get("iat_va",-1))==value or int(x.get("iat_rva",-1))==value-image_base),None)
    if imp: return "IMPORT_IAT", int(imp["iat_rva"]), imp
    rva=value-image_base if value>=image_base else value
    in_image=any(int(s["virtual_address"])<=rva<int(s["virtual_address"])+max(int(s["virtual_size"]),int(s["raw_size"])) for s in pe.get("sections",[]))
    if not in_image: rva=None
    if rva is None: return "EXTERNAL_ADDRESS", None, None
    target_ins=next((x for x in functions if int(x["rva"])==rva),None)
    if target_ins and str(target_ins.get("instruction","")).upper() in ("JMP", "BRA"):
        return "THUNK", rva, None
    return "INTERNAL_FUNCTION", rva, None

def disassemble_module(path, entry_rva=None, instruction_limit=4096):
    """Decode executable PE32 SH4 sections; preserve RVAs and file offsets."""
    path=Path(path); data=path.read_bytes(); pe=pe_analyze(data)
    if not pe: return {"status":"INVALID_PE","module":path.name,"error_code":"PE_PARSE_FAILED"}
    if pe["machine"] not in (0x1a6,0x1a3,0x1a2): return {"status":"UNSUPPORTED_ARCH","module":path.name,"machine":pe["machine_hex"],"error_code":"SH4_MACHINE_REQUIRED"}
    mn_sh4,bin_stream_str=_decoder(); entry_rva=int(entry_rva if entry_rva is not None else pe.get("entry_point_rva",0))
    sections=[s for s in pe["sections"] if s["characteristics"]&0x20000000 and s["raw_size"]>0]
    imports=pe.get("import_records",[]); iat_by_va={int(x["iat_va"]):x for x in imports}; iat_by_rva={int(x["iat_rva"]):x for x in imports}
    code=[]; xrefs=[]; functions=[]; errors=[]; literals=[]; indirect=[]; total=0
    for section in sections:
        start=int(section["virtual_address"]); raw=int(section["raw_offset"]); size=min(int(section["raw_size"]),max(0,len(data)-raw))
        if size<2: continue
        section_bytes=data[raw:raw+size]; pos=start; limit=start+size; regs={}; run=[]; run_start=None; return_pending=False; pending_delay=None
        while pos+2<=limit and total<instruction_limit:
            try:
                # Miasm's SH4 decoder accepts bytes and stream-relative offsets.
                ins=mn_sh4.dis(section_bytes,None,offset=pos-start); length=int(ins.l)
                if length!=2 or pos+length>limit: raise ValueError("unexpected SH4 instruction width")
            except Exception as exc:
                errors.append({"rva":pos,"error":str(exc)}); pos+=2; continue
            off=raw+pos-start; word=struct.unpack_from("<H",data,off)[0]; target_type,target_rva=_branch(word,pos); operands=str(ins).strip()
            row={"module":path.name,"rva":pos,"file_offset":off,"virtual_address":pe["image_base"]+pos,"instruction":str(ins.name),"operands":operands,"function_start":None,"function_end":None,"xref_type":target_type,"target":target_rva,"bytes":data[off:off+length].hex(),"delay_slot_of":pending_delay}
            code.append(row); total+=1
            if run_start is None: run_start=pos
            run.append(row)
            if target_type: xrefs.append({"module":path.name,"source_rva":pos,"source_file_offset":off,"xref_type":target_type,"target_rva":target_rva,"target_va":pe["image_base"]+target_rva,"instruction":operands})
            # MOV.L @(disp,PC),Rn supplies a verifiable literal/data reference.
            if word&0xf000==0xd000:
                reg=(word>>8)&0xf; literal=((pos+4)&~3)+((word&0xff)*4); loff=_offset_for_rva(pe,literal)
                if loff is not None and loff+4<=len(data):
                    # Windows CE SH4 PE images are little-endian; instruction and
                    # data byte order follow the PE encoding, not host byte order.
                    ptr=struct.unpack_from("<I",data,loff)[0]; imp=iat_by_va.get(ptr) or iat_by_rva.get(ptr-pe["image_base"])
                    regs[reg]={"value":ptr,"literal_rva":literal,"raw_value":ptr,"import":imp}
                    value_rva=ptr-pe["image_base"] if ptr>=pe["image_base"] else ptr
                    in_image=any(int(s["virtual_address"])<=value_rva<int(s["virtual_address"])+max(int(s["virtual_size"]),int(s["raw_size"])) for s in pe["sections"])
                    literals.append({"module":path.name,"instruction_rva":pos,"register":f"R{reg}","literal_rva":literal,"raw_value":f"0x{ptr:08X}","resolved_va":f"0x{ptr:08X}","resolved_rva":f"0x{value_rva:08X}" if in_image else "","resolution_type":"IMPORT_IAT" if imp else ("INTERNAL_IMAGE_ADDRESS" if in_image else "EXTERNAL_ADDRESS"),"confidence":"HIGH: SH4 PC-relative literal formula and PE little-endian value"})
                    xrefs.append({"module":path.name,"source_rva":pos,"source_file_offset":off,"xref_type":"data","target_rva":literal,"target_va":pe["image_base"]+literal,"value":ptr})
            # MOV Rm,Rn (0110 nnnn mmmm 0011) propagates a tracked constant.
            if word&0xf00f==0x6003:
                n=(word>>8)&0xf; m=(word>>4)&0xf
                if m in regs: regs[n]=dict(regs[m])
                else: regs.pop(n,None)
            # A resolved JSR/JMP is a real code edge, including non-import targets.
            if word&0xf0ff in (0x400b,0x402b):
                reg=(word>>8)&0xf; tracked=regs.get(reg); is_call=(word&0xf0ff)==0x400b
                value=tracked["value"] if tracked else None
                kind,target,imp=_target_info(value,pe,imports,code) if value is not None else ("UNRESOLVED",None,None)
                callrow={"module":path.name,"caller_function_rva":None,"call_instruction_rva":pos,"register":f"R{reg}","literal_rva":tracked.get("literal_rva") if tracked else None,"raw_target":f"0x{value:08X}" if value is not None else "","resolved_target_rva":target,"target_type":kind,"import_dll":imp.get("dll") if imp else None,"import_name":imp.get("name") if imp else None,"import_ordinal":imp.get("ordinal") if imp else None,"confidence":"HIGH: tracked constant" if tracked else "UNRESOLVED","control_type":"JSR" if is_call else "JMP","delay_slot_rva":pos+2}
                indirect.append(callrow)
                if target is not None:
                    xrefs.append({"module":path.name,"source_rva":pos,"caller_rva":pos,"source_file_offset":off,"xref_type":"indirect_call" if is_call else "indirect_jump","target_rva":target,"target_va":pe["image_base"]+target,"target_type":kind,"register":f"R{reg}","literal_rva":callrow["literal_rva"],"raw_target":callrow["raw_target"],"dll":callrow["import_dll"],"name":callrow["import_name"],"ordinal":callrow["import_ordinal"],"instruction":operands})
                    if imp: xrefs.append({"module":path.name,"source_rva":pos,"caller_rva":pos,"source_file_offset":off,"xref_type":"import_call","target_iat_rva":imp["iat_rva"],"dll":imp["dll"],"name":imp["name"],"ordinal":imp["ordinal"],"status":imp["status"],"instruction":operands})
                row["indirect_target_type"]=kind; row["indirect_target_rva"]=target; row["delay_slot_rva"]=pos+2
            if pending_delay is not None:
                # Branch/call target takes effect after the delay-slot instruction.
                pending_delay=None; regs.clear()
            if str(ins.name).upper() in ("RTS","RTE"): return_pending=True
            elif return_pending:
                end=pos+length; functions.append({"module":path.name,"start_rva":run_start,"end_rva":end,"confidence":"LOW: return and delay slot bound the end; linear-sweep start is unverified"})
                for item in run: item["function_start"]=run_start; item["function_end"]=end
                return_pending=False; run=[]; run_start=None
            if target_type or (word&0xf0ff in (0x400b,0x402b)) or (word&0xf0ff in (0x000b,0x002b)):
                pending_delay=pos; row["has_delay_slot"]=True
            pos+=length
        if run and run_start is not None:
            end=pos
            for item in run: item["function_start"]=run_start; item["function_end"]=end
            functions.append({"module":path.name,"start_rva":run_start,"end_rva":end,"confidence":"LOW: section-bounded linear code region; function start and end are unverified"})
    str_rows=[]
    for off,value,encoding in strings(data,min_len=4,limit=30000):
        rva=None
        for s in pe["sections"]:
            if s["raw_offset"]<=off<s["raw_offset"]+s["raw_size"]: rva=s["virtual_address"]+off-s["raw_offset"]; break
        if rva is not None: str_rows.append({"file_offset":off,"rva":rva,"encoding":encoding,"value":value})
    by_va={pe["image_base"]+s["rva"]:s for s in str_rows}; by_rva={s["rva"]:s for s in str_rows}
    for ref in list(xrefs):
        value=ref.get("value"); st=by_va.get(value) or by_rva.get(value)
        if st: xrefs.append({"module":path.name,"source_rva":ref["source_rva"],"xref_type":"string","target_rva":st["rva"],"target_file_offset":st["file_offset"],"value":st["value"]})
    entry_rows=[x for x in code if entry_rva<=x["rva"]<entry_rva+0x100]; entry_fn=next((f for f in functions if f["start_rva"]<=entry_rva<f["end_rva"]),None)
    # Preserve the original UI/CLI xref fields and expose a stable normalized
    # interface for navigation and machine-readable reports.
    normalized=[]
    kind_map={"call":("CALL","CODE"),"indirect_call":("CALL","CODE"),"indirect_jump":("CALL","CODE"),"branch":("BRANCH","CODE"),"data":("DATA","DATA"),"string":("STRING","STRING"),"import_call":("IMPORT","IMPORT")}
    for ref in xrefs:
        pair=kind_map.get(ref.get("xref_type"))
        if not pair: continue
        xref_type,target_type=pair
        fn=next((f for f in functions if f["start_rva"]<=ref["source_rva"]<f["end_rva"]),None)
        confidence="low" if fn else "instruction-only"
        normalized.append({"module":path.name,"function_rva":fn["start_rva"] if fn else None,"instruction_rva":ref["source_rva"],"target_rva":ref.get("target_rva"),"xref_type":xref_type,"target_type":ref.get("target_type",target_type),"confidence":confidence,"function_boundary_note":fn["confidence"] if fn else "no function boundary recovered","target_iat_rva":ref.get("target_iat_rva"),"dll":ref.get("dll"),"name":ref.get("name"),"ordinal":ref.get("ordinal"),"value":ref.get("value"),"resolution_type":ref.get("target_type")})
    for row in code:
        fn=next((f for f in functions if f["start_rva"]<=row["rva"]<f["end_rva"]),None)
        row["function_start"]=fn["start_rva"] if fn else None
        row["function_end"]=fn["end_rva"] if fn else None
    for r in indirect:
        fn=next((f for f in functions if f["start_rva"]<=r["call_instruction_rva"]<f["end_rva"]),None); r["caller_function_rva"]=fn["start_rva"] if fn else None
    return {"status":"SUPPORTED","module":path.name,"path":str(path),"machine":pe["machine_hex"],"pe32_plus":pe["pe32_plus"],"image_base":pe["image_base"],"entry_point_rva":entry_rva,"entry_point_file_offset":_offset_for_rva(pe,entry_rva),"sections":pe["sections"],"imports":imports,"ordinal_imports":[x for x in imports if x["ordinal"] is not None],"instructions":code,"entry_instructions":entry_rows,"functions":functions,"entry_function":entry_fn,"xrefs":xrefs,"normalized_xrefs":normalized,"literal_pool_resolutions":literals,"indirect_call_xrefs":indirect,"strings":str_rows,"errors":errors,"backend":BACKEND}

def get_function_at(result,rva):
    """Return only a code region bounded by the current conservative analysis."""
    return next((f for f in result.get("functions",[]) if f["start_rva"]<=rva<f["end_rva"]),None)

def _normalized(result):
    rows=result.get("normalized_xrefs")
    if rows is not None: return rows
    kind_map={"call":("CALL","CODE"),"indirect_call":("CALL","CODE"),"indirect_jump":("CALL","CODE"),"branch":("BRANCH","CODE"),"data":("DATA","DATA"),"string":("STRING","STRING"),"import_call":("IMPORT","IMPORT")}
    rows=[]
    for ref in result.get("xrefs",[]):
        pair=kind_map.get(ref.get("xref_type"))
        if not pair: continue
        fn=get_function_at(result,ref["source_rva"]); rows.append({"module":result.get("module"),"function_rva":fn["start_rva"] if fn else None,"instruction_rva":ref["source_rva"],"target_rva":ref.get("target_rva"),"xref_type":pair[0],"target_type":pair[1],"confidence":"low" if fn else "instruction-only","function_boundary_note":fn["confidence"] if fn else "no function boundary recovered","target_iat_rva":ref.get("target_iat_rva"),"dll":ref.get("dll"),"name":ref.get("name"),"ordinal":ref.get("ordinal"),"value":ref.get("value")})
    return rows

def get_callers(result,target_rva): return [x for x in _normalized(result) if x["xref_type"]=="CALL" and x.get("target_rva")==target_rva]
def get_callees(result,function_rva):
    fn=get_function_at(result,function_rva); start=fn["start_rva"] if fn else function_rva
    return [x for x in _normalized(result) if x["xref_type"]=="CALL" and x.get("function_rva")==start]
def get_code_xrefs_to(result,target_rva): return [x for x in _normalized(result) if x["xref_type"] in ("CALL","BRANCH") and x.get("target_rva")==target_rva]
def get_data_xrefs_to(result,target_rva): return [x for x in _normalized(result) if x["xref_type"]=="DATA" and x.get("target_rva")==target_rva]
def get_string_xrefs(result,text=None): return [x for x in _normalized(result) if x["xref_type"]=="STRING" and (text is None or text.casefold() in str(x.get("value","")).casefold())]
def get_import_xrefs(result,dll=None,name=None,ordinal=None): return [x for x in _normalized(result) if x["xref_type"]=="IMPORT" and (dll is None or (x.get("dll") or "").lower()==dll.lower()) and (name is None or x.get("name")==name) and (ordinal is None or x.get("ordinal")==ordinal)]

def get_function(result,rva): return get_function_at(result,rva)
def get_xrefs(result,target): return [x for x in result.get("xrefs",[]) if x.get("target_rva")==target or x.get("target_iat_rva")==target]

def render_report(result):
    lines=["# SH4 analysis capability test",f"\nStatus: {result.get('status')}",f"\nModule: `{result.get('module')}`",f"\nMachine: {result.get('machine')} · Entry RVA `0x{result.get('entry_point_rva',0):08X}` · file offset `0x{(result.get('entry_point_file_offset') or 0):08X}`",f"\nBackend: {result.get('backend',{}).get('tool')} {result.get('backend',{}).get('version')}","\n## Entry point disassembly"]
    lines.extend(f"- RVA `0x{x['rva']:08X}` · file `0x{x['file_offset']:08X}` · `{x['bytes']}` · {x['operands']}" for x in result.get("entry_instructions",[]))
    lines += ["\n## Imports",f"\nNamed and ordinal import entries: {len(result.get('imports',[]))}",f"\nOrdinal-only entries: {len(result.get('ordinal_imports',[]))}","\n## Xrefs",f"\nDirect calls: {sum(x.get('xref_type')=='call' for x in result.get('xrefs',[]))}",f"\nImport-call xrefs: {len(get_import_xrefs(result))}",f"\nString xrefs: {len(get_string_xrefs(result))}","\nNo semantic function names are inferred."]
    return "\n".join(lines)+"\n"
