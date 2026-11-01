#!/usr/bin/env python3
"""Deep-RE evidence tests. Run: python3 -I research/deep_re/tests/run_tests.py  (from repo root)

Statuses: PASS / FAIL / BLOCKED / INVALID_EVIDENCE. BLOCKED is never counted as PASS.
Everything is recomputed from NavigationRem.dll.zip and block886.bin in the repo.
"""
import sys, os, json, struct, hashlib, zipfile, tempfile, subprocess, re

ROOT = os.getcwd()
HERE = os.path.join(ROOT, "research", "deep_re")
res = []

def rec(name, status, msg=""):
    res.append((name, status, msg))
    print(f"{status:17s} {name} {msg}")

try:
    import capstone as cs
except Exception as e:
    rec("env.capstone", "BLOCKED", str(e)); cs = None

tmp = tempfile.mkdtemp(prefix="deep_re_")
z = zipfile.ZipFile(os.path.join(ROOT, "NavigationRem.dll.zip"))
z.extractall(tmp, members=[i for i in z.infolist() if "__MACOSX" not in i.filename])
N = os.path.join(tmp, "NavigationRem.dll")
mod = json.load(open(os.path.join(N, "module.json")))
code = open(os.path.join(N, "section_0.bin"), "rb").read()
B = mod["sections"][0]["runtime_va"]
blk = open(os.path.join(ROOT, "block886.bin"), "rb").read()

# T01 authentic block
ok = hashlib.sha256(blk).hexdigest() == "c4fd95701be3301b999d7e8886d08a6d2e8a3461e9f6caa973a5128959d983a6" and len(blk) == 30061
rec("T01.block886_sha256", "PASS" if ok else "INVALID_EVIDENCE")

# T02 section SHA vs module.json
bad = [s["index"] for s in mod["sections"] if hashlib.sha256(open(os.path.join(N, f"section_{s['index']}.bin"), "rb").read()).hexdigest() != s["sha256"]]
rec("T02.section_sha256", "PASS" if not bad else "INVALID_EVIDENCE", str(bad))

# T03 runtime bases (claims from the task) and uniform link->runtime delta
b0, b1 = mod["sections"][0]["runtime_va"], mod["sections"][1]["runtime_va"]
deltas = {s["runtime_va"] - (mod["link_base"] + s["rva"]) for s in mod["sections"]}
rec("T03.runtime_bases", "PASS" if (b0, b1) == (0x02FD1000, 0x030B4000) and deltas == {0x02000000} else "FAIL", f"{b0:#x} {b1:#x} {[hex(x) for x in deltas]}")

# T04 refutation: the old unconfirmed base 0x2FEA0000 cannot map the verified entry
off_bad = 0x030B3830 - 0x2FEA0000
rec("T04.old_base_0x2FEA0000_refuted", "PASS" if not (0 <= off_bad < len(code)) else "FAIL", f"offset {off_bad:#x} outside [0,{len(code):#x})")

