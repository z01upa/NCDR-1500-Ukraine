# Tooling and reproducibility

## Reproduce the byte-structure checks

From the `NCDR_MAP_RESEARCH` root:

```powershell
python .\research\geometry_breakthrough\xip_extract_v9\scripts\inspect_nk_format.py `
  '${NCDR_SOURCE_ROOT}\SW\LK841\HU_HARDWARE_LOC_0000000001\HU_KERNEL_LOC_0101000870\NK.BIN' `
  --json .\research\geometry_breakthrough\xip_extract_v9\evidence\nk_format_probe.json

python .\research\geometry_breakthrough\xip_extract_v9\scripts\verify_results.py `
  '${NCDR_SOURCE_ROOT}\SW\LK841\HU_HARDWARE_LOC_0000000001\HU_KERNEL_LOC_0101000870\NK.BIN' `
  --root .\research\geometry_breakthrough\xip_extract_v9
```

The first script only reads NK.BIN and writes the JSON evidence file. The second hashes the original, checks that no accepted ROMHDR/TOC appeared, and verifies that the two extractor output folders contain no files. A `PASS` from the second script means the negative finding and input integrity are reproducible; it does **not** mean the target modules were extracted.

## Bounded upstream parser attempt

The evaluated source was `https://github.com/gweslab/extract-wince-rom` at commit `5eedf30beced801fa753b9ab693cd06bb5068133`; downloaded archive SHA-256: `DEB991CAE7745C5A5697AA43921A776D14F5EBF99B016B77A46D13B8353A3D3E`.

Its dependency was `https://github.com/KodaSec/wince-decompr` at commit `d08163aeda0dec22dbcc363dabf80606413d119c`; archive SHA-256: `AEDC161C5367283F855FDD9CB10DBDD2F251C9FAE31769B693B0190683C56AE4`.

The parser removes an existing output directory before extraction, so both actual runs used new, explicit output paths. The source repository has no license declared in its GitHub metadata; to avoid redistributing it, only the tool name, pinned commit, hashes, and actual logs are retained here. The script outputs in this directory do not depend on that parser.
