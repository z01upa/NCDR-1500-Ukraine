"""SH4 branch-semantics unit tests (NCDR-QWEN-CFG-058). Run: python -m pytest -q or python test file."""

def T_tst(rn, r0):  # tst Rn,R0 : T = ((Rn & R0) == 0)
    return (rn & r0) == 0

def cmp_pl(v):      # cmp/pl Rn : T = (signed(Rn) > 0)   [STRICT]
    s = v - 0x100000000 if v >= 0x80000000 else v
    return s > 0

def bt(T):  return T
def bf(T):  return not T

# CHECK 1: 030ac200 tst r13,r11 ; 030ac202 bf 0x30ac1de
def test_bit_set_jumps_to_advance():
    assert bf(T_tst(1<<3, 1<<3)) is True     # bit set -> taken -> 0x30ac1de
def test_bit_clear_falls_through():
    assert bf(T_tst(1<<3, 0)) is False       # bit clear -> process candidate at 204

# CHECK 2: 030ac160-166
def test_r8_zero_uses_byte_table_path():
    T1 = T_tst(0,0); r3 = 1 if T1 else 0; T2 = T_tst(r3,r3)
    assert bt(T2) is False                    # falls through to 0x30ac16a
def test_r8_nonzero_calls_ac72c():
    T1 = T_tst(5,5); r3 = 1 if T1 else 0; T2 = T_tst(r3,r3)
    assert bt(T2) is True                     # goes to 0x30ac188 (bsr ac72c)

# CHECK 3: cmp/pl strict positivity
def test_cmppl_strict():
    for v in (-2,-1,0,0x80000000,0xFFFFFFFF):
        assert cmp_pl(v & 0xFFFFFFFF) is False
    for v in (1,2,0x7FFFFFFF):
        assert cmp_pl(v) is True

if __name__ == "__main__":
    import sys
    fns=[v for k,v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns: f()
    print(f"ALL {len(fns)} SH4 SEMANTICS TESTS PASSED")