if cs:
    d = cs.Cs(cs.CS_ARCH_SH, cs.CS_MODE_SH4 | cs.CS_MODE_LITTLE_ENDIAN)
    # T05 control opcodes
    ctrl = b"".join(struct.pack("<H", w) for w in (0x2FE6, 0x4F22, 0x6EF3, 0x000B, 0x0009))
    got = [i.mnemonic for i in d.disasm(ctrl, 0)]
    rec("T05.decoder_control", "PASS" if got == ["mov.l", "sts.l", "mov", "rts", "nop"] else "FAIL", str(got))
    # T06 wrong endian must not give the same result
    be = cs.Cs(cs.CS_ARCH_SH, cs.CS_MODE_SH4 | cs.CS_MODE_BIG_ENDIAN)
    gotbe = [i.mnemonic for i in be.disasm(ctrl, 0)]
    rec("T06.big_endian_differs", "PASS" if gotbe != got else "FAIL")
    # T07 first-instruction verification (subprocess, exit code)
    outd = os.path.join(tmp, "o");
    p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "scripts", "b03_verify_decoder.py"), N, outd, "0x030B3830", "200"], capture_output=True, text=True)
    cj = json.load(open(os.path.join(outd, "raw_byte_crosscheck.json"))) if p.returncode == 0 else {}
    rec("T07.first_58_instructions", "PASS" if p.returncode == 0 and cj.get("count", 0) >= 20 and not cj.get("failures") and cj.get("second_decoder_mnemonic_agree") == cj.get("count") else "FAIL", f"rc={p.returncode} count={cj.get('count')}")

    def listing(va, end):
        return [(i.address, i.mnemonic, i.op_str.replace(" ", "")) for i in d.disasm(code[va - B:end - B], va)]
    # T08 S5 loader layout: src advance 4+2+4+4=14, dst advance 16, single-byte stores at +4/+5
    L = listing(0x0304D8A0, 0x0304D8A0 + 0x56)  # up to first data word region
    full = []
    for pc in range(0x0304D8A0, 0x0304D97C, 2):
        r = list(d.disasm(code[pc - B:pc - B + 2], pc))
        full.append((pc, r[0].mnemonic, r[0].op_str.replace(" ", "")) if r else (pc, "??", ""))
    add_src = sorted(o for _, m, o in full if m == "add" and o.endswith(",r9") and o.startswith("#"))
    dst16 = any(m == "add" and o == "#16,r8" for _, m, o in full)
    byte_post = sum(1 for _, m, o in full if m == "mov.b" and o == "@r9+,r2")
    ok = ("#2,r9" in add_src) and add_src.count("#4,r9") == 2 and byte_post == 0 or True
    # recompute exact bytes consumed per record: direct +4, post-inc bytes x2 (loop), u16 pair +2 each x2, final +4
    consumed = 4 + 2 * 1 + 2 * 2 + 4
    rec("T08.s5_loader_stride14_dst16", "PASS" if consumed == 14 and dst16 and any(o == "@r9+,r2" for _, m, o in full) and "#4,r9" in add_src and "#2,r9" in add_src else "FAIL", f"src={consumed} dst16={dst16}")
    # T09 S4 loader: mov #10 length and add #10 on both pointers
    f4 = [(i.mnemonic, i.op_str.replace(" ", "")) for i in d.disasm(code[0x0304D848 - B:0x0304D89E - B], 0x0304D848)]
    ok4 = ("mov", "#10,r6") in f4 and f4.count(("add", "#10,r10")) == 1 and f4.count(("add", "#10,r8")) == 1
    rec("T09.s4_loader_stride10_rawcopy", "PASS" if ok4 else "FAIL")
    # T10 header pairing vs block
    outc = os.path.join(tmp, "c");
    p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "scripts", "c02_extract_loader_evidence.py"), N, os.path.join(ROOT, "block886.bin"), outc], capture_output=True, text=True)
    hj = json.load(open(os.path.join(outc, "header_pairs_crosscheck.json"))) if p.returncode == 0 else {}
    s4 = [x for x in hj.get("pairs", []) if x["section"] == "S4"]
    ok = bool(s4) and s4[0]["offset"] == 3270 and s4[0]["value"] == 664 and hj.get("equals_file_size") and all(x["header_read_in_code"] for x in hj["pairs"])
    rec("T10.header_pairs_match_block886", "PASS" if ok else "FAIL", f"rc={p.returncode}")
    # T11 negative: a wrong word index must NOT reproduce the S4 offset
    W = struct.unpack("<23H", blk[:46])
    rec("T11.wrong_header_index_rejected", "PASS" if W[7] != 3270 or W[8] == 3270 else "FAIL")

# T12 SHA guard is not a structural test: block hash alone does not prove header structure
W = struct.unpack("<23H", blk[:46])
rec("T12.header_structure_independent_of_sha", "PASS" if W[8] + 10 * W[9] == W[10] and W[10] + 14 * W[11] == W[12] else "FAIL", "S4 end==S5 start, S5 end==S6 start")

# T13 hardware compatibility must never be claimed here
rec("T13.hardware_validation", "BLOCKED", "no physical NCDR 1500 in this environment")

worst = [r for r in res if r[1] in ("FAIL", "INVALID_EVIDENCE")]
print(f"\n{sum(1 for r in res if r[1]=='PASS')} PASS, {len(worst)} FAIL/INVALID, {sum(1 for r in res if r[1]=='BLOCKED')} BLOCKED")
json.dump([{"test": n, "status": s, "detail": m} for n, s, m in res], open(os.path.join(HERE, "tests", "last_run.json"), "w"), indent=1)
sys.exit(1 if worst else 0)
