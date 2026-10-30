#!/usr/bin/env python3
"""Conservative static parser for the 4D AD 00 02 firmware container.

The format is only partially recoverable from patch.exe.  Unknown fields are
reported as unknown; the parser never rewrites the source image.
"""
from __future__ import annotations
import argparse, struct, sys
from pathlib import Path

MAGIC = b"\x4d\xad\x00\x02"

def u32be(b, off):
    return struct.unpack_from(">I", b, off)[0] if off + 4 <= len(b) else None

def hits(b, needle):
    p = 0
    while True:
        p = b.find(needle, p)
        if p < 0: return
        yield p
        p += 1

def candidates(b):
    """Return only records with code-supported magic/size invariants.

    patch.exe checks magic 4DAD0002, reads a big-endian size at +4, requires
    the size to exceed 0x5c, be 4-byte aligned, and fit in the input buffer.
    The remaining header fields are deliberately retained as raw/unknown.
    """
    out=[]
    for off in hits(b, MAGIC):
        size=u32be(b, off+4)
        if size is not None and size > 0x5c and size % 4 == 0 and off+size <= len(b):
            out.append((off,size))
    return out

def describe(b, path):
    print(f"image: {path}\nsize: {len(b)}")
    ms=list(hits(b,MAGIC)); print(f"magic_hits: {len(ms)}")
    for off in ms:
        print(f"  magic_offset=0x{off:X} bytes=4D AD 00 02")
    cs=candidates(b); print(f"validated_magic_size_candidates: {len(cs)}")
    for off,size in cs:
        print(f"  candidate_offset=0x{off:X} record_size={size} (0x{size:X})")
    print("outer-header fields: unresolved (no complete outer-header layout is encoded as literals)")
    print("integrity: CRC polynomial clue 0x800021; initial/final/range/storage unresolved")

def list_modules(b):
    cs=candidates(b)
    if not cs: print("no code-supported module record candidates found")
    for off,size in cs:
        end=off+size; name=list(hits(b[off:end],b"navboot"))
        print(f"record_offset=0x{off:X}, record_size={size}, navboot_offsets="+
              (",".join(f"0x{off+x:X}" for x in name) if name else "none"))
    # Always report strings, including those outside validated records.
    for needle in (b"navboot",b"NAVBOOT"):
        for off in hits(b,needle): print(f"string {needle.decode()}: offset=0x{off:X}")

def extract(b, image, module, output):
    if module.lower() != "navboot": raise SystemExit("only navboot is supported by the recovered target logic")
    cs=[]
    for off,size in candidates(b):
        if b[off:off+size].find(b"navboot") >= 0: cs.append((off,size))
    if len(cs) != 1:
        raise SystemExit("navboot record is not uniquely recoverable; refusing to guess payload offset")
    off,size=cs[0]
    # The module body begins after the validated 0x5c-byte header only when
    # the recovered image confirms that convention; no such image is local.
    raise SystemExit(f"navboot record found at 0x{off:X} size {size}, but payload/header boundary is unresolved; no output written")

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    for cmd in ("info","list"):
        p=sub.add_parser(cmd); p.add_argument("image")
    p=sub.add_parser("extract"); p.add_argument("image"); p.add_argument("module"); p.add_argument("output")
    a=ap.parse_args(); data=Path(a.image).read_bytes()
    if not data.startswith(MAGIC): raise SystemExit("invalid image: missing 4D AD 00 02 at offset 0")
    if a.cmd=="info": describe(data,a.image)
    elif a.cmd=="list": list_modules(data)
    else: extract(data,a.image,a.module,a.output)
if __name__=="__main__": main()
