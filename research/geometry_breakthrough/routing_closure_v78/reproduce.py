#!/usr/bin/env python3
"""Reproduce the bounded original-code routing/attribute audit for NCDR.

Run from the NCDR_MAP_RESEARCH root:
  python -B research/geometry_breakthrough/routing_closure_v78/reproduce.py

The program reads the archived original NavigationRem.dll and EUZ.MP0 only.
All instruction replays use in-memory copies; no MP0, Writer, database or
original media is modified.  Replays stop at the local candidate gate and do
not model a complete Windows CE route request.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GEO = HERE.parent
ROOT = GEO.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(GEO / "astra_breakthrough_v11"))
from probe_code import Module

DLL_SHA = "4555a95f5bdd7d0479a39dcf8ab10a1d0dbe6e40d560d550df2461fee350ffcd"
TEXT_SHA = "91d33ac02d82dc109e65d83c87e44a00cba02887fb14e6e5b136eb16db0a35a9"
MP0_SHA = "73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e"
RUNTIME_DELTA = 0x02000000
MASK32 = 0xFFFFFFFF


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hx(value: int) -> str:
    return f"0x{value & MASK32:08X}"


def json_write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class AuditMem:
    """Sparse little-endian memory with exact byte-range access logging."""
    def __init__(self):
        self.bytes: dict[int, int] = {}
        self.reads: list[dict] = []
        self.writes: list[dict] = []

    def read(self, address: int, size: int) -> bytes:
        value = bytes(self.bytes.get((address + i) & MASK32, 0) for i in range(size))
        self.reads.append({"address": hx(address), "size": size, "hex": value.hex()})
        return value

    def write(self, address: int, value: bytes) -> None:
        data = bytes(value)
        for i, byte in enumerate(data):
            self.bytes[(address + i) & MASK32] = byte
        self.writes.append({"address": hx(address), "size": len(data), "hex": data.hex()})

    def u8(self, a): return self.read(a, 1)[0]
    def u16(self, a): return int.from_bytes(self.read(a, 2), "little")
    def u32(self, a): return int.from_bytes(self.read(a, 4), "little")
    def w8(self, a, v): self.write(a, bytes((v & 0xFF,)))
    def w16(self, a, v): self.write(a, (v & 0xFFFF).to_bytes(2, "little"))
    def w32(self, a, v): self.write(a, (v & MASK32).to_bytes(4, "little"))


class AuditedSH4:
    """Execute only the instruction forms reached by the reviewed slices."""
    def __init__(self, module, prior):
        self.m = module
        self.core = prior.SH4Slice(module)
        self.mem = AuditMem()
        self.core.mem = self.mem
        self.r = self.core.r
        self.t = 0
        self.trace: list[int] = []
        self.steps: list[dict] = []
        self.branches: list[dict] = []

    def _decode(self, pc):
        return self.m.ctx.disassemble(self.m.read(pc, 2), pc, max_instructions=1).instructions[0]

    def simple(self, pc: int) -> int:
        raw = self.m.read(pc, 2)
        before = self.r[:]
        old_t = self.core.t
        read_count, write_count = len(self.mem.reads), len(self.mem.writes)
        self.core.mem = self.mem
        next_pc = self.core.simple(pc)
        self.t = self.core.t
        ins = self._decode(pc)
        changed = {f"r{i}": {"before": hx(before[i]), "after": hx(self.r[i])}
                   for i in range(16) if before[i] != self.r[i]}
        self.steps.append({
            "pc": hx(pc), "opcode_le": raw.hex(),
            "instruction": f"{ins.mnem} {ins.body}".strip(),
            "T_before": old_t, "T_after": self.t,
            "register_changes": changed,
            "reads": self.mem.reads[read_count:],
            "writes": self.mem.writes[write_count:],
        })
        self.trace.append(pc)
        return next_pc

    def run(self, start: int, stops: set[int], max_steps: int = 256) -> int:
        pc = start
        for _ in range(max_steps):
            if pc in stops:
                return pc
            word = int.from_bytes(self.m.read(pc, 2), "little")
            top = word >> 12
            if top == 8 and (word & 0xFF00) in (0x8900, 0x8B00, 0x8D00, 0x8F00):
                kind = word & 0xFF00
                take = self.t if kind in (0x8900, 0x8D00) else not self.t
                delayed = kind in (0x8D00, 0x8F00)
                dest = pc + 4 + 2 * (((word & 0xFF) ^ 0x80) - 0x80)
                ins = self._decode(pc)
                self.trace.append(pc)
                branch = {"pc": hx(pc), "opcode_le": self.m.read(pc, 2).hex(),
                          "instruction": f"{ins.mnem} {ins.body}".strip(),
                          "T_at_branch": self.t, "taken": bool(take),
                          "target": hx(dest), "delay_slot": hx(pc + 2) if delayed else None}
                self.branches.append(branch)
                if delayed:
                    self.simple(pc + 2)
                pc = dest if take else pc + (4 if delayed else 2)
            elif top == 0xA:  # BRA; its delay slot executes on every path.
                dest = pc + 4 + 2 * (((word & 0xFFF) ^ 0x800) - 0x800)
                ins = self._decode(pc)
                self.trace.append(pc)
                self.branches.append({"pc": hx(pc), "opcode_le": self.m.read(pc, 2).hex(),
                                      "instruction": f"{ins.mnem} {ins.body}".strip(),
                                      "T_at_branch": self.t, "taken": True,
                                      "target": hx(dest), "delay_slot": hx(pc + 2)})
                self.simple(pc + 2)
                pc = dest
            else:
                pc = self.simple(pc)
        raise RuntimeError(f"SH4 slice exceeded {max_steps} steps at {hx(pc)}")


def pcode_listing(m, start: int, end: int) -> list[str]:
    return m.disasm(start, end)


def r8_replay(m) -> dict:
    """Instruction-semantic replay of the exact 160..168 branch sequence."""
    required = {
        0x010AC160: "tst r8,r8",
        0x010AC162: "movt r3",
        0x010AC164: "tst r3,r3",
        0x010AC166: "bt/s 0x10ac188",
        0x010AC168: "mov.l r3,@(0x24,r15)",
    }
    for pc, expected in required.items():
        decoded = m.disasm(pc, pc + 2)[0].lower()
        if expected not in decoded:
            raise AssertionError((hx(pc), decoded, expected))
    cases = []
    for value in (0, 1, 2, 0x80000000, 0xFFFFFFFF):
        # Execute TST, MOVT, TST, then BT/S plus its mandatory delay slot.
        t1 = int((value & value) == 0)
        r3 = t1
        t2 = int((r3 & r3) == 0)
        taken = bool(t2)
        delay_store = {"pc": hx(0x010AC168), "executed": True,
                       "stored_value": hx(r3), "stack_offset": "0x24"}
        cases.append({"input_r8": hx(value),
                      "steps": [
                          {"pc": "0x010AC160", "instruction": "tst r8,r8", "T_after": t1},
                          {"pc": "0x010AC162", "instruction": "movt r3", "r3_after": hx(r3)},
                          {"pc": "0x010AC164", "instruction": "tst r3,r3", "T_after": t2},
                          {"pc": "0x010AC166", "instruction": "bt/s", "taken": taken,
                           "target": "0x010AC188" if taken else "0x010AC16A",
                           "delay_slot": delay_store}],
                      "path": "generator_010AC72C" if taken else "indexed_byte_seed",
                      "result": "TAKEN iff r8 != 0"})
    assert [x["path"] for x in cases] == ["indexed_byte_seed", "generator_010AC72C",
                                                 "generator_010AC72C", "generator_010AC72C",
                                                 "generator_010AC72C"]
    return {"status": "PASS", "basis": "exact original opcodes asserted; SH-4 TST/MOVT/BT-S semantics replayed",
            "delay_slot_executes_on_both_paths": True, "cases": cases,
            "refuted": "r8 == 0 -> generator", "confirmed": "r8 != 0 -> generator"}


def run_real_row(m, prior, row: bytes, side: int, slot: int, label: str) -> dict:
    # The MP0 row is expanded into the actual 16-byte RAM representation read
    # by 0106886C. Address bases are isolated fixtures; their values are explicit.
    src, adj, state, sp = 0x00200000, 0x00300000, 0x00410000, 0x00600000
    expanded = bytearray(16)
    expanded[:10] = row[:10]
    expanded[12:16] = row[10:14]
    c = AuditedSH4(m, prior)
    c.mem.write(src, expanded)
    c.mem.w16(state + 0x38, side)
    c.mem.w16(state + 0x3A, slot)
    c.mem.w32(sp + 0x28, 0)
    c.r[15] = sp
    c.r[4], c.r[5] = adj, src
    c.r[6], c.r[7] = 0, 0
    initial = [hx(x) for x in c.r]
    fixture_writes = list(c.mem.writes)
    c.mem.reads.clear(); c.mem.writes.clear()
    c.run(0x0106886C, {0x01068882})
    producer_end = len(c.trace)
    adj_bytes = bytes(c.mem.bytes.get((adj + i) & MASK32, 0) for i in range(0x12))
    c.r[4], c.r[5], c.r[6], c.r[7] = state, adj, 1, 0
    c.run(0x010AC732, {0x010AC796})
    generator_end = len(c.trace)
    result = c.r[0] & MASK32
    c.r[11] = result
    gate = c.run(0x010AC1F8, {0x010AC1DE, 0x010AC204})
    return {
        "case": label,
        "input": {"section5_row_hex": row.hex(), "expanded_row_hex": expanded.hex(),
                  "side_selector_fixture": side, "predecessor_slot_fixture": slot,
                  "candidate_count_fixture": 1, "candidate_ordinal": 0,
                  "memory_bases": {"expanded_row": hx(src), "adjacency": hx(adj),
                                   "route_state": hx(state), "stack": hx(sp)},
                  "initial_registers_r0_r15": initial},
        "adjacency_after_0106886C": adj_bytes.hex(),
        "fixture_initialization_writes": fixture_writes,
        "result_r0_010AC72C": result,
        "candidate_gate": {"input_r11": hx(c.r[11]), "decision_pc": hx(gate),
                           "skipped": gate == 0x010AC1DE},
        "executed_instructions": [m.disasm(pc, pc + 2)[0] for pc in c.trace],
        "instruction_trace_pc": [hx(pc) for pc in c.trace],
        "branch_decisions": c.branches,
        "memory_reads": c.mem.reads,
        "memory_writes": c.mem.writes,
        "step_register_deltas": c.steps,
        "phase_boundaries": {"after_0106886C": producer_end,
                             "after_010AC72C": generator_end,
                             "after_candidate_gate": len(c.trace)},
        "termination": {"builder": "stop before RTS at 0x01068882",
                        "generator": "stop at loop exit 0x010AC796",
                        "candidate_gate": hx(gate),
                        "scope": "bounded SH4 local slices; no full route-request state"}
    }


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / "tests").mkdir(exist_ok=True)
    mp_script = GEO / "mask_producer_v48" / "reproduce.py"
    prior_script = GEO / "closure_v41" / "reproduce.py"
    mp = load_module("v48_replay_helpers", mp_script)
    prior = mp.prior
    m = Module("NavigationRem.dll")
    if sha(m.b) != DLL_SHA or sha(m.text) != TEXT_SHA:
        raise AssertionError("NavigationRem.dll hash mismatch")
    source, block = mp.mp0.source_block()
    if sha(source) != MP0_SHA:
        raise AssertionError("original EUZ.MP0 hash mismatch")
    sections, counts = mp.topo.layout(block)
    if counts[5] != 706:
        raise AssertionError(f"block 886 Section 5 count changed: {counts[5]}")
    nodes = mp.topo.decode_section4(block[sections[4]:sections[5]], counts[5])
    by_id = {n.physical_id: n for n in nodes}

    # Keep the three prior real samples, including the independently useful
    # edge 593 case. Every endpoint slot is recovered from the actual Section 4.
    edge_ids = [0, 1, 593]
    real_edges = []
    for edge_id in edge_ids:
        row = bytes(block[sections[5] + 14 * edge_id: sections[5] + 14 * (edge_id + 1)])
        a, b = struct.unpack_from("<HH", row, 6)
        if a not in by_id or b not in by_id:
            raise AssertionError(f"endpoint missing for edge {edge_id}")
        slots = [by_id[a].edges.index(edge_id), by_id[b].edges.index(edge_id)]
        real_edges.append({"edge_id": edge_id, "row": row, "row_hex": row.hex(),
                           "endpoints": [a, b], "endpoint_slots": slots,
                           "endpoint_degrees": [by_id[a].degree, by_id[b].degree],
                           "ordered_incident_edges": [by_id[a].edges, by_id[b].edges]})

    # Differential tests: each real edge, each of the 8 bits in each mask byte,
    # plus original baseline, header bit 13, endpoint swap, and isolated gate bit.
    diffs = []
    for item in real_edges:
        row = item["row"]
        for side in (0, 1):
            diffs.append(run_real_row(m, prior, row, side, item["endpoint_slots"][side],
                                      f"edge{item['edge_id']}_baseline_side{side}"))
        for off, side in ((4, 0), (5, 1)):
            for bit in range(8):
                mut = bytearray(row)
                mut[off] ^= 1 << bit
                diffs.append(run_real_row(m, prior, bytes(mut), side,
                                          item["endpoint_slots"][side],
                                          f"edge{item['edge_id']}_byte{off}_bit{bit}"))
        bit13 = bytearray(row)
        word = int.from_bytes(bit13[:4], "little") ^ 0x2000
        bit13[:4] = word.to_bytes(4, "little")
        diffs.append(run_real_row(m, prior, bytes(bit13), 0, item["endpoint_slots"][0],
                                  f"edge{item['edge_id']}_toggle_first_u32_bit13"))
        swapped = bytearray(row)
        swapped[6:8], swapped[8:10] = row[8:10], row[6:8]
        diffs.append(run_real_row(m, prior, bytes(swapped), 0, item["endpoint_slots"][0],
                                  f"edge{item['edge_id']}_swap_endpoint_ids"))
    # Directly perturb the candidate bit after generation to verify the local
    # gate independently of how the upstream mask was seeded.
    gate_mutations = []
    for bit in (0, 1):
        c = AuditedSH4(m, prior)
        c.r[15] = 0x00600000
        c.r[11] = bit
        c.mem.w32(c.r[15] + 0x28, 0)
        initial = [hx(x) for x in c.r]
        fixture_writes = list(c.mem.writes)
        c.mem.reads.clear(); c.mem.writes.clear()
        end = c.run(0x010AC1F8, {0x010AC1DE, 0x010AC204})
        gate_mutations.append({"candidate_bit0_set": bool(bit & 1),
                               "decision_pc": hx(end), "skipped": end == 0x010AC1DE,
                               "initial_registers_r0_r15": initial,
                               "fixture_initialization_writes": fixture_writes,
                               "executed_instructions": [m.disasm(pc, pc + 2)[0] for pc in c.trace],
                               "trace": [hx(x) for x in c.trace], "branches": c.branches,
                               "memory_reads": c.mem.reads, "memory_writes": c.mem.writes,
                               "step_register_deltas": c.steps,
                               "fixture": "candidate ordinal 0; isolate R11 bit only"})
    assert gate_mutations[0]["skipped"] is False and gate_mutations[1]["skipped"] is True

    # Separate Section5 -> callback -> cover -> 0308C1F0 control. Its input
    # pointer is intentionally the same RAM address in this replay; production
    # pointer identity remains unproven.
    r6 = prior.r6_module()
    cover_tests = []
    for item in real_edges:
        for label, offset in (("baseline", None), ("toggle_edge_plus4_at_A_slot", 4),
                              ("toggle_edge_plus5_at_B_slot", 5)):
            variant = bytearray(item["row"])
            if offset is not None:
                side = 0 if offset == 4 else 1
                variant[offset] ^= 1 << item["endpoint_slots"][side]
            masks, converter_trace = mp.replay_fcd8_cover(m, r6, item["edge_id"], bytes(variant))
            consumer = [mp.replay_cover_consumer(m, r6, masks, side,
                                                 item["endpoint_slots"][side]) for side in (0, 1)]
            cover_tests.append({"edge_id": item["edge_id"], "case": label,
                                "source_row_hex": bytes(variant).hex(),
                                "cover_bytes_10_11": list(masks),
                                "converter_pc_trace": converter_trace,
                                "consumer_by_endpoint": consumer,
                                "same_buffer_in_controlled_replay": True,
                                "same_buffer_in_production": "UNKNOWN"})

    # Load real code boundaries from PDATA. Embedded literal pool bytes are
    # recorded separately and not disassembled as instructions.
    # Focused instruction windows. Discontiguous windows avoid decoding
    # inline pointer/constant pools as if they were executable SH4 instructions.
    spans = {
        "AC04C_ENTRY": [(0x010AC04C, 0x010AC080)],
        "AC04C_R8_BRANCH_AND_SEED": [(0x010AC158, 0x010AC1A0)],
        "AC04C_CANDIDATE_GATE": [(0x010AC1F8, 0x010AC204), (0x010AC350, 0x010AC358)],
        "AC72C": [(0x010AC72C, 0x010AC79E)],
        "C1F0": [(0x0108C1F0, 0x0108C220)],
        "AB6F0_context": [(0x010AB6F0, 0x010AB770)],
        "AC3BC_context": [(0x010AC3BC, 0x010AC410), (0x010AC438, 0x010AC45C)],
        "AC5AC": [(0x010AC5AC, 0x010AC610)],
        "AC610_executable_slices": [(0x010AC610, 0x010AC6AC), (0x010AC6C6, 0x010AC72C)],
        "AB4D0_CALL_AND_RETURN_TEST": [(0x010AB54C, 0x010AB55E)],
        "AB4D0_RESULT_CONSUMER_98AE8": [(0x01099046, 0x01099070), (0x01099220, 0x01099248)],
        "98AE8_RESULT_CONSUMER_718AC": [(0x01071958, 0x01071974), (0x010719C0, 0x010719CE)],
        "718AC_RESULT_CONSUMER_6D104": [(0x0106D2B6, 0x0106D2D8), (0x0106D3C4, 0x0106D3DC)],
        "6D104_RESULT_CONSUMER_7AC78": [(0x0107AC96, 0x0107ACA2), (0x0107ACD4, 0x0107AD8C)],
        "FCD8_COVER_CONVERTER": [(0x0101FCD8, 0x0101FD40), (0x0101FD3A, 0x0101FD80),
                                  (0x0101FDC2, 0x0101FDE0)],
        "STRIDE_58_CALL_SETUP": [(0x01099360, 0x0109937A), (0x010995E0, 0x01099620)],
        "STRIDE_58_WRITERS": [(0x01099404, 0x01099424), (0x01099468, 0x01099476),
                              (0x01099480, 0x01099490), (0x010997CC, 0x01099808)],
        "SECTION5_ADJACENCY_COPY": [(0x0106886C, 0x01068882)],
        "SECTION5_EXPANSION_ENTRY": [(0x0104D8A0, 0x0104D8C0)],
    }
    owners = {}
    disassembly = []
    for name, ranges in spans.items():
        range_records = []
        disassembly.append(f"## {name}")
        for start, end in ranges:
            root = m.owner(start)
            if root is None:
                raise AssertionError(f"no PDATA owner for {hx(start)}")
            ix = m.roots.index(root)
            next_root = m.roots[ix + 1] if ix + 1 < len(m.roots) else None
            section = next(s for s in m.h["sections"]
                           if m.base + s["virtual_address"] <= start
                           and end <= m.base + s["virtual_address"] + s["virtual_size"])
            raw_off = section["raw_pointer"] + start - (m.base + section["virtual_address"])
            range_records.append({"range_start": hx(start), "range_end": hx(end),
                                  "runtime_start": hx(start + RUNTIME_DELTA),
                                  "raw_file_offset": hx(raw_off), "link_owner": hx(root),
                                  "owner_next_pdata": hx(next_root) if next_root else None,
                                  "owner_is_exact_start": root == start})
            disassembly.append(f"### {hx(start)}..{hx(end)}; runtime {hx(start+RUNTIME_DELTA)}; raw {hx(raw_off)}; PDATA owner {hx(root)}")
            disassembly.extend(pcode_listing(m, start, end))
        owners[name] = {"ranges": range_records}
        disassembly.append("")
    code_text = ("; Original module: NavigationRem.dll\n"
                 f"; SHA-256: {sha(m.b)}\n; .text SHA-256: {sha(m.text)}\n"
                 "; Decoder: pypcode SuperH4:LE:32:default\n"
                 "; Focused original instruction windows; gaps include literal pools/data and are intentionally omitted.\n\n"
                 + "\n".join(disassembly)
                 + "\n## Literal values\n"
                 + "\n".join(f"{hx(a)} raw={m.read(a,n).hex()} value=0x{int.from_bytes(m.read(a,n),'little'):0{n*2}X}"
                             for a, n in ((0x010AC6B8, 4), (0x010AC6BC, 4), (0x010AC7E8, 2),
                                          (0x010AB614, 4), (0x010AB634, 4), (0x010AB640, 4),
                                          (0x010AB644, 4), (0x0108C224, 4)))
                 + "\n")
    (HERE / "ORIGINAL_DISASSEMBLY.md").write_text(code_text, encoding="utf-8")

    # Executable CFGs. AC3BC and AB6F0 are explicitly tagged as internal ranges
    # of the corresponding owner, not independent functions.
    cfgs = {}
    for key, start, end in (
        ("010AC04C", 0x010AC04C, 0x010AC5AC),
        ("010AC72C", 0x010AC72C, 0x010AC7A0),
        ("0108C1F0", 0x0108C1F0, 0x0108C228),
        ("010AC5AC", 0x010AC5AC, 0x010AC610),
        ("010AC610", 0x010AC610, 0x010AC72C),
        ("010AB4D0", 0x010AB4D0, 0x010ABAC0),
        ("01098AE8", 0x01098AE8, 0x01099288),
        ("010718AC", 0x010718AC, 0x01071A10),
        ("0106D104", 0x0106D104, 0x0106D3DC),
        ("0107AC78", 0x0107AC78, 0x0107AD8C),
        ("0101FCD8", 0x0101FCD8, 0x0101FE5C),
        ("0104D8A0", 0x0104D8A0, 0x0104D97C),
        ("0106886C", 0x0106886C, 0x010688C8),
        ("010688E8", 0x010688E8, 0x01068D38),
        ("010995E0", 0x010995E0, 0x01099620),
        ("01099404", 0x01099404, 0x01099490),
        ("010997CC", 0x010997CC, 0x01099808),
    ):
        cfgs[key] = mp.build_cfg(m, start, end)
    cfgs["internal_ranges"] = {
        "010AC3BC": {"owner": "0x010AC04C", "included_in": "010AC04C CFG"},
        "010AB6F0": {"owner": "0x010AB4D0", "included_in": "010AB4D0 CFG"},
        "interpretation": "CFG reachable instructions with SH4 delay slots executed; indirect targets retained as unresolved where present"
    }
    json_write(HERE / "CFG.json", cfgs)

    callers = mp.literal_callers(m, 0x0108C1F0)
    if len(callers) != 11:
        raise AssertionError(f"expected the targeted 11 C1F0 literal callers; got {len(callers)}")
    route_callers = {
        "010AB4D0": mp.literal_callers(m, 0x010AB4D0),
        "01098AE8": mp.literal_callers(m, 0x01098AE8),
        "010718AC": mp.literal_callers(m, 0x010718AC),
        "0106D104": mp.literal_callers(m, 0x0106D104),
    }
    expected_route_sites = {"010AB4D0": "0x0109904A", "01098AE8": "0x01071960",
                            "010718AC": "0x0106D2C4", "0106D104": "0x0107AC98"}
    for target, expected_pc in expected_route_sites.items():
        sites = [item["call_pc"].upper() for item in route_callers[target]]
        if expected_pc.upper() not in sites:
            raise AssertionError(f"route caller {target}: missing {expected_pc}; got {sites}")
    c1_asm = "\n".join(m.disasm(0x0108C1F0, 0x0108C224))
    if "0108c208 8c01 mov.b @(r0,r8),r1" not in c1_asm.lower():
        raise AssertionError("cover byte load opcode changed")
    consumer = {
        "module_sha256": sha(m.b), "module": "NavigationRem.dll",
        "consumer": {"runtime_va": "0x0308C1F0", "link_va": "0x0108C1F0",
                     "input_R4": "saved to R8 and used as cover base",
                     "byte_loads": ["0108C208: MOV.B @(R0,R8),R1 after R0 is 0/1 and R8 += 0x10",
                                    "selected address is cover+0x10 or cover+0x11"],
                     "result": "R0=-1 on overlap; R0=0 on no overlap",
                     "gate": "TST one_hot,selected_byte; BF/S to 21A on overlap; delay slot sets R0=-1"},
        "direct_literal_callers": callers,
        "direct_bsr_sites": {"0108C1F0": mp.direct_bsr_sites(m, 0x0108C1F0),
                              "010AC04C": mp.direct_bsr_sites(m, 0x010AC04C),
                              "010AC72C": mp.direct_bsr_sites(m, 0x010AC72C)},
        "differential_replay": cover_tests,
        "limits": ["C1F0 input R4 at each live caller is not proven to alias FCD8 callback's R10 output.",
                   "No static direct call from AC04C to C1F0; C1F0 callers consume their local return.",
                   "No result dataflow from C1F0 into AC04C's R11 candidate bitset established.",
                   "Controlled replay intentionally uses the same cover pointer to test the local byte consumer."]
    }
    json_write(HERE / "CONSUMER_TRACE.json", consumer)

    replay = {"status": "PASS_BOUNDED_REPLAY", "dll_sha256": sha(m.b),
              "text_sha256": sha(m.text), "mp0_sha256_before": sha(source),
              "mp0_sha256_after": sha(mp.topo.SOURCE.read_bytes()),
              "block": 886, "section5_edge_count": counts[5],
              "route_state_inputs_are_fixtures": True,
              "real_edges": [{k: v for k, v in e.items() if k != "row"} for e in real_edges],
              "cases": diffs, "candidate_gate_direct_bit_test": gate_mutations,
              "coverage_limits": [
                  "All eight bit positions in each Section5 +4/+5 byte were toggled on three real rows, but the actual Section4 predecessor slots in these rows are only 0/1; bits 2..7 are not validated as live endpoint slots in this block.",
                  "Route selector, predecessor slot and candidate count are controlled fixtures, not captured from a real route request.",
                  "Endpoint-ID swap is observed only through the 0106886C copy + AC72C gate slice; later graph/node lookup rebuilding is outside that replay."
              ],
              "assertions": {"all_eight_bits_of_edge4_and_edge5_tested": True,
                             "three_real_edges": True, "bit13_tested": True,
                             "endpoint_swap_tested": True,
                             "candidate_gate_bit_tested": True,
                             "original_mp0_unchanged": sha(mp.topo.SOURCE.read_bytes()) == MP0_SHA}}
    if replay["mp0_sha256_after"] != MP0_SHA:
        raise AssertionError("MP0 source changed during read-only replay")
    json_write(HERE / "DIFFERENTIAL_REPLAY.json", replay)

    mapping = {"module": m.name, "sha256": sha(m.b), "text_sha256": sha(m.text),
               "preferred_image_base": hx(m.h["image_base"]), "runtime_minus_link_va": hx(RUNTIME_DELTA),
               "sections": [{"name": s["name"], "virtual_address_rva": hx(s["virtual_address"]),
                             "virtual_size": hx(s["virtual_size"]), "raw_pointer": hx(s["raw_pointer"]),
                             "raw_size": hx(s["raw_size"])}
                            for s in m.h["sections"]],
               "code_fragments": owners,
               "raw_offset_formula": "section.raw_pointer + (link_VA - (preferred_base + section.virtual_address))",
               "rva_formula": "link_VA - preferred_image_base",
               "decoder": "pypcode SuperH4:LE:32:default"}
    json_write(HERE / "BINARY_MAPPING.json", mapping)

    r8 = r8_replay(m)
    json_write(HERE / "R8_REPLAY.json", r8)

    edge_mask_json = {
        "section5_to_candidate_mask": {
            "producer": {"function": "0x0106886C", "caller_chain": ["0x0104D8A0 expansion", "0x010688C8", "0x010688E8", "0x0106886C"],
                          "instructions": ["01068874 MOV.B @(5,R5),R0", "0106887C MOV.B R0,@(0x11,GBR)",
                                           "0106887E MOV.B @(4,R5),R0", "01068880 MOV.B R0,@(0x10,GBR)"],
                          "record_stride": "0x34", "confirmed_from_original_code": True},
            "consumer": {"function": "0x010AC72C", "caller": "0x010AC18E from 0x010AC04C",
                         "reads_route_state": ["+0x38 selector", "+0x3A predecessor slot"],
                         "selected_record_byte": "adjacency+0x10 or +0x11",
                         "test": "1 << predecessor_slot", "output": "R0 candidate-ordinal bitset"},
            "gate": {"function": "0x010AC04C", "producer_R0_to_R11": "010AC192 MOV R0,R11",
                     "instruction": "010AC1F8..0202 builds 1<<candidate_ordinal, TST against R11, BF to 010AC1DE on set bit",
                     "effect": "skips this candidate in this local loop"},
            "semantic_limit": "candidate exclusion is confirmed; road access, turn legality, and final route outcome are not established"
        },
        "separate_cover_path": {
            "producer": "0101FCD8 callback copies looked-up bytes to cover+0x10/+0x11",
            "consumer": "0308C1F0 reads selected cover byte and returns -1 on overlap, 0 otherwise",
            "routing_link": "UNKNOWN; no direct C1F0 call or R0-to-R11 dataflow into AC04C established"
        },
        "r11_producers": {
            "initial_assignments": ["010AC078 MOV #1,R11", "010AC100 MOV #0,R11"],
            "seed_when_r8_nonzero": "010AC166 BT/S 010AC188; call 010AC72C; 010AC192 MOV R0,R11",
            "seed_when_r8_zero": "010AC184 BRA 010AC19A; delay 010AC186 EXTu.B R2,R11",
            "post_seed_ORs": [
                {"pc": "010AC1CE", "instruction": "OR R4,R11", "condition": "overlap of candidate one-hot and stride-0x58 value at 010AC1CA"},
                {"pc": "010AC356", "instruction": "OR R13,R11 in BRA delay slot", "condition": "010AC350 CMP/EQ #9 then 010AC352 BF 010AC358 not taken"}
            ],
            "meaning": "local candidate ordinal bitset; full policy UNKNOWN"
        },
        "stride_0x58_runtime_tables": [
            {"base": "0x010F7880", "writer_call": "01099360 -> 010995E0", "conditional_inner_call": "01099612 -> 01099404",
             "stores": ["01099474 writes [R4+4]", "01099488 delay writes [R6+4], where R6=R4+0x58"],
             "second_writer": "010997FA writes [R8+4] with R8=0x010F7880", "field_source_semantics": "UNKNOWN"},
            {"base": "0x010F73E0", "consumer": "010AC1AA loads +4 at R8*0x58 stride", "writer_provenance": "UNKNOWN"}
        ],
        "route_state_selection": {
            "010AC5AC": {"reads": "candidate records at 0x34 stride; compare candidate+0x18 with [R4+4]",
                         "writes": "R4+0x38 word = accumulated matching candidate ordinal bits",
                         "additional_calls": ["0x00FFB7EC", "0x0100A868"], "their semantic effects": "UNKNOWN"},
            "010AC610": {"inputs": "R4 route-state base; R5/R7 adjacency candidate arrays; R6 candidate count; R7 saved as secondary array base",
                         "stride": "0x34", "match_fields": ["state+0x1C vs candidate+8", "state+0x18 vs candidate+4", "state+0x20 vs candidate+0x0C"],
                         "writes": {"+0x3A": "selected candidate ordinal R11", "+0x3C": "bit (state+0x38 >> ordinal)&1",
                                    "+0x44": "preserves all bits except 12..14, then stores ordinal in bits 12..14"},
                         "instruction_proof": [
                             "010AC6C6 MOV #0x3A,R0; 010AC6C8 MOV.W R11,@(R0,R8)",
                             "010AC6CE MOV.W @(0x38,GBR),R0; 010AC6CA NEG R11,R2; 010AC6D4 SHAD R2,R0; 010AC6D8 AND #1,R0; 010AC6DA MOV.W R0,@(0x3C,GBR)",
                             "010AC6D6 MOV.W literal [010AC7E8]=0x8FFF,R2; pypcode lifts MOV.W as sign-extended 0xFFFF8FFF",
                             "010AC6E2 load [R8+0x44]; 010AC6E4 AND with 0xFFFF8FFF clears bits 12..14 only",
                             "010AC6E8 SHLD R2,R3 with R2=12; 010AC6EC forms 0x7000; 010AC6EE masks ordinal to bits 12..14; 010AC6F0 OR; 010AC6F2 store [R8+0x44]"],
                         "selection_helpers": ["0x01016684", "0x00FF8910"], "cost/policy semantics": "UNKNOWN"}
        }
    }
    json_write(HERE / "MASK_PRODUCERS.json", edge_mask_json)

    lineage = {
        "binaries": {"NavigationRem.dll_sha256": sha(m.b), "NavigationRem.dll_text_sha256": sha(m.text),
                     "EUZ.MP0_sha256": sha(source), "block": 886},
        "section5_to_adjacency": {"source_row_bytes": "Section5 row +4/+5", "source_expansion": "0104D8A0",
                                   "exact_copy_instructions": ["01068874 read row+5", "0106887C write adjacency+0x11",
                                                                "0106887E read row+4", "01068880 write adjacency+0x10"],
                                   "row_hex_examples": [{"edge_id": e["edge_id"], "row_hex": e["row_hex"]} for e in real_edges]},
        "adjacency_to_R11": {"adjacency_base_in_demonstrated_caller": "0x010F6D60",
                             "callsite": "010AB552 -> 010AC04C", "generator_callsite": "010AC18E -> 010AC72C",
                             "generator_result": "R0 -> R11 at 010AC192",
                             "candidate_gate": "010AC200 TST; 010AC202 BF 010AC1DE when bit is set"},
        "cover_path": {"callback": "0101FCD8", "callback_output_pointer": "R10", "consumer_input_pointer": "R4 saved in R8 at 0108C1F0",
                       "pointer_alias_in_real_callers": "UNKNOWN", "same-pointer test fixture": "0x00930000", "result_to_AC04C": "UNKNOWN"},
        "route_state_fields": {"0x010AC5AC": "writes R4+0x38 candidate ordinal bitmap from .34-stride scan",
                               "0x010AC610": {"+0x3A": "candidate ordinal", "+0x3C": "selected bit from +0x38",
                                              "+0x44": "ordinal encoded in bits 12..14, other bits preserved"},
                               "business meanings": "UNKNOWN beyond these exact bit operations"}
    }
    lineage["higher_level_status_chain"] = {
        "purpose_limit": "static call and return-control chain only; not an end-to-end route-result classification",
        "links": [
            {"target": "0x010AB4D0", "call_pc": "0x0109904A", "caller": "0x01098AE8",
             "caller_pdata_owner": "0x01098AE8", "delay_slot": "0109904C MOV R9,R4",
             "after_return": ["01099050 CMP/EQ #-1,R0", "01099052 BF 01099060"],
             "observed_control": "R0 != -1 takes branch to 01099060; R0 == -1 falls through and continues the alternate path"},
            {"target": "0x01098AE8", "call_pc": "0x01071960", "caller": "0x010718AC",
             "delay_slot": "01071962 ADD R15,R6", "after_return": ["01071966 MOV R0,R9", "0107196A CMP/EQ #4,R9", "0107196C BF/S 01071974"],
             "return": "if R9==4, BF/S is not taken and BRA at 01071970 returns R9 via delay 01071972; if R9!=4, BF/S takes 01071974 for more callbacks, then R9 reaches R0 at 010719C0"},
            {"target": "0x010718AC", "call_pc": "0x0106D2C4", "caller": "0x0106D104",
             "delay_slot": "0106D2C6 MOV.L @(0x1C,R15),R4", "after_return": ["0106D2C8 TST R0,R0", "0106D2CE BT/S 0106D346"],
             "return": "R0 copied to R11 at 0106D2CC; later status checks alter R11 on some arms; function returns R11 at 0106D3C8"},
            {"target": "0x0106D104", "call_pc": "0x0107AC98", "caller": "0x0107AC78",
             "delay_slot": "0107AC9A MOV R8,R4", "after_return": ["0107AC9C TST R0,R0", "0107AC9E BF/S 0107ACD4", "0107ACA0 MOV R0,R10 (delay)"],
             "return": "local handler later sets R0=0 at 0107AD7E and returns at 0107AD88; this is handler completion, not a proven route/no-route result"}
        ],
        "direct_bsr_to_010AB4D0": mp.direct_bsr_sites(m, 0x010AB4D0),
        "literal_call_xrefs_are_targeted_to_known_link_values": True,
        "unresolved": "the runtime/external caller of 0x0107AC78 and interpretation of the status values as route choice remain UNKNOWN"
    }
    json_write(HERE / "MEMORY_LINEAGE.json", lineage)

    # Hashes only; no proprietary executable or full binary dump is emitted.
    hashes = [f"{sha(m.b)}  NavigationRem.dll (archived original module; not included)",
              f"{sha(m.text)}  NavigationRem.dll .text (hash only)",
              f"{sha(source)}  EUZ.MP0 (original; not included)",
              f"{sha((GEO / 'mask_producer_v48' / 'reproduce.py').read_bytes())}  mask_producer_v48/reproduce.py",
              f"{sha(prior_script.read_bytes())}  closure_v41/reproduce.py",
              f"{sha(Path(__file__).read_bytes())}  routing_closure_v78/reproduce.py",
              f"{sha((HERE / 'tests' / 'test_artifacts.py').read_bytes())}  routing_closure_v78/tests/test_artifacts.py"]
    (HERE / "tests" / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="utf-8")

    write_docs(HERE, m, owners, real_edges, callers, replay, r8, edge_mask_json, consumer)
    print(json.dumps({"status": "PASS_BOUNDED_REPLAY", "edges": edge_ids,
                      "differential_cases": len(diffs), "cover_cases": len(cover_tests),
                      "C1F0_callers": len(callers), "r8_cases": len(r8["cases"]),
                      "MP0_unchanged": replay["assertions"]["original_mp0_unchanged"],
                      "artifacts": str(HERE)}, ensure_ascii=False))


def write_docs(out, m, owners, edges, callers, replay, r8, producers, consumer):
    edge_rows = "\n".join(f"| {e['edge_id']} | `{e['row_hex']}` | {e['endpoints']} | {e['endpoint_slots']} | {e['endpoint_degrees']} |" for e in edges)
    (out / "EVIDENCE.md").write_text(f"""# NCDR route closure v78 — evidence

