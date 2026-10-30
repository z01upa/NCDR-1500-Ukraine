# NK.BIN format findings

## Scope

Input was read-only:

`${NCDR_SOURCE_ROOT}\SW\LK841\HU_HARDWARE_LOC_0000000001\HU_KERNEL_LOC_0101000870\NK.BIN`

Size: **11,021,915 bytes**. SHA-256 before and after this work: `d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847`.

The original begins with the text `LK-01-05-000.000.0000`. This is recorded as an observed prefix only; no meaning is assigned to it.

## Standard Windows CE layout checks

The open `extract-wince-rom` parser was tried with `--fs=no --sections=no`, both with and without a SH4 override, each time using a new output directory. It classified the file as an unrecognized flat/NB0 image and found **zero resolved XIP regions**. Its output directories remained empty. Its successful process exit means only that the CLI completed; it did not mean parsing or extraction succeeded. Exact logs are in `evidence/`.

Additional read-only checks are reproducible with `scripts/inspect_nk_format.py`:

| Check | Observation | Interpretation |
|---|---|---|
| Standard B000FF signature at file offset 0 | Absent | Not a direct B000FF container |
| Windows CE 1.x detector in the tried parser | False | No supported CE1 layout recognized |
| `CE00FF\n` at `0x400` | Present | Marker only; not treated as proof of format |
| Candidate little-endian values after that marker | `start=0x1F00000B`, `length=0x10BE248C` | Length exceeds remaining image; not a consistent standard B000FF header |
| Raw `ECEC` occurrence | One at `0x9CEAD3`, offset modulo 4 is 3 | Unaligned occurrence alone does not validate an XIP region |
| `ECEC+4` | `0x8D2F66CC` | Falls in a CE kernel VA range, but pointer alone is insufficient |
| `ECEC+8` | `0x025A4543` | As a ROMHDR offset it resolves outside this file |
| Resolved ROMHDR/XIP regions | 0 | No region accepted |

The upstream parser's as-stored ECEC calculation yields ROMHDR file offset `0x02F72FD6`, outside the 11 MB input. When `ECEC+8` is treated explicitly as absent, the standard address derivations produce offsets `0x8D2F66CC`, `0x0D2F66CC`, and `0x002F66CC`. The first two are outside the image; the in-file candidate at `0x002F66CC` fails ROMHDR field checks.

## Structural scan and false positive

A four-byte-aligned scan found **one weak ROMHDR-shaped numeric candidate** at file offset `0x009D7794`. Its physical span and module/file counts pass coarse numeric bounds, but its contents do not resolve as a ROMHDR+TOC:

- `nummods=150`, `numfiles=16647`, `usCPUType=0x0661`.
- RAM fields are inconsistent: `ulRAMStart=0x02D74543`, `ulRAMFree=0x8C2EC600`, `ulRAMEnd=0x00000A00`.
- The arithmetic TOC window fits in the file, but **0 of the first 32 names are printable**, `nk.exe` is absent, and the sample name pointers translate to negative/out-of-image offsets.

This candidate is rejected. It is not evidence for a module table or CPU type. Full fields and sample TOC entries are retained in `evidence/nk_format_probe.json`.

## Conclusion

The available `NK.BIN` is **not yet structurally identified** as a standard B000FF, NB0/XIP, or CE1 image by the checks performed. The evidence instead points to an unparsed Siemens/OEM wrapper or another custom representation. The exact outer format and the address mapping from the image to a Windows CE ROMHDR remain unknown.

Do not infer ROMHDR, TOC, XIP, or module boundaries from `CE00FF`, `ECEC`, or the `LK-01-05` prefix alone.
