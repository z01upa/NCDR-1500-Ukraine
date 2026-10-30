"""Read-only deterministic parser for the confirmed road grammar.

This module deliberately implements no inferred alternate formats.  Every
rejection carries the exact confirmed invariant that failed.
"""
from __future__ import annotations

from dataclasses import dataclass
import mmap
from pathlib import Path
import zlib

SECTOR_SIZE = 512
MULCOORD_SCALE = 5_555_555


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Header:
    sector: int
    span: int
    block_type: int
    compression: int
    logical_size: int


@dataclass(frozen=True)
class ChIdxEntry:
    source_sector: int
    offset: int
    target_sector: int
    target_span: int
    key: int
    flags: int
    list_ptr: int
    list_count: int
    reserved: int
    raw: bytes


def u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "big")


def u24(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 3], "big")


def u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "big")


class DB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._file = self.path.open("rb")
        self.data = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        self.headers = self._headers()
        self._views: dict[int, bytes] = {}

    def close(self) -> None:
        self.data.close()
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _headers(self) -> dict[int, Header]:
        result = {}
        for sector in range(len(self.data) // SECTOR_SIZE):
            pos = sector * SECTOR_SIZE
            if u24(self.data, pos) != sector:
                continue
            result[sector] = Header(sector, self.data[pos + 3], self.data[pos + 5],
                                    self.data[pos + 6], self.data[pos + 7] * SECTOR_SIZE)
        return result

    def logical(self, sector: int) -> bytes:
        if sector in self._views:
            return self._views[sector]
        header = self.headers[sector]
        raw = bytes(self.data[sector * SECTOR_SIZE:(sector + header.span) * SECTOR_SIZE])
        if header.compression == 2:
            payload = raw[:8] + zlib.decompress(raw[8:])
            if len(payload) != header.logical_size:
                raise ParseError(f"sector {sector:#x}: zlib logical extent mismatch")
        elif header.compression == 0:
            payload = raw[:header.logical_size]
        else:
            # Compression 0x01 is intentionally not decoded; owning 0x0E and
            # 0x0F blocks used by this parser are required to be readable.
            payload = raw[:header.logical_size]
        self._views[sector] = payload
        return payload


def pstr(data: bytes, ptr: int) -> str | None:
    if ptr <= 0 or ptr >= len(data):
        return None
    end = data.find(b"\0", ptr, min(len(data), ptr + 256))
    if end < 0 or end == ptr:
        return None
    raw = data[ptr:end]
    if not all(32 <= value < 127 for value in raw):
        return None
    return raw.decode("latin1")


def parse_object(db: DB, owner_sector: int, offset: int) -> dict:
    block = db.logical(owner_sector)
    raw = block[offset:offset + 24]
    if len(raw) != 24:
        raise ParseError(f"object {owner_sector:#x}:{offset:#x}: truncated 24-byte object")
    target, span = u24(raw, 16), raw[19]
    target_header = db.headers.get(target)
    if target_header is None or target_header.span != span or target_header.block_type != 0:
        raise ParseError(f"object {owner_sector:#x}:{offset:#x}: +0x10 is not a type-0x00 BL_ADDR")
    hlon, hlat = u32(raw, 0), u32(raw, 4)
    lon, lat = hlon / MULCOORD_SCALE - 30, hlat / MULCOORD_SCALE
    if not (-180 < lon < 180 and -90 < lat < 90):
        raise ParseError(f"object {owner_sector:#x}:{offset:#x}: implausible MULCOORD")
    e = u16(raw, 20)
    return {"offset": offset, "raw": raw.hex(), "hlon": hlon, "hlat": hlat,
            "lon": lon, "lat": lat, "A": u16(raw, 8), "B": u16(raw, 10),
            "C": u16(raw, 12), "D": u16(raw, 14), "target_sector": target,
            "target_span": span, "target_compression": target_header.compression,
            "E": e, "E_flags": e >> 14, "ptr": e & 0x3fff, "F": u16(raw, 22)}


def parse_brif(db: DB, sector: int, offset: int) -> dict:
    data = db.logical(sector)
    if offset < 8 or offset + 8 > len(data):
        raise ParseError(f"BRIF {sector:#x}:{offset:#x}: outside logical block")
    name_ptr, region_ptr, more = u16(data, offset), u16(data, offset + 4), u16(data, offset + 6)
    name, region = pstr(data, name_ptr), pstr(data, region_ptr)
    # Ownership is structural.  Text decoding is retained as metadata and is
    # deliberately not an ownership prerequisite (confirmed control blocks
    # contain non-decodable name/region pointers).
    if more + 6 > len(data):
        raise ParseError(f"BRIF {sector:#x}:{offset:#x}: MORE_INFO PTR out of bounds")
    object_ptr, field1, field2 = u16(data, more), u16(data, more + 2), u16(data, more + 4)
    count = field1 >> 8
    if count == 0 or object_ptr + count * 24 > len(data):
        raise ParseError(f"MORE_INFO {sector:#x}:{more:#x}: object array out of bounds")
    objects = [parse_object(db, sector, object_ptr + index * 24) for index in range(count)]
    return {"sector": sector, "brif_offset": offset, "name": name or "", "region": region or "",
            "place_bitemask": data[offset + 2], "language": data[offset + 3],
            "moreinfo_offset": more, "object_ptr": object_ptr, "object_count": count,
            "flag": field1 & 0xff, "field2": field2, "objects": objects}


def parse_road_list(db: DB, sector: int, list_ptr: int, count: int) -> list[dict]:
    data = db.logical(sector)
    header = db.headers[sector]
    if header.block_type != 0x0e:
        raise ParseError(f"sector {sector:#x}: expected type-0x0e")
    if list_ptr + count * 8 > len(data):
        raise ParseError(f"road list {sector:#x}:{list_ptr:#x}: out of bounds")
    return [parse_brif(db, sector, list_ptr + index * 8) for index in range(count)]


def parse_moscow_control(db: DB) -> list[dict]:
    return parse_road_list(db, 0x31A0, 0x0F20, 185)


def parse_ch_idx_entry(data: bytes, offset: int, source_sector: int = 0) -> ChIdxEntry:
    """Parse the confirmed 12-byte CH_IDX entry without validating its target."""
    raw = data[offset:offset + 12]
    if len(raw) != 12:
        raise ParseError(f"CH_IDX {source_sector:#x}:{offset:#x}: truncated 12-byte entry")
    return ChIdxEntry(source_sector, offset, u24(raw, 0), raw[3], raw[4], raw[5],
                      u16(raw, 6), u16(raw, 8), u16(raw, 10), raw)


def enumerate_ch_idx(db: DB, sector: int, list_ptr: int, list_count: int,
                     recursive: bool = True) -> list[ChIdxEntry]:
    """Enumerate a validated CH_IDX LIST, following child type-0x0F LISTs.

    The caller supplies the actual LIST pointer/count selected by its parent;
    this function never searches 12-byte alignments.
    """
    result: list[ChIdxEntry] = []
    visited: set[tuple[int, int, int]] = set()

    def walk(current_sector: int, ptr: int, count: int) -> None:
        key = current_sector, ptr, count
        if key in visited:
            return
        visited.add(key)
        header = db.headers.get(current_sector)
        if header is None or header.block_type != 0x0f:
            raise ParseError(f"CH_IDX target {current_sector:#x}: expected type-0x0f")
        data = db.logical(current_sector)
        if ptr < 8 or count == 0 or ptr + count * 12 > len(data):
            raise ParseError(f"CH_IDX LIST {current_sector:#x}:{ptr:#x}/{count}: out of bounds")
        for index in range(count):
            entry = parse_ch_idx_entry(data, ptr + index * 12, current_sector)
            target = db.headers.get(entry.target_sector)
            if target is None or target.span != entry.target_span:
                raise ParseError(f"CH_IDX {current_sector:#x}:{entry.offset:#x}: invalid BL_ADDR")
            result.append(entry)
            if recursive and target.block_type == 0x0f:
                walk(entry.target_sector, entry.list_ptr, entry.list_count)
    walk(sector, list_ptr, list_count)
    return result


def moscow_ch_idx(db: DB) -> list[ChIdxEntry]:
    return enumerate_ch_idx(db, 0x1B19, 0x4A10, 30)
