"""Independent readback parser for the observed fixed MP0 header.

This module deliberately does not import the production MP0 reader.  It checks
only the 64-byte header shape already observed in the three source files; it
does not assign meaning to the MP0 payload.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any


_HEADER_LENGTH = 64
_KNOWN_MARKER = b"(*$SIEMENS&^)"
_DATASET_CODE = re.compile(rb"(?:EU|SC|I)[0-9]{8}\.[0-9]{2}\Z")


class IndependentMp0Error(ValueError):
    """The file does not match the observed fixed MP0 header shape."""


def _text_field(header: bytes, begin: int, end: int, label: str) -> str:
    raw = header[begin:end]
    nul = raw.find(b"\x00")
    if nul <= 0:
        raise IndependentMp0Error(f"{label} is not NUL-terminated in its observed field")
    try:
        return raw[:nul].decode("ascii", "strict")
    except UnicodeDecodeError as exc:
        raise IndependentMp0Error(f"{label} is not ASCII") from exc


def inspect_mp0_independently(path: str | Path) -> dict[str, Any]:
    """Read a bounded header and hash the complete file in read-only mode."""
    source = Path(path)
    if source.suffix.upper() != ".MP0":
        raise IndependentMp0Error(f"expected an .MP0 file, got {source.name!r}")
    digest = hashlib.sha256()
    prefix = bytearray()
    size = 0
    with source.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            if len(prefix) < _HEADER_LENGTH:
                prefix.extend(block[:_HEADER_LENGTH - len(prefix)])
            digest.update(block)
            size += len(block)
    header = bytes(prefix)
    if len(header) != _HEADER_LENGTH:
        raise IndependentMp0Error(f"header is truncated: {len(header)} bytes; need {_HEADER_LENGTH}")
    if header[:len(_KNOWN_MARKER)] != _KNOWN_MARKER:
        raise IndependentMp0Error("fixed Siemens marker differs from the observed MP0 header")
    copyright_text = _text_field(header, 16, 32, "copyright")
    version_text = _text_field(header, 32, 48, "format version")
    code_bytes = header[48:64].split(b"\x00", 1)[0]
    if not _DATASET_CODE.fullmatch(code_bytes):
        raise IndependentMp0Error(f"dataset code has an unrecognized observed shape: {code_bytes!r}")
    return {
        "file_name": source.name,
        "file_size": size,
        "sha256": digest.hexdigest(),
        "magic": _KNOWN_MARKER.decode("ascii"),
        "copyright": copyright_text,
        "internal_format_version": version_text,
        "dataset_code": code_bytes.decode("ascii"),
        "header_hex": header.hex(" "),
        "claim_scope": "independent fixed-header readback only; MP0 payload semantics unknown",
    }
