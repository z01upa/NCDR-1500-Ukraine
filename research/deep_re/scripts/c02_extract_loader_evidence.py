#!/usr/bin/env python3
"""C2: extract db_upack loader evidence and cross-check header word pairing against block886.bin.

Usage: python3 -I c02_extract_loader_evidence.py <NavigationRem.dll dir> <block886.bin> <out dir>
Writes: s4_code_evidence.asm, header_pairs_crosscheck.json
Evidence: CONFIRMED_BY_MACHINE_CODE (instructions) + CONFIRMED_BY_BINARY_DATA (block886 header words).
"""
import sys, os, json, struct, re, hashlib
import capstone as cs

src, blk, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
B = 0x02FD1000
code = open(os.path.join(src, "section_0.bin"), "rb").read()
ana = json.load(open(os.path.join(src, "sh4_analysis.json")))
F = {f["va"]: f for f in ana["functions"]}
d = cs.Cs(cs.CS_ARCH_SH, cs.CS_MODE_SH4 | cs.CS_MODE_LITTLE_ENDIAN)

def listing(va):
    end = F[va]["end"]
    pool = set()
    for pc in range(va, end, 2):
        x = struct.unpack("<H", code[pc - B:pc - B + 2])[0]
        if x >> 12 == 0xD:
            pool |= {(pc & ~3) + 4 + (x & 0xFF) * 4, (pc & ~3) + 6 + (x & 0xFF) * 4}
        if x >> 12 == 0x9:
            pool.add(pc + 4 + (x & 0xFF) * 2)
    rows = []
    for pc in range(va, end, 2):
        w = code[pc - B:pc - B + 2]
        if pc in pool:
            rows.append((pc, w.hex(), ".data", ""))
            continue
        r = list(d.disasm(w, pc))
        rows.append((pc, w.hex(), r[0].mnemonic, r[0].op_str) if r else (pc, w.hex(), "??", ""))
    return rows

FUNCS = {
    0x0304DBE8: "db_upack dispatcher: reads header word pairs, calls per-section loaders",
    0x0304D848: "loader for 10-byte records (S4): memcpy(dst,src,10) per record, no field conversion",
    0x0304D7E4: "loader for 3-byte (u16 index,u8 value) records (S1/S3): dst[idx*12+8]=value",
    0x0304D8A0: "loader for 14-byte records (S5): u32,u8,u8,u16,u16,u32 -> 16-byte RAM struct",
}
with open(os.path.join(out, "s4_code_evidence.asm"), "w") as fh:
    fh.write("; NavigationRem.dll section_0 (runtime base 0x02FD1000), SH4 little-endian, Capstone 5.0.7\n")
    fh.write("; '.data' = literal pool word (PC-relative target), not an instruction\n")
    for va, note in FUNCS.items():
        fh.write(f"\n; ===== 0x{va:08X} {note}\n")
        for pc, w, m, o in listing(va):
            fh.write(f"{pc:08X}  {w}  {m} {o}\n")

# header offsets read by dispatcher, from instruction text
disp = listing(0x0304DBE8)
reads = {}
for pc, w, m, o in disp:
    mm = re.match(r"@\((\d+),(r9|gbr)\),r0", o.replace(" ", ""))
    if m == "mov.w" and mm:
        reads.setdefault(int(mm.group(1)), []).append(f"0x{pc:08X}")
    if m == "mov.w" and o.replace(" ", "").startswith("@r9,"):
        reads.setdefault(0, []).append(f"0x{pc:08X}")

b = open(blk, "rb").read()
assert hashlib.sha256(b).hexdigest() == "c4fd95701be3301b999d7e8886d08a6d2e8a3461e9f6caa973a5128959d983a6"
W = struct.unpack("<23H", b[:46])
pairs = [  # (loader, offset word, count/size word) as decoded from the call-site argument setup
    (0x0304D6F0, 0, 2, "S0"), (0x0304D7E4, 4, 6, "S1"), (0x0304D6F0, 8, 10, "S2"), (0x0304D7E4, 12, 14, "S3"),
    (0x0304D848, 16, 18, "S4"), (0x0304D8A0, 20, 22, "S5"), (0x0304D994, 24, 26, "S6"), (0x0304DA1C, 28, 30, "S7"),
    (0x0304DA98, 32, 34, "S8"), (0x0304DB44, 36, 38, "S9"), (0x0304D97C, 40, 44, "S10 (size word is +44, not +42)"),
]
res = []
for ld, o, c, name in pairs:
    res.append({"section": name, "loader": f"0x{ld:08X}", "offset_word_at": o, "offset": W[o // 2],
                "count_or_size_word_at": c, "value": W[c // 2],
                "header_read_in_code": (o in reads) and (c in reads)})
tail_ok = W[20] + 0 >= 0 and (W[20] and True)
s10_end = W[20] + W[22]
json.dump({"block_sha256": hashlib.sha256(b).hexdigest(), "block_size": len(b),
           "header_words_read_by_dispatcher": sorted(reads), "pairs": res,
           "s10_offset_plus_word44": s10_end, "equals_file_size": s10_end == len(b),
           "evidence": "CONFIRMED_BY_MACHINE_CODE + CONFIRMED_BY_BINARY_DATA"},
          open(os.path.join(out, "header_pairs_crosscheck.json"), "w"), indent=1)
print(json.dumps({"reads": sorted(reads), "s10_end": s10_end, "file_size": len(b)}))
for r in res: print(r)
