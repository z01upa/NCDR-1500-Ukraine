"""Bounded helpers for SH4 argument, value-flow, PE-data and GUID evidence."""
from __future__ import annotations
import re, struct, uuid

def read_rva_bytes(data, pe, rva, length):
    rva=int(rva); length=int(length)
    if rva<0 or length<0: raise ValueError("RVA and length must be non-negative")
    for section in pe.get("sections",[]):
        start=int(section["virtual_address"]); raw=int(section["raw_offset"])
        raw_size=int(section["raw_size"]); virtual_size=int(section["virtual_size"])
        if start<=rva<start+max(raw_size,virtual_size):
            delta=rva-start
            if delta+length>raw_size: raise ValueError("requested bytes exceed raw section data")
            offset=raw+delta
            if offset+length>len(data): raise ValueError("requested bytes exceed file bounds")
            return {"rva":rva,"va":int(pe["image_base"])+rva,"file_offset":offset,"section":section.get("name",""),"length":length,"raw_hex":data[offset:offset+length].hex(),"raw_bytes":data[offset:offset+length]}
    raise ValueError("RVA is not mapped by a validated PE section")

def hex_view(data):
    b=bytes(data); return {"length":len(b),"hex":b.hex(" ").upper()}

def ascii_view(data):
    b=bytes(data); return {"length":len(b),"text":"".join(chr(x) if 32<=x<127 else "." for x in b)}

