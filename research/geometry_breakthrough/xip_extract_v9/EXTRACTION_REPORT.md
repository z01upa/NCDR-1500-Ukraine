# Extraction report

## Tool tried

The public `gweslab/extract-wince-rom` parser was evaluated at commit `5eedf30beced801fa753b9ab693cd06bb5068133`. It documents support for B000FF, flat NB0, ROMHDR/TOC, XIP PE reconstruction, and SH4 output selection. Its own README calls results best-effort and says some parser stages have not been independently verified. The repository declares no license in its metadata, so the source was used for this bounded evaluation but is not vendored here.

The required `wince-decompr` dependency was fetched at commit `d08163aeda0dec22dbcc363dabf80606413d119c` solely to run the parser. The dependency is MIT-licensed; neither downloaded source tree is retained in this research directory.

## Actual runs

Both commands used an explicit, previously absent output directory and did not write to the source image:

```text
python extract_wince_rom.py --fs=no --sections=no --machine=sh4 --output-dir <fresh-output> <NK.BIN>
python extract_wince_rom.py --fs=no --sections=no --output-dir <fresh-output> <NK.BIN>
```

Both completed with exit code 0, emitted `WARNING: Not a recognised format (sig=0x302D4B4C)`, selected the NB0 fallback, and emitted **zero files**. Neither found a resolved ROMHDR/XIP region. Logs:

- `evidence/extractor_parse_only.log`
- `evidence/extractor_parse_only_no_override.log`

The first command's `--machine=sh4` did not establish architecture; there was no module to which it could apply. The second run confirms that the result does not depend on that override.

## Outcome

`NavigationRem.dll` and `nmicore_ce.dll` were **not extracted**. This is a format-resolution blocker, not a failed SH4 disassembly. The next step is to recover the Siemens `LK-01-05` wrapper and prove a ROMHDR/TOC mapping before attempting module reconstruction.
