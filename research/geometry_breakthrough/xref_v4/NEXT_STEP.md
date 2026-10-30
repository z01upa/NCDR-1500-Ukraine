# Next step

Build or obtain an offline SH4 decoder and a bounded Windows CE ROM/XIP
extractor, then analyze the two existing inputs without changing them:

1. Resolve the `NK.BIN` wrapper from offset `0x400` (`CE00FF\n`) and test the
   `ECEC` record at `0x9CEAD3`; confirm whether its following DWORD is a valid
   ROM/XIP address and locate a ROMHDR/TOC by its internal invariants, not by
   guessing the base. Extract only the module table needed to identify
   `coredll.dll` ordinal exports and navigation-related modules.
2. Disassemble SH4 `NAVIMAIN.EXE` at entry VA `0x11E24` (file offset `0x1224`),
   resolve its imported ordinals, then follow the named communication-broker
   calls to the actual navigation process. Search only those call paths for
   10-byte and 14-byte access patterns and record exact instruction addresses.
3. If those call paths lead into an NK module, extract and hash that module,
   disassemble its Section 4/5 readers, and validate candidate semantics on
   held-out original blocks. Only then inspect Section 6–9, RT, or RL if an
   identified code path references them.
4. Return to the frozen block 886 nodes 412/414 case. A topology edit is
   permitted only after the high-degree `+2`/continuation mechanism, occupied
   `+8/+9` behavior, and Section 5/auxiliary update rules have independent
   byte-level tests.

Microsoft's Windows CE documentation says Romimage generates `NK.BIN` runtime
images and supports separate XIP regions, and documents `OEMRomChain.pTOC` as
the ROM table-of-contents pointer. This is background for the next parser only;
it does **not** establish that this vendor `CE00FF` prefix or `ECEC` marker has
standard ROMHDR semantics:

- [Romimage](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms938650%28v%3Dmsdn.10%29)
- [OEMRomChain](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms904941%28v%3Dmsdn.10%29)