def utf16le_view(data):
    b=bytes(data)
    even=b[:len(b)//2*2]
    try: text=even.decode("utf-16le","strict")
    except UnicodeDecodeError:
        try: text=even.decode("utf-16le","replace")
        except Exception: text=""
        return {"status":"PARTIAL_TEXT","text":text,"trailing_byte":b[-1:].hex() if len(b)%2 else ""}
    useful=any(ch.isprintable() and not ch.isspace() for ch in text)
    if len(b)%2:return {"status":"PARTIAL_TEXT","text":text,"trailing_byte":b[-1:].hex()}
    return {"status":"VALID_TEXT" if useful else "NOT_VALID_OR_USEFUL_TEXT","text":text if useful else ""}

def windows_guid_interpret(data, evidence=None):
    b=bytes(data)
    if len(b)!=16: raise ValueError("Windows GUID interpretation requires exactly 16 bytes")
    d1,d2,d3=struct.unpack("<IHH",b[:8]); d4=b[8:]
    evidence=list(evidence or [])
    semantic=any(not str(x).casefold().startswith("4-byte aligned") for x in evidence)
    return {"raw_hex":b.hex().upper(),"Data1":d1,"Data2":d2,"Data3":d3,"Data4":list(d4),"canonical_guid":str(uuid.UUID(bytes_le=b)),"GUID_FORMAT_VALID":True,"GUID_SEMANTIC_EVIDENCE":semantic,"semantic_evidence":evidence,"interpretation":"GUID_CANDIDATE" if semantic else "FORMAT_ONLY"}

_PRIMITIVES={"X":"void","D":"char","C":"signed char","E":"unsigned char","F":"short","G":"unsigned short","H":"int","I":"unsigned int","J":"long","K":"unsigned long","M":"float","N":"double","_N":"bool"}
def parse_msvc_decorated_symbol(symbol):
    """Parse a useful, deliberately partial subset of Microsoft C++ names."""
    s=str(symbol).strip(); match=re.match(r"^\?(?P<method>[^@]+)@(?P<scope>.+?)@@(?P<encoding>.+)$",s)
    if not match: return {"status":"UNPARSED","raw_symbol":s,"confidence":"LOW"}
    method,scope,enc=match.group("method"),match.group("scope"),match.group("encoding")
    parts=scope.split("@"); cls=parts[0] if parts else ""
    # An S storage marker denotes a static member. Access and remaining
    # calling-convention bytes are retained verbatim for auditable evidence.
    static=bool(enc and enc[0]=="S"); access_code=enc[0] if enc else "?"
    access={"A":"private","I":"protected","Q":"public","S":"public"}.get(access_code,"unknown")
    type_start=2 if static else 3
    ret_code=enc[type_start:type_start+1]
    return_type=_parse_msvc_type(ret_code)[1] if ret_code else "unknown"
    args_blob=enc[type_start+1:]
    if args_blob.endswith("Z"): args_blob=args_blob[:-1]
    if args_blob.endswith("@"): args_blob=args_blob[:-1]
    if args_blob=="X":args_blob=""
    params=[]; i=0; backrefs=[]
    while i<len(args_blob) and args_blob[i]!="@":
        typ,nxt,desc=_parse_msvc_type_at(args_blob,i)
        if nxt<=i: break
        if typ=="backref":
            # MSVC's digit back-references address the user-type/name table;
            # primitive K/J parameters do not consume an entry.
            desc=backrefs[0] if backrefs else "unresolved MSVC type back-reference"
        params.append(desc)
        if typ in ("user","ref","ptr","ptrptr") and "GUID" in desc.upper(): backrefs.append(desc)
        i=nxt
    return {"status":"PARTIAL_PARSE","raw_symbol":s,"class":cls,"method":method,"member":True,"static":static,"access":access,"calling_convention_encoding":enc[1:3],"return_type":return_type,"parameter_count":len(params),"parameter_types":params,"confidence":"MEDIUM: symbol scope and common MSVC type codes parsed; undecoded suffix preserved","undecoded_suffix":args_blob[i:]}

def _parse_msvc_type(code):
    return _parse_msvc_type_at(code,0)[:1]+(_parse_msvc_type_at(code,0)[2],)

def _parse_msvc_type_at(s,i):
    if i>=len(s): return "unknown",i,"unknown"
    if s.startswith("ABU",i):
        _,n,name=_parse_msvc_type_at(s,i+2)
        return "ref",n,"const reference to "+name
    if s.startswith("PAU",i):
        _,n,name=_parse_msvc_type_at(s,i+2)
        return "ptr",n,"pointer to interface/struct "+name
    if s.startswith("PAPAX",i):return "ptrptr",i+5,"pointer to pointer to void"
    c=s[i]
    if c=="0":return "backref",i+1,"repeated prior parameter type"
    if c in "AB":
        const=(i+1<len(s) and s[i+1] in "BC")
        j=i+2 if const else i+1
        inner,n,desc=_parse_msvc_type_at(s,j)
        prefix="const " if const else ""
        return "ref",n,(prefix+"reference to "+desc).strip()
    if c in "PQR":
        inner,n,desc=_parse_msvc_type_at(s,i+1)
        return "ptr",n,"pointer to "+desc
    if c in "UVTW":
        end=s.find("@@",i+1)
        if end<0:return "user",len(s),"user-defined type (incomplete encoding)"
        name=s[i+1:end].replace("?AV","class ").replace("?AU","struct ").replace("?AW4","enum ")
        return "user",end+2,name
    if c=="_" and i+1<len(s) and s[i+1]=="N":return "bool",i+2,"bool"
    return c,i+1,_PRIMITIVES.get(c,"type code "+c)

def sh4_wince_abi():
    return {"architecture":"SH-4 Windows CE","status":"SUPPORTED_BOUNDED_MODEL","member_this_register":"R4","argument_registers":["R4","R5","R6","R7"],"member_argument_registers":["R5","R6","R7"],"stack_arguments":"arguments beyond available registers are expected in caller stack area; exact offsets require call-site evidence","integer_return_register":"R0","pointer_return_register":"R0","out_pointer_storage":"address carried in the corresponding pointer argument location; OUT semantics require post-call storage evidence","confidence":"MEDIUM: conventional Windows CE SH4 register model; caller-site values remain instruction evidence"}

def trace_registers_at_call(analysis,call_rva,decorated_symbol=None):
    call_rva=int(call_rva); rows=analysis.get("instructions",[]); call=next((x for x in rows if int(x["rva"])==call_rva),None)
    if not call: return {"status":"CALLSITE_NOT_FOUND","call_rva":call_rva,"arguments":[]}
    start=call.get("function_start")
    selected=[x for x in rows if int(x["rva"])<call_rva and (start is None or x.get("function_start")==start) and call_rva-int(x["rva"])<=0x100]
    literals={int(x["instruction_rva"]):x for x in analysis.get("literal_pool_resolutions",[])}
    regs={}; steps=[]; stack_values=[]
    for ins in selected:
        w=bytes.fromhex(ins.get("bytes",""))
        if len(w)!=2: continue
        word=int.from_bytes(w,"little"); rva=int(ins["rva"])
        # Calls invalidate volatile SH-4 argument registers. Retain only ABI
        # preserved R8-R14 values; arguments are reconstructed from later writes.
        if ins.get("instruction", "").upper() in ("JSR", "BSRF", "BRAF") or (word & 0xf0ff in (0x400b,0x0003)):
            regs={k:v for k,v in regs.items() if k in range(8,15)}
            steps.append({"rva":rva,"instruction":ins.get("operands"),"bytes":ins.get("bytes"),"effect":"call_clobbers_volatile_registers"})
            continue
        if rva in literals:
            lr=literals[rva]; reg=int(lr["register"][1:]); regs[reg]={"value":lr["resolved_va"],"source_rva":rva,"literal_rva":lr["literal_rva"],"confidence":lr["confidence"]}
        elif word&0xf00f==0x6003:
            n=(word>>8)&15;m=(word>>4)&15
            if m in regs: regs[n]=dict(regs[m],source_rva=rva)
            else: regs.pop(n,None)
        elif word&0xf000==0xe000:
            n=(word>>8)&15; imm=word&0xff; imm=imm-256 if imm&128 else imm
            regs[n]={"value":imm,"source_rva":rva,"literal_rva":None,"confidence":"MEDIUM: sign-extended MOV immediate"}
        elif word&0xf000==0x1000 and ((word>>8)&15)==15:
            n=(word>>8)&15; m=(word>>4)&15; off=(word&15)*4
            value=regs.get(m)
            stored=value.get("value") if value else None
            stack_values.append({"location":f"STACK+0x{off:X}","stack_offset":off,"value":stored,"classification":"POINTER_TO_CALLER_LOCAL_STORAGE" if isinstance(stored,str) and "R14 +" in stored else "VALUE","source_rva":rva,"register":f"R{m}","confidence":value.get("confidence","UNRESOLVED") if value else "UNRESOLVED"})
        elif word&0xf00f==0x2006 and ((word>>8)&15)==15:
            m=(word>>4)&15; stack_values.append({"location":f"stack push #{len(stack_values)+1}","value":regs.get(m,{}).get("value"),"source_rva":rva,"register":f"R{m}","confidence":regs.get(m,{}).get("confidence","UNRESOLVED")})
        elif word&0xf00f in (0x6002,0x6006,0x6007):
            regs.pop((word>>8)&15,None)
        elif word&0xf000==0x7000:
            n=(word>>8)&15; imm=word&255; imm=imm-256 if imm&128 else imm
            prior=regs.get(n)
            regs[n]={"value":f"{prior['value']} + {imm}" if prior and isinstance(prior.get("value"),str) else (int(prior["value"])+imm if prior and isinstance(prior.get("value"),int) else None),"source_rva":rva,"literal_rva":None,"confidence":"MEDIUM: ADD immediate"}
        elif word&0xf00f==0x300c:
            n=(word>>8)&15;m=(word>>4)&15
            left,right=regs.get(n),regs.get(m)
            value=(f"R14 + {left['value']}" if m==14 and left and isinstance(left.get("value"),int) else f"{left['value']} + {right['value']}" if left and right else None)
            regs[n]={"value":value,"source_rva":rva,"literal_rva":None,"confidence":"MEDIUM: register addition" if value is not None else "UNRESOLVED"}
        steps.append({"rva":rva,"instruction":ins.get("operands"),"bytes":ins.get("bytes")})
    # JSR's delay slot executes before transfer. Apply only the delay-slot
    # instruction to the final register state, after earlier call clobbers.
    delay=next((x for x in analysis.get("instructions",[]) if int(x["rva"])==call_rva+2),None)
    if delay:
        wbytes=bytes.fromhex(delay.get("bytes",""))
        if len(wbytes)==2:
            w=int.from_bytes(wbytes,"little"); rva=int(delay["rva"])
            if rva in literals:
                lr=literals[rva]; regs[int(lr["register"][1:])] = {"value":lr["resolved_va"],"source_rva":rva,"literal_rva":lr.get("literal_rva"),"confidence":lr.get("confidence")}
            elif w&0xf000==0xe000:
                n=(w>>8)&15; imm=w&255; regs[n]={"value":imm-256 if imm&128 else imm,"source_rva":rva,"literal_rva":None,"confidence":"MEDIUM: delay-slot MOV immediate"}
            elif w&0xf00f==0x6003:
                n=(w>>8)&15;m=(w>>4)&15
                if m in regs:regs[n]=dict(regs[m],source_rva=rva)
                else:regs.pop(n,None)
            else:
                dest=(w>>8)&15
                if w&0xf00f in (0x6002,0x6006,0x6007,0x2002,0x2006,0x2007):regs.pop(dest,None)
            steps.append({"rva":rva,"instruction":delay.get("operands"),"bytes":delay.get("bytes"),"effect":"delay_slot_applied_before_call"})
    symbol=parse_msvc_decorated_symbol(decorated_symbol) if decorated_symbol else None
    abi=sh4_wince_abi(); member=bool(symbol and symbol.get("member") and not symbol.get("static")); locations=abi["member_argument_registers"] if member else abi["argument_registers"]
    this_value=regs.get(4) if member else None
    args=[]
    for i,loc in enumerate(locations):
        n=int(loc[1:]); item=regs.get(n)
        args.append({"location":loc,"role":f"register argument {i+1}","value":item.get("value") if item else None,"source_rva":item.get("source_rva") if item else None,"literal_rva":item.get("literal_rva") if item else None,"confidence":item.get("confidence") if item else "UNRESOLVED"})
    this_arg={"location":"R4","role":"this pointer","value":this_value.get("value") if this_value else None,"source_rva":this_value.get("source_rva") if this_value else None,"confidence":this_value.get("confidence") if this_value else "UNRESOLVED"} if member else None
    stack_values.sort(key=lambda x:x.get("stack_offset",0))
    return {"status":"RECOVERED" if any(x["value"] is not None for x in args+stack_values) or (this_arg and this_arg["value"] is not None) else "NO_REGISTER_CONSTANTS_RECOVERED","call_rva":call_rva,"decorated_symbol":symbol,"abi":abi,"this_pointer":this_arg,"arguments":args,"stack_arguments":stack_values,"stack_argument_status":"RECOVERED_FROM_PREDECREMENT_STORES" if stack_values else "NOT_RECOVERED: no recognized stack argument stores before call","source_instructions":steps,"delay_slot_rva":call_rva+2,"delay_slot_executed_before_call":bool(delay)}

def trace_local_value_flow(analysis,start_rva,register=0,direction="return",limit=64):
    first=next((x for x in analysis.get("instructions",[]) if int(x["rva"])==int(start_rva)),None); fn=first.get("function_start") if first else None
    rows=[x for x in analysis.get("instructions",[]) if int(x["rva"])>=int(start_rva) and (fn is None or x.get("function_start")==fn)][:limit]
    tracked={int(register)};steps=[]
    for ins in rows:
        b=bytes.fromhex(ins.get("bytes",""))
        if len(b)!=2:continue
        w=int.from_bytes(b,"little"); n=(w>>8)&15;m=(w>>4)&15; operation=None; src=None; dst=None
        if w&0xf00f==0x6003 and m in tracked: tracked.add(n);operation="register_copy";src=f"R{m}";dst=f"R{n}"
        elif w&0xf00f==0x6003 and n in tracked: tracked.remove(n);operation="overwritten";src=f"R{m}";dst=f"R{n}"
        elif w&0xf00f in (0x2002,0x2006,0x2007) and m in tracked:operation="stored";src=f"R{m}";dst=f"@R{n}"
        elif w&0xf00f in (0x6002,0x6006,0x6007) and m in tracked:tracked.add(n);operation="dereferenced_load";src=f"@R{m}";dst=f"R{n}"
        elif w&0xf00f in (0x6002,0x6006,0x6007) and n in tracked:operation="loaded_or_overwritten";src=f"@R{m}";dst=f"R{n}";tracked.remove(n)
        elif w&0xf000==0xe000 and n in tracked:operation="overwritten";src="immediate";dst=f"R{n}";tracked.remove(n)
        elif w&0xf00f==0x2008 and (n in tracked or m in tracked):operation="tested";src=f"R{n}, R{m}";dst=None
        elif w&0xf00f==0x3000 and (n in tracked or m in tracked):operation="tested";src=f"R{n}, R{m}";dst=None
        elif ins.get("instruction","").upper() in ("RTS","RTE") and direction=="return":operation="returned";src=f"R{next(iter(tracked))}";dst="caller"
        if operation:steps.append({"source_rva":steps[-1]["instruction_rva"] if steps else int(start_rva),"instruction_rva":int(ins["rva"]),"source_location":src,"destination_location":dst,"operation":operation,"value_identity":f"R{register}@{int(start_rva):X}","confidence":"MEDIUM: bounded register and local instruction pattern"})
        if operation in ("overwritten","returned"):break
    return {"status":"TRACED" if steps else "NO_LOCAL_FLOW_RECOVERED","start_rva":int(start_rva),"steps":steps}

def trace_object_flow(analysis,start_rva,register=0,limit=128,end_rva=None,start_location=None):
    """Track one value through bounded register, stack-local and memory patterns."""
    first=next((x for x in analysis.get("instructions",[]) if int(x["rva"])==int(start_rva)),None); fn=first.get("function_start") if first else None
    rows=[x for x in analysis.get("instructions",[]) if int(x["rva"])>=int(start_rva) and (end_rva is None or int(x["rva"])<=int(end_rva)) and (fn is None or x.get("function_start")==fn)][:limit]
    literals={int(x["instruction_rva"]):x for x in analysis.get("literal_pool_resolutions",[])}
    calls={int(x["call_instruction_rva"]):x for x in analysis.get("indirect_call_xrefs",[])}
    regs={int(register):f"value@R{register}:{int(start_rva):08X}"};memory={};steps=[];sp_depth=0
    if start_location:
        key=str(start_location).upper().replace(" ","").replace("0X","0x")
        memory["memory["+key+"]"]="object_from_out_storage"
    def emit(ins,source,dest,op,identity,confidence="MEDIUM: bounded SH4 instruction pattern"):
        steps.append({"source_rva":steps[-1]["instruction_rva"] if steps else int(start_rva),"instruction_rva":int(ins["rva"]),"source_location":source,"destination_location":dest,"operation":op,"value_identity":identity,"confidence":confidence})
    for ins in rows:
        rva=int(ins["rva"]); b=bytes.fromhex(ins.get("bytes",""))
        if len(b)!=2:continue
        w=int.from_bytes(b,"little"); n=(w>>8)&15;m=(w>>4)&15
        if rva in literals:
            item=literals[rva];regs[n]=str(item.get("resolved_va") or item.get("raw_value"));emit(ins,f"literal RVA 0x{item['literal_rva']:X}",f"R{n}","load_literal",regs[n],item.get("confidence","HIGH"))
        elif w&0xf00f==0x6003:
            if m in regs:regs[n]=regs[m];emit(ins,f"R{m}",f"R{n}","register_copy",regs[n])
            else:regs.pop(n,None)
        elif w&0xf00f==0x2006 and n==15:
            sp_depth+=4;key=f"stack+0x{sp_depth:X}"
            if m in regs:memory[key]=regs[m];emit(ins,f"R{m}",key,"stack_local_store",regs[m])
        elif w&0xf00f==0x6006 and m==15:
            key=f"stack+0x{sp_depth:X}"
            if key in memory:regs[n]=memory[key];emit(ins,key,f"R{n}","stack_local_load",regs[n]);memory.pop(key,None);sp_depth=max(0,sp_depth-4)
            else:regs.pop(n,None)
        elif w&0xf00f==0x2002:
            if m in regs:
                key=f"memory[@R{n}]";memory[key]=regs[m];emit(ins,f"R{m}",key,"memory_store",regs[m])
        elif w&0xf00f==0x6002:
            key=f"memory[@R{m}]"
            if key in memory:regs[n]=memory[key];emit(ins,key,f"R{n}","memory_load",regs[n])
            elif m in regs:regs[n]=regs[m]+f"->*{rva:08X}";emit(ins,f"*{regs[m]}",f"R{n}","dereference",regs[n])
            else:regs.pop(n,None)
        elif w&0xf000==0x1000:
            disp=w&15;key=f"memory[@R{n}+0x{disp*4:X}]"
            if m in regs:memory[key]=regs[m];emit(ins,f"R{m}",key,"memory_store",regs[m])
        elif w&0xf000==0x5000:
            disp=w&15;key=f"memory[@R{m}+0x{disp*4:X}]"
            if key in memory:regs[n]=memory[key];emit(ins,key,f"R{n}","memory_load",regs[n])
            elif m in regs:regs[n]=regs[m]+f"+0x{disp*4:X}";emit(ins,f"{regs[m]}+0x{disp*4:X}",f"R{n}","dereference",regs[n])
            else:regs.pop(n,None)
        elif w&0xf0ff in (0x400b,0x402b):
            call=calls.get(rva);emit(ins,f"R{n}","control-flow edge","indirect_call",regs.get(n,"unresolved"),"HIGH: callsite record" if call else "LOW: opcode only")
        elif w&0xf000==0xe000 and n in regs:
            old=regs.pop(n);emit(ins,"immediate",f"R{n}","overwrite",old)
        elif ins.get("instruction","").upper() in ("RTS","RTE"):
            if register in regs:emit(ins,f"R{register}","caller","return",regs[register])
            break
    return {"status":"TRACED" if steps else "NO_OBJECT_FLOW_RECOVERED","start_rva":int(start_rva),"end_rva":int(end_rva) if end_rva is not None else None,"initial_register":f"R{register}","initial_location":start_location,"steps":steps,"register_values":{f"R{k}":v for k,v in regs.items()},"stack_local_count":sum(k.startswith("stack") or k.startswith("memory[STACK") for k in memory)}

def trace_out_parameter(analysis,call_rva,argument_location=None,decorated_symbol=None,limit=48):
    args=trace_registers_at_call(analysis,call_rva,decorated_symbol)
    location=str(argument_location or "").upper()
    symbol=args.get("decorated_symbol") or {}
    if not location and symbol.get("parameter_types") and "pointer to pointer to void" in symbol["parameter_types"][-1].casefold():
        index=len(symbol["parameter_types"])-1
        stack_offset=(0x10+(index-3)*4) if symbol.get("member") and not symbol.get("static") and index>=3 else (index-4)*4
        location=f"STACK+0X{max(0,stack_offset):X}"
    passed=next((x for x in args.get("arguments",[]) if x["location"].upper()==location),None)
    if location=="R4" and args.get("this_pointer"):passed=args["this_pointer"]
    if location.startswith("STACK+"):
        try:offset=int(location.split("+",1)[1],16);passed=next((x for x in args.get("stack_arguments",[]) if x.get("stack_offset")==offset),None)
        except ValueError:passed=None
    caller=next((x for x in analysis.get("instructions",[]) if int(x["rva"])==int(call_rva)),None)
    fnend=caller.get("function_end") if caller else None
    following=[x for x in analysis.get("instructions",[]) if int(x["rva"])>=int(call_rva)+4 and (fnend is None or int(x["rva"])<int(fnend)) and (caller is None or caller.get("function_start") is None or x.get("function_start")==caller.get("function_start"))][:limit]
    reads=[]
    for ins in following:
        b=bytes.fromhex(ins.get("bytes","")); word=int.from_bytes(b,"little") if len(b)==2 else 0
        if re.search(r"MOV\.L\s+@R\d+,|MOV\s+@R\d+,",ins.get("operands", ""),re.I) or (word&0xf000==0x5000 and ((word>>4)&15)==14 and (word&15)==2):reads.append({"rva":ins["rva"],"instruction":ins.get("operands"),"evidence":"post-call memory read"})
    passed_value=passed.get("value") if passed else None
    storage="CALLER_LOCAL_ADDRESS" if isinstance(passed_value,str) and ("R14" in passed_value or "0x8" in passed_value) else "UNKNOWN_UNTIL_ADDRESS_PROVEN"
    local_read=storage=="CALLER_LOCAL_ADDRESS" and any(re.search(r"@\(?R14\s*,\s*(?:0x)?8\)?",x["instruction"],re.I) for x in reads)
    linked=bool(passed and local_read)
    return {"status":"OUT_STORAGE_CONFIRMED" if linked else "POST_CALL_READS_FOUND" if reads else "INCONCLUSIVE_NO_POST_CALL_READ","call_rva":int(call_rva),"argument_location":location or None,"address_passed":passed_value,"source_rva":passed.get("source_rva") if passed else None,"storage_class":storage,"signature_indication":"decorated pointer type alone does not prove OUT semantics","post_call_reads":reads,"combined_out_evidence":linked}

def detect_vtable_calls(analysis):
    # Candidate evidence uses adjacent object/vtable/function loads. A confirmed
    # label is reserved for a known indirect target and explicit slot load.
    result=[]; rows=analysis.get("instructions",[])
    for ref in analysis.get("indirect_call_xrefs",[]):
        call=int(ref["call_instruction_rva"]); prior=[x for x in rows if call-12<=int(x["rva"])<call]
        operands=" ".join(x.get("operands","") for x in prior)
        candidate=bool(re.search(r"@R\d+|\+0x[0-9A-F]+",operands,re.I))
        object_source=None;vtable_source=None;slot_offset=None
        loads=[]
        for ins in prior:
            op=ins.get("operands","")
            m=re.search(r"@R(\d+)\s*,\s*R(\d+)",op,re.I)
            if m:loads.append((m.group(1),m.group(2)))
            sm=re.search(r"@\(R(\d+)\s*,\s*(0x[0-9a-f]+|\d+)\)[^,]*,\s*R(\d+)",op,re.I)
            if sm:
                vreg,disp,dest=sm.group(1),sm.group(2),sm.group(3)
                vtable_source="R"+vreg;slot_offset=int(disp,0);loads.append((vreg,dest))
            else:
                rev=re.search(r"@\((0x[0-9a-f]+|\d+)\s*,\s*R(\d+)\)[^,]*,\s*R(\d+)",op,re.I)
                if rev:
                    disp,vreg,dest=rev.group(1),rev.group(2),rev.group(3)
                    vtable_source="R"+vreg;slot_offset=int(disp,0);loads.append((vreg,dest))
        if len(loads)>=2:
            object_source="R"+loads[0][0];vtable_source=vtable_source or "R"+loads[0][1]
            candidate=True
        result.append({"call_rva":call,"target_rva":ref.get("resolved_target_rva"),"classification":"VTABLE_CALL_CANDIDATE" if candidate else ("GENERIC_INDIRECT_CALL" if ref.get("target_type")!="UNRESOLVED" else "UNRESOLVED"),"object_source":object_source or ("register source not recovered" if candidate else None),"vtable_source":vtable_source,"slot_offset":slot_offset,"confidence":"LOW: bounded instruction neighborhood; candidate only"})
    return result
