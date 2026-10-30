# NCDR DB Laboratory

NCDR DB Laboratory is a local, deterministic tool for inspecting Continental / CARiN / VDO navigation database records. It does not use AI and opens the source `DB_0` read-only. Compression `0x01` remains an experimental research target; candidate scores are clues, not proof that a transform decodes a block.

## Launch

1. Install Python 3.9 or newer. Tkinter is needed for the desktop window. The first version uses only Python's standard library.
2. Open Terminal in the project folder.
3. Run `python3 -m research.db_lab.app`.

The command line is also available as `python3 -m research.db_lab.cli /path/to/DB_0 --analysis-folder /path/to/results`.

## Start an analysis

- Select the `DB_0` file.
- Choose an analysis folder. A timestamped `NCDR_DB_LAB_YYYYMMDD_HHMMSS` folder is created inside it.
- Choose Quick, Standard, Deep, or Experimental. They test 8, 24, 64, or 96 representative compression-`0x01` blocks, respectively, using the bounded first-stage transform set.
- Choose AUTO, CPU, or GPU. CPU is the implemented execution backend. Optional backends are detected and reported; unsupported GPU work falls back to CPU.
- Start the analysis. The original file is hashed before analysis and never opened for writing.

The run folder contains a SQLite index, CSV summaries, an offline HTML report, checkpoint state, logs, and small candidate samples. The source database is not copied into it.

## Pause and resume

Pause takes effect at the next checkpoint. Resume continues the run whose source path and SHA256 match. If the source file has changed, the run will not resume. Stop leaves the latest checkpoint available for a later resume.

## Reports and block inspection

Use the block inspector to enter a sector number in decimal or hexadecimal (for example `0x0899`). It shows the physical header and a raw preview. The HTML report opens offline from the `html` folder.

Choose **Create ChatGPT analysis package** after a run completes to create a compact ZIP beside the timestamped run folder. It contains the summaries, CSVs, small candidate samples, logs, and the analysis database, without the source `DB_0`.

## Resource controls

CPU load controls throttle between batches. The database is streamed from a read-only mapping and candidate testing is bounded, so normal operation uses a small sample rather than caching the whole source in memory. The selected RAM ceiling is recorded but is not a hard process memory limit. GPU load is recorded for the run; GPU compute adapters are not included in this first milestone. Hardware detection and a CPU benchmark are reported at startup. No GPU backend is installed or available on the original environment inspected for this milestone.
