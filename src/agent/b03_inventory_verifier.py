"""Independent readback verifier for Mission Pack B03 firmware inventory."""

from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3
import struct
from typing import Any
import zlib

from src.agent import coordinator_runtime


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_EXTENSIONS = frozenset({".ABS", ".BIN", ".DLL", ".EXE", ".HEX"})
ARCHITECTURES = {
    0x014C: "x86", 0x01A6: "SH4", 0x01C0: "ARM",
    0x01C2: "ARM or Thumb", 0x01C4: "ARMNT", 0x8664: "x86-64", 0xAA64: "ARM64",
}


def _magic(prefix: bytes) -> str:
    if prefix.startswith(b"MZ"):
        return "DOS_MZ"
    if prefix.startswith(b"\x7fELF"):
        return "ELF"
    if prefix.startswith(b"PK\x03\x04"):
        return "ZIP_LOCAL_HEADER"
    return "UNKNOWN_PREFIX"


def _independent_pe_summary(raw: bytes) -> tuple[str, dict[str, Any] | None]:
    """Parse only PE header facts with a separate bounded implementation."""
    if len(raw) < 64 or raw[:2] != b"MZ":
        return "NOT_MZ", None
    try:
        offset = struct.unpack_from("<I", raw, 0x3C)[0]
        if offset < 64 or offset + 24 > len(raw) or raw[offset:offset + 4] != b"PE\x00\x00":
            return "INVALID_BOUNDED_PE", None
        machine = struct.unpack_from("<H", raw, offset + 4)[0]
        sections = struct.unpack_from("<H", raw, offset + 6)[0]
        optional_size = struct.unpack_from("<H", raw, offset + 20)[0]
        optional = offset + 24
        if not 1 <= sections <= 96 or optional_size < 70 or optional + optional_size > len(raw):
            return "INVALID_BOUNDED_PE", None
        if optional + optional_size + sections * 40 > len(raw):
            return "INVALID_BOUNDED_PE", None
        kind = struct.unpack_from("<H", raw, optional)[0]
        if kind not in {0x10B, 0x20B}:
            return "INVALID_BOUNDED_PE", None
        base_at = optional + (28 if kind == 0x10B else 24)
        base_width = 4 if kind == 0x10B else 8
        if base_at + base_width > optional + optional_size:
            return "INVALID_BOUNDED_PE", None
        image_base = int.from_bytes(raw[base_at:base_at + base_width], "little")
        parsed = {
            "pe_offset": offset,
            "machine_code": machine,
            "architecture": ARCHITECTURES.get(machine, "UNKNOWN_MACHINE"),
            "section_count": sections,
            "optional_header_magic": kind,
            "optional_header_kind": "PE32" if kind == 0x10B else "PE32+",
            "image_base": image_base,
            "size_of_image": struct.unpack_from("<I", raw, optional + 56)[0],
            "subsystem_code": struct.unpack_from("<H", raw, optional + 68)[0],
        }
        return "PASS_PE_HEADERS", parsed
    except (struct.error, IndexError, OverflowError):
        return "INVALID_BOUNDED_PE", None