## Scope and provenance

This package rechecks original bytes from the archived `NavigationRem.dll` and the read-only original `EUZ.MP0`. SHA-256 values are in `tests/SHA256SUMS.txt`. The program uses pypcode `SuperH4:LE:32:default`; all mutations are in sparse RAM fixtures. No MP0/Writer/database output is written.

| Edge ID | Original Section 5 row | endpoint IDs | Section 4 slots | endpoint degrees |
|---:|---|---|---|---|
{edge_rows}

## Confirmed machine-level chain

1. `0106886C` copies Section 5 byte `+5` to adjacency `+0x11` (`01068874`, `0106887C`) and byte `+4` to adjacency `+0x10` (`0106887E`, `01068880`).
2. `010AC72C` selects one byte using route-state `+0x38`, reads predecessor slot `+0x3A`, tests `1 << slot`, and returns candidate-ordinal bits in `R0`.
3. In the caller, `010AC192 MOV R0,R11`; `010AC200 TST` and `010AC202 BF 010AC1DE` skip the current candidate when its bit is set.
4. Exact `r8` branch replay is in `R8_REPLAY.json`: generator path is taken iff `r8 != 0`; the `010AC168` delay slot executes on either path.

This proves a Section 5 attribute affects a local candidate skip in a bounded routing-search routine. The sample endpoints have actual predecessor slots only 0/1; toggling bits 2–7 does not test those bits at a real high-degree endpoint. It does **not** prove a forbidden legal turn, a road-level access rule, or a final route/no-route outcome.

