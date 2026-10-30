from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from decode_comp01 import decode_comp01, Comp01DecodeError

def test_strict_rejection_until_token_grammar_is_proven():
    record = bytes.fromhex("0115760d00000117") + b"\x00" * (13 * 512 - 8)
    try:
        decode_comp01(record)
    except Comp01DecodeError:
        return
    raise AssertionError("unresolved comp01 input must not be decoded speculatively")

