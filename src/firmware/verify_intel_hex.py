"""Second implementation used to independently re-read Intel HEX files."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from src.firmware.intel_hex import IntelHexError


def verify_file_independently(path: str | Path, *, max_bytes: int = 16 * 1024 * 1024) -> dict[str, Any]:
    """Reconstruct the address image with an independent line/field decoder."""
    raw_file = Path(path).read_bytes()
    if len(raw_file) > max_bytes:
        raise IntelHexError(f"input exceeds independent read limit of {max_bytes} bytes")
    address_bytes: dict[int, int] = {}
    type_counts: dict[str, int] = {}
    base = 0
    eof = False
    input_records = data_bytes = 0
    for line_number, raw_line in enumerate(raw_file.splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        if eof:
            raise IntelHexError(f"independent verifier: trailing record at line {line_number}")
        if line[:1] != b":" or (len(line) - 1) % 2:
            raise IntelHexError(f"independent verifier: malformed record at line {line_number}")
        try:
            fields = [int(line[i:i + 2], 16) for i in range(1, len(line), 2)]
        except ValueError as exc:
            raise IntelHexError(f"independent verifier: non-hex field at line {line_number}") from exc
        if len(fields) < 5 or (sum(fields) & 255) != 0:
            raise IntelHexError(f"independent verifier: length/checksum failure at line {line_number}")
        length = fields[0]
        if len(fields) != length + 5:
            raise IntelHexError(f"independent verifier: byte-count failure at line {line_number}")
        offset = (fields[1] << 8) | fields[2]
        kind = fields[3]
        payload = bytes(fields[4:-1])
        input_records += 1
        type_counts[f"{kind:02X}"] = type_counts.get(f"{kind:02X}", 0) + 1
        if kind == 0:
            if offset + length > 0x10000:
                raise IntelHexError(f"independent verifier: address-window overflow at line {line_number}")
            start = base + offset
            for index, value in enumerate(payload):
                key = start + index
                old = address_bytes.get(key)
                if old is not None and old != value:
                    raise IntelHexError(f"independent verifier: conflicting overlap at 0x{key:08X}")
                address_bytes[key] = value
            data_bytes += length
        elif kind == 1:
            if length != 0 or offset != 0:
                raise IntelHexError("independent verifier: invalid EOF fields")
            eof = True
        elif kind == 2:
            if length != 2 or offset != 0:
                raise IntelHexError("independent verifier: invalid segment-base fields")
            base = ((payload[0] << 8) | payload[1]) << 4
        elif kind == 4:
            if length != 2 or offset != 0:
                raise IntelHexError("independent verifier: invalid linear-base fields")
            base = ((payload[0] << 8) | payload[1]) << 16
        elif kind == 3:
            if length != 4 or offset != 0:
                raise IntelHexError("independent verifier: invalid segment start fields")
        elif kind == 5:
            if length != 4 or offset != 0:
                raise IntelHexError("independent verifier: invalid linear start fields")
        else:
            raise IntelHexError(f"independent verifier: unsupported record type {kind}")
    if not eof:
        raise IntelHexError("independent verifier: missing EOF")
    ordered = sorted(address_bytes.items())
    ranges: list[list[int]] = []
    digest = hashlib.sha256()
    for address, value in ordered:
        digest.update(address.to_bytes(4, "big"))
        digest.update(bytes([value]))
        if not ranges or ranges[-1][1] != address:
            ranges.append([address, address + 1])
        else:
            ranges[-1][1] = address + 1
    return {"record_count": input_records, "record_type_counts": dict(sorted(type_counts.items())),
            "data_record_bytes": data_bytes, "unique_image_bytes": len(address_bytes),
            "address_range_count": len(ranges), "address_ranges_preview": ranges[:256],
            "address_ranges_truncated": len(ranges) > 256,
            "address_image_sha256": digest.hexdigest(), "eof_seen": eof}
