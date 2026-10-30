#!/usr/bin/env python3
"""Scoped, repeatable audit for the NCDR GitHub sync 085 change set."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
REPORT = HERE / "AUDIT_REPORT.json"
REQUESTED_DIRS = (
    "research/github_complete_sources_084",
    "research/routing_closure_v78",
    "research/index_producer_080",
    "research/index_forensics_079",
)
MISSING_COMMITS = ("249d656", "ca3a9c7", "165e24d")
FORBIDDEN_SUFFIXES = {".bin", ".mp0", ".rt", ".rl", ".euz", ".dll", ".exe", ".rom", ".sqlite", ".sqlite3", ".db"}
TEXT_SUFFIXES = {".md", ".json", ".py", ".txt", ".csv", ".toml", ".yaml", ".yml"}
LOCAL_PATH_RE = re.compile(r"(?i)[A-Z]:[\\/](?:Users|Documents|home)[\\/]")
SECRET_RE = re.compile(
    r"(?i)(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"-----BEGIN (?:RSA|OPENSSH|EC) PRIVATE KEY-----)"
)
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def git(*args: str, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)
    if check and p.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout.strip()


def git_at(root: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True)
    if check and p.returncode:
        raise RuntimeError(f"git -C <local-worktree> {' '.join(args)} failed")
    return p.stdout.strip()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def changed_paths() -> list[str]:
    paths = set()
    for args in (("diff", "--name-only", "origin/main...HEAD"),
                 ("diff", "--name-only"),
                 ("ls-files", "--others", "--exclude-standard")):
        paths.update(p for p in git(*args).splitlines() if p)
    paths.add("research/github_sync_085/AUDIT_REPORT.json")
    return sorted(paths)


def verify_manifest(path: Path) -> tuple[list[dict], list[str], dict]:
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    results, errors = [], []
    for item in [*doc.get("source_files", []), *doc.get("disassembly_artifacts", [])]:
        p = Path(item["path"])
        exists = p.is_file()
        size_ok = exists and p.stat().st_size == item["bytes"]
        hash_ok = exists and digest(p) == item["sha256"].lower()
        results.append({
            "name": item.get("name", p.name), "present": exists,
            "size_bytes": item["bytes"] if size_ok else (p.stat().st_size if exists else None),
            "size_match": bool(size_ok), "sha256": item["sha256"].lower(),
            "sha256_match": bool(hash_ok),
            "distribution": item.get("distribution", "LOCAL_ONLY"),
        })
        if not exists or not size_ok or not hash_ok:
            errors.append(f"local source check failed: {item.get('name', p.name)}")
    return results, errors, doc.get("full_module_disassembly", {})


def summarize_active_worktree(path: Path) -> dict:
    root_text = git_at(path, "rev-parse", "--show-toplevel", check=False)
    if not root_text:
        return {"git_repository": False}
    root = Path(root_text)
    status = git_at(root, "status", "--porcelain=v1").splitlines()
    branches = git_at(root, "branch", "--format=%(refname:short) %(objectname)").splitlines()
    remotes = git_at(root, "remote").splitlines()
    object_status = {}
    for h in MISSING_COMMITS:
        p = subprocess.run(["git", "-C", str(root), "cat-file", "-t", h],
                           text=True, capture_output=True)
        object_status[h] = p.stdout.strip() if p.returncode == 0 else "MISSING"
    return {
        "git_repository": True,
        "checkout_name": root.name,
        "branch": git_at(root, "branch", "--show-current"),
        "remote_names": remotes,
        "dirty": bool(status),
        "modified_or_staged_entries": sum(1 for s in status if not s.startswith("??")),
        "untracked_entries": sum(1 for s in status if s.startswith("??")),
        "local_branches": branches,
        "requested_commit_objects": object_status,
        "requested_directories": {p: (root / p).is_dir() for p in REQUESTED_DIRS},
        "actual_v78_directory": {
            "research/geometry_breakthrough/routing_closure_v78":
                (root / "research/geometry_breakthrough/routing_closure_v78").is_dir()
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-manifest", type=Path)
    ap.add_argument("--active-worktree", type=Path)
    args = ap.parse_args()
    errors: list[str] = []
    paths = changed_paths()
    present = [p for p in paths if (ROOT / p).is_file()]
    json_checked, markdown_checked, binary_files, secret_hits, path_hits = [], [], [], [], []
    link_errors = []
    for rel in present:
        p = ROOT / rel
        if p.suffix.lower() in FORBIDDEN_SUFFIXES:
            binary_files.append(rel)
        if p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if SECRET_RE.search(text):
            secret_hits.append(rel)
        if LOCAL_PATH_RE.search(text):
            path_hits.append(rel)
        if p.suffix.lower() == ".json":
            json.loads(text)
            json_checked.append(rel)
        if p.suffix.lower() == ".md":
            markdown_checked.append(rel)
            for target in LINK_RE.findall(text):
                target = target.strip().split()[0].strip("<>")
                parsed = urlsplit(target)
                if parsed.scheme or not parsed.path:
                    continue
                dest = unquote(parsed.path)
                candidate = (ROOT / dest.lstrip("/")) if dest.startswith("/") else (p.parent / dest)
                if not candidate.exists():
                    link_errors.append({"source": rel, "target": target})
    if binary_files:
        errors.append("original/binary files found in scoped change set")
    if secret_hits:
        errors.append("secret pattern found in scoped change set")
    if path_hits:
        errors.append("local absolute path found in scoped change set")
    if link_errors:
        errors.append("broken local Markdown link found in scoped change set")

    commit_objects = {}
    for h in MISSING_COMMITS:
        p = subprocess.run(["git", "cat-file", "-t", h], cwd=ROOT, text=True, capture_output=True)
        commit_objects[h] = p.stdout.strip() if p.returncode == 0 else "MISSING"

    requested = {p: (ROOT / p).is_dir() for p in REQUESTED_DIRS}
    v78_path = "research/geometry_breakthrough/routing_closure_v78"
    refs = {}
    remote = subprocess.run(["git", "ls-remote", "--heads", "origin"], cwd=ROOT,
                            text=True, capture_output=True)
    if remote.returncode == 0:
        for line in remote.stdout.splitlines():
            sha, ref = line.split(None, 1)
            name = ref.removeprefix("refs/heads/")
            if name in {"main", "codex/cover-xref-046", "codex/routing-closure-v78"}:
                refs[name] = sha
    else:
        errors.append("remote refs could not be checked")

    local_sources, manifest_errors, full_disassembly = [], [], {"status": "NOT_CHECKED"}
    if args.source_manifest:
        local_sources, manifest_errors, full_disassembly = verify_manifest(args.source_manifest)
        errors.extend(manifest_errors)
    else:
        errors.append("local source manifest was not supplied")

    active_worktree = summarize_active_worktree(args.active_worktree) if args.active_worktree else {
        "status": "NOT_CHECKED"
    }

    report = {
        "schema_version": 1,
        "scope": "change set relative to origin/main plus local NCDR source manifest; no binaries uploaded",
        "branch": git("branch", "--show-current"),
        "origin_main": git("rev-parse", "origin/main"),
        "remote_heads": refs,
        "remote_heads_scope": "baseline refs only; the new sync branch is verified after push",
        "published_v78_commit_verified_remote": refs.get("codex/routing-closure-v78") ==
            "df645355eabab875cc57277d1c03ffb3a810b0f8",
        "requested_directories": requested,
        "actual_v78_directory": {v78_path: (ROOT / v78_path).is_dir()},
        "requested_commit_objects": commit_objects,
        "active_worktree": active_worktree,
        "changed_file_count": len(present),
        "changed_files": present,
        "json_parsed": json_checked,
        "markdown_link_check": {"files": markdown_checked, "broken": link_errors},
        "binary_files_in_change_set": binary_files,
        "secret_pattern_files": secret_hits,
        "local_absolute_path_files": path_hits,
        "local_sources": local_sources,
        "full_module_disassembly": full_disassembly,
        "errors": errors,
        "status": "PASS_WITH_BLOCKERS" if not errors else "FAIL",
        "limitations": [
            "Missing source packages/commit objects are recorded, not fabricated.",
            "No full NavigationRem.dll disassembly or hardware route test was performed.",
            "Binary distribution rights remain unverified; original binaries are withheld.",
        ],
    }
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "changed_files": len(present),
                      "json_parsed": len(json_checked), "manifest_files": len(local_sources),
                      "errors": errors, "report": REPORT.relative_to(ROOT).as_posix()},
                     ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
