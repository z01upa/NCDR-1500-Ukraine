"""Reproducible pre-write gate for a candidate local edge insertion.

It records what can be planned from confirmed section-4 fields and then
refuses before producing MP0 bytes wherever section semantics remain unknown.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from topology_validator import SOURCE, _read_container, _section_pairs
from decoder import decode_runs


def build_gate_report(block_id: int = 886, node_a: int = 412, node_b: int = 414) -> dict:
    _, blocks = _read_container(SOURCE)
    raw = blocks[block_id]
    offsets, counts = _section_pairs(raw)
    main, _ = decode_runs(raw, offsets[0], offsets[1], counts[0])
    incident_by_node = [[] for _ in main]
    for edge_id in range(counts[5]):
        edge_pos = offsets[5] + 14 * edge_id
        flags, _, _, ea, eb = struct.unpack_from("<5H", raw, edge_pos)
        if not flags & 0x1000:
            incident_by_node[ea].append(edge_id)
        if not flags & 0x2000:
            incident_by_node[eb].append(edge_id)
    coordinate_frequency = {}
    for point in main:
        coordinate_frequency[point] = coordinate_frequency.get(point, 0) + 1
    degree_data = []
    for node_id in (node_a, node_b):
        pos = offsets[4] + 10 * node_id
        rec = raw[pos:pos + 10]
        degree = rec[0] & 0x0F
        refs = list(struct.unpack_from("<4H", rec, 2))
        local_refs = [ref for ref in refs[:degree] if ref < counts[5]]
        incidence_exact = sorted(local_refs) == sorted(incident_by_node[node_id])
        degree_data.append({"node": node_id, "coordinate_integer": main[node_id],
                            "record_offset": pos, "record_hex": rec.hex(),
                            "degree_low_nibble": degree,
                            "active_candidate_refs": refs[:min(degree, 4)],
                            "local_incident_edges": incident_by_node[node_id],
                            "active_local_refs_match_incidence": incidence_exact,
                            "coordinate_duplicate_count": coordinate_frequency[main[node_id]],
                            "next_slot_u16_at_plus_8": refs[3]})
    dx, dy = main[node_b][0] - main[node_a][0], main[node_b][1] - main[node_a][1]
    distance_m = math.hypot(dx * math.cos((main[node_a][1] + main[node_b][1]) / 200000 * math.pi / 180), dy) * 1.11195
    a, b = sorted((node_a, node_b))
    already_connected = False
    for edge_id in range(counts[5]):
        pos = offsets[5] + 14 * edge_id
        flags, _, _, ea, eb = struct.unpack_from("<5H", raw, pos)
        if not flags & 0x3000 and tuple(sorted((ea, eb))) == (a, b):
            already_connected = True
            break
    section_lengths = {str(s): offsets[s + 1] - offsets[s] for s in range(6, 10)}
    section_counts = {str(s): counts[s] for s in range(6, 10)}
    existing_edge_count = counts[5]
    result = {
        "status": "REFUSED_BEFORE_MP0_MUTATION",
        "source_sha256": "73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e",
        "candidate": {"block": block_id, "nodes": degree_data,
                      "approximate_straight_line_separation_m": distance_m,
                      "already_connected_by_local_primary_edge": already_connected,
                      "current_edge_count": existing_edge_count,
                      "hypothetical_new_edge_id_if_appended": existing_edge_count,
                      "known_inline_adjacency_capacity": all(row["degree_low_nibble"] <= 3 and row["active_local_refs_match_incidence"] and row["coordinate_duplicate_count"] == 1 for row in degree_data)},
        "layout_only_if_supported": {
            "new_section5_record_size_bytes": 14,
            "new_edge_count": existing_edge_count + 1,
            "downstream_section_offsets_if_inserted_at_section5_end_shift_bytes": 14,
            "section6_to_9_existing_count_and_size": {"counts": section_counts, "byte_lengths": section_lengths},
            "mutation_performed": False,
            "mp0_file_written": False,
        },
        "specific_write_blockers": [
            "Both candidate nodes have low-nibble degree 3 and the three active references match their actual local incident edges, but each next u16 slot at +8 is already nonzero (518 and 271). It is not established whether raising degree to 4 permits replacing these bytes or whether another firmware consumer uses them.",
            "Section 5 attributes at +2 and unresolved at +4 have not been assigned safe semantics/defaults; copying arbitrary values or zeroing them would invent route behavior.",
            "Only coordinate-table selectors 0x1000/0x2000 and shape-present 0x8000 are interpreted. Other flag bits and direction/access semantics remain unresolved.",
            "Sections 7, 8, and 9 are present after section 5 (7-byte records in section 7 for all blocks; 11-byte records when section 8 has entries; 13-byte section-9 records in 26 blocks). Their association with edge indexes is not known, so appending 14 bytes and shifting offsets alone is not proven sufficient.",
        ],
        "decision": "Do not serialize a new edge until the inactive section-4 slot and the section-5/sections-7-9 dependencies are resolved. A syntactically parseable edge with guessed fields is not a safe topology result.",
    }
    (HERE / "edge_insertion_gate.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(build_gate_report(), indent=2))
