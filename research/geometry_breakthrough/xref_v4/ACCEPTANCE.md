# NCDx XREF v4 acceptance

**Result: targeted static cross-reference completed; no new node/edge storage rule recovered. No MP0 was edited and no new edge was attempted.**

## Reproducible observations

- `NAVIMAIN.EXE` hash remains
  `8bbeb2a919a4b5e470dd1eaaf47dd029dd2ccf12586b1a4ebb0ea9729087fb07`;
  size is 9,798 bytes. PE headers identify SH4 (`machine=0x01A6`), PE32,
  image base `0x10000`, and five file-backed sections.
- Entry point RVA `0x1E24` maps to VA `0x11E24`, file offset `0x1224`, in
  `.text`. The exact following 64 bytes are stored as
  `entry_point_hex_64_bytes` in `evidence/firmware_xref.json`. They are raw
  bytes, not a decoded instruction listing; no procedure reading Section 4 or
  Section 5 was located.
- The import table has 39 entries: 18 ordinal-only `coredll.dll`, 9
  ordinal-only `mfcce212.dll`, 7 named `commgr.dll`, 2 named `ole32.dll`, and
  3 named `memmgr.dll`. The named imports include the remote COM manager APIs;
  no named import matched the bounded file-I/O name filter. The 18 coredll
  ordinals remain unresolved, so this is **not** evidence that the executable
  has no file access. Forty-five preferred-base IAT address literals occur in
  `.text`; for example `0x00013004` (coredll ordinal 455) is stored at file
  offset `0xEA0`. These establish static import references, not decoded call
  sites.
- The PE has ordinary file-backed `.text`, `.rdata`, `.data`, `.pdata`, and
  `.rsrc` ranges; known packer markers tested here are absent. Whether it
  requires runtime unpacking remains **unestablished**.
- `NK.BIN` remains bound to SHA-256
  `d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847` and
  11,021,915 bytes. The bounded existing scanner found 15 `MZ` markers and
  zero valid embedded PE images. An alternative raw scan found one `PE\0\0`
  signature, but its machine field is not SH4. `NAVIMAIN`, `NAVIMAIN.EXE`,
  `MMIDIS.EXE`, `EUZ.MP0`, `MP0`, and `ROMHDR` are absent as both ASCII and
  UTF-16LE strings.
- New raw NK observations, with no format assignment: `CE00FF\n` at file
  offset `0x400`, and `ECEC` at `0x9CEAD3`; the little-endian DWORD immediately
  following the latter is `0x8D2F66CC`; the same DWORD appears again at
  `0x9CEADF` (and at file offset 3513), with raw bytes `CEZ\x02` between the
  copies. These bytes are preserved as an untyped header-like pattern in the
  JSON evidence. The NK wrapper/ROM module table is not decoded.
- Existing topology evidence was referenced rather than rescanned: **1,325**
  low-nibble->4 node records have no local primary Section 5 endpoint
  incidence; **511** low-degree identity mismatches remain associated with
  repeated coordinates. The prior Writer v2 candidate remains block 886,
  nodes 412/414, with occupied unknown next words 518/271.

## Tests and integrity

`test_firmware_xref.py`: **7 PASS, 0 FAIL**. Checks exact source hashes,
entrypoint mapping and raw bytes, import/ordinal limits, IAT references,
packer-scan scope, the NK alternative scan, inherited high-degree evidence,
and that no decoding claim is made. Before/after hashes match for both source
files; source write count is zero. Test output is in
`evidence/firmware_xref_tests.log`.

## Exact remaining blocker

No SH4 disassembler or Windows CE ROM/XIP module extractor is available in
this environment. `NAVIMAIN.EXE` exposes ordinal OS imports whose API names are
unknown; `NK.BIN` has an unexplained `CE00FF` wrapper and an `ECEC` marker, but
no parsed ROMHDR/TOC or extracted module. Therefore there is no instruction
address/call graph to map to Section 4/5, no decoded meaning for the 1,325
high-degree rows or their `+2` words, and no new independently confirmed
link-storage mechanism that would clear Writer v2's insertion gate.
