#!/usr/bin/env python3
"""Read-only, bounded ROMHDR/TOC candidate validation for Siemens NK.BIN.

This is a format probe, not an extractor. The standard-parser attempt is
preserved separately in evidence/extractor_parse_only_no_override.log.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import struct
from pathlib import Path


ROMHDR_SIZE = struct.calcsize("<17I2HI2I")
TOCENTRY_SIZE = 8 * 4
KERNEL_RANGE = (0x80000000, 0xC0000000)
TARGETS = (b"NavigationRem.dll", b"nmicore_ce.dll")


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def parse_romhdr(data: bytes, offset: int) -> dict | None:
    if offset < 0 or offset + ROMHDR_SIZE > len(data):
        return None
    f = struct.unpack_from("<17I2HI2I", data, offset)
    names = (
        "dllfirst", "dlllast", "physfirst", "physlast", "nummods",
        "ulRAMStart", "ulRAMFree", "ulRAMEnd", "ulCopyEntries",
        "ulCopyOffset", "ulProfileLen", "ulProfileOffset", "numfiles",
        "ulKernelFlags", "ulFSRamPercent", "ulDrivglobStart",
        "ulDrivglobLen", "usCPUType", "usMiscFlags", "pExtensions",
        "ulTrackingStart", "ulTrackingLen",
    )
    h = dict(zip(names, f))
    h["offset"] = offset
    h["bounds_valid"] = (
        h["dllfirst"] <= h["dlllast"]
        and h["physfirst"] <= h["physlast"]
        and h["nummods"] <= 10000
        and h["numfiles"] <= 50000
    )
    h["ce_reasonable_counts"] = 1 <= h["nummods"] <= 4096 and h["numfiles"] <= 50000
    return h


def ascii_z(data: bytes, offset: int, limit: int = 256) -> str:
    if not 0 <= offset < len(data):
        return ""
    raw = data[offset:min(len(data), offset + limit)].split(b"\0", 1)[0]
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        return ""


def check_toc(data: bytes, header_offset: int, load_offset: int, hdr: dict) -> dict:
    begin = header_offset + ROMHDR_SIZE
    end = begin + hdr["nummods"] * TOCENTRY_SIZE
    result = {"start": begin, "end_exclusive": end,
              "bounds_inside_file": 0 <= begin <= end <= len(data),
              "printable_names_checked": 0, "nk_exe_seen_in_first_32": False,
              "sample_names": []}
    if not result["bounds_inside_file"]:
        return result
    all_printable = True
    for i in range(min(hdr["nummods"], 32)):
        off = begin + i * TOCENTRY_SIZE
        attrs, ft_lo, ft_hi, size, name_va, e32_va, o32_va, load_va = struct.unpack_from(
            "<8I", data, off)
        name_off = name_va - load_offset
        name = ascii_z(data, name_off)
        printable = bool(name) and all(0x20 <= ord(c) <= 0x7E for c in name)
        all_printable &= printable
        result["printable_names_checked"] += int(printable)
        result["nk_exe_seen_in_first_32"] |= name.lower() == "nk.exe"
        if i < 8:
            result["sample_names"].append({
                "index": i, "name": name, "entry_offset": off,
                "attrs": attrs, "file_size": size, "name_va": name_va,
                "e32_va": e32_va, "o32_va": o32_va, "load_va": load_va,
                "name_offset": name_off,
            })
    result["all_first_names_printable"] = all_printable
    return result


def ecec_candidates(data: bytes) -> list[dict]:
    out = []
    pos = 0
    while True:
        pos = data.find(b"ECEC", pos)
        if pos < 0:
            break
        item = {"offset": pos, "offset_mod_4": pos % 4}
        if pos + 12 <= len(data):
            ptoc = u32(data, pos + 4)
            romhdr_field = u32(data, pos + 8)
            item.update({"ptoc_va": ptoc, "romhdr_offset_field": romhdr_field,
                         "ptoc_in_ce_kernel_range": KERNEL_RANGE[0] <= ptoc < KERNEL_RANGE[1]})
            candidates = [("as_stored", max(pos - 0x40, 0) + romhdr_field)]
            if romhdr_field >= len(data):
                # Test the standard ECEC+4/base derivations only as explicit
                # alternatives; do not silently reinterpret the +8 value.
                candidates.extend(("offset_field_absent", ptoc - base)
                                  for base in (0, 0x80000000, ptoc & 0xFF000000,
                                               ptoc & 0xF0000000))
            checks = []
            seen = set()
            for interpretation, header_offset in candidates:
                if header_offset in seen:
                    continue
                seen.add(header_offset)
                hdr = parse_romhdr(data, header_offset)
                check = {
                    "interpretation": interpretation,
                    "romhdr_offset": header_offset,
                    "romhdr_bounds_inside_file": 0 <= header_offset <= len(data) - ROMHDR_SIZE,
                    "romhdr": hdr,
                }
                if hdr and hdr["bounds_valid"] and hdr["ce_reasonable_counts"]:
                    check["toc"] = check_toc(data, header_offset, ptoc - header_offset, hdr)
                checks.append(check)
            item["romhdr_candidates"] = checks
        out.append(item)
        pos += 4
    return out


def structural_scan(data: bytes) -> dict:
    tested = 0
    bounded_candidates = []
    plausible = []
    for off in range(0, len(data) - ROMHDR_SIZE + 1, 4):
        physfirst = u32(data, off + 8)
        physlast = u32(data, off + 12)
        if not (KERNEL_RANGE[0] <= physfirst < physlast <= physfirst + 0x10000000):
            continue
        hdr = parse_romhdr(data, off)
        if not hdr or not hdr["bounds_valid"] or not hdr["ce_reasonable_counts"]:
            continue
        tested += 1
        toc = check_toc(data, off, physfirst, hdr)
        bounded_candidates.append({"romhdr": hdr, "toc": toc})
        if toc["all_first_names_printable"] and toc["nk_exe_seen_in_first_32"]:
            plausible.append({"romhdr": hdr, "toc": toc})
    return {"bounded_header_candidates": tested,
            "candidates": bounded_candidates,
            "validated_candidates": plausible}


def inspect(path: Path) -> dict:
    data = path.read_bytes()
    ce_marker = data.find(b"CE00FF\n")
    ce00ff = None
    if ce_marker >= 0 and ce_marker + 15 <= len(data):
        start_candidate = u32(data, ce_marker + 7)
        length_candidate = u32(data, ce_marker + 11)
        ce00ff = {
            "offset": ce_marker,
            "signature_bytes": data[ce_marker:ce_marker + 7].hex(" "),
            "bytes_after_signature_hex": data[ce_marker + 7:ce_marker + 15].hex(" "),
            "le_start_candidate": start_candidate,
            "le_length_candidate": length_candidate,
            "length_within_image": length_candidate <= len(data) - ce_marker,
        }

    names = []
    for target in TARGETS:
        positions = []
        pos = 0
        while True:
            pos = data.find(target, pos)
            if pos < 0:
                break
            lo, hi = max(0, pos - 24), min(len(data), pos + len(target) + 24)
            positions.append({"offset": pos, "nul_terminated": data[pos + len(target):pos + len(target) + 1] == b"\0",
                              "prefix_hex": data[lo:pos].hex(" "),
                              "suffix_hex": data[pos + len(target):hi].hex(" ")})
            pos += len(target)
        names.append({"name": target.decode("ascii"), "hits": positions})

    b000ff = data[:7] == b"B000FF\n"
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(path.resolve()),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "first_64_hex": data[:64].hex(" "),
        "first_64_ascii": data[:64].decode("ascii", "replace"),
        "checks": {
            "standard_b000ff_magic_at_offset_0": b000ff,
            "ce1_ecec_free_structural_romhdr": structural_scan(data),
            "ce00ff_marker_candidate": ce00ff,
            "raw_ecec_candidates": ecec_candidates(data),
        },
        "target_name_strings": names,
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path)
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args()
    report = inspect(args.image)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {
        "size": report["size"], "sha256": report["sha256"],
        "checks": report["checks"], "target_name_strings": report["target_name_strings"],
        "json": str(args.json.resolve()),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
