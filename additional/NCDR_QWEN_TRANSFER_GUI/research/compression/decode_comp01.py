#!/usr/bin/env python3
"""Strict placeholder for the unresolved DB compression-0x01 decoder.

The loader entry point and native-unpack caller are localized in poison.exe,
but no differential logical-buffer oracle is available in this environment.
Returning guessed bytes would corrupt the authoritative corpus, so malformed
or unsupported input is rejected explicitly.
"""
from __future__ import annotations

class Comp01DecodeError(ValueError):
    pass

def decode_comp01(record_bytes: bytes) -> bytes:
    if len(record_bytes) < 8:
        raise Comp01DecodeError("record shorter than 8-byte header")
    if record_bytes[6] != 1:
        raise Comp01DecodeError(f"expected compression 0x01, got 0x{record_bytes[6]:02x}")
    expected = record_bytes[7] * 512
    raise Comp01DecodeError(
        f"compression-0x01 token grammar unresolved; expected logical size {expected}"
    )

