"""Bounded first-stage transform search; scores are heuristic, not a decoder claim."""
from __future__ import annotations
from collections import Counter
import math
from ..analysis.entropy import profile

def _bit_reverse(b): return bytes(int(f"{x:08b}"[::-1], 2) for x in b)
def _nibble_swap(b): return bytes(((x << 4) | (x >> 4)) & 255 for x in b)
def _xor_previous(b):
    if not b: return b
    return bytes([b[0]]) + bytes(b[i] ^ b[i-1] for i in range(1, len(b)))
def _delta_decode(b):
    out=bytearray(); acc=0
    for x in b: acc=(acc+x)&255; out.append(acc)
    return bytes(out)

def transforms(data):
    yield "identity", data
    yield "bitwise_not", bytes(x ^ 255 for x in data)
    yield "reverse_bytes", data[::-1]
    yield "bit_reverse", _bit_reverse(data)
    yield "nibble_swap", _nibble_swap(data)
    yield "previous_byte_xor", _xor_previous(data)
    yield "delta8_decode", _delta_decode(data)
    for k in range(256): yield f"xor_0x{k:02x}", bytes(x ^ k for x in data)

def score(candidate, reference_profile):
    p=profile(candidate)
    if not reference_profile: return 0.0, p
    # Profile similarity only: entropy, zero ratio, unique byte count.
    e=max(0.0, 1.0-abs(p["entropy"]-reference_profile["entropy"])/8.0)
    z=max(0.0, 1.0-abs(p["zero_ratio"]-reference_profile["zero_ratio"]))
    u=max(0.0, 1.0-abs(p["unique_bytes"]-reference_profile["unique_bytes"])/256.0)
    return round(100*(0.5*e+0.3*z+0.2*u), 4), p

def reference_profile(payloads):
    if not payloads: return {"entropy": 0.0, "zero_ratio": 0.0, "unique_bytes": 0}
    ps=[profile(x[8:]) for x in payloads if len(x)>8]
    if not ps: return {"entropy": 0.0, "zero_ratio": 0.0, "unique_bytes": 0}
    return {k:sum(p[k] for p in ps)/len(ps) for k in ("entropy","zero_ratio","unique_bytes")}
