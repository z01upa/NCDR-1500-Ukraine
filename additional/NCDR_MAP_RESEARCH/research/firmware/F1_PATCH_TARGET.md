# Firmware RE F1: `patch.exe` target

Static-only analysis of `tools/POISoN/patch.exe` (PE32 i386, 16,896 bytes). The executable was not run.

## Conclusion

`patch.exe` expects a binary container holding a module named `navboot` (lower-case, exact string at RVA/file offset `0x50A5`/`0x34A5`). It does not identify a flat NAVBOOT image by a conventional executable magic. The parser accepts container magic `0x4DAD0002` when read as big-endian at the input start (code `0x4015B9`, helper `0x4015B0`), then walks module records and uses a module-name lookup. The requested target is therefore the `navboot` module inside a firmware/container file, not `lng_rel.tbl`, `voice.lst`, or the map DB.

The module format has a big-endian header/data model, module type labels (`program`, `subroutine`, `multi`, `data`, `configuration`, `trap library`, `system`, `file manager`, `device driver`, `device descriptor`, `user defined`, `unknown`), CRC/parity checks, alignment/size checks, and a module body. `navboot` is selected by name. No fixed target-file byte size, version string, or target-file extension is embedded in this executable.

## Patch engine

The generic patch primitive is reached through the module method table from `0x402330` and ultimately calls the module body writer at `0x4016F0`. It computes a module-relative address, bounds-checks it, compares the current value against an expected value, and writes the replacement in big-endian form. Failure text is `Unexpected value %08x during patch %08x %08x %08x`, `Unable to patch address %08x (address out of range)`, and `Unable to patch module '%s' - module not found`.

`patch.exe` contains no statically recoverable concrete navboot patch records in the executable's literal data. The application builds/loads its patch description through the generic object/parser path; the embedded table at `.data` is parser/runtime data, not a list of proven NAVBOOT offsets. Consequently exact navboot offsets, original bytes, replacements, and patch count are **not present/provable from this binary alone** and are reported as unresolved rather than guessed.

## File access

Imports include `fopen`, `fread`, `fwrite`, `fseek`, `ftell`, `fclose`, `_access`; the visible mode strings are `rb`, `wb`, and `wb`-family output handling. Input is read as a whole/structured container and output is rewritten. Error paths cover too-small input, read/open failure, unknown format/data, module-size/alignment/name/data/header-parity/CRC failures, and unsupported aligned-pool saving. No literal input filename or extension is embedded.

## Architecture

The patcher itself is x86/i386 only as a Windows PE host. The target-module parser uses big-endian fields and `bswap`; that is format evidence, not proof of the target CPU. The executable contains no target instruction decoder or architecture-specific instruction signatures. Therefore Motorola 68k, PowerPC, SH, ARM, and target x86 cannot be distinguished from patched bytes because no concrete navboot patch bytes are embedded.

## Constants / relations

`0x3FFF` and `0x800`/`0x200` are not present as DB-navigation constants in the patch logic; `0x800021` occurs in the CRC-like routine at `0x402896`, but is not the DB coordinate constant. Decimal `5,555,555` (`0x0054C563`) is absent. No recognized CARiN record-type table is present. Neither `lng_rel.tbl` nor `voice.lst` is referenced. `0x4DAD0002` is the useful firmware-container magic; the expected search name is `navboot`.

## Ghidra loading

Load the recovered outer container as raw binary initially; confirm the big-endian container magic `4D AD 00 02`, locate the module record whose name is `navboot`, extract its body using the module size/header fields, and then create a separate raw image in Ghidra. The target processor cannot be selected from `patch.exe`; use the recovered module header's architecture field and validate against its entry/body instruction patterns.