## Separate cover consumer

`0308C1F0` reads `cover+0x10/+0x11`, tests the selected bit, and returns `-1` on overlap or `0` otherwise. Eleven direct literal-call sites were found by targeted pointer xref. Its live input-pointer identity with the `0101FCD8` callback output and any result path into `010AC04C` remain UNKNOWN. The controlled replay deliberately reuses one buffer to verify only local semantics.

## Newly verified route-state writes

`010AC5AC` scans `.34`-stride candidate rows and writes a candidate-ordinal bitmap to `state+0x38` (`010AC5D8`). `010AC610` has two `.34`-stride arrays and, after matching fields and helper calls, writes: `+0x3A = selected ordinal` (`010AC6C8`); `+0x3C = bit ((state+0x38 >> ordinal) & 1)` (`010AC6CE–6DA`); `+0x44` preserves other bits and replaces bits 12–14 with the selected ordinal (`010AC6D6–6F2`). The mask literal at `010AC7E8` is `0x8FFF`; the SH4 `MOV.W` sign-extends it to `0xFFFF8FFF`, so `AND` clears exactly bits 12–14 of the 32-bit field. The business meanings and helper-produced score are still UNKNOWN.

The `.58`-stride tables are distinct addresses (`0x010F7880`, `0x010F73E0`). Writes to one table are confirmed in `01099404` and `010997FA`; their semantic source/policy and relationship to Sections 6–9/RT/RL are UNKNOWN.

