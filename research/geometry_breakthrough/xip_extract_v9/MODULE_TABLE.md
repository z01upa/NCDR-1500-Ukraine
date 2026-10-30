# Module table findings

## Result

No genuine TOC row for `NavigationRem.dll` or `nmicore_ce.dll` was recovered. No valid ROMHDR was found, so the module count, TOC location, name-pointer base, `e32_rom`/`o32_rom` addresses, load addresses, and module byte ranges are unknown.

The only target evidence is a NUL-terminated raw filename string for each module:

| Name | File offset | Evidence status |
|---|---:|---|
| `NavigationRem.dll` | `0x009FA304` | Literal string only; no validated TOC row or code bytes |
| `nmicore_ce.dll` | `0x009FB1C8` | Literal string only; no validated TOC row or code bytes |

The existing `routing_owner_v8` inventory reports 74 module-looking filename strings in `0x009D0000–0x00A10000`. It explicitly classified them as candidate names, not TOC entries. The current checks do not upgrade that evidence.

## Why reconstruction was not attempted

Windows CE XIP reconstruction needs validated `e32_rom`/`o32_rom` records and a load-address mapping. Guessing module starts from string locations would risk treating arbitrary packed bytes as executable code. Neither target was emitted by the parser, and no PE or CE module container exists in the extraction output.

No module hash, PE machine type, imports, exports, code-section range, or SH4 disassembly is reported because there are no extracted module bytes to validate.
