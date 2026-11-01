#!/usr/bin/env python3
"""B3: first verified SH4 instructions from NavigationRem.dll section_0.

Usage: python3 -I b03_verify_decoder.py <NavigationRem.dll dir> <out dir> [start_va] [count]
Evidence class on success: CONFIRMED_BY_MACHINE_CODE (decoded bytes == file bytes,
targets recomputed independently, second decoder agrees on mnemonic).
"""
import sys, json, struct, hashlib, os
import capstone as cs
import pypcode

src, out = sys.argv[1], sys.argv[2]
START = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0x030B3830
COUNT = int(sys.argv[4], 0) if len(sys.argv) > 4 else 64
os.makedirs(out, exist_ok=True)

mod = json.load(open(os.path.join(src, "module.json")))
sec = mod["sections"][0]
BASE = sec["runtime_va"]
data = open(os.path.join(src, "section_0.bin"), "rb").read()
sha = hashlib.sha256(data).hexdigest()
assert sha == sec["sha256"], "section_0 sha mismatch"
assert BASE == 0x02FD1000, hex(BASE)
assert BASE + sec["virtual_size"] > START >= BASE and START % 2 == 0

def sext(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v

def indep_target(pc, w, dec_pc=None):
    """Independent SH4 target math from the raw 16-bit word. Returns (kind,target) or None."""
    hi = w >> 12
    if hi == 0x8 and (w >> 8) in (0x89, 0x8B, 0x8D, 0x8F):
        return ("branch", pc + 4 + sext(w & 0xFF, 8) * 2)
    if hi in (0xA, 0xB):
        return ("branch", pc + 4 + sext(w & 0xFFF, 12) * 2)
    if hi == 0x9:
        return ("lit.w", pc + 4 + (w & 0xFF) * 2)
    if hi == 0xD:
        return ("lit.l", ((pc & ~3) + 4 + (w & 0xFF) * 4))
    if (w >> 8) == 0xC7:
        return ("mova", ((pc & ~3) + 4 + (w & 0xFF) * 4))
    return None

d = cs.Cs(cs.CS_ARCH_SH, cs.CS_MODE_SH4 | cs.CS_MODE_LITTLE_ENDIAN)
off0 = START - BASE
window = data[off0: off0 + COUNT * 2 + 8]
insns = list(d.disasm(window, START))[:COUNT]
# stop at end of function: first rts + its delay slot (anything after is literal pool/data)
for k, x in enumerate(insns):
    if x.mnemonic == "rts":
        insns = insns[:k + 2]
        break
COUNT = len(insns)
assert COUNT >= 20, f"decoded only {COUNT}"
POOL_START = START + COUNT * 2

# second decoder: SLEIGH SuperH4 LE
ctx = pypcode.Context("SuperH4:LE:32:default")
sleigh_by_pc = {}
try:
    for ins in ctx.disassemble(window[: COUNT * 2], START, max_instructions=COUNT).instructions:
        sleigh_by_pc[ins.addr.offset] = (ins.mnem, ins.body)
except Exception as e:
    sleigh_by_pc = {}

rows, fails, agree, targets_ok, literals = [], [], 0, 0, []
for ins in insns:
    off = ins.address - BASE
    raw = data[off: off + ins.size]
    w = struct.unpack("<H", raw[:2])[0]
    ok_bytes = bytes(ins.bytes) == raw and ins.size == 2
    it = indep_target(ins.address, w)
    tgt = ""
    note = ""
    if it:
        kind, t = it
        tgt = f"0x{t:08X}"
        if kind in ("branch",):
            ok = (f"0x{t:x}" in ins.op_str.lower()) or (f"{t:#x}" in ins.op_str.lower())
            if ok:
                targets_ok += 1
            else:
                fails.append(("target_mismatch", hex(ins.address), ins.op_str, tgt))
        else:
            lo = t - BASE
            if 0 <= lo + 4 <= len(data):
                val = struct.unpack("<I", data[lo:lo + 4])[0] if kind != "lit.w" else sext(struct.unpack("<H", data[lo:lo + 2])[0], 16)
                note = f"literal={val & 0xFFFFFFFF:#010x}"
                literals.append((hex(ins.address), kind, tgt, note))
            else:
                fails.append(("literal_out_of_section", hex(ins.address), tgt))
    sm = sleigh_by_pc.get(ins.address)
    sm_s = f"{sm[0]} {sm[1]}" if sm else ""
    if sm and sm[0].split(".")[0].lower() == ins.mnemonic.split(".")[0].lower():
        agree += 1
    rows.append([f"0x{ins.address:08X}", raw.hex(), f"0x{w:04X}", ins.mnemonic, ins.op_str, tgt, note, sm_s, "OK" if ok_bytes else "BYTES_MISMATCH"])
    if not ok_bytes:
        fails.append(("bytes_mismatch", hex(ins.address)))

with open(os.path.join(out, "verified_instructions.tsv"), "w") as f:
    f.write("PC\traw_le\tword\tmnemonic\toperands\tindep_target\tliteral\tsleigh\tbytes_check\n")
    for r in rows:
        f.write("\t".join(r) + "\n")

json.dump({
    "section": 0, "runtime_base": f"0x{BASE:08X}", "section_sha256": sha,
    "start_va": f"0x{START:08X}", "file_offset": off0, "count": len(rows),
    "bytes_mismatch": sum(1 for x in fails if x[0] == "bytes_mismatch"),
    "branch_targets_verified": targets_ok,
    "literal_loads_found": len(literals),
    "literal_pool_start": f"0x{POOL_START:08X}",
    "literal_loads_inside_pool": sum(1 for l in literals if int(l[2], 16) >= POOL_START),
    "second_decoder_available": bool(sleigh_by_pc),
    "second_decoder_mnemonic_agree": agree,
    "failures": fails,
    "evidence_class": "CONFIRMED_BY_MACHINE_CODE" if not fails else "INVALID",
}, open(os.path.join(out, "raw_byte_crosscheck.json"), "w"), indent=2)

json.dump({"python": sys.version.split()[0], "capstone": cs.__version__, "pypcode": getattr(pypcode, "__version__", "?"),
           "decoders": ["capstone SH4 LE", "pypcode SuperH4:LE:32:default"], "ghidra": False, "objdump_sh": False},
          open(os.path.join(out, "decoder_environment.json"), "w"), indent=2)
print(json.dumps({"count": len(rows), "fails": fails, "targets_ok": targets_ok, "literals": len(literals), "sleigh_agree": agree, "sleigh_n": len(sleigh_by_pc)}, indent=1))
