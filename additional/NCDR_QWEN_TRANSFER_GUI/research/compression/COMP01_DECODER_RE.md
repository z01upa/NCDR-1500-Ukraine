# Compression 0x01 decoder reverse-engineering checkpoint

## Confirmed observations

- The global DB contains 5,240 type-0x00 compression-0x01 records.
- The authoritative road corpus references 324 of them, containing 74,963
  owned road-object occurrences.
- The 0x01 control at sector `0x11576` has header
  `01 15 76 0D 00 00 01 17`, physical size 6,656 bytes, and expected logical
  size 11,776 bytes.
- Its bytes after the header begin
  `00 74 00 03 00 94 00 05 00 C8 ...`, matching the known type-0x00 logical
  prefix family. This is evidence of a literal/structured prefix, not proof
  that the whole record is literal.
- Standard zlib, raw-deflate, gzip, bz2, and lzma attempts failed on all 100
  sampled compression-0x01 records.

## Static POISoN localization

In `tools/POISoN/poison.exe`, the record-loader dispatch is at `0x40EE97`-
`0x40EF0B`; it switches on the byte at record-buffer `+0x06` through the jump
table at `0x45C6C0`.

Relevant targets:

- `0x40EFD7`: allocation/header-copy path ending in the imported
  `zlib1.dll!uncompress` thunk at `0x448890`; zlib failure logging is at
  `0x40F306`.
- `0x40EF62`: alternate allocation/header-copy path with “Error unpacking
  block” logging at `0x40F004`.
- `0x40F041`: native post-processing path; it allocates the advertised logical
  size, copies the 8-byte header, calls the same imported unpack/decompress
  entry, then processes block-local tables through context offsets `+0x710`,
  `+0x714`, and `+0x214`.

The static result localizes candidate loader paths but does not prove which
path handles the observed 0x01 records, because the surrounding loader context
and jump-table state are not yet reconstructed. It is not safe to translate
the native routine into a decoder from disassembly alone.

## Offset and boundary status

The visible first 256 physical bytes of the 0x01 controls contain valid-looking
type-0x00 prefix words. No verified logical output buffer exists, so a
physical-to-logical pointer mapping and compression boundary cannot yet be
claimed. The only safe statement is that the prefix is physically visible at
the start of the record.

## Current validation

`decode_comp01.py` intentionally rejects unresolved streams. It preserves the
8-byte header contract and expected logical-size calculation but emits no
guessed data. This prevents false readable objects from entering the road
corpus.

## Exact blocker

Obtain one dynamic logical-buffer oracle for sector `0x11576` (or equivalent):
the expanded `23 * 512` bytes after POISoN has loaded the record. Then derive
physical-to-logical token mappings and implement the decoder against that
pair. No geometry analysis should resume before this oracle is available.
