"""Read-only sector scanner using the already-confirmed DB_0 framing."""
from __future__ import annotations
import hashlib
import mmap
from pathlib import Path
import zlib
from dataclasses import asdict, dataclass
from ..config import SECTOR_SIZE


@dataclass(frozen=True)
class Block:
    sector: int
    offset: int
    span: int
    alignment: int
    block_type: int
    compression: int
    logical_units: int

    @property
    def logical_size(self):
        return self.logical_units * SECTOR_SIZE

    def as_dict(self):
        return asdict(self)


def sha256_file(path: Path, chunk_size=4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk: break
            digest.update(chunk)
    return digest.hexdigest()


class DBReader:
    def __init__(self, path):
        self.path = Path(path)
        self.file = self.path.open("rb")
        self.data = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        self.blocks = self.scan()
        self.by_sector = {b.sector: b for b in self.blocks}

    def close(self):
        self.data.close(); self.file.close()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def scan(self):
        candidates = []
        total = len(self.data) // SECTOR_SIZE
        # Sector ID must self-identify; records must fit in the source file.
        for sector in range(total):
            offset = sector * SECTOR_SIZE
            if int.from_bytes(self.data[offset:offset+3], "big") != sector: continue
            span = self.data[offset+3]
            if not span or offset + span * SECTOR_SIZE > len(self.data): continue
            candidates.append((sector, offset, span))
        starts = {sector for sector, _, _ in candidates}
        blocks = []
        for sector, offset, span in candidates:
            nxt = sector + span
            # Respect physical record framing: accept records whose next sector
            # is another self-identifying header, and the final record at EOF.
            if nxt not in starts and offset + span * SECTOR_SIZE != len(self.data):
                continue
            blocks.append(Block(sector, offset, span, self.data[offset+4],
                                self.data[offset+5], self.data[offset+6],
                                self.data[offset+7]))
        return blocks

    def raw(self, block):
        return self.data[block.offset:block.offset + block.span * SECTOR_SIZE]

    def logical(self, block):
        raw = self.raw(block)
        if block.compression == 0:
            if block.logical_size > len(raw): raise ValueError("logical extent exceeds physical record")
            return bytes(raw[:block.logical_size])
        if block.compression == 2:
            dec = zlib.decompressobj()
            payload = dec.decompress(raw[8:]) + dec.flush()
            if not dec.eof: raise ValueError("bounded zlib stream is incomplete")
            logical = bytes(raw[:8]) + payload
            if len(logical) != block.logical_size:
                raise ValueError("zlib logical extent does not match byte 7")
            return logical
        raise ValueError("compression 0x01 is unresolved")

    def header_hex(self, block):
        return bytes(self.data[block.offset:block.offset+8]).hex()
