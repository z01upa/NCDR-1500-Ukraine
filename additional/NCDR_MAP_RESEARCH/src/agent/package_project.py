"""Create a source-only project snapshot with persisted SQLite checkpoints."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = PROJECT_ROOT.parents[1] / "outputs" / "NCDR_MAP_RESEARCH.zip"
EXCLUDED_PARTS = {".git", "__pycache__", ".pytest_cache"}


def should_include(path: Path) -> bool:
    relative = path.relative_to(PROJECT_ROOT)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if relative.parts and relative.parts[0].startswith("tmp"):
        return False
    if path.suffix in {".pyc", ".pyo"} or path.name.endswith(("-wal", "-shm", "-journal")):
        return False
    return True


def checkpoint_databases() -> None:
    for path in PROJECT_ROOT.glob("*.sqlite"):
        conn = sqlite3.connect(path)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            check = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError(f"{path.name} failed integrity_check: {check}")
        finally:
            conn.close()


def package() -> dict[str, object]:
    checkpoint_databases()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    files = [path for path in PROJECT_ROOT.rglob("*") if path.is_file() and should_include(path)]
    with zipfile.ZipFile(OUTPUT_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(files):
            archive.write(path, Path("NCDR_MAP_RESEARCH") / path.relative_to(PROJECT_ROOT))
    with zipfile.ZipFile(OUTPUT_PATH) as archive:
        names = archive.namelist()
        if any("Desktop" in name or "original_readonly/" in name and not name.endswith("README.md") for name in names):
            raise RuntimeError("archive unexpectedly contains original-source files")
    return {"path": str(OUTPUT_PATH), "files": len(files), "bytes": OUTPUT_PATH.stat().st_size,
            "original_source_files_included": 0}


if __name__ == "__main__":
    import json

    print(json.dumps(package(), ensure_ascii=False, indent=2))
