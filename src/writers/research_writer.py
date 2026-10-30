"""Experimental byte-preserving copy and one-field MP0 header experiment.

All outputs are no-clobber working copies. The original is only opened in rb
mode. The controlled field experiment proves only that the known header reader
can read the changed header while every byte outside that field is preserved.
It does not claim the resulting map database is device-usable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

from src.readers.ncdx_mp0_header import DATASET_CODE, DATASET_CODE_OFFSET, FIELD_WIDTH, read_mp0_header

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _checked_paths(source: str | Path, destination: str | Path) -> tuple[Path, Path]:
    source_path = Path(source).resolve(strict=True)
    target_path = Path(destination).resolve()
    if source_path == target_path:
        raise ValueError("writer refuses an in-place operation")
    if target_path.exists():
        raise FileExistsError(f"refusing to overwrite working copy: {target_path}")
    if target_path.parent == source_path.parent and target_path.name.casefold() == source_path.name.casefold():
        raise ValueError("source and destination resolve to the same file")
    return source_path, target_path


def no_op_roundtrip(source: str | Path, destination: str | Path) -> dict[str, Any]:
    source_path, target_path = _checked_paths(source, destination)
    source_before = sha256_file(source_path)
    size_before = source_path.stat().st_size
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source_path.open("rb") as original, target_path.open("xb") as copy:
            shutil.copyfileobj(original, copy, length=1024 * 1024)
            copy.flush()
        copied_hash = sha256_file(target_path)
        source_after = sha256_file(source_path)
        result = {"source_path": str(source_path), "working_copy": str(target_path),
                  "source_sha256_before": source_before, "working_copy_sha256": copied_hash,
                  "source_sha256_after": source_after, "source_bytes": size_before,
                  "no_op_roundtrip_pass": source_before == copied_hash == source_after,
                  "readback_bytes": target_path.stat().st_size,
                  "claim_scope": "byte-for-byte no-op copy only; no NCDx write semantics inferred"}
        if not result["no_op_roundtrip_pass"] or result["readback_bytes"] != size_before:
            raise RuntimeError("no-op working-copy roundtrip failed SHA/size comparison")
        return result
    except BaseException:
        # The destination is an experiment output, never an original. Do not
        # publish a partial result if the copy failed.
        target_path.unlink(missing_ok=True)
        raise


def controlled_dataset_code_change(source: str | Path, destination: str | Path,
                                   replacement_code: str) -> dict[str, Any]:
    source_path, target_path = _checked_paths(source, destination)
    old_header = read_mp0_header(source_path)
    encoded = replacement_code.encode("ascii", "strict")
    if not DATASET_CODE.fullmatch(encoded):
        raise ValueError("replacement must match the confirmed fixed-width dataset-code shape")
    old = old_header.dataset_code.encode("ascii")
    if len(old) != len(encoded):
        raise ValueError("controlled experiment requires an equal-length replacement")
    source_before = sha256_file(source_path)
    prefix = bytearray()
    with source_path.open("rb") as original:
        prefix.extend(original.read(DATASET_CODE_OFFSET + FIELD_WIDTH))
    old_field = bytes(prefix[DATASET_CODE_OFFSET:DATASET_CODE_OFFSET+len(old)])
    if old_field != old:
        raise RuntimeError("reader output and raw dataset-code field disagree")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source_path.open("rb") as original, target_path.open("xb") as copy:
            offset = 0
            while chunk := original.read(1024 * 1024):
                start = max(DATASET_CODE_OFFSET, offset)
                end = min(DATASET_CODE_OFFSET + len(encoded), offset + len(chunk))
                if start < end:
                    mutable = bytearray(chunk)
                    mutable[start-offset:end-offset] = encoded[start-DATASET_CODE_OFFSET:end-DATASET_CODE_OFFSET]
                    chunk = bytes(mutable)
                copy.write(chunk)
                offset += len(chunk)
        new_header = read_mp0_header(target_path)
        target_hash = sha256_file(target_path)
        source_after = sha256_file(source_path)
        if new_header.dataset_code != replacement_code:
            raise RuntimeError("independent file readback did not parse the replacement dataset code")
        if source_before != source_after:
            raise RuntimeError("original source hash changed during the read-only experiment")
        # Verify every byte outside the explicitly modified ASCII field.
        differences: list[int] = []
        with source_path.open("rb") as original, target_path.open("rb") as copy:
            offset = 0
            while left := original.read(1024 * 1024):
                right = copy.read(len(left))
                if len(right) != len(left):
                    raise RuntimeError("working copy length changed")
                differences.extend(offset+i for i, (a, b) in enumerate(zip(left, right)) if a != b)
                offset += len(left)
        allowed = set(range(DATASET_CODE_OFFSET, DATASET_CODE_OFFSET+len(encoded)))
        outside = [offset for offset in differences if offset not in allowed]
        if outside:
            raise RuntimeError(f"unexpected changes outside dataset-code field: {outside[:12]}")
        return {"source_path": str(source_path), "working_copy": str(target_path),
            "source_sha256_before": source_before, "source_sha256_after": source_after,
            "working_copy_sha256": target_hash, "old_code": old_header.dataset_code,
            "new_code": new_header.dataset_code, "changed_offsets": differences,
            "changed_byte_count": len(differences), "field_offset": DATASET_CODE_OFFSET,
            "fixed_field_width": FIELD_WIDTH, "working_copy_header_readback": new_header.to_dict(),
            "controlled_change_pass": True,
            "claim_scope": "one confirmed header string changed on a copy; payload/device validity not asserted"}
    except BaseException:
        target_path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Experimental safe-copy NCDx writer tests")
    sub = parser.add_subparsers(dest="operation", required=True)
    copy_parser = sub.add_parser("roundtrip")
    copy_parser.add_argument("--source", type=Path, required=True)
    copy_parser.add_argument("--output", type=Path, required=True)
    change_parser = sub.add_parser("change-code")
    change_parser.add_argument("--source", type=Path, required=True)
    change_parser.add_argument("--output", type=Path, required=True)
    change_parser.add_argument("--new-code", required=True)
    args = parser.parse_args(argv)
    if args.operation == "roundtrip":
        result = no_op_roundtrip(args.source, args.output)
    else:
        result = controlled_dataset_code_change(args.source, args.output, args.new_code)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
