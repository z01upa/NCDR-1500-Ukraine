"""Strict, read-only Intel HEX record reader for firmware research."""

from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
from typing import BinaryIO, Any


class IntelHexError(ValueError):
    """Malformed or unsupported Intel HEX input."""


def _record(line: bytes, line_number: int) -> tuple[int, int, int, bytes]:
    raw = line.strip()
    if not raw.startswith(b":"):
        raise IntelHexError(f"line {line_number}: missing ':' record marker")
    try:
        payload = bytes.fromhex(raw[1:].decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise IntelHexError(f"line {line_number}: record is not even-length ASCII hex") from exc
    if len(payload) < 5:
        raise IntelHexError(f"line {line_number}: record is shorter than the fixed fields")
    count, address, record_type = payload[0], int.from_bytes(payload[1:3], "big"), payload[3]
    if len(payload) != count + 5:
        raise IntelHexError(f"line {line_number}: byte count {count} disagrees with record length {len(payload)}")
    if sum(payload) & 0xFF:
        raise IntelHexError(f"line {line_number}: checksum mismatch")
    return count, address, record_type, payload[4:-1]


def summarize_stream(stream: BinaryIO, *, max_bytes: int = 16 * 1024 * 1024,
                     max_records: int = 2_000_000) -> dict[str, Any]:
    """Validate standard record lengths/checksums and summarize the address image.

    The full decoded image is never written. Overlapping identical data bytes are
    counted and accepted; conflicting overlaps are rejected.
    """
    memory: dict[int, int] = {}
    counts: Counter[str] = Counter()
    byte_count = input_bytes = record_count = duplicate_bytes = 0
    base = 0
    eof = False
    start_records: list[dict[str, int]] = []
    for line_number, line in enumerate(stream, start=1):
        input_bytes += len(line)
        if input_bytes > max_bytes:
            raise IntelHexError(f"input exceeds bounded read limit of {max_bytes} bytes")
        if not line.strip():
            continue
        if eof:
            raise IntelHexError(f"line {line_number}: data appears after EOF record")
        count, address, record_type, data = _record(line, line_number)
        record_count += 1
        if record_count > max_records:
            raise IntelHexError(f"record count exceeds bounded limit of {max_records}")
        counts[f"{record_type:02X}"] += 1
        if record_type == 0x00:
            if address + count > 0x10000:
                raise IntelHexError(f"line {line_number}: data record crosses a 64 KiB address window")
            absolute = base + address
            if absolute + count > 0x1_0000_0000:
                raise IntelHexError(f"line {line_number}: absolute data address exceeds 32-bit space")
            for offset, value in enumerate(data):
                target = absolute + offset
                previous = memory.get(target)
                if previous is not None:
                    if previous != value:
                        raise IntelHexError(f"line {line_number}: conflicting overlapping byte at 0x{target:08X}")
                    duplicate_bytes += 1
                else:
                    memory[target] = value
            byte_count += count
        elif record_type == 0x01:
            if count or address:
                raise IntelHexError(f"line {line_number}: EOF record must have zero address and data length")
            eof = True
        elif record_type == 0x02:
            if count != 2 or address:
                raise IntelHexError(f"line {line_number}: extended-segment record requires address 0 and two data bytes")
            base = int.from_bytes(data, "big") << 4
        elif record_type == 0x04:
            if count != 2 or address:
                raise IntelHexError(f"line {line_number}: extended-linear record requires address 0 and two data bytes")
            base = int.from_bytes(data, "big") << 16
        elif record_type == 0x03:
            if count != 4 or address:
                raise IntelHexError(f"line {line_number}: start-segment record requires address 0 and four data bytes")
            start_records.append({"type": record_type, "cs": int.from_bytes(data[:2], "big"),
                                  "ip": int.from_bytes(data[2:], "big")})
        elif record_type == 0x05:
            if count != 4 or address:
                raise IntelHexError(f"line {line_number}: start-linear record requires address 0 and four data bytes")
            start_records.append({"type": record_type, "address": int.from_bytes(data, "big")})
        else:
            raise IntelHexError(f"line {line_number}: unsupported record type 0x{record_type:02X}")
    if not eof:
        raise IntelHexError("missing EOF record")

    addresses = sorted(memory)
    ranges: list[list[int]] = []
    for address in addresses:
        if not ranges or address != ranges[-1][1]:
            ranges.append([address, address + 1])
        else:
            ranges[-1][1] += 1
    image_digest = hashlib.sha256()
    for address in addresses:
        image_digest.update(address.to_bytes(4, "big"))
        image_digest.update(bytes((memory[address],)))
    return {
        "format": "Intel HEX record syntax; payload semantics unknown",
        "record_count": record_count, "record_type_counts": dict(sorted(counts.items())),
        "data_record_bytes": byte_count, "unique_image_bytes": len(memory),
        "identical_duplicate_bytes": duplicate_bytes, "eof_seen": eof,
        "address_range_count": len(ranges),
        "address_ranges_preview": ranges[:256],
        "address_ranges_truncated": len(ranges) > 256,
        "start_address_records": start_records,
        "address_image_sha256": image_digest.hexdigest(),
        "checksum_policy": "every record sum modulo 256 equals zero",
        "unknowns": ["firmware instruction semantics", "device-specific memory map", "hardware compatibility"],
    }


def summarize_file(path: str | Path, *, max_bytes: int = 16 * 1024 * 1024) -> dict[str, Any]:
    source = Path(path)
    if source.stat().st_size > max_bytes:
        raise IntelHexError(f"input size exceeds bounded read limit of {max_bytes} bytes")
    with source.open("rb") as stream:
        return summarize_stream(stream, max_bytes=max_bytes)
