"""Conservative DB_0 structural validator; byte signatures alone are not sufficient."""
from __future__ import annotations
import hashlib
import mmap
from pathlib import Path

SECTOR_SIZE = 512
MIN_RECORDS = 16
MAX_BLOCK_TYPE = 0x1F
VALID_COMPRESSION = {0, 1, 2}
START_SECTOR = 2


def db0_signature_hit(prefix: bytes) -> bool:
    """Weak candidate clue only: a short zero prefix is not DB_0 validation."""
    return bytes(prefix[:3]) == b"\x00\x00\x00"


def _read(data, offset, size):
    return data[offset:offset + size]


def validate_db0(path, offset=0, length=None, min_records=MIN_RECORDS):
    """Validate a complete 512-byte record chain in an mmap-backed source.

    The format has two leading 512-byte sectors before its first main-chain
    record. Every chain record must self-identify by uint24 BE sector ID,
    advance by a positive physical span, use observed block/compression
    ranges, and terminate exactly at the declared file boundary.
    """
    path = Path(path)
    try:
        with path.open("rb") as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                extent = len(mm) - offset if length is None else length
                if extent <= 0 or extent % SECTOR_SIZE:
                    sig=db0_signature_hit(_read(mm,offset,min(4096,max(0,len(mm)-offset)))) if 0<=offset<len(mm) else False
                    return {"valid": False, "status": "INVALID_SIZE_ALIGNMENT", "record_count": 0, "signature_hit":sig,"sha256":hashlib.sha256(_read(mm,offset,min(max(0,extent),max(0,len(mm)-offset)))).hexdigest(), "errors": ["size is not a positive multiple of 512"]}
                if offset < 0 or offset + extent > len(mm):
                    return {"valid": False, "status": "INVALID_EXTENT", "record_count": 0, "errors": ["declared extent is outside source file"]}
                if extent < (START_SECTOR + MIN_RECORDS) * SECTOR_SIZE:
                    return {"valid": False, "status": "TOO_SMALL", "record_count": 0,"signature_hit":db0_signature_hit(_read(mm,offset,min(4096,extent))),"sha256":hashlib.sha256(_read(mm,offset,extent)).hexdigest(), "errors": ["too few sectors for a DB_0 record chain"]}
                pos = START_SECTOR * SECTOR_SIZE
                records = []
                errors = []
                file_digest = hashlib.sha256()
                file_digest.update(_read(mm, offset, START_SECTOR * SECTOR_SIZE))
                while pos < extent:
                    if pos + 8 > extent:
                        errors.append(f"truncated header at relative offset 0x{pos:x}")
                        break
                    header = _read(mm, offset + pos, 8)
                    sector = int.from_bytes(header[0:3], "big")
                    span, alignment, block_type, compression, logical_units = header[3:8]
                    physical_sector = pos // SECTOR_SIZE
                    if sector > 0xFFFFFF or sector != physical_sector:
                        errors.append(f"sector ID {sector} does not match physical sector {physical_sector}")
                        break
                    if span <= 0:
                        errors.append(f"zero span at sector {sector}")
                        break
                    if block_type > MAX_BLOCK_TYPE:
                        errors.append(f"block type {block_type} is outside the observed range 0..{MAX_BLOCK_TYPE}")
                        break
                    if compression not in VALID_COMPRESSION:
                        errors.append(f"compression code {compression} is outside the supported observed set")
                        break
                    record_size = span * SECTOR_SIZE
                    end = pos + record_size
                    if end > extent:
                        errors.append(f"record at sector {sector} extends beyond the file")
                        break
                    records.append({"sector": sector, "offset": pos, "span": span,
                                    "alignment": alignment, "block_type": block_type,
                                    "compression": compression, "logical_units": logical_units,
                                    "physical_size": record_size, "header_hex": bytes(header).hex(),
                                    "record_sha256": hashlib.sha256(_read(mm, offset + pos, record_size)).hexdigest()})
                    file_digest.update(_read(mm, offset + pos, record_size))
                    if end < extent:
                        if end % SECTOR_SIZE:
                            errors.append(f"next record is not sector-aligned after {sector}")
                            break
                        # Next loop checks both the next sector ID and header.
                        next_header = _read(mm, offset + end, 4)
                        expected_next = end // SECTOR_SIZE
                        if len(next_header) != 4 or int.from_bytes(next_header[:3], "big") != expected_next:
                            errors.append(f"record-chain discontinuity after sector {sector}; expected sector {expected_next}")
                            break
                    pos = end
                if len(records) < min_records:
                    errors.append(f"only {len(records)} consecutive records; at least {min_records} required")
                if pos != extent:
                    errors.append(f"record chain ends at 0x{pos:x}, file extent ends at 0x{extent:x}")
                valid = not errors
                return {"valid": valid, "status": "VALIDATED_DB_0" if valid else "REJECTED_DB_0_CANDIDATE",
                        "record_count": len(records), "size": extent, "start_sector": START_SECTOR,
                        "end_sector": extent // SECTOR_SIZE,
                        "types": sorted({r["block_type"] for r in records}),
                        "compression_codes": sorted({r["compression"] for r in records}),
                        "sha256": file_digest.hexdigest(),
                        "records": records if valid else [], "errors": errors,
                        "signature_hit": db0_signature_hit(_read(mm, offset, min(4096, extent)))}
    except (OSError, ValueError, BufferError) as exc:
        return {"valid": False, "status": "READ_ERROR", "record_count": 0, "errors": [str(exc)]}