## Test coverage and limits

`DIFFERENTIAL_REPLAY.json` contains {len(replay['cases'])} bounded cases on three original edges: baseline at each endpoint, every individual bit of Section 5 `+4` and `+5`, first-u32 bit 13, endpoint-ID swap, and direct candidate-gate bit mutation. Every case records initial registers, expanded row/adjacency, executed original opcodes, memory reads/writes, branches, and stop reason. Route selector/slot/count are controlled fixtures based on real Section 4 slots, not a captured device route request. The original MP0 SHA-256 was unchanged.
""", encoding="utf-8")

    (out / "CONTRADICTIONS.md").write_text(f"""# Evidence reconciliation

## Local artifacts present / absent

Present and read: `mask_producer_v48`, `route_closure_066`, `closure_v41`, `payload_consumers_v21`, `caller_v40`, `sh4_audit_051`. Absent at the requested paths: `cover_routing_v47`, `routing_engine_v77`, `route_closure_066` is present, `cover_xref_v46`, `consumer_trace_v22`, `qwen_redteam_063`. No claims from an absent report are treated as evidence.

## Conflict matrix

| Claim | Verdict | Direct check |
|---|---|---|
| `r8 == 0` calls `010AC72C` | REFUTED | `010AC160 TST; 162 MOVT; 164 TST; 166 BT/S 188`; exact test cases in `R8_REPLAY.json`. |
| `r8 != 0` calls `010AC72C` | CONFIRMED | `BT/S` takes only for nonzero r8 after the second `TST`; delay `010AC168` executes both ways. |
| Section 5 `+4/+5` become candidate exclusion bits | CONFIRMED, local scope | Original copy opcodes at `01068874/7C/7E/80`, consumer at `010AC75A–768`, caller seed `010AC192`, local skip at `010AC200–202`; differential replay. |
| Route-state writers for `+0x38/+0x3A/+0x3C/+0x44` were entirely unknown | NARROWED | `010AC5D8` writes `+0x38`; `010AC6C8` writes selected ordinal to `+0x3A`; `010AC6DA` writes the selected bit to `+0x3C`; `010AC6F2` replaces bits 12–14 in `+0x44`. Their semantic origin before this producer chain and actual request inputs remain UNKNOWN. |
| `cover+0x10/+0x11` and adjacency `+0x10/+0x11` are the same structure | REFUTED as a proven identity | Independent producer pointers and consumers; no alias/dataflow proof. Similar offsets are insufficient. |
| `caller_v40/COVER_CONSUMERS.md`: no consumer of cover `+0x10/+0x11` found | REFUTED as a complete inventory; ROUTING ROLE UNKNOWN | `0308C1F0` directly loads the selected cover byte at `0108C208`; its 11 callers are outside the demonstrated AC04C path. |
| C1F0 result reaches AC04C's R11 | UNKNOWN | 11 caller sites are outside AC04C; no direct call or result def-use into R11 found. |
| Section 5 mask changes final route availability | UNKNOWN | Local candidate skip is proven; full request state and final route result are not replayed. |
| No Section 7–9 record is needed for a new routable edge | UNKNOWN | The examined mask chain does not prove completeness of all route inputs. |

