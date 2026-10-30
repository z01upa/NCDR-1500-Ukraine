# NCDR-ASTRA-MODULE-RECOVERY-013

Recovered sections, not bootable/relinked PE files. Original ROM relocations/import binding remain intact. Use `module.json` to distinguish ROM storage VA, original link VA and CE runtime VA. Do not load these bytes at the TOC load address.

## Run on macOS / Windows
Python 3.9 and pypcode 2.0.0 were tested locally on macOS Intel. Windows execution is NOT VERIFIED.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python recover_modules.py
.venv/bin/python scan_sh4.py
.venv/bin/python verify_recovery.py
.venv/bin/python verify_graph_readers.py
.venv/bin/python extract_function.py 0x0301fcd8
```
On Windows replace `.venv/bin/python` with `.venv\Scripts\python.exe` and `python3` with `py -3.9`.
`recover_modules.py --decoded PATH` accepts another location for the previous addressed image and map. Other scripts expect the existing project layout. No paid API, local model, NK re-decoding, or topology_v6 rerun.

`modules/<name>/section_0.bin` contains the complete executable section. Other `section_N.bin` files contain actual recovered bytes; virtual tails are not appended. `.stored.bin` preserves the encoded source bytes. `module.json` includes imports, exports, addresses, lengths, hashes and compressed-block boundaries. `reachable.jsonl.gz` stores reachable instruction evidence; `string_xrefs.tsv` links actual instructions to strings.

## Provenance and limits
Input: `../astra_final_breakthrough/decoded/addressed_image.bin`, SHA-256 `ed2f3546e83130e03e8e8ef713540417e56e4dd7eebd313cba1065408e4d7906`.
Original NK.BIN SHA-256 `d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847`.
No `decode_lk.zip` or prior reconstructed target DLL was found in the supplied NCDR project/transfer/input_reference; the targeted Downloads/NCDR check also found no target DLL. This is not a claim about files on other computers.
All 10 stored-section ranges match the pinned image and 10 corresponding verified packet outputs. Uncompressed storage alignment padding outside virtual section size is excluded, never substituted for code. Compressed sections pass strict bounds and exact input/output consumption; section-level checksum is not invented.
Each compressed PDATA ends with 6 bytes of a final 8-byte entry; its last two virtual bytes are absent from the stored stream. That final entry is excluded from CFG validation. No synthetic trailing zeros are counted as recovered bytes.
The CFG follows direct branches and delay slots. Indirect calls/jumps are not exhaustively resolved, and successful decoding is not proof of hardware execution. NavigationRem includes SH4 floating-point instructions; nmicore's reached code is compatible with the same decoder. ROMHDR CPU remains zero.
The minimal p-code interpreter is a bounded offline check, not a Windows CE emulator. Its one external hook is the independently resolved COREDLL ordinal 1044 (`memcpy`). Unsupported operations/calls and unmapped memory fail.

Format references consulted (no upstream tool executed or bundled):
- [e32 layout and CE block encoding reference, pinned commit](https://github.com/gweslab/extract-wince-rom/tree/5eedf30beced801fa753b9ab693cd06bb5068133/winmob_extract)
- [Microsoft CE runtime function entries](https://learn.microsoft.com/en-us/previous-versions/windows/embedded/ms879748(v=msdn.10))

No original, MP0, SQLite, GUI, Reader or Writer was changed. Local knowledge checkout unavailable; evidence is queued separately for Knowledge Sync.
