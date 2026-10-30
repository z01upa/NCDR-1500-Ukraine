# Technical notes

## Design

- `core/db_reader.py` scans sector-aligned self-identifying records and accepts records whose next physical boundary is another header or exact file EOF. It memory maps the input read-only.
- The 8-byte BL_HEAD is retained. Compression `0x00` reads the advertised logical extent; `0x02` uses bounded zlib beginning at local byte `+8` and validates the advertised logical size. `0x01` is deliberately not decoded.
- `analysis/runner.py` builds an SQLite block index, streams block profiles, writes run checkpoints, exports CSV/JSON/Markdown, and creates the offline report and compact ZIP.
- The confirmed road parser in `research/roads/parse_roads.py` is invoked for its Moscow control list when the package is run in the project tree.
- `acceleration/backend.py` centralizes hardware discovery and benchmarking. CPU is the only implemented execution backend in this milestone.

## Compression `0x01` search and score

The first-stage funnel tests identity, complement, byte reversal, bit reversal, nibble swap, previous-byte XOR, delta-8 accumulation, and constant-byte XOR values `0x00` through `0xFF`. It works on 8/24/64/96 representative blocks by mode. The score (0–100) compares candidate entropy, zero-byte ratio, and distinct-byte count with the average profile of readable type-`0x00` blocks. This is coarse statistical similarity only; it does not prove valid framing, pointers, coordinates, or decompression. The report preserves that limitation.

Candidate progress is checkpointed as JSON and can resume. The SQLite index stores metadata and statistics, not duplicate logical payload blobs. Candidate samples contain short hex previews only.

## Checkpoints and integrity

`run_manifest.json` includes source path, byte size, SHA256, mode, resource preferences, and backend report. Resume selects a matching DB path and SHA256. Block indexing and decode status are persisted in SQLite; transform progress is checkpointed periodically. CPU load throttling occurs between batches. The RAM selector records the preference but does not set a hard OS memory cap.

## Supported scope

This is milestone 1: local indexing, known compression handling, compression-`0x01` corpus profiling, first-stage candidates, a basic GUI, checkpointing, and reports. It does not write DB_0 files or emit decoded compression-`0x01` payloads. GPU execution, advanced resource throttling, broad reference extraction, and advanced visual block inspection remain future work.
