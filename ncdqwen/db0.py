from __future__ import annotations

import hashlib
import mmap
import zlib
from pathlib import Path
from typing import Iterator

SECTOR_SIZE = 512

def u16(data: bytes | mmap.mmap, pos: int) -> int:
    return int.from_bytes(data[pos:pos+2], "big")

def u24(data: bytes | mmap.mmap, pos: int) -> int:
    return int.from_bytes(data[pos:pos+3], "big")

def u32(data: bytes | mmap.mmap, pos: int) -> int:
    return int.from_bytes(data[pos:pos+4], "big")

def sha256_file(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8*1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()

class DB0Reader:
    """Read-only access to the self-identifying 512-byte sector chain."""
    def __init__(self,path:Path):
        self.path=Path(path)
        self._file=self.path.open("rb")
        self.data=mmap.mmap(self._file.fileno(),0,access=mmap.ACCESS_READ)
        if len(self.data) % SECTOR_SIZE:
            self.data.close(); self._file.close()
            raise ValueError("DB_0 length is not an exact multiple of 512 bytes")
        self.sector_count=len(self.data)//SECTOR_SIZE
        self.records=list(self._walk_chain())
        if not self.records:
            self.data.close(); self._file.close()
            raise ValueError("no DB_0 records found from sector 2")
        self.by_sector={row["sector"]:row for row in self.records}

    def close(self):
        self.data.close(); self._file.close()

    def __enter__(self): return self
    def __exit__(self,*_): self.close()

    def _walk_chain(self) -> Iterator[dict]:
        sector=2
        visited=set()
        while True:
            if sector == self.sector_count:
                return
            if sector > self.sector_count:
                raise ValueError("record chain ended beyond exact EOF")
            if sector in visited:
                raise ValueError(f"record chain cycle at sector 0x{sector:x}")
            visited.add(sector); pos=sector*SECTOR_SIZE
            if u24(self.data,pos)!=sector:
                raise ValueError(f"record chain header mismatch at sector 0x{sector:x}")
            span=self.data[pos+3]
            if span<1 or sector+span>self.sector_count:
                raise ValueError(f"invalid physical span {span} at sector 0x{sector:x}")
            block_type=self.data[pos+5]
            compression=self.data[pos+6]
            units=self.data[pos+7]
            yield {"sector":sector,"span":span,"block_type":block_type,
                   "compression":compression,"logical_size":units*SECTOR_SIZE,
                   "offset":pos}
            next_sector=sector+span
            if next_sector==self.sector_count: return
            if u24(self.data,next_sector*SECTOR_SIZE)!=next_sector:
                raise ValueError(f"next record header missing after sector 0x{sector:x}")
            sector=next_sector

    def stored(self,sector:int)->bytes:
        row=self.by_sector[sector]
        start=row["offset"]; end=start+row["span"]*SECTOR_SIZE
        return bytes(self.data[start:end])

    def logical(self,sector:int)->bytes:
        row=self.by_sector[sector]
        raw=self.stored(sector)
        expected=row["logical_size"]
        if row["compression"]==0:
            if expected>len(raw): raise ValueError(f"logical extent exceeds stored record at 0x{sector:x}")
            return raw[:expected]
        if row["compression"]==2:
            payload=zlib.decompress(raw[8:])
            result=raw[:8]+payload
            if len(result)!=expected:
                raise ValueError(f"zlib logical extent mismatch at 0x{sector:x}: {len(result)} != {expected}")
            return result
        raise ValueError(f"compression 0x{row['compression']:02x} is unresolved")

    def logical_or_stored(self,sector:int)->tuple[bytes,str]:
        row=self.by_sector[sector]
        if row["compression"] in (0,2): return self.logical(sector),"logical"
        return self.stored(sector),"physical"

def logical_zlib_valid(reader:DB0Reader,row:dict)->bool|None:
    if row["compression"]!=2: return None
    return len(reader.logical(row["sector"]))==row["logical_size"]
