"""Manifest-bounded local evidence inventory for Mission Pack E03."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3
from typing import Any

from src.agent import coordinator_runtime


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_GROUPS = (
    "SW",
    "OPEL NCDx Italia 2010-2011",
    "OPEL NCDx Scandinavia 2010-2011",
)
SECTOR_EXTENSIONS = frozenset({
    ".ISO", ".IMG", ".CUE", ".NRG", ".CCD", ".MDF", ".MDS", ".RAW", ".CIF", ".FCD",
})
LARGE_RAW_IMAGE_MIN_BYTES = 64 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _safe_source(root: Path, relative: str) -> Path:
    parsed = PurePosixPath(relative.replace("\\", "/"))
    if parsed.is_absolute() or ".." in parsed.parts:
        raise RuntimeError(f"E03 manifest path is unsafe: {relative}")
    source = (root / Path(*parsed.parts)).resolve(strict=True)
    if not source.is_relative_to(root) or not source.is_file():
        raise RuntimeError(f"E03 source escaped the read-only original tree: {relative}")
    return source


def build_e03_optical_layout_evidence(
    *,
    source_root: Path | None = None,
    project_root: Path | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Prove available optical-source evidence and park honestly if sectors are absent."""
    root = Path(source_root or coordinator_runtime.SOURCE_ROOT).resolve(strict=True)
    project = Path(project_root or PROJECT_ROOT).resolve(strict=True)
    ledger = Path(ledger_path or project / "EVIDENCE_LEDGER.sqlite").resolve(strict=True)
    placeholders = ",".join("?" for _ in SOURCE_GROUPS)
    with closing(sqlite3.connect(f"file:{ledger.as_posix()}?mode=ro", uri=True, timeout=30)) as conn:
        rows = conn.execute(
            f"SELECT source_group,source_path,sha256,size_bytes,extension FROM artifacts "
            f"WHERE source_group IN ({placeholders}) ORDER BY source_group,source_path",
            SOURCE_GROUPS,
        ).fetchall()
    if not rows:
        raise RuntimeError("E03 original-source groups are absent from EVIDENCE_LEDGER")
    groups_count: dict[str, int] = {group: 0 for group in SOURCE_GROUPS}
    source_records: list[dict[str, Any]] = []
    sector_candidates: list[dict[str, Any]] = []
    version_record: dict[str, Any] | None = None
    version_lines: list[str] = []
    for group, raw_path, raw_sha, raw_size, raw_extension in rows:
        relative = str(raw_path).replace("\\", "/").strip("/")
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or ".." in parsed.parts or not raw_sha:
            raise RuntimeError(f"E03 ledger contains an unsafe or unhashed source path: {relative}")
        groups_count[str(group)] += 1
        extension = str(raw_extension or Path(relative).suffix).upper()
        size = int(raw_size or 0)
        role = "manifest_only"
        if extension in SECTOR_EXTENSIONS or (extension == ".BIN" and size >= LARGE_RAW_IMAGE_MIN_BYTES):
            role = "possible_sector_image_by_extension_and_size"
        elif relative.casefold().endswith("/cdrom.toc") or relative.casefold() == "sw/cdrom.toc":
            role = "textual_cdrom_toc_metadata"
        elif relative.casefold() == "sw/version.txt":
            role = "textual_firmware_filesystem_requirement"
        else:
            continue
        source = _safe_source(root, relative)
        before = source.stat()
        if before.st_size != size or _sha256(source) != str(raw_sha).lower():
            raise RuntimeError(f"E03 source differs from its evidence-ledger entry: {relative}")
        after = source.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise RuntimeError(f"E03 source changed during the read-only inventory: {relative}")
        record = {
            "source_group": str(group),
            "source_path": parsed.as_posix(),
            "extension": extension,
            "size_bytes": size,
            "sha256": str(raw_sha).lower(),
            "role": role,
        }
        source_records.append(record)
        if role == "possible_sector_image_by_extension_and_size":
            sector_candidates.append(record)
        elif role == "textual_firmware_filesystem_requirement":
            if size > 16 * 1024:
                raise RuntimeError("E03 VERSION.TXT exceeds its bounded 16 KiB text limit")
            text = source.read_text(encoding="cp1252", errors="replace")
            version_lines = [
                line.strip() for line in text.splitlines()
                if "filesystem" in line.casefold() or "iso9660" in line.casefold()
                or "long filename" in line.casefold()
            ]
            if not any("iso9660 level 2" in line.casefold() for line in version_lines):
                raise RuntimeError("E03 VERSION.TXT no longer contains the documented ISO9660 level 2 requirement")
            version_record = record

    source_records.sort(key=lambda row: (row["source_group"].casefold(), row["source_path"].casefold()))
    sector_candidates.sort(key=lambda row: (row["source_group"].casefold(), row["source_path"].casefold()))
    source_fingerprint = hashlib.sha256(json.dumps(source_records, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    status = "WAITING_EXTERNAL" if not sector_candidates else "WAITING_LOCAL"
    reason = (
        "No manifest-backed optical sector image or cue/track image is present in the three original source groups; "
        "CDROM.TOC and VERSION.TXT are text metadata, not sector-layout proof. Supply a read-only sector image or cue/bin pair."
        if not sector_candidates else
        "Image-like inputs exist, but no bounded local sector-layout parser is registered; keep them read-only and add a tested parser."
    )
    evidence = {
        "schema": "ncdr.e03.optical-layout-evidence.v1",
        "canonical_id": "E03",
        "status": status,
        "source_groups": list(SOURCE_GROUPS),
        "ledger_entry_count_by_group": groups_count,
        "source_fingerprint": source_fingerprint,
        "inspected_metadata_sources": source_records,
        "sector_image_candidates": sector_candidates,
        "sector_image_candidate_count": len(sector_candidates),
        "version_requirement_lines": version_lines,
        "filesystem_requirement_classification": (
            "DOCUMENTED_REQUIREMENT_ONLY" if version_lines else "NOT_FOUND"
        ),
        "track_layout": "NOT_PROVEN",
        "sector_geometry": "NOT_PROVEN",
        "physical_compatibility": "NOT_TESTED",
        "original_media_write_count": 0,
        "reason": reason,
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    output = project / "evidence" / "optical-layout-proof.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    resolved = output.resolve()
    if not resolved.is_relative_to(project):
        raise RuntimeError("E03 artifact path escaped the project root")
    if resolved.exists():
        old = resolved.read_bytes()
        archive_dir = (project / "work" / "autonomous_manager" / "mission_pack" / "history").resolve()
        archive_dir.mkdir(parents=True, exist_ok=True)
        if not archive_dir.is_relative_to((project / "work" / "autonomous_manager").resolve()):
            raise RuntimeError("E03 prior-artifact archive escaped manager work")
        old_hash = hashlib.sha256(old).hexdigest()
        archive = archive_dir / f"E03-optical-layout-{old_hash[:16]}.json"
        if archive.exists() and _sha256(archive) != old_hash:
            raise RuntimeError("E03 prior-artifact archive hash collision")
        if not archive.exists():
            archive.write_bytes(old)
    temp = resolved.with_suffix(".json.tmp")
    temp.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(resolved)
    return {
        "status": status,
        "reason": reason,
        "artifact_path": resolved.relative_to(project).as_posix(),
        "artifact_sha256": _sha256(resolved),
        "source_fingerprint": source_fingerprint,
        "source_group_count": len(SOURCE_GROUPS),
        "source_entry_count": sum(groups_count.values()),
        "inspected_metadata_count": len(source_records),
        "sector_image_candidate_count": len(sector_candidates),
        "filesystem_requirement_classification": evidence["filesystem_requirement_classification"],
        "track_layout": evidence["track_layout"],
        "sector_geometry": evidence["sector_geometry"],
        "original_media_write_count": 0,
    }
