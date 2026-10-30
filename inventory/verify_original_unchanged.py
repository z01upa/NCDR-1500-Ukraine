"""Verify the source tree still matches its saved inventory without writing to it."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import os


DEFAULT_SOURCE = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[1]))
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "inventory" / "discs_manifest.json"


def verify(source_root: Path = DEFAULT_SOURCE) -> dict:
    expected_rows = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    expected = {row["relative_path"].replace("/", "\\"): row for row in expected_rows}
    observed: set[str] = set()
    missing: list[str] = []
    changed_size: list[str] = []
    changed_mtime: list[str] = []
    for path in source_root.rglob("*"):
        if not path.is_file():
            continue
        relative = str(path.relative_to(source_root)).replace("/", "\\")
        observed.add(relative)
        row = expected.get(relative)
        if row is None:
            continue
        stat = path.stat()
        if stat.st_size != row["length_bytes"]:
            changed_size.append(relative)
        saved_mtime = datetime.fromisoformat(row["last_write_utc"].replace("Z", "+00:00")).timestamp()
        if abs(stat.st_mtime - saved_mtime) > 0.00001:
            changed_mtime.append(relative)
    missing = sorted(set(expected) - observed)
    added = sorted(observed - set(expected))
    result = {
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source_root),
        "manifest_files": len(expected),
        "current_files": len(observed),
        "missing_files": missing,
        "added_files": added,
        "changed_size": changed_size,
        "changed_mtime": changed_mtime,
        "unchanged": not (missing or added or changed_size or changed_mtime),
        "scope": "paths, sizes, and last-write timestamps compared with the full SHA-256 inventory; no source files were written",
    }
    output = PROJECT_ROOT / "reports" / "original_source_verification.json"
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only comparison of the original source tree to the saved SHA-256 inventory.")
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    result = verify(args.source_root)
    print(json.dumps({key: result[key] for key in ("manifest_files", "current_files", "unchanged", "missing_files", "added_files", "changed_size", "changed_mtime")}, ensure_ascii=False, indent=2))
    return 0 if result["unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
