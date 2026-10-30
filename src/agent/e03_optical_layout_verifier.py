"""Independent source and claim verifier for Mission Pack E03 evidence."""

from __future__ import annotations

from contextlib import closing
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


def _read_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _read_only_file(root: Path, relative: str) -> Path:
    parsed = PurePosixPath(relative.replace("\\", "/"))
    if parsed.is_absolute() or ".." in parsed.parts:
        raise RuntimeError(f"E03 proof contains an unsafe source path: {relative}")
    source = (root / Path(*parsed.parts)).resolve(strict=True)
    if not source.is_relative_to(root) or not source.is_file():
        raise RuntimeError(f"E03 proof source escaped the original root: {relative}")
    return source


def verify_e03_optical_layout_evidence(
    artifact_path: Path,
    *,
    source_root: Path | None = None,
    project_root: Path | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Recompute the candidate census and source hashes without trusting the builder."""
    project = Path(project_root or PROJECT_ROOT).resolve(strict=True)
    root = Path(source_root or coordinator_runtime.SOURCE_ROOT).resolve(strict=True)
    ledger = Path(ledger_path or project / "EVIDENCE_LEDGER.sqlite").resolve(strict=True)
    artifact = Path(artifact_path).resolve(strict=True)
    if not artifact.is_relative_to(project):
        raise RuntimeError("E03 artifact escaped the current project")
    saved = json.loads(artifact.read_text(encoding="utf-8"))
    if (
        saved.get("schema") != "ncdr.e03.optical-layout-evidence.v1"
        or saved.get("canonical_id") != "E03"
        or saved.get("status") != "WAITING_EXTERNAL"
        or saved.get("original_media_write_count") != 0
        or saved.get("track_layout") != "NOT_PROVEN"
        or saved.get("sector_geometry") != "NOT_PROVEN"
        or saved.get("physical_compatibility") != "NOT_TESTED"
    ):
        raise RuntimeError("E03 evidence overstates its status or violates the read-only claim boundary")
    placeholders = ",".join("?" for _ in SOURCE_GROUPS)
    with closing(sqlite3.connect(f"file:{ledger.as_posix()}?mode=ro", uri=True, timeout=30)) as conn:
        rows = conn.execute(
            f"SELECT source_group,source_path,sha256,size_bytes,extension FROM artifacts "
            f"WHERE source_group IN ({placeholders}) ORDER BY source_group,source_path",
            SOURCE_GROUPS,
        ).fetchall()
    if not rows:
        raise RuntimeError("E03 original-source groups are absent from the manifest")
    group_counts = {group: 0 for group in SOURCE_GROUPS}
    expected_sources: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    version_requirement_lines: list[str] = []
    for group, raw_path, raw_sha, raw_size, raw_extension in rows:
        relative = str(raw_path).replace("\\", "/").strip("/")
        parsed = PurePosixPath(relative)
        extension = str(raw_extension or Path(relative).suffix).upper()
        size = int(raw_size or 0)
        if parsed.is_absolute() or ".." in parsed.parts or not raw_sha:
            raise RuntimeError(f"E03 manifest entry is not safe and hashed: {relative}")
        group_counts[str(group)] += 1
        role = "manifest_only"
        if extension in SECTOR_EXTENSIONS or (extension == ".BIN" and size >= LARGE_RAW_IMAGE_MIN_BYTES):
            role = "possible_sector_image_by_extension_and_size"
        elif relative.casefold().endswith("/cdrom.toc") or relative.casefold() == "sw/cdrom.toc":
            role = "textual_cdrom_toc_metadata"
        elif relative.casefold() == "sw/version.txt":
            role = "textual_firmware_filesystem_requirement"
        else:
            continue
        source = _read_only_file(root, relative)
        before = source.stat()
        if before.st_size != size or _read_hash(source) != str(raw_sha).lower():
            raise RuntimeError(f"E03 source readback differs from the manifest: {relative}")
        after = source.stat()
        if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            raise RuntimeError(f"E03 source changed while independently verifying: {relative}")
        record = {
            "source_group": str(group),
            "source_path": parsed.as_posix(),
            "extension": extension,
            "size_bytes": size,
            "sha256": str(raw_sha).lower(),
            "role": role,
        }
        expected_sources.append(record)
        if role == "possible_sector_image_by_extension_and_size":
            candidates.append(record)
        elif role == "textual_firmware_filesystem_requirement":
            if size > 16 * 1024:
                raise RuntimeError("E03 VERSION.TXT exceeds independent verifier size limit")
            text = source.read_text(encoding="cp1252", errors="replace")
            version_requirement_lines = [
                line.strip() for line in text.splitlines()
                if "filesystem" in line.casefold() or "iso9660" in line.casefold()
                or "long filename" in line.casefold()
            ]
    expected_sources.sort(key=lambda row: (row["source_group"].casefold(), row["source_path"].casefold()))
    candidates.sort(key=lambda row: (row["source_group"].casefold(), row["source_path"].casefold()))
    if saved.get("ledger_entry_count_by_group") != group_counts:
        raise RuntimeError("E03 source-group manifest counts differ on independent readback")
    if saved.get("inspected_metadata_sources") != expected_sources:
        raise RuntimeError("E03 metadata/image source list differs from the source ledger")
    if saved.get("sector_image_candidates") != candidates or candidates:
        raise RuntimeError("E03 WAITING_EXTERNAL claim is invalid: image candidates exist or were omitted")
    if saved.get("sector_image_candidate_count") != 0:
        raise RuntimeError("E03 sector-image candidate count is not zero")
    if saved.get("version_requirement_lines") != version_requirement_lines:
        raise RuntimeError("E03 filesystem requirement text differs from the source readback")
    if (saved.get("filesystem_requirement_classification") != "DOCUMENTED_REQUIREMENT_ONLY"
            or not any("iso9660 level 2" in line.casefold() for line in version_requirement_lines)
            or not any("long filenames up to 30 characters" in line.casefold()
                       for line in version_requirement_lines)):
        raise RuntimeError("E03 VERSION.TXT requirement is absent or was promoted beyond documented-only")
    fingerprint = hashlib.sha256(json.dumps(expected_sources, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    if saved.get("source_fingerprint") != fingerprint:
        raise RuntimeError("E03 optical evidence fingerprint differs from the actual source set")
    if "No manifest-backed optical sector image" not in str(saved.get("reason", "")):
        raise RuntimeError("E03 external blocker lacks a concrete sector-image requirement")
    return {
        "independent_manifest_readback": "PASS",
        "source_group_count": len(SOURCE_GROUPS),
        "source_entry_count": sum(group_counts.values()),
        "metadata_source_count": len(expected_sources),
        "sector_image_candidate_count": 0,
        "version_requirement": "ISO9660 level 2; long filenames up to 30 characters; documented requirement only",
        "track_layout": "NOT_PROVEN",
        "sector_geometry": "NOT_PROVEN",
        "original_media_write_count": 0,
    }