`DIFFERENTIAL_REPLAY.json` directly tests the requested fields. The tests only interpret the original SH4 slices and controlled in-memory state; they do not promote local branch effects into map-wide semantics.
""", encoding="utf-8")

    (out / "ROUTING_GATE.md").write_text("""# Routing gate and result boundary

## Proven local gate

`Section5 row +4/+5 -> 0106886C -> adjacency row +0x10/+0x11 -> 010AC72C R0 -> 010AC192 R11 -> 010AC200 TST -> 010AC202 BF 010AC1DE`.

At the tested branch, a set bit for the current candidate ordinal takes the branch to candidate advance; the current candidate is skipped. The replay executes the actual builder copy, actual candidate-mask function, and actual gate on three original MP0 rows. It records all read/write addresses and SH4 branch outcomes.

An adjacent route-state selection procedure is also visible: `010AC5AC` writes a bitmap at `+0x38`; `010AC610` writes selected ordinal at `+0x3A`, selected bitmap bit at `+0x3C`, and ordinal into dword `+0x44` bits 12–14. These transformations are confirmed; they do not prove that a Section 5 byte controls final route availability.

## Not proven

- Whether an excluded candidate is later reconsidered through another adjacency or search state.
- Whether any mask bit is a legal one-way, turn-prohibition, or access restriction.
- Whether C1F0 is a map-matching filter, a routing filter, or both in all its callers.
- Which full route-state fields and RT/RL records are mandatory for a new edge.
- The upper-level caller's final route result. Static literal-call links now extend `010AB4D0 -> 01098AE8 -> 010718AC -> 0106D104 -> 0107AC78`, but this chain carries status/control values and the runtime/external caller of `0107AC78` plus final route-choice interpretation are unresolved.

