"""Static PE inspection, string extraction and cross-artifact binary search."""
from __future__ import annotations
import struct

KNOWN = [
    ("firmware_magic", bytes.fromhex("4dad0002")), ("MULCOORD_BE32_5555555",bytes.fromhex("0054c563")),
    ("MULCOORD_LE32_5555555",bytes.fromhex("63c55400")), ("sector_size_BE16",bytes.fromhex("0200")),
    ("sector_size_BE32",bytes.fromhex("00000200")), ("compression_01",b"\x01"), ("compression_02",b"\x02"),
    ("navboot",b"navboot"),("DB_0",b"DB_0"),("CARINET",b"CARINET"),("ABSTRACT",b"ABSTRACT"),
    ("5555555_ASCII",b"5555555"),("block_type_00",b"\x00"),("block_type_06",b"\x06"),
    ("block_type_07",b"\x07"),("block_type_08",b"\x08"),("block_type_09",b"\x09"),
    ("block_type_0A",b"\x0a"),("block_type_0C",b"\x0c"),("block_type_0E",b"\x0e"),
    ("block_type_0F",b"\x0f"),("block_type_10",b"\x10")]

def strings(data,min_len=4,limit=30000):
    out=[]
    for encoding,pattern in (("ascii",lambda b:32<=b<127),("utf16le",None)):
        if encoding=="ascii":
            start=None; chars=[]
            for i,b in enumerate(data):
                if pattern(b):
                    if start is None: start=i
                    chars.append(b)
                else:
                    if len(chars)>=min_len: out.append((start,bytes(chars).decode("ascii"),encoding))
                    start=None; chars=[]
                if len(out)>=limit: break
            if len(chars)>=min_len and len(out)<limit: out.append((start,bytes(chars).decode("ascii"),encoding))
        else:
            i=0
            while i+2<=len(data) and len(out)<limit:
                start=i; chars=[]
                while i+1<len(data) and 32<=data[i]<127 and data[i+1]==0:
                    chars.append(data[i]); i+=2
                if len(chars)>=min_len: out.append((start,bytes(chars).decode("ascii"),encoding))
                i=max(i+2,start+2)
    out.sort(key=lambda x:x[0]); return out[:limit]

