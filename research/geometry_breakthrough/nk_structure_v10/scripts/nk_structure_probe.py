#!/usr/bin/env python3
"""Read-only NK.BIN structure, XIP mapping, and 74-name-cluster probe.

This is deliberately an auditor, not a ROM extractor. It never writes to an
input image and never treats an address/string hit as executable code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import zlib
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


ROMHDR_FMT = "<17I2HI2I"
ROMHDR_SIZE = struct.calcsize(ROMHDR_FMT)
TOC_FMT = "<8I"
TOC_SIZE = struct.calcsize(TOC_FMT)
KERNEL_LO, KERNEL_HI = 0x80000000, 0xC0000000
MAX_MODULES = 4096
TARGET_NAMES = {"NavigationRem.dll", "nmicore_ce.dll"}


@dataclass(frozen=True)
class Segment:
    va: int
    size: int
    file_offset: int
    checksum: int = 0


class AddressMap:
    """Sparse VA-to-file map. Physical record order is irrelevant."""

    def __init__(self, data: bytes, segments: list[Segment]):
        self.data = data
        self.segments = segments

    def offset(self, va: int, size: int = 1) -> int | None:
        if size < 0:
            return None
        hits = [s for s in self.segments if s.va <= va and va + size <= s.va + s.size]
        if len(hits) != 1:
            return None
        s = hits[0]
        return s.file_offset + va - s.va

    def read(self, va: int, size: int) -> bytes | None:
        if size < 0:
            return None
        out = bytearray()
        cur = va
        left = size
        while left:
            hits = [s for s in self.segments if s.va <= cur < s.va + s.size]
            if len(hits) != 1:
                return None
            s = hits[0]
            take = min(left, s.va + s.size - cur)
            pos = s.file_offset + cur - s.va
            if pos < 0 or pos + take > len(self.data):
                return None
            out.extend(self.data[pos:pos + take])
            cur += take
            left -= take
        return bytes(out)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def entropy(buf: bytes) -> float:
    if not buf:
        return 0.0
    counts = Counter(buf)
    n = len(buf)
    return -sum((v / n) * math.log2(v / n) for v in counts.values())


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def parse_b000ff(data: bytes) -> dict:
    """Parse only documented B000FF section framing; preserve raw file offsets."""
    if data[:7] != b"B000FF\n":
        return {"recognized": False, "reason": "signature absent", "segments": []}
    if len(data) < 15:
        return {"recognized": True, "valid": False, "reason": "short global header", "segments": []}
    image_start, image_length = struct.unpack_from("<II", data, 7)
    cur = 15
    segments = []
    errors = []
    terminated = False
    while cur + 12 <= len(data):
        base, size, checksum = struct.unpack_from("<III", data, cur)
        payload = cur + 12
        if base == 0 and (size == 0 or size > len(data)):
            terminated = True
            cur = payload
            break
        if size == 0 or size > 0x10000000 or payload + size > len(data):
            errors.append({"header_offset": cur, "base": base, "size": size,
                           "reason": "invalid payload bounds"})
            break
        segments.append(Segment(base, size, payload, checksum))
        cur = payload + size
    return {
        "recognized": True, "valid": bool(segments) and not errors,
        "image_start": image_start, "image_length": image_length,
        "terminator_seen": terminated, "trailing_bytes": len(data) - cur,
        "segments": [asdict(s) for s in segments], "errors": errors,
    }


def make_address_map(data: bytes, parsed: dict) -> AddressMap | None:
    if not parsed.get("valid"):
        return None
    return AddressMap(data, [Segment(**x) for x in parsed["segments"]])


def parse_romhdr(data: bytes, off: int) -> dict | None:
    if off < 0 or off + ROMHDR_SIZE > len(data):
        return None
    f = struct.unpack_from(ROMHDR_FMT, data, off)
    fields = (
        "dllfirst", "dlllast", "physfirst", "physlast", "nummods",
        "ulRAMStart", "ulRAMFree", "ulRAMEnd", "ulCopyEntries",
        "ulCopyOffset", "ulProfileLen", "ulProfileOffset", "numfiles",
        "ulKernelFlags", "ulFSRamPercent", "ulDrivglobStart", "ulDrivglobLen",
        "usCPUType", "usMiscFlags", "pExtensions", "ulTrackingStart", "ulTrackingLen",
    )
    h = dict(zip(fields, f))
    h.update({
        "file_offset": off,
        "bounds_order_ok": h["dllfirst"] <= h["dlllast"] and h["physfirst"] <= h["physlast"],
        "count_bounds_ok": h["nummods"] <= 10000 and h["numfiles"] <= 50000,
        "module_count_supported": 1 <= h["nummods"] <= MAX_MODULES,
    })
    h["coarse_bounds_ok"] = h["bounds_order_ok"] and h["count_bounds_ok"]
    return h


def printable_z(data: bytes, off: int, limit: int = 256) -> str | None:
    if off < 0 or off >= len(data):
        return None
    raw = data[off:min(len(data), off + limit)]
    end = raw.find(b"\0")
    if end <= 0:
        return None
    value = raw[:end]
    if not all(0x20 <= b < 0x7f for b in value):
        return None
    return value.decode("ascii")


def flat_toc(data: bytes, hdr: dict, header_off: int, origin: int) -> dict:
    count = hdr["nummods"]
    start = header_off + ROMHDR_SIZE
    end = start + count * TOC_SIZE
    result = {"mapping": f"flat file origin 0x{origin:x}, VA base=physfirst", "flat_origin": origin,
              "toc_file_bounds": 0 <= start <= end <= len(data),
              "entries": [], "readable_names": 0, "e32_mapped": 0, "o32_mapped": 0,
              "nk_exe_index": None}
    if not result["toc_file_bounds"] or not hdr["module_count_supported"]:
        return result
    for i in range(count):
        row_off = start + i * TOC_SIZE
        attrs, ftlo, fthi, fsize, name_va, e32_va, o32_va, load_va = struct.unpack_from(TOC_FMT, data, row_off)
        name_off = origin + name_va - hdr["physfirst"]
        name = printable_z(data, name_off)
        result["readable_names"] += int(name is not None)
        result["e32_mapped"] += int(0 <= origin + e32_va - hdr["physfirst"] < len(data))
        result["o32_mapped"] += int(0 <= origin + o32_va - hdr["physfirst"] < len(data))
        if name and name.lower() == "nk.exe":
            result["nk_exe_index"] = i
        if i < 8:
            result["entries"].append({"index": i, "name": name, "row_file_offset": row_off,
                                      "name_va": name_va, "name_file_offset": name_off,
                                      "e32_va": e32_va, "o32_va": o32_va, "load_va": load_va,
                                      "file_size": fsize, "attributes": attrs,
                                      "filetime_lo": ftlo, "filetime_hi": fthi})
    result["all_names_readable"] = result["readable_names"] == count
    result["all_e32_o32_mapped"] = result["e32_mapped"] == count and result["o32_mapped"] == count
    result["coherent_without_kernel_order_assumption"] = (
        result["toc_file_bounds"] and result["all_names_readable"] and result["all_e32_o32_mapped"]
    )
    return result


def sparse_toc(amap: AddressMap, hdr: dict, header_va: int) -> dict:
    count = hdr["nummods"]
    toc_va = header_va + ROMHDR_SIZE
    raw = amap.read(toc_va, count * TOC_SIZE) if hdr["module_count_supported"] else None
    result = {"mapping": "sparse B000FF VA map", "toc_va": toc_va,
              "toc_fully_mapped": raw is not None, "entries": [],
              "readable_names": 0, "e32_mapped": 0, "o32_mapped": 0,
              "nk_exe_index": None}
    if raw is None:
        return result
    for i in range(count):
        attrs, ftlo, fthi, fsize, name_va, e32_va, o32_va, load_va = struct.unpack_from(TOC_FMT, raw, i * TOC_SIZE)
        nraw = amap.read(name_va, 256)
        name = None
        if nraw is not None and b"\0" in nraw:
            bname = nraw.split(b"\0", 1)[0]
            if bname and all(0x20 <= c < 0x7f for c in bname):
                name = bname.decode("ascii")
        result["readable_names"] += int(name is not None)
        result["e32_mapped"] += int(amap.offset(e32_va) is not None)
        result["o32_mapped"] += int(amap.offset(o32_va) is not None)
        if name and name.lower() == "nk.exe":
            result["nk_exe_index"] = i
        if i < 8:
            result["entries"].append({"index": i, "name": name, "name_va": name_va,
                                      "name_file_offset": amap.offset(name_va),
                                      "e32_va": e32_va, "o32_va": o32_va, "load_va": load_va,
                                      "file_size": fsize, "attributes": attrs,
                                      "filetime_lo": ftlo, "filetime_hi": fthi})
    result["all_names_readable"] = result["readable_names"] == count
    result["all_e32_o32_mapped"] = result["e32_mapped"] == count and result["o32_mapped"] == count
    result["coherent_without_kernel_order_assumption"] = (
        result["toc_fully_mapped"] and result["all_names_readable"] and result["all_e32_o32_mapped"]
    )
    return result


def scan_headers(data: bytes, mode: str, amap: AddressMap | None = None,
                 segments: list[Segment] | None = None, origins=(0, 0x400)) -> dict:
    """Bytewise scan. Does not require nk.exe to be in any specific TOC slot."""
    windows = []
    if mode == "flat":
        windows = [(0, len(data), None)]
    else:
        windows = [(s.file_offset, s.file_offset + s.size, s) for s in (segments or [])]
    coarse = 0
    candidates = []
    seen = set()
    for lo, hi, seg in windows:
        last = min(hi, len(data)) - ROMHDR_SIZE
        for off in range(max(0, lo), last + 1):
            pf = u32(data, off + 8)
            if not (KERNEL_LO <= pf < KERNEL_HI):
                continue
            pl = u32(data, off + 12)
            if not (pf < pl <= pf + 0x10000000):
                continue
            hdr = parse_romhdr(data, off)
            if not hdr or not hdr["coarse_bounds_ok"] or not hdr["module_count_supported"]:
                continue
            coarse += 1
            key = (off, seg.va if seg else None)
            if key in seen:
                continue
            seen.add(key)
            if seg and amap:
                header_va = seg.va + off - seg.file_offset
                toc = sparse_toc(amap, hdr, header_va)
                hypotheses = [toc]
            else:
                header_va = pf + off
                hypotheses = [flat_toc(data, hdr, off, origin) for origin in origins]
            candidates.append({"header_file_offset": off, "header_offset_mod4": off % 4,
                               "header_va_under_section_map": header_va,
                               "romhdr": hdr, "toc_hypotheses": hypotheses,
                               "toc_coherent": any(t.get("coherent_without_kernel_order_assumption") for t in hypotheses)})
    return {"bytewise_scan": True, "nk_exe_required_in_first_32": False,
            "coarse_candidates": coarse,
            "alignment_counts": dict(Counter(str(x["header_offset_mod4"]) for x in candidates)),
            "accepted_candidates": sum(x["toc_coherent"] for x in candidates),
            "candidates": candidates[:200]}


def ecec_scan(data: bytes, parsed: dict, amap: AddressMap | None,
              header_scan: dict) -> list[dict]:
    segments = [Segment(**x) for x in parsed.get("segments", [])] if parsed.get("valid") else []
    out = []
    pos = 0
    while True:
        pos = data.find(b"ECEC", pos)
        if pos < 0:
            break
        va = None
        owners = [s for s in segments if s.file_offset <= pos < s.file_offset + s.size]
        if len(owners) == 1:
            va = owners[0].va + pos - owners[0].file_offset
        rec = {"file_offset": pos, "offset_mod4": pos % 4, "mapped_va": va}
        if pos + 12 <= len(data):
            ptoc, romhdr_field = struct.unpack_from("<II", data, pos + 4)
            rec.update({"ptoc_va": ptoc, "romhdr_offset_field": romhdr_field,
                        "ptoc_in_ce_kernel_range": KERNEL_LO <= ptoc < KERNEL_HI,
                        "header_field_fits_file_as_raw_offset": romhdr_field < len(data)})
            candidates = []
            raw_header_offset = pos - 0x40 + romhdr_field
            if amap is None:
                raw_hdr = parse_romhdr(data, raw_header_offset)
                candidates.append({"basis": "flat ECEC file offset - 0x40 + ECEC+8",
                                   "romhdr_file_offset": raw_header_offset,
                                   "inside_file": 0 <= raw_header_offset <= len(data) - ROMHDR_SIZE,
                                   "romhdr_bounds_order_ok": bool(raw_hdr and raw_hdr["bounds_order_ok"]),
                                   "romhdr": raw_hdr})
                for candidate in header_scan.get("candidates", []):
                    hdr = candidate["romhdr"]
                    for toc in candidate["toc_hypotheses"]:
                        origin = toc.get("flat_origin", 0)
                        header_va = hdr["physfirst"] + candidate["header_file_offset"] - origin
                        ecec_va = hdr["physfirst"] + pos - origin
                        matches = (candidate["header_file_offset"] == raw_header_offset
                                   or header_va == ptoc)
                        if matches:
                            candidates.append({"basis": "cross-check with bytewise header candidate",
                                               "header_file_offset": candidate["header_file_offset"],
                                               "flat_origin": origin, "ptoc_matches_header_va": header_va == ptoc,
                                               "ecec_matches_physfirst_plus_0x40": ecec_va == hdr["physfirst"] + 0x40,
                                               "toc_coherent": toc.get("coherent_without_kernel_order_assumption", False)})
            if amap and amap.offset(ptoc, ROMHDR_SIZE) is not None:
                raw = amap.read(ptoc, ROMHDR_SIZE)
                h = parse_romhdr(raw, 0) if raw else None
                candidates.append({"basis": "ptoc_va through sparse segment map",
                                   "romhdr_at_ptoc_valid": bool(h and h["coarse_bounds_ok"]),
                                   "romhdr": h})
            if va is not None:
                derived_va = va - 0x40 + romhdr_field
                loc = amap.offset(derived_va, ROMHDR_SIZE) if amap else None
                if loc is not None:
                    raw = amap.read(derived_va, ROMHDR_SIZE)
                    h = parse_romhdr(raw, 0) if raw else None
                    candidates.append({"basis": "mapped ECEC VA - 0x40 + ECEC+8",
                                       "romhdr_va": derived_va, "file_offset": loc,
                                       "romhdr_valid": bool(h and h["coarse_bounds_ok"]), "romhdr": h})
            rec["direct_address_candidates"] = candidates
        out.append(rec)
        pos += 1
    return out


def block_stats(data: bytes, block_size: int = 65536) -> dict:
    blocks = []
    for start in range(0, len(data), block_size):
        b = data[start:start + block_size]
        counts = Counter(b)
        blocks.append({"offset": start, "length": len(b), "entropy_bits_per_byte": round(entropy(b), 5),
                       "zero_fraction": round(counts[0] / len(b), 6),
                       "ff_fraction": round(counts[255] / len(b), 6),
                       "printable_fraction": round(sum(n for c, n in counts.items() if 0x20 <= c < 0x7f) / len(b), 6)})
    values = [x["entropy_bits_per_byte"] for x in blocks]
    ordered = sorted(values)
    return {"block_size": block_size, "count": len(blocks),
            "entropy_min": min(values), "entropy_median": ordered[len(ordered) // 2],
            "entropy_max": max(values), "entropy_mean": round(sum(values) / len(values), 5),
            "blocks": blocks}


def fill_runs(buf: bytes, value: int, min_run: int = 8) -> list[dict]:
    runs = []
    i = 0
    while i < len(buf):
        if buf[i] != value:
            i += 1
            continue
        j = i + 1
        while j < len(buf) and buf[j] == value:
            j += 1
        if j - i >= min_run:
            runs.append({"offset": i, "length": j - i, "byte": f"{value:02X}"})
        i = j
    return runs


def strings_analysis(data: bytes, source_json: Path) -> dict:
    original = json.loads(source_json.read_text(encoding="utf-8"))
    cluster = original["module_name_cluster_candidate"]
    entries = cluster["entries"]
    rows = []
    matches = []
    for i, entry in enumerate(entries):
        off = entry["offset"]
        expected = entry["name"].encode("ascii")
        actual = data[off:off + len(expected)] == expected and data[off + len(expected):off + len(expected) + 1] == b"\0"
        if actual:
            matches.append(i)
        start, end = max(0, off - 64), min(len(data), off + len(expected) + 64)
        before = data[max(0, off - 64):off]
        after = data[off + len(expected) + 1:min(len(data), off + len(expected) + 65)]
        prev = entries[i - 1]["offset"] if i else None
        nxt = entries[i + 1]["offset"] if i + 1 < len(entries) else None
        before_words = {str(rel): u32(data, off + rel) for rel in range(-64, -3, 4) if off + rel >= 0}
        after0 = off + len(expected) + 1
        after_words = {str(rel): u32(data, after0 + rel) for rel in range(0, 61, 4) if after0 + rel + 4 <= len(data)}
        neighborhood = data[start:end]
        crc = zlib.crc32(expected) & 0xffffffff
        crc_hits = [p for p in range(max(0, off - 64), min(len(data) - 3, off + len(expected) + 64), 4)
                    if u32(data, p) == crc]
        rows.append({"index": i, "name": entry["name"], "file_offset": off,
                     "nul_terminated_exact_match": actual, "offset_mod4": off % 4,
                     "gap_from_previous_name": off - prev if prev is not None else None,
                     "gap_to_next_name": nxt - off if nxt is not None else None,
                     "context_start": start, "context_length": len(neighborhood),
                     "context_rule": "up to 64 bytes before + name + NUL + up to 64 bytes after",
                     "context_hex": neighborhood.hex(" "),
                     "before_words_relative_to_name_le": before_words,
                     "after_words_relative_to_post_nul_le": after_words,
                     "name_length": len(expected), "crc32_name": f"0x{crc:08X}",
                     "crc32_name_in_aligned_context": crc_hits})

    field_summary = []
    all_positions = sorted(set(
        [f"before:{i}" for i in range(-64, -3, 4)] +
        [f"after:{i}" for i in range(0, 61, 4)]
    ))
    for slot in all_positions:
        vals = []
        for row in rows:
            group, rel = slot.split(":")
            source = row["before_words_relative_to_name_le"] if group == "before" else row["after_words_relative_to_post_nul_le"]
            key = rel if group == "before" else rel
            if key in source:
                vals.append((row["file_offset"], source[key]))
        if not vals:
            continue
        value_counts = Counter(v for _, v in vals)
        deltas = Counter(v - off for off, v in vals)
        field_summary.append({"slot": slot, "present": len(vals),
                              "values_in_file_range": sum(0 <= v < len(data) for _, v in vals),
                              "values_aligned4": sum(v % 4 == 0 for _, v in vals),
                              "equals_own_name_offset": sum(v == off for off, v in vals),
                              "max_same_value_count": max(value_counts.values()),
                              "max_constant_delta_to_name_count": max(deltas.values()),
                              "most_common_value": {"value": max(value_counts, key=value_counts.get),
                                                    "count": max(value_counts.values())}})
    gaps = [entries[i + 1]["offset"] - entries[i]["offset"] for i in range(len(entries) - 1)]
    return {"manifest_range": cluster.get("range_start"), "manifest_range_end": cluster.get("range_end_exclusive"),
            "manifest_count": cluster["filename_count"], "verified_exact_nul_string_count": len(matches),
            "unmatched_indexes": [i for i in range(len(entries)) if i not in matches],
            "target_entries": [r for r in rows if r["name"] in TARGET_NAMES],
            "offset_mod4_counts": dict(Counter(str(r["offset_mod4"]) for r in rows)),
            "gap_summary_bytes": {"min": min(gaps), "median": sorted(gaps)[len(gaps)//2],
                                  "max": max(gaps), "unique_gaps": len(set(gaps))},
            "relative_field_recurrence": field_summary,
            "module_name_contexts": rows}


def module_record_family_scan(data: bytes, entries: list[dict]) -> dict:
    """Test the repeated CE+metadata pattern adjacent to the 74 manifest names.

    This reports a byte-level candidate record family; it intentionally assigns
    no meanings to the fields. Exact little-endian pointer hits are evidence of
    recurrence only, not proof that a consumer dereferences them.
    """
    rows = []
    for i, entry in enumerate(entries):
        name = entry["name"].encode("ascii")
        name_off = entry["offset"]
        nul_off = name_off + len(name)
        if data[name_off:nul_off] != name or data[nul_off:nul_off + 1] != b"\0":
            continue
        search_start = nul_off + 1
        marker_off = data.find(b"CE", search_start, min(len(data), search_start + 17))
        if marker_off < 0 or marker_off + 16 > len(data):
            continue
        field16 = struct.unpack_from("<H", data, marker_off + 2)[0]
        field04, field08, field12 = struct.unpack_from("<III", data, marker_off + 4)
        ptr_bytes = struct.pack("<I", field04)
        refs = []
        pos = 0
        while True:
            pos = data.find(ptr_bytes, pos)
            if pos < 0:
                break
            if pos != marker_off + 4:
                refs.append(pos)
            pos += 1
        rows.append({
            "index": entry.get("index", i), "name": entry["name"],
            "name_file_offset": name_off, "nul_offset": nul_off,
            "marker_file_offset": marker_off,
            "marker_distance_after_nul": marker_off - search_start,
            "record_hex_16": data[marker_off:marker_off + 16].hex(" "),
            "field_u16_at_marker_plus_2": f"0x{field16:04X}",
            "field_u32_at_marker_plus_4": f"0x{field04:08X}",
            "field_plus_4_in_kernel_va_range": KERNEL_LO <= field04 < KERNEL_HI,
            "field_u32_at_marker_plus_8": f"0x{field08:08X}",
            "field_u32_at_marker_plus_12": f"0x{field12:08X}",
            "field_plus_4_exact_secondary_reference_offsets": refs,
        })
    addresses = [int(r["field_u32_at_marker_plus_4"], 16) for r in rows]
    transitions = list(zip(addresses, addresses[1:]))
    va_file_deltas = [int(r["field_u32_at_marker_plus_4"], 16) - off
                      for r in rows for off in r["field_plus_4_exact_secondary_reference_offsets"]]
    delta_counts = Counter(va_file_deltas)
    return {
        "interpretation": "repeated byte pattern candidate only; field semantics and record boundaries are unproven",
        "candidate_count": len(rows),
        "distinct_plus_4_values": len(set(addresses)),
        "plus_4_kernel_va_count": sum(KERNEL_LO <= v < KERNEL_HI for v in addresses),
        "plus_4_four_byte_aligned_count": sum(v % 4 == 0 for v in addresses),
        "plus_4_strictly_increasing_transitions": sum(a < b for a, b in transitions),
        "plus_4_transition_count": len(transitions),
        "secondary_reference_count_distribution": dict(Counter(
            str(len(r["field_plus_4_exact_secondary_reference_offsets"])) for r in rows)),
        "secondary_reference_total": len(va_file_deltas),
        "distinct_va_minus_file_offset_deltas": len(delta_counts),
        "most_common_va_minus_file_offset_delta_count": max(delta_counts.values(), default=0),
        "va_minus_file_offset_delta_min_hex": f"0x{min(va_file_deltas):X}" if va_file_deltas else None,
        "va_minus_file_offset_delta_max_hex": f"0x{max(va_file_deltas):X}" if va_file_deltas else None,
        "rows": rows,
    }


def pointer_reference_scan(data: bytes, entries: list[dict]) -> dict:
    targets: dict[int, list[str]] = defaultdict(list)
    bases = {"raw_file_offset": 0, "candidate_va_base_0x80000000": 0x80000000,
             "candidate_va_base_0x8D000000": 0x8D000000}
    for e in entries:
        for label, base in bases.items():
            v = base + e["offset"]
            if 0 < v <= 0xffffffff:
                targets[v].append(f"{e['name']}@0x{e['offset']:X}:{label}")
    matches = []
    counts = Counter()
    targetset = set(targets)
    # Check all byte alignments; record the exact word location and target.
    for phase in range(4):
        for off in range(phase, len(data) - 3, 4):
            value = u32(data, off)
            if value in targetset:
                labels = targets[value]
                for item in labels:
                    label = item.rsplit(":", 1)[-1]
                    counts[label] += 1
                if len(matches) < 100:
                    matches.append({"word_file_offset": off, "word_value": f"0x{value:08X}",
                                    "possible_string_targets": labels})
    return {"tested_word_alignments": [0, 1, 2, 3],
            "candidate_bases_are_unvalidated": bases,
            "counts_by_hypothesis": dict(counts),
            "exact_pointer_word_matches": matches,
            "interpretation": "Exact words only; any hit is a lead, not a verified record reference."}


def sibling_summary(nk: Path) -> list[dict]:
    rows = []
    for name in ("BOOTSECTOR.BIN", "KERNELLOADER.BIN"):
        path = nk.parent / name
        if not path.is_file():
            continue
        b = path.read_bytes()
        rows.append({"name": name, "path": str(path), "size": len(b), "sha256": sha256(b),
                     "first_64_hex": b[:64].hex(" "), "first_64_ascii": b[:64].decode("ascii", "replace"),
                     "entropy_first_4k": round(entropy(b[:4096]), 5),
                     "zero_fraction_first_4k": round(b[:4096].count(0) / max(1, min(len(b), 4096)), 6),
                     "ff_fraction_first_4k": round(b[:4096].count(255) / max(1, min(len(b), 4096)), 6)})
    return rows


def inventory_nk_rows(path: Path) -> dict:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        item = json.loads(line)
        if item.get("path", "").lower().endswith("nk.bin"):
            rows.append({"path": item["path"], "size_bytes": item.get("size_bytes"),
                         "sha256": item.get("previous_manifest_sha256")})
    return {"manifest_path": str(path), "nk_path_count": len(rows),
            "unique_size_sha_pairs": len({(r["size_bytes"], r["sha256"]) for r in rows}),
            "entries": rows}


def analyze(nk: Path, name_manifest: Path, inventory_manifest: Path) -> dict:
    data = nk.read_bytes()
    b000ff = parse_b000ff(data)
    amap = make_address_map(data, b000ff)
    if b000ff.get("valid"):
        segments = [Segment(**x) for x in b000ff["segments"]]
        headers = scan_headers(data, "sparse", amap, segments)
    else:
        headers = scan_headers(data, "flat")
    module_data = strings_analysis(data, name_manifest)
    name_doc = json.loads(name_manifest.read_text(encoding="utf-8"))
    name_entries = name_doc["module_name_cluster_candidate"]["entries"]
    module_records = module_record_family_scan(data, name_entries)
    ececs = ecec_scan(data, b000ff, amap, headers)
    first = data[:4096]
    signature_names = [b"LK-01-05", b"CE00FF\n", b"ECEC", b"B000FF\n", b"MZ", b"PE\0\0", b"ROMHDR"]
    sigcounts = {s.decode("ascii", "replace"): data.count(s) for s in signature_names}
    chunks = []
    for start in range(0, len(first), 256):
        b = first[start:start + 256]
        chunks.append({"offset": start, "length": len(b), "entropy": round(entropy(b), 5),
                       "zero_fraction": round(b.count(0) / len(b), 6),
                       "ff_fraction": round(b.count(255) / len(b), 6),
                       "unique_byte_count": len(set(b))})
    z = zlib.compress(data, 1)
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(nk.resolve()), "size": len(data), "sha256": sha256(data),
        "v9_audit": {
            "ROMHDR_scan_was_4byte_aligned": True,
            "v10_scans_all_byte_offsets": True,
            "v9_structural_rule_required_nk_exe_in_first_32": True,
            "v10_requires_no_fixed_nk_exe_slot": True,
            "v9_linear_va_to_file_formula_only": "name_file_offset = origin + (name_va - load_base)",
            "v10_supports_sparse_B000FF_map_when_signature_and_records_validate": True,
            "v10_checks_all_raw_ECEC_occurrences_and_all_bounded_header_candidates": True,
        },
        "container": b000ff,
        "romhdr_scan": headers,
        "ecec_occurrences": ececs,
        "header_4096": {"first_4096_hex": first.hex(" "),
                         "first_4096_entropy": round(entropy(first), 5),
                         "first_4096_zero_fraction": round(first.count(0) / len(first), 6),
                         "first_4096_ff_fraction": round(first.count(255) / len(first), 6),
                         "256_byte_windows": chunks,
                         "zero_runs_ge8": fill_runs(first, 0), "ff_runs_ge8": fill_runs(first, 255),
                         "signature_counts_full_image": sigcounts},
        "entropy_64k_blocks": block_stats(data),
        "zlib_level1_size": len(z),
        "zlib_level1_ratio": round(len(z) / len(data), 6),
        "module_names": module_data,
        "module_record_family_candidate": module_records,
        "name_pointer_references": pointer_reference_scan(data, name_entries),
        "sibling_files": sibling_summary(nk),
        "existing_nk_inventory": inventory_nk_rows(inventory_manifest),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[4]
    ap = argparse.ArgumentParser()
    ap.add_argument("nk", type=Path)
    ap.add_argument("--name-manifest", type=Path,
                    default=root / "research/geometry_breakthrough/routing_owner_v8/evidence/nk_targeted_inspection.json")
    ap.add_argument("--inventory-manifest", type=Path,
                    default=root / "research/geometry_breakthrough/routing_owner_v8/evidence/physical_files.jsonl")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    report = analyze(args.nk, args.name_manifest, args.inventory_manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "sha256": report["sha256"], "container": {k: v for k, v in report["container"].items() if k != "segments"},
        "romhdr_scan": {k: v for k, v in report["romhdr_scan"].items() if k != "candidates"},
        "ecec_occurrences": report["ecec_occurrences"],
        "module_names": {k: v for k, v in report["module_names"].items() if k != "module_name_contexts"},
        "module_record_family_candidate": {k: v for k, v in report["module_record_family_candidate"].items() if k != "rows"},
        "pointer_matches": len(report["name_pointer_references"]["exact_pointer_word_matches"]),
        "sibling_files": report["sibling_files"],
        "existing_nk_inventory": report["existing_nk_inventory"], "output": str(args.output.resolve())
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