Therefore the result is an actual candidate-list exclusion in one examined search loop, not a complete route decision. A new edge is not yet proven to be routable.
""", encoding="utf-8")

    (out / "BLOCKERS.md").write_text("""# Remaining blockers

1. **Live route-state provenance.** The selector (`state+0x38`), predecessor slot (`+0x3A`), candidate count, and candidate list are controlled fixtures, not captured values from an actual route request. Capture one request entering `010AB4D0` / `010AC04C` to verify the exercised path and actual order.
2. **Candidate choice above the local gate.** Static callers now show `010AB4D0 -> 01098AE8 -> 010718AC -> 0106D104 -> 0107AC78`, and the intermediate R0 tests are decoded. The values are handled as local status/control fields; the runtime/external caller of `0107AC78` and the final route-choice/result consumer remain unresolved.
3. **C1F0 pointer/dataflow.** Need one live call chain from the `0101FCD8` output pointer to a C1F0 caller's R4, and its returned R0 through to any routing-state transition. Static direct xrefs are distinct from AC04C.
4. **Cost and auxiliary records.** `010AC610` invokes `01016684` and `00FF8910`; those return values affect candidate selection. The `.58`-stride arrays are mutated, but their semantic sources and Section6–9/RT/RL membership rules are not known.
5. **Route interpretation.** Local set-bit behavior is skip-current-candidate only. Need a differential full route request on an independent route fixture or device/runtime capture before asserting final road/turn availability.

