#!/usr/bin/env python3
"""Read-only structural scan of a CARiN/VDO Dayton DB_0 file.

This tool records observations only.  It never opens DB_0 for writing and does
not infer a record type from any bytes beyond the explicitly tested rules.
"""

from __future__ import annotations

import argparse
import csv
import mmap
import zlib
from collections import Counter
from pathlib import Path

SECTOR_SIZE = 512
ZLIB_HEADERS = (b"\x78\x01", b"\x78\x5e", b"\x78\x9c", b"\x78\xda")


def sector_id(data: mmap.mmap, sector: int) -> int:
    offset = sector * SECTOR_SIZE
    return int.from_bytes(data[offset : offset + 3], "big")


def scan_headers(data: mmap.mmap) -> list[dict[str, int | bool | str]]:
    total_sectors = len(data) // SECTOR_SIZE
    candidates: dict[int, int] = {}
    for sector in range(total_sectors):
        if sector_id(data, sector) == sector:
            candidates[sector] = data[sector * SECTOR_SIZE + 3]

    rows: list[dict[str, int | bool | str]] = []
    for sector, span in candidates.items():
        offset = sector * SECTOR_SIZE
        next_sector = sector + span
        # A span of zero cannot identify a forward record boundary.
        next_valid = span > 0 and next_sector in candidates
        rows.append(
            {
                "sector": sector,
                "offset": offset,
                "span": span,
                "next_sector": next_sector,
                "next_valid": next_valid,
                "header_hex": data[offset + 4 : offset + 32].hex(),
                "payload_prefix": data[offset + 4 : offset + 68].hex(),
            }
        )
    return rows


def validated_rows(rows: list[dict[str, int | bool | str]]) -> list[dict[str, int | bool | str]]:
    return [row for row in rows if bool(row["next_valid"])]


def write_record_index(rows: list[dict[str, int | bool | str]], path: Path) -> None:
    fields = ["sector", "offset", "span", "next_sector", "next_valid", "header_hex", "payload_prefix"]
    with path.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_compression(data: mmap.mmap, rows: list[dict[str, int | bool | str]], path: Path) -> None:
    fields = ["sector", "span", "zlib_offset", "compressed_size", "decompressed_size", "success"]
    with path.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            sector, span = int(row["sector"]), int(row["span"])
            start = sector * SECTOR_SIZE
            # The record itself sets this upper bound.  It is deliberately not
            # extended to later records when a decompressor wants more input.
            end = min(start + span * SECTOR_SIZE, len(data))
            probe = data[start + 4 : min(start + 68, end)]
            for rel in range(max(0, len(probe) - 1)):
                if probe[rel : rel + 2] not in ZLIB_HEADERS:
                    continue
                zlib_offset = 4 + rel
                compressed = data[start + zlib_offset : end]
                success = False
                compressed_size = 0
                decompressed_size = 0
                try:
                    decoder = zlib.decompressobj()
                    output = decoder.decompress(compressed)
                    output += decoder.flush()
                    success = decoder.eof
                    decompressed_size = len(output)
                    compressed_size = len(compressed) - len(decoder.unused_data)
                except zlib.error:
                    pass
                writer.writerow(
                    {
                        "sector": sector,
                        "span": span,
                        "zlib_offset": zlib_offset,
                        "compressed_size": compressed_size,
                        "decompressed_size": decompressed_size,
                        "success": success,
                    }
                )


def chains(rows: list[dict[str, int | bool | str]]) -> list[list[dict[str, int | bool | str]]]:
    by_sector = {int(row["sector"]): row for row in rows}
    predecessors = {int(row["next_sector"]) for row in rows if bool(row["next_valid"])}
    starts = [row for row in rows if int(row["sector"]) not in predecessors]
    result: list[list[dict[str, int | bool | str]]] = []
    for start in starts:
        chain, current, seen = [], start, set()
        while current and int(current["sector"]) not in seen:
            chain.append(current)
            seen.add(int(current["sector"]))
            current = by_sector.get(int(current["next_sector"])) if bool(current["next_valid"]) else None
        result.append(chain)
    return result


def write_statistics(rows: list[dict[str, int | bool | str]], path: Path) -> None:
    validated = validated_rows(rows)
    record_chains = chains(rows)
    span_counts = Counter(int(row["span"]) for row in rows)
    byte_counts = Counter(str(row["header_hex"])[:8] for row in rows)
    # A record chain is a more meaningful region than adjacent header starts:
    # records regularly span several sectors, so header starts are expected to
    # have gaps even when storage is contiguous.
    regions = []
    for chain in record_chains:
        first = int(chain[0]["sector"])
        last = int(chain[-1]["sector"]) + int(chain[-1]["span"]) - 1
        regions.append((first, last))
    regions.sort()

    with path.open("w", encoding="utf-8") as out:
        out.write(f"total_candidate_headers: {len(rows)}\n")
        out.write(f"validated_headers: {len(validated)}\n")
        out.write("sector_count_distribution:\n")
        for value, count in sorted(span_counts.items()):
            out.write(f"  {value}: {count}\n")
        out.write("bytes_4_to_7_distribution:\n")
        for value, count in byte_counts.most_common():
            out.write(f"  {value}: {count}\n")
        out.write("longest_chains:\n")
        for chain in sorted(record_chains, key=len, reverse=True)[:20]:
            out.write(f"  length={len(chain)} start=0x{int(chain[0]['sector']):06x} end=0x{int(chain[-1]['sector']):06x}\n")
        out.write("record_regions_from_chains:\n")
        for first, last in regions:
            out.write(f"  0x{first:06x}-0x{last:06x} ({last - first + 1} covered sectors)\n")
        out.write("gaps_between_record_regions:\n")
        for (_, last), (first, _) in zip(regions, regions[1:]):
            out.write(f"  0x{last + 1:06x}-0x{first - 1:06x} ({first - last - 1} sectors)\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db0", type=Path, help="Path to DB_0; opened read-only")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with args.db0.open("rb") as source:
        with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
            rows = scan_headers(data)
            write_record_index(rows, args.output_dir / "record_index.csv")
            write_compression(data, validated_rows(rows), args.output_dir / "compression.csv")
            write_statistics(rows, args.output_dir / "scan_statistics.txt")


if __name__ == "__main__":
    main()
