"""Read-only reader for the confirmed 512-byte DB_0 record chain."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import mmap
from pathlib import Path
import zlib

SECTOR_SIZE = 512
FIRST_RECORD_SECTOR = 2
_LOGICAL_CACHE_LIMIT = 128


class DB0FormatError(ValueError):
    """The physical record chain or a confirmed payload invariant is invalid."""


class UnsupportedCompressionError(DB0FormatError):
    """The requested logical view uses a compression method not yet decoded."""


def sha256_file(path: Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


class DB0Reader:
    """Walk validated BL_HEAD records without writing to the source image."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._file = self.path.open("rb")
        try:
            self._size = self.path.stat().st_size
            if self._size == 0 or self._size % SECTOR_SIZE:
                raise DB0FormatError("DB_0 size is not a nonzero multiple of 512 bytes")
            self._sector_count = self._size // SECTOR_SIZE
            self._data = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
            self.records = self._read_chain()
            self.by_sector = {row["sector"]: row for row in self.records}
            self._logical_cache: OrderedDict[int, bytes] = OrderedDict()
        except Exception:
            data = getattr(self, "_data", None)
            if data is not None and not data.closed:
                data.close()
            self._file.close()
            raise

    def __enter__(self) -> "DB0Reader":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        data = getattr(self, "_data", None)
        if data is not None and not data.closed:
            data.close()
        if not self._file.closed:
            self._file.close()

    @staticmethod
    def _u24be(data: mmap.mmap, offset: int) -> int:
        return int.from_bytes(data[offset:offset + 3], "big")

    def _read_chain(self) -> list[dict[str, int]]:
        records: list[dict[str, int]] = []
        sector = FIRST_RECORD_SECTOR
        while sector < self._sector_count:
            offset = sector * SECTOR_SIZE
            if offset + 8 > self._size:
                raise DB0FormatError(f"Truncated BL_HEAD at sector 0x{sector:06X}")
            stored_sector = self._u24be(self._data, offset)
            span = self._data[offset + 3]
            if stored_sector != sector:
                raise DB0FormatError(
                    f"BL_HEAD sector mismatch at 0x{sector:06X}: found 0x{stored_sector:06X}"
                )
            if span < 1 or sector + span > self._sector_count:
                raise DB0FormatError(f"Invalid physical span {span} at sector 0x{sector:06X}")

            records.append({
                "sector": sector,
                "span": span,
                "block_type": self._data[offset + 5],
                "compression": self._data[offset + 6],
                "logical_size": self._data[offset + 7] * SECTOR_SIZE,
            })
            sector += span

        if sector != self._sector_count:
            raise DB0FormatError("Validated record chain does not end at the image boundary")
        return records

    def _record(self, sector: int) -> dict[str, int]:
        try:
            return self.by_sector[sector]
        except KeyError as exc:
            raise DB0FormatError(f"Sector 0x{sector:06X} is not a record start in the validated chain") from exc

    def stored(self, sector: int) -> bytes:
        row = self._record(sector)
        start = sector * SECTOR_SIZE
        end = start + row["span"] * SECTOR_SIZE
        return bytes(self._data[start:end])

    def logical(self, sector: int) -> bytes:
        row = self._record(sector)
        cached = self._logical_cache.get(sector)
        if cached is not None:
            self._logical_cache.move_to_end(sector)
            return cached

        raw = self.stored(sector)
        logical_size = row["logical_size"]
        if logical_size < 8:
            raise DB0FormatError(f"Invalid logical extent at sector 0x{sector:06X}")
        if row["compression"] == 0:
            if logical_size > len(raw):
                raise DB0FormatError(f"Uncompressed extent exceeds stored record at 0x{sector:06X}")
            result = raw[:logical_size]
        elif row["compression"] == 2:
            try:
                result = raw[:8] + zlib.decompress(raw[8:])
            except zlib.error as exc:
                raise DB0FormatError(f"Invalid zlib payload at sector 0x{sector:06X}: {exc}") from exc
            if len(result) != logical_size:
                raise DB0FormatError(
                    f"Zlib extent mismatch at sector 0x{sector:06X}: "
                    f"expected {logical_size}, got {len(result)}"
                )
        else:
            raise UnsupportedCompressionError(
                f"Compression 0x{row['compression']:02X} at sector 0x{sector:06X} has no confirmed decoder"
            )

        self._logical_cache[sector] = result
        self._logical_cache.move_to_end(sector)
        while len(self._logical_cache) > _LOGICAL_CACHE_LIMIT:
            self._logical_cache.popitem(last=False)
        return result

    def logical_or_stored(self, sector: int) -> tuple[bytes, str]:
        row = self._record(sector)
        if row["compression"] in (0, 2):
            return self.logical(sector), "logical"
        return self.stored(sector), f"stored bytes; compression 0x{row['compression']:02X} is undecoded"
