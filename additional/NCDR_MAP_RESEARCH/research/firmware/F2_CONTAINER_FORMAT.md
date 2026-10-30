# Firmware RE F2 — container reconstruction

Static-only analysis of `tools/POISoN/patch.exe`; the executable was not run.

## Confirmed

- The target name is the exact lower-case module string `navboot` (patch.exe file offset `0x34A5`).
- A big-endian magic comparison accepts `4D AD 00 02` (`0x4DAD0002`) at code RVA `0x15B9`.
- The parser reads a big-endian size field at module-record offset `+0x04`, rejects sizes at or below `0x5C`, requires 4-byte alignment, and rejects records extending beyond the loaded buffer. These are code-supported invariants, not a complete outer-header reconstruction.
- Module names/types and body data are handled through an internal object/method model. The visible type labels are `program`, `subroutine`, `multi`, `data`, `configuration`, `trap library`, `system`, `file manager`, `device driver`, `device descriptor`, `user defined`, and `unknown`.
- The generic patch writer is module-relative, bounds-checks the computed address, compares an expected value, and writes replacement values in big-endian form.
- The CRC-like routine uses a table and XOR constant `0x800021`; its initial value, polynomial interpretation, bit order, covered range, final XOR, and stored CRC location are not proven by available code evidence.

## Not established

No complete outer-header field map, directory entry size, module directory offset, total-size field, version field, separate container/directory/module CRC scheme, padding-byte rule, or nested NAVBOOT executable header is recoverable with confidence from `patch.exe` alone. The strings and code do not provide a fixed firmware filename, extension, or target size. No target instruction decoder, relocation parser, load-address parser, or architecture signature is present.

Accordingly the supplied extractor preserves unknowns and refuses to emit a guessed payload. It accepts only a file beginning with `4D AD 00 02`, reports code-supported magic/size candidates, reports `navboot` locations, and refuses extraction unless a unique, evidence-backed payload boundary is available. This is intentional: a false extraction would corrupt the firmware search.

## Pseudocode supported by the binary

```text
read input into buffer
require buffer[0:4] == 4D AD 00 02
for each candidate module/container record:
    read big_endian_u32(record + 4) as size
    require size > 0x5c and size % 4 == 0
    require record + size <= buffer_end
    parse module metadata through the internal object model
    compare module name with "navboot"
    if selected: apply module-relative checked writes and serialize output
```

The exact directory-to-payload offset and replacement-size update sequence remain blocked until a matching image or a fuller patch description is obtained.

## Local search

Read-only search under `~/Desktop/NCDR_MAP_RESEARCH/` found no file containing the magic bytes `4D AD 00 02`. The only binary `navboot` hit is the literal inside `patch.exe` at file offset `0x34A5`; it is not a firmware image. Textual hits in the research reports are self-references and are excluded from firmware candidates. Results are in `f2_local_search.csv`.
