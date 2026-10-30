"""Conservative reader for the fixed header of NCDx ``*Z.MP0`` files.

Only fields that were independently visible in the three included 2010
regional files are exposed. This module does not decode map records.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import re


MAGIC = b"(*$SIEMENS&^)"
COPYRIGHT_OFFSET = 16
FORMAT_VERSION_OFFSET = 32
DATASET_CODE_OFFSET = 48
FIELD_WIDTH = 16
DATASET_CODE = re.compile(rb"(?:EU|SC|I)[0-9]{8}\.[0-9]{2}\Z")


class NcdxHeaderError(ValueError):
    """Raised when a file does not match the observed MP0 header shape."""


@dataclass(frozen=True)
class Mp0Header:
    file_name: str
    file_size: int
    sha256: str
    magic: str
    copyright: str
    internal_format_version: str
    dataset_code: str
    header_hex: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _nul_terminated_ascii(data: bytes, offset: int, width: int, field: str) -> str:
    field_bytes = data[offset : offset + width]
    terminator = field_bytes.find(b"\0")
    if terminator < 1:
        raise NcdxHeaderError(f"{field} is not NUL-terminated within {width} bytes")
    try:
        return field_bytes[:terminator].decode("ascii")
    except UnicodeDecodeError as exc:
        raise NcdxHeaderError(f"{field} is not ASCII") from exc


def parse_mp0_header(data: bytes) -> tuple[str, str, str, str]:
    """Parse the observed fixed fields from the first 65 bytes of an MP0."""
    minimum = DATASET_CODE_OFFSET + FIELD_WIDTH
    if len(data) < minimum:
        raise NcdxHeaderError(f"header is truncated: {len(data)} bytes; need {minimum}")
    if data[: len(MAGIC)] != MAGIC:
        raise NcdxHeaderError("unrecognized Siemens MP0 marker at offset 0")
    copyright_text = _nul_terminated_ascii(data, COPYRIGHT_OFFSET, FIELD_WIDTH, "copyright")
    format_version = _nul_terminated_ascii(data, FORMAT_VERSION_OFFSET, FIELD_WIDTH, "format version")
    dataset_bytes = data[DATASET_CODE_OFFSET : DATASET_CODE_OFFSET + FIELD_WIDTH]
    terminator = dataset_bytes.find(b"\0")
    if terminator < 1:
        raise NcdxHeaderError("dataset code is not NUL-terminated within 16 bytes")
    code = dataset_bytes[:terminator]
    if not DATASET_CODE.fullmatch(code):
        raise NcdxHeaderError(f"dataset code has an unrecognized shape: {code!r}")
    return MAGIC.decode("ascii"), copyright_text, format_version, code.decode("ascii")


def read_mp0_header(path: str | Path, expected_sha256: str | None = None) -> Mp0Header:
    """Read a file in binary read-only mode, hash it, and parse its MP0 header."""
    source = Path(path)
    if source.suffix.upper() != ".MP0":
        raise NcdxHeaderError(f"expected an .MP0 file, got {source.name!r}")

    digest = hashlib.sha256()
    size = 0
    prefix = bytearray()
    with source.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            if len(prefix) < DATASET_CODE_OFFSET + FIELD_WIDTH:
                prefix.extend(chunk[: DATASET_CODE_OFFSET + FIELD_WIDTH - len(prefix)])
            digest.update(chunk)
            size += len(chunk)

    sha256 = digest.hexdigest()
    if expected_sha256 and sha256.lower() != expected_sha256.lower():
        raise NcdxHeaderError(f"SHA-256 mismatch: expected {expected_sha256}, got {sha256}")

    magic, copyright_text, version, dataset_code = parse_mp0_header(bytes(prefix))
    return Mp0Header(
        file_name=source.name,
        file_size=size,
        sha256=sha256,
        magic=magic,
        copyright=copyright_text,
        internal_format_version=version,
        dataset_code=dataset_code,
        header_hex=bytes(prefix[:64]).hex(" "),
    )
