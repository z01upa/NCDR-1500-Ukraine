# Local source access

Original NCDR map and firmware/module files remain local. Their distribution rights are unverified, so this branch contains no copies of them. The local-only manifest records exact paths, sizes, and SHA-256 values; do not commit or upload that manifest.

Set these variables on a workstation that has the source files:

```powershell
$env:NCDR_SOURCE_ROOT = 'C:\path\to\local\NCDR'
$env:NCDR_RESEARCH_ROOT = 'C:\path\to\local\NCDR_MAP_RESEARCH'
```

The original files are resolved relative to `NCDR_SOURCE_ROOT`: `SW\LK841\HU_HARDWARE_LOC_0000000001\HU_KERNEL_LOC_0101000870\NK.BIN` and `SW\DB\EUZ.MP0`, `EUZ.RT`, `EUZ.RL`. `NavigationRem.dll`, `NavigationRem.dll.s0.stored.bin`, and partial analysis artifacts are resolved relative to `NCDR_RESEARCH_ROOT`. The stored section is proprietary binary data; `code_probe.json` contains function and cross-reference metadata, not a complete instruction listing. Open originals read-only and verify them against the local manifest before analysis. Missing inputs must remain missing; do not substitute empty files.

Run the repository audit from the checkout root with the private manifest path:

```powershell
python research\github_sync_085\audit_repo.py --source-manifest "$env:NCDR_RESEARCH_ROOT\research\github_sync_085\local_only\LOCAL_SOURCE_MANIFEST.json"
```

The audit report omits local absolute paths. Hardware compatibility and a complete module disassembly are not established by this package.
