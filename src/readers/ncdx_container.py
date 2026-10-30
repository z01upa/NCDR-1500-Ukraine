"""Bounded reader for the observed NCDx ``zip\x01`` block container.

The reader validates the block table and each independent zlib stream without
assigning semantics to the decoded payload.  It accepts a seekable binary
stream so production callers can keep the source opened read-only.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import struct
from typing import BinaryIO, Iterator
import zlib


MAGIC = b"zip\x01"
HEADER_BYTES = 16
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_LOGICAL_BYTES = 256 * 1024 * 1024
MAX_BLOCK_BYTES = 64 * 1024
MAX_COMPRESSED_BLOCK_BYTES = 1024 * 1024
MAX_BLOCKS = 1_000_000


class NcdxContainerError(ValueError):
    """Raised when an NCDx block container violates a validated invariant."""


@dataclass(frozen=True)
class ContainerIndex:
    block_size_bytes: int
    logical_size_bytes: int
    opaque_header_u32_le: int
    physical_size_bytes: int
    offsets: tuple[int, ...]

    @property
    def block_count(self) -> int:
        return len(self.offsets) - 1


def read_index(stream: BinaryIO, *, max_file_bytes: int = MAX_FILE_BYTES,
               max_logical_bytes: int = MAX_LOGICAL_BYTES,
               max_blocks: int = MAX_BLOCKS) -> ContainerIndex:
    """Validate the fixed header and complete absolute-offset table."""
    if not stream.seekable():
        raise NcdxContainerError("container input must be seekable")
    stream.seek(0, io.SEEK_END)
    physical_size = stream.tell()
    stream.seek(0)
    if physical_size < HEADER_BYTES or physical_size > max_file_bytes:
        raise NcdxContainerError(
            f"physical file size is outside the accepted range: {physical_size}"
        )
    header = stream.read(HEADER_BYTES)
    if len(header) != HEADER_BYTES or header[:4] != MAGIC:
        raise NcdxContainerError("container does not begin with the observed zip\\x01 marker")
    block_size, logical_size, opaque_word = struct.unpack_from("<III", header, 4)
    if not 0 < block_size <= MAX_BLOCK_BYTES:
        raise NcdxContainerError(f"declared block size is outside the accepted range: {block_size}")
    if not 0 < logical_size <= max_logical_bytes:
        raise NcdxContainerError(f"declared logical size is outside the accepted range: {logical_size}")
    count = (logical_size + block_size - 1) // block_size
    if count > max_blocks:
        raise NcdxContainerError(f"declared block count exceeds the accepted limit: {count}")
    table_end = HEADER_BYTES + 4 * (count + 1)
    if table_end > physical_size:
        raise NcdxContainerError("absolute-offset table extends beyond the physical file")
    encoded_offsets = stream.read(4 * (count + 1))
    if len(encoded_offsets) != 4 * (count + 1):
        raise NcdxContainerError("absolute-offset table is truncated")
    offsets = struct.unpack(f"<{count + 1}I", encoded_offsets)
    if offsets[0] != table_end or offsets[-1] != physical_size:
        raise NcdxContainerError("absolute-offset table does not exactly span the payload")
    previous = offsets[0]
    for offset in offsets[1:]:
        compressed_bytes = offset - previous
        if compressed_bytes <= 0 or compressed_bytes > MAX_COMPRESSED_BLOCK_BYTES:
            raise NcdxContainerError("compressed block has an invalid size")
        previous = offset
    return ContainerIndex(block_size, logical_size, opaque_word, physical_size, tuple(offsets))


def iter_decoded_blocks(stream: BinaryIO, index: ContainerIndex) -> Iterator[tuple[int, bytes]]:
    """Yield ``(logical_offset, decoded_block)`` with a strict output bound."""
    logical_offset = 0
    for block_number, (start, end) in enumerate(zip(index.offsets, index.offsets[1:])):
        expected = min(index.block_size_bytes, index.logical_size_bytes - logical_offset)
        stream.seek(start)
        compressed = stream.read(end - start)
        if len(compressed) != end - start:
            raise NcdxContainerError(f"compressed block {block_number} is truncated")
        decoder = zlib.decompressobj()
        try:
            decoded = decoder.decompress(compressed, expected + 1)
        except zlib.error as exc:
            raise NcdxContainerError(f"compressed block {block_number} is not a valid zlib stream") from exc
        if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
                or len(decoded) != expected):
            raise NcdxContainerError(f"compressed block {block_number} violates its declared output size")
        yield logical_offset, decoded
        logical_offset += len(decoded)
    if logical_offset != index.logical_size_bytes:
        raise NcdxContainerError("decoded blocks do not equal the declared logical size")


def decode_bytes(encoded: bytes, *, max_file_bytes: int = MAX_FILE_BYTES,
                 max_logical_bytes: int = MAX_LOGICAL_BYTES) -> tuple[ContainerIndex, bytes]:
    """Decode a bounded in-memory container; useful for fixtures and copies."""
    stream = io.BytesIO(encoded)
    index = read_index(stream, max_file_bytes=max_file_bytes, max_logical_bytes=max_logical_bytes)
    output = bytearray()
    for _offset, block in iter_decoded_blocks(stream, index):
        output.extend(block)
    return index, bytes(output)


def decode_to_stream(stream: BinaryIO, output: BinaryIO, *,
                     max_file_bytes: int = MAX_FILE_BYTES,
                     max_logical_bytes: int = MAX_LOGICAL_BYTES) -> dict[str, object]:
    """Stream decoded bytes to a caller-owned destination and return a digest."""
    index = read_index(stream, max_file_bytes=max_file_bytes, max_logical_bytes=max_logical_bytes)
    digest = hashlib.sha256()
    written = 0
    for _offset, block in iter_decoded_blocks(stream, index):
        output.write(block)
        digest.update(block)
        written += len(block)
    if written != index.logical_size_bytes:
        raise NcdxContainerError("decoded output length does not match the container header")
    return {"index": index, "decoded_size_bytes": written, "decoded_sha256": digest.hexdigest()}
