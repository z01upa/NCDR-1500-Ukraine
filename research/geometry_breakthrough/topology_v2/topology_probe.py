"""Read-only byte-level probe of MP0 sections 4 and 5.

This script does not edit the source MP0. Its hypotheses are deliberately
descriptive; fields are not assigned semantics unless separately validated.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import os
import struct
import zlib

SOURCE = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3])) / 'SW' / 'DB' / 'EUZ.MP0'
OUT = Path(__file__).resolve().parent
HEADER = 114
ENTRY = 24
BLOCKS = 2956


def u16(buf: bytes, pos: int) -> int:
    return struct.unpack_from("<H", buf, pos)[0]


def read_blocks(path: Path):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != "73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e":
        raise ValueError("source MP0 hash differs from the reviewed original")
    count = struct.unpack_from("<I", data, 86)[0]
    if count != BLOCKS or u16(data, 112) != count:
        raise ValueError("unexpected MP0 block count")
    payload_floor = HEADER + 28 * count
    streams = []
    for block in range(count):
        row = HEADER + ENTRY * block
        offset, raw_size, packed_size = struct.unpack_from("<IHH", data, row + 16)
        if offset < payload_floor or offset + packed_size > len(data):
            raise ValueError(f"block {block}: bad stream extent")
        dec = zlib.decompressobj()
        raw = dec.decompress(data[offset:offset + packed_size], raw_size + 1)
        raw += dec.flush()
        if not dec.eof or dec.unused_data or dec.unconsumed_tail or len(raw) != raw_size:
            raise ValueError(f"block {block}: invalid exact zlib stream")
        streams.append(raw)
    physical = sorted((struct.unpack_from("<I", data, HEADER + ENTRY * i + 16)[0], i) for i in range(count))
    cursor = payload_floor
    for offset, block in physical:
        size = struct.unpack_from("<H", data, HEADER + ENTRY * block + 22)[0]
        if offset != cursor:
            raise ValueError(f"physical gap/overlap before block {block}")
        cursor += size
    if cursor != len(data):
        raise ValueError("unindexed/trailing bytes")
    return data, streams


def parse_block(raw: bytes, block: int):
    sections = [u16(raw, 4 * i) for i in range(11)]
    counts = [u16(raw, 4 * i + 2) for i in range(11)]
    n_nodes, n_edges = counts[4], counts[5]
    if sections[5] - sections[4] != 10 * n_nodes:
        raise ValueError(f"block {block}: section 4 stride/count disagreement")
    if sections[6] - sections[5] != 14 * n_edges:
        raise ValueError(f"block {block}: section 5 stride/count disagreement")
    nodes = []
    for n in range(n_nodes):
        pos = sections[4] + 10 * n
        rec = raw[pos:pos + 10]
        nodes.append({
            "id": n,
            "offset": pos,
            "hex": rec.hex(),
            "b0": rec[0],
            "b1": rec[1],
            "refs": list(struct.unpack_from("<4H", rec, 2)),
        })
    edges = []
    for e in range(n_edges):
        pos = sections[5] + 14 * e
        flags, attributes, unresolved, a, b, length = struct.unpack_from("<5HI", raw, pos)
        edges.append({"id": e, "offset": pos, "flags": flags,
                      "attributes": attributes, "unresolved": unresolved,
                      "a": a, "b": b, "length": length,
                      "hex": raw[pos:pos + 14].hex()})
    return sections, counts, nodes, edges


def main() -> None:
    data, streams = read_blocks(SOURCE)
    digest = hashlib.sha256(data).hexdigest()
    tally = Counter()
    degree_matrix = Counter()
    degree_cases = Counter()
    all_nodes = 0
    block_rows = []
    examples = defaultdict(list)
    node_ref_samples = defaultdict(list)
    attr_values = Counter()
    unresolved_values = Counter()
    flag_values = Counter()
    bit_counts = {name: Counter() for name in ("flags", "attributes", "unresolved")}
    reciprocity = Counter()
    mismatch_examples = []
    all_graph_ok = True

    for block, raw in enumerate(streams):
        sections, counts, nodes, edges = parse_block(raw, block)
        n_nodes, n_edges = len(nodes), len(edges)
        incidences = [[] for _ in nodes]
        for e in edges:
            flag_values[e["flags"]] += 1
            attr_values[e["attributes"]] += 1
            unresolved_values[e["unresolved"]] += 1
            for name, value in (("flags", e["flags"]), ("attributes", e["attributes"]), ("unresolved", e["unresolved"])):
                for bit in range(16):
                    if value & (1 << bit):
                        bit_counts[name][bit] += 1
            # The documented selectors mark section-2 endpoints. Section-4
            # node indexes are expected only for non-secondary endpoints.
            for side, index, selector in (("a", e["a"], 0x1000), ("b", e["b"], 0x2000)):
                if e["flags"] & selector:
                    tally[f"secondary_{side}_endpoints"] += 1
                    continue
                tally[f"primary_{side}_endpoints"] += 1
                if index >= n_nodes:
                    tally["primary_endpoint_out_of_range"] += 1
                    all_graph_ok = False
                    if len(mismatch_examples) < 30:
                        mismatch_examples.append({"block": block, "edge": e["id"], "side": side,
                                                  "node_index": index, "node_count": n_nodes,
                                                  "kind": "endpoint_out_of_range"})
                else:
                    incidences[index].append(e["id"])

        for node, incident in zip(nodes, incidences):
            all_nodes += 1
            actual = len(incident)
            tally["nodes"] += 1
            tally[f"actual_degree_{actual}"] += 1
            degree_nibble = node["b0"] & 0x0F
            high_nibble = node["b0"] >> 4
            tally[f"stored_low_nibble_{degree_nibble}"] += 1
            tally[f"stored_high_nibble_{high_nibble}"] += 1
            degree_matrix[(actual, degree_nibble)] += 1
            degree_cases[f"stored_degree_{degree_nibble}"] += 1
            # The first byte's low nibble is tested as a count: only that
            # many of the four u16 slots are interpreted as inline refs.
            n_inline = min(degree_nibble, 4)
            inline = node["refs"][:n_inline]
            local_inline = [r for r in inline if r < n_edges]
            for slot, ref in enumerate(inline):
                if ref >= n_edges:
                    tally[f"inline_slot{slot}_outside_local_edge_range"] += 1
                else:
                    tally[f"inline_slot{slot}_local_edge_id"] += 1
            if degree_nibble <= 4 and sorted(local_inline) == sorted(incident):
                tally["degree_le4_local_incidence_refs_match"] += 1
            elif degree_nibble <= 4:
                tally["degree_le4_local_incidence_refs_mismatch"] += 1
                all_graph_ok = False
                if len(mismatch_examples) < 30:
                    examples[actual].append({"block": block, "node": node["id"], "record_offset": node["offset"],
                                             "record_hex": node["hex"], "actual_local_degree": actual,
                                             "stored_degree_nibble": degree_nibble, "byte1": node["b1"],
                                             "expected_local_edges": incident, "inline_refs": inline})
                    mismatch_examples.append(examples[actual][-1])
            else:
                # Degree > 4 cannot fit in the four 16-bit slots. Retain the
                # cases as evidence for discovering the overflow mechanism.
                tally["degree_gt4_needs_overflow_representation"] += 1
                all_graph_ok = False
                if len(mismatch_examples) < 30:
                    examples[actual].append({"block": block, "node": node["id"], "record_offset": node["offset"],
                                             "record_hex": node["hex"], "actual_local_degree": actual,
                                             "stored_degree_nibble": degree_nibble, "byte1": node["b1"],
                                             "expected_local_edges": incident, "four_u16_slots": node["refs"]})
                    mismatch_examples.append(examples[actual][-1])
            if actual <= 8 and len(node_ref_samples[actual]) < 8:
                node_ref_samples[actual].append({"block": block, "node": node["id"], "record_offset": node["offset"],
                                                 "record_hex": node["hex"], "degree_byte": node["b0"],
                                                 "byte1": node["b1"], "expected_edges": incident,
                                                 "u16_offsets_2_4_6_8": node["refs"]})
        block_rows.append({"block": block, "raw_size": len(raw), "node_count": n_nodes,
                           "edge_count": n_edges, "section4_offset": sections[4],
                           "section5_offset": sections[5], "section6_offset": sections[6]})

    result = {
        "source": str(SOURCE), "source_sha256": digest,
        "blocks": len(streams), "all_streams_exactly_inflated": len(streams),
        "nodes": all_nodes, "counts": dict(tally),
        "degree_nibble_vs_actual_degree": {f"actual{a}_stored{b}": n for (a, b), n in sorted(degree_matrix.items())},
        "edge_attribute_top_values": {"flags": flag_values.most_common(30),
                                      "attributes": attr_values.most_common(30),
                                      "unresolved": unresolved_values.most_common(30)},
        "bit_occurrences": {k: {str(bit): count for bit, count in sorted(v.items())} for k, v in bit_counts.items()},
        "representative_node_records": {str(k): v for k, v in node_ref_samples.items()},
        "mismatch_examples": mismatch_examples[:30],
        "all_local_adjacency_fully_validated": all_graph_ok,
        "note": "The low nibble appears to be an adjacency degree count. For degree <=4, only that many u16 slots from +2 are candidate inline references. Degree >4 necessarily requires an overflow/continuation representation not yet identified.",
    }
    (OUT / "topology_probe.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("source_sha256", "blocks", "all_streams_exactly_inflated", "nodes", "counts", "degree_nibble_vs_actual_degree", "edge_attribute_top_values", "all_local_adjacency_fully_validated")}, indent=2))


if __name__ == "__main__":
    main()