def verify_b03_binary_format_inventory(
    inventory_path: Path,
    *,
    source_root: Path | None = None,
    project_root: Path | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Compare saved claims with the exact ledger set and fresh source readback."""
    project = Path(project_root or PROJECT_ROOT).resolve(strict=True)
    root = Path(source_root or coordinator_runtime.SOURCE_ROOT).resolve(strict=True)
    ledger = Path(ledger_path or project / "EVIDENCE_LEDGER.sqlite").resolve(strict=True)
    report = Path(inventory_path).resolve(strict=True)
    if not report.is_relative_to(project):
        raise RuntimeError("B03 inventory artifact escaped the project")
    saved = json.loads(report.read_text(encoding="utf-8"))
    if (
        saved.get("schema") != "ncdr.b03.binary-format-inventory.v1"
        or saved.get("canonical_id") != "B03"
        or saved.get("status") != "PASS"
        or saved.get("original_media_write_count") != 0
    ):
        raise RuntimeError("B03 inventory schema or read-only claim is invalid")

    with closing(sqlite3.connect(f"file:{ledger.as_posix()}?mode=ro", uri=True, timeout=30)) as conn:
        ledger_rows = conn.execute(
            "SELECT source_path,sha256,size_bytes,extension FROM artifacts "
            "WHERE source_group='SW' ORDER BY source_path"
        ).fetchall()
    expected: dict[str, dict[str, Any]] = {}
    for raw_path, raw_sha, raw_size, raw_extension in ledger_rows:
        relative = str(raw_path).replace("\\", "/").strip("/")
        parsed = PurePosixPath(relative)
        extension = str(raw_extension or Path(relative).suffix).upper()
        if (
            not relative.casefold().startswith("sw/")
            or parsed.is_absolute()
            or ".." in parsed.parts
            or extension not in ALLOWED_EXTENSIONS
            or not raw_sha
            or int(raw_size or 0) <= 0
            or int(raw_size or 0) > 32 * 1024 * 1024
        ):
            continue
        expected[parsed.as_posix()] = {
            "sha256": str(raw_sha).lower(),
            "size_bytes": int(raw_size),
            "extension": extension,
        }

    components = saved.get("components")
    if (
        not isinstance(components, list)
        or len(components) != len(expected)
        or saved.get("component_count") != len(expected)
    ):
        raise RuntimeError("B03 inventory does not match the complete bounded ledger set")
    seen: set[str] = set()
    pe_count = 0
    architectures: dict[str, int] = {}
    nk_included = False
    for item in components:
        if not isinstance(item, dict):
            raise RuntimeError("B03 inventory contains a non-object component")
        relative = str(item.get("source_path", ""))
        parsed = PurePosixPath(relative)
        if (
            relative not in expected
            or relative in seen
            or parsed.is_absolute()
            or ".." in parsed.parts
            or not relative.casefold().startswith("sw/")
        ):
            raise RuntimeError(f"B03 inventory contains an unmanifested or repeated path: {relative}")
        seen.add(relative)
        manifest = expected[relative]
        source = (root / Path(*parsed.parts)).resolve(strict=True)
        if not source.is_relative_to(root) or not source.is_file():
            raise RuntimeError(f"B03 source escaped the original read-only tree: {relative}")
        before = source.stat()
        if before.st_size != manifest["size_bytes"]:
            raise RuntimeError(f"B03 source size differs from its ledger entry: {relative}")
        digest = hashlib.sha256()
        crc = 0
        prefix = b""
        with source.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                if len(prefix) < 16:
                    prefix += block[:16 - len(prefix)]
                digest.update(block)
                crc = zlib.crc32(block, crc)
        after = source.stat()
        sha256 = digest.hexdigest()
        if (
            sha256 != manifest["sha256"]
            or item.get("source_manifest_sha256") != manifest["sha256"]
            or item.get("sha256") != sha256
            or item.get("size_bytes") != after.st_size
            or item.get("extension") != manifest["extension"]
            or item.get("crc32") != f"{crc & 0xffffffff:08x}"
            or item.get("prefix_hex") != prefix.hex()
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise RuntimeError(f"B03 independent source hash/CRC/stat check failed: {relative}")
        if (item.get("analysis_tool") != "ncdx_binary_headers.inspect_pe_headers v1"
                or item.get("semantic_format") != "UNKNOWN; observed signatures/header fields only"):
            raise RuntimeError(f"B03 tool or semantic-scope claim is invalid: {relative}")
        magic = _magic(prefix)
        if item.get("magic_observation") != magic:
            raise RuntimeError(f"B03 magic claim differs from independent readback: {relative}")
        if magic == "DOS_MZ":
            pe_status, pe = _independent_pe_summary(source.read_bytes())
        else:
            pe_status, pe = "NOT_MZ", None
        if item.get("pe_status") != pe_status or item.get("pe_headers") != pe:
            raise RuntimeError(f"B03 PE claim differs from the independent parser: {relative}")
        if pe_status == "PASS_PE_HEADERS":
            pe_count += 1
            architecture = str(pe["architecture"])
            architectures[architecture] = architectures.get(architecture, 0) + 1
        nk_included = nk_included or relative.casefold().endswith("/nk.bin")

    if seen != set(expected):
        raise RuntimeError("B03 inventory omitted one or more manifest-backed SW components")
    if not nk_included:
        raise RuntimeError("B03 inventory omitted NK.BIN")
    fingerprint = hashlib.sha256(json.dumps(
        [{"source_path": item["source_path"], "size_bytes": item["size_bytes"], "sha256": item["sha256"]}
         for item in components], sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if saved.get("inventory_fingerprint") != fingerprint:
        raise RuntimeError("B03 inventory fingerprint does not match its source set")
    return {
        "independent_source_readback": "PASS",
        "component_count": len(seen),
        "pe_header_count": pe_count,
        "architecture_counts": architectures,
        "nk_bin_included": True,
        "original_media_write_count": 0,
        "semantic_formats_proven": [],
    }