Highest-value next experiment: resolve the runtime caller of `0107AC78`, then instrument one real route request from `010AB4D0` through `010AC04C` and capture pointed route-state memory, return values and final consumer; replay only one matching Section5 mask bit against that captured state.
""", encoding="utf-8")

    (out / "EVIDENCE.md").write_text(f"""# v78 compact evidence index

- Original NavigationRem.dll SHA-256: `{sha(m.b)}`; `.text`: `{sha(m.text)}`.
- Original EUZ.MP0 SHA-256 before/after: `{replay['mp0_sha256_before']}` / `{replay['mp0_sha256_after']}`.
- pypcode SH4 little-endian listing and mapping: `ORIGINAL_DISASSEMBLY.md`, `BINARY_MAPPING.json`.
- Rebuilt reachable CFGs with delay slots: `CFG.json`.
- R8 condition replay: `R8_REPLAY.json` ({len(r8['cases'])} test values).
- Section 5 bit replay: `DIFFERENTIAL_REPLAY.json` ({len(replay['cases'])} cases; three original edges).
- Cover consumer trace/callers: `CONSUMER_TRACE.json`.
- Producer/source chains: `MEMORY_LINEAGE.json`, `MASK_PRODUCERS.json`.
- Static higher-level status-call chain `0109904A -> 01071960 -> 0106D2C4 -> 0107AC98`: `MEMORY_LINEAGE.json`, `CFG.json`, and `ORIGINAL_DISASSEMBLY.md`; status flow is not classified as route success/failure.
- Executable assertions and captured output: `reproduce.py`, `tests/test_artifacts.py`, `tests/stdout.txt`, `tests/stderr.txt`.
- Interpretation and blockers: `ROUTING_GATE.md`, `BLOCKERS.md`, `CONTRADICTIONS.md`.

Only the local candidate exclusion is confirmed. End-to-end route selection remains UNKNOWN.
""", encoding="utf-8")


if __name__ == "__main__":
    main()
