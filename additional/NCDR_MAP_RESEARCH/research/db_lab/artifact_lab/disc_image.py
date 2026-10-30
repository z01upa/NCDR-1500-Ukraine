"""Minimal read-only ISO-9660 directory reader for ISO and raw BIN/IMG files."""
from __future__ import annotations
import re

def cue_layout(cue_path):
    text=cue_path.read_text(errors="replace")
    image=None; mode=None
    for line in text.splitlines():
        m=re.match(r'\s*FILE\s+"?([^" ]+)"?\s+\w+',line,re.I)
        if m: image=(cue_path.parent/m.group(1)).resolve()
        m=re.match(r'\s*TRACK\s+\d+\s+(MODE1/2352|MODE1/2048)',line,re.I)
        if m: mode=m.group(1).upper()
    if not image: raise ValueError("CUE has no readable FILE entry")
    return image, (2352,16) if mode=="MODE1/2352" else (2048,0)

def enumerate_iso(data, sector_size=2048, data_offset=0):
    """Yield ISO path/extent/length records. Does not extract or modify image."""
    def sector(n):
        pos=n*sector_size+data_offset
        return bytes(data[pos:pos+2048]) if pos+2048<=len(data) else b""
    pvd=sector(16)
    if len(pvd)<2048 or pvd[1:6]!=b"CD001": raise ValueError("No ISO-9660 primary volume descriptor at sector 16")
    rec=pvd[156:]; root_len=rec[0]
    if root_len<34: raise ValueError("Invalid ISO root directory record")
    root_extent=int.from_bytes(rec[2:6],"little"); root_size=int.from_bytes(rec[10:14],"little")
    seen=set(); output=[]
    def walk(prefix,extent,size,depth):
        if depth>24 or (extent,size) in seen: return
        seen.add((extent,size)); blob=bytearray()
        count=(size+2047)//2048
        for i in range(count): blob.extend(sector(extent+i))
        cursor=0
        while cursor<len(blob):
            n=blob[cursor]
            if n==0: cursor=((cursor//2048)+1)*2048; continue
            if n<34 or cursor+n>len(blob): break
            r=blob[cursor:cursor+n]; pos=int.from_bytes(r[2:6],"little"); length=int.from_bytes(r[10:14],"little")
            flags=r[25]; namelen=r[32]; rawname=bytes(r[33:33+namelen])
            name="." if rawname==b"\0" else ".." if rawname==b"\1" else rawname.decode("ascii","replace").split(";",1)[0].rstrip(".")
            if name not in (".",".."):
                path=f"{prefix}/{name}" if prefix else name
                isdir=bool(flags&2)
                output.append({"path":path,"extent_sector":pos,"size":length,"is_directory":isdir,"image_offset":pos*sector_size+data_offset})
                if isdir: walk(path,pos,length,depth+1)
            cursor+=n
    walk("",root_extent,root_size,0)
    return output