def pe_analyze(data):
    """Parse common PE32/PE32+ section/import/export/resource directory metadata."""
    if data[:2]!=b"MZ" or len(data)<0x40: return None
    peoff=int.from_bytes(data[0x3c:0x40],"little")
    if peoff+24>len(data) or data[peoff:peoff+4]!=b"PE\0\0": return None
    machine,nsections,_,_,_,optsize,characteristics=struct.unpack_from("<HHIIIHH",data,peoff+4)
    opt=peoff+24; magic=int.from_bytes(data[opt:opt+2],"little")
    is64=magic==0x20b; dd=opt+(112 if is64 else 96); sizeheaders=int.from_bytes(data[opt+60:opt+64],"little")
    sections=[]; secpos=opt+optsize
    for i in range(nsections):
        p=secpos+i*40
        if p+40>len(data): break
        name=data[p:p+8].split(b"\0",1)[0].decode("ascii","replace")
        vsize,vaddr,rsize,rptr=struct.unpack_from("<IIII",data,p+8)
        sections.append({"name":name,"virtual_address":vaddr,"virtual_size":vsize,"raw_offset":rptr,"raw_size":rsize,"characteristics":int.from_bytes(data[p+36:p+40],"little")})
    def off(rva):
        if rva<sizeheaders and rva<len(data): return rva
        for s in sections:
            if s["virtual_address"]<=rva<s["virtual_address"]+max(s["virtual_size"],s["raw_size"]):
                pos=s["raw_offset"]+rva-s["virtual_address"]
                return pos if pos<len(data) else None
        return None
    def cstr(pos):
        if pos is None: return ""
        end=data.find(b"\0",pos,min(len(data),pos+512)); return data[pos:end].decode("ascii","replace") if end>=0 else ""
    dirs=[]
    ndd=int.from_bytes(data[opt+(108 if is64 else 92):opt+(112 if is64 else 96)],"little") if opt+(112 if is64 else 96)<=len(data) else 0
    for idx in range(min(ndd,16)):
        p=dd+idx*8
        if p+8<=len(data): dirs.append((int.from_bytes(data[p:p+4],"little"),int.from_bytes(data[p+4:p+8],"little")))
    def directory(i): return dirs[i] if i<len(dirs) else (0,0)
    imports=[]; import_records=[]; irva,_=directory(1); ip=off(irva)
    if ip is not None:
        for j in range(2048):
            p=ip+j*20
            if p+20>len(data): break
            orig,stamp,chain,name_rva,iat=struct.unpack_from("<IIIII",data,p)
            if not any((orig,stamp,chain,name_rva,iat)): break
            dll=cstr(off(name_rva)); thunk_rva=orig or iat; thunk=off(thunk_rva); names=[]
            if thunk is not None:
                width=8 if is64 else 4
                for k in range(8192):
                    q=thunk+k*width
                    if q+width>len(data): break
                    val=int.from_bytes(data[q:q+width],"little")
                    if not val: break
                    ordmask=(1<<(width*8-1))
                    iat_rva=iat+k*width
                    if val&ordmask:
                        ordinal=val&0xffff; name=None; status="UNRESOLVED"
                        names.append(f"ordinal_{ordinal}")
                    else:
                        name_rva=val&0x7fffffff; name_off=off(name_rva); name=cstr(name_off+2) if name_off is not None else None
                        ordinal=None; status="NAMED" if name else "UNRESOLVED"
                        names.append(name if name else f"rva_{name_rva:x}")
                    import_records.append({"dll":dll,"name":name,"ordinal":ordinal,"iat_rva":iat_rva,"iat_va":(int.from_bytes(data[opt+28:opt+32],"little")+iat_rva) if not is64 else (int.from_bytes(data[opt+24:opt+32],"little")+iat_rva),"thunk_rva":thunk_rva+k*width,"status":status})
            imports.append({"dll":dll,"symbols":names})
    exports=[]; erva,_=directory(0); ep=off(erva)
    if ep is not None and ep+40<=len(data):
        vals=struct.unpack_from("<IIHHIIIIIII",data,ep); nn=vals[7]; nrva=vals[9]; namespos=off(nrva)
        if namespos is not None:
            for j in range(min(nn,10000)):
                q=namespos+j*4
                if q+4>len(data): break
                exports.append(cstr(off(int.from_bytes(data[q:q+4],"little"))))
    resources=[]; rrva,_=directory(2); rp=off(rrva)
    if rp is not None:
        def walk(rel,prefix,depth=0):
            if depth>3 or len(resources)>10000 or rel+16>len(data): return
            named,ids=struct.unpack_from("<HH",data,rel+12); n=min(named+ids,4096)
            for i in range(n):
                q=rel+16+i*8
                if q+8>len(data): break
                name,child=struct.unpack_from("<II",data,q); label=f"name_{name&0x7fffffff:x}" if name&0x80000000 else str(name&0xffff)
                dest=rp+(child&0x7fffffff)
                if child&0x80000000: walk(dest,prefix+[label],depth+1)
                elif dest+16<=len(data):
                    rva,size=struct.unpack_from("<II",data,dest); resources.append({"path":"/".join(prefix+[label]),"size":size,"file_offset":off(rva)})
        walk(rp,[])
    entry_rva=int.from_bytes(data[opt+16:opt+20],"little") if opt+20<=len(data) else 0
    image_base=int.from_bytes(data[opt+(24 if is64 else 28):opt+(32 if is64 else 32)],"little") if opt+(32 if is64 else 32)<=len(data) else 0
    return {"pe_offset":peoff,"machine":machine,"machine_hex":f"0x{machine:04x}","pe32_plus":is64,"entry_point_rva":entry_rva,"image_base":image_base,"sections":sections,"imports":imports,"import_records":import_records,"exports":exports,"resources":resources}

def representations(query,mode="auto"):
    if mode=="hex" or (mode=="auto" and all(c in "0123456789abcdefABCDEF \t:_-" for c in query) and any(c in "abcdefABCDEF" for c in query)):
        try: return [bytes.fromhex("".join(c for c in query if c not in " :_-"))]
        except ValueError: return []
    found=[]
    if mode in ("auto","ascii"): found.append(query.encode("utf-8"))
    if mode in ("auto","utf16"): found.append(query.encode("utf-16le"))
    if mode in ("auto","numeric"):
        try:
            n=int(query,0)
            for width in (2,4,8):
                if 0<=n<1<<(8*width):
                    found.extend((n.to_bytes(width,"big"),n.to_bytes(width,"little")))
                    if width==4: found.extend((struct.pack(">f",float(n)),struct.pack("<f",float(n))))
                    if width==8: found.extend((struct.pack(">d",float(n)),struct.pack("<d",float(n))))
        except (ValueError,OverflowError): pass
    return list(dict.fromkeys(x for x in found if x))

def find_all(data,needles,max_hits=1000):
    hits=[]
    for needle in needles:
        pos=0
        while len(hits)<max_hits:
            pos=data.find(needle,pos)
            if pos<0: break
            hits.append((pos,needle)); pos+=max(1,len(needle))
        if len(hits)>=max_hits: break
    return sorted(hits,key=lambda x:x[0])

def pe_file_offset_to_rva(pe,file_offset):
    """Map a raw PE file offset only when it is inside validated section bytes."""
    offset=int(file_offset)
    if offset<0:raise ValueError("file offset must be non-negative")
    for section in pe.get("sections",[]):
        raw=int(section["raw_offset"]);size=int(section["raw_size"])
        if raw<=offset<raw+size:
            delta=offset-raw;rva=int(section["virtual_address"])+delta
            return {"file_offset":offset,"section":section.get("name",""),"rva":rva,"va":int(pe.get("image_base",0))+rva,"section_file_start":raw,"section_file_end":raw+size,"section_rva_start":int(section["virtual_address"])}
    raise ValueError("file offset is not inside a mapped PE section")
