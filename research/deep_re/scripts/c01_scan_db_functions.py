#!/usr/bin/env python3
"""C1: scan DB-layer functions of NavigationRem.dll for packed-field access patterns.

Usage: python3 -I c01_scan_db_functions.py <NavigationRem.dll dir> <out dir>
Output is a CANDIDATE list (evidence class: HYPOTHESIS) - not proof of S4/S5 semantics.
Features are counted from Capstone SH4 decode of [va,end) of each pdata function.
"""
import sys, os, json, re, csv, collections
import capstone as cs

src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
mod = json.load(open(os.path.join(src, "module.json")))
sec0 = mod["sections"][0]
BASE = sec0["runtime_va"]
code = open(os.path.join(src, "section_0.bin"), "rb").read()
ana = json.load(open(os.path.join(src, "sh4_analysis.json")))
funcs = {f["va"]: f for f in ana["functions"]}
starts = sorted(funcs)

# function VA -> source files (assert strings)
fn_src = collections.defaultdict(set)
for r in csv.DictReader(open(os.path.join(src, "string_xrefs.tsv")), delimiter="\t"):
    m = re.match(r"K:\\siemens\\src\\(.+)", r["text"].strip())
    if m:
        fn_src[int(r["function_va"], 16)].add(m.group(1))

WANT = re.compile(r"^(db\\db_(upack|read|get|intersection|page|find|fea_cell_cache|road_cache|succ|shape|utils|subs)\.c|"
                  r"idb\\idb_feacell\.c|rg\\(dtg_nd_access|rg_mn_access|rm_db)\.c|dbutils\\du_get(_road_data)?\.c)$")

d = cs.Cs(cs.CS_ARCH_SH, cs.CS_MODE_SH4 | cs.CS_MODE_LITTLE_ENDIAN)

def feats(va, end):
    raw = code[va - BASE: end - BASE]
    f = collections.Counter()
    n = 0
    for i in d.disasm(raw, va):
        n += 1
        m, o = i.mnemonic, i.op_str.replace(" ", "")
        if m == "and" and o.startswith("#"):
            v = int(o[1:].split(",")[0], 0)
            if v == 0x0F: f["and_0F"] += 1
            elif v == 0xF0: f["and_F0"] += 1
            elif v in (0x1, 0x3, 0x7): f["and_small"] += 1
        if m in ("shlr2", "shlr8", "shlr16", "shlr"): f[m] += 1
        if m in ("shll2", "shll8", "shll16", "shll"): f[m] += 1
        if m == "mov" and o.startswith("#"):
            v = int(o[1:].split(",")[0], 0)
            if v == 10: f["imm10"] += 1
            if v == 14: f["imm14"] += 1
        if m in ("mulu.w", "muls.w", "mul.l", "dmulu.l", "dmuls.l"): f["mul"] += 1
        if m == "extu.b": f["extu_b"] += 1
        if m == "extu.w": f["extu_w"] += 1
        if m == "swap.b": f["swap_b"] += 1
        if m.startswith("mov.") and "@(" in o: f["disp_access"] += 1
    f["insns"] = n
    return f

rows = []
for va in starts:
    s = fn_src.get(va, set())
    hit = [x for x in s if WANT.match(x)]
    if not hit:
        continue
    f = funcs[va]
    c = feats(va, f["end"])
    score = 3 * c["and_0F"] + 3 * c["and_F0"] + 2 * (c["shlr2"] >= 2) + 2 * c["imm10"] + 2 * c["imm14"] + c["mul"] + c["swap_b"]
    rows.append((score, va, f["end"], ";".join(sorted(hit)), c))

rows.sort(key=lambda r: -r[0])
with open(os.path.join(out, "runtime_readsites.tsv"), "w") as fh:
    fh.write("score\tfunction_va\tend\tsource\tinsns\tand_0F\tand_F0\tshlr2\tshlr8\timm10\timm14\tmul\tswap_b\tstatus\n")
    for sc, va, end, s, c in rows:
        fh.write(f"{sc}\t0x{va:08X}\t0x{end:08X}\t{s}\t{c['insns']}\t{c['and_0F']}\t{c['and_F0']}\t{c['shlr2']}\t{c['shlr8']}\t{c['imm10']}\t{c['imm14']}\t{c['mul']}\t{c['swap_b']}\tHYPOTHESIS\n")
print(len(rows), "functions scanned")
for sc, va, end, s, c in rows[:25]:
    print(f"{sc:3d} 0x{va:08X} n={c['insns']:4d} and0F={c['and_0F']} andF0={c['and_F0']} shlr2={c['shlr2']} i10={c['imm10']} i14={c['imm14']} mul={c['mul']} {s}")
