"""Full-map connectivity audit built on the existing independent MP0 parser.

This is independent from Writer v1: it imports no writer or geometry decoder.
The container and section primitives are reused from topology_v3's standalone
standard-library reader so this module does not create a second MP0 parser.
Unknown/high-degree fields are reported, never interpreted as free storage.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
GEOMETRY = HERE.parent
TOPOLOGY_V3 = GEOMETRY / "topology_v3"
if str(TOPOLOGY_V3) not in sys.path:
    sys.path.insert(0, str(TOPOLOGY_V3))

from node_link_validator import SOURCE, EXPECTED_SHA256, _read_container, _sections  # noqa: E402

EVIDENCE = HERE / "evidence"


def audit_topology(source: Path = SOURCE, *, write_evidence: bool = True) -> dict:
    before_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    data, blocks = _read_container(source)
    if before_hash != EXPECTED_SHA256 or hashlib.sha256(data).hexdigest() != before_hash:
        raise ValueError("MP0 does not match the existing read-only source manifest")

    totals = Counter()
    degree_rows = Counter()
    exact_by_degree = Counter()
    primary_endpoints_by_degree = Counter()
    primary_link_pass_by_degree = Counter()
    primary_link_fail_by_degree = Counter()
    high_degree_rows = Counter()
    high_primary_endpoints = Counter()
    high_word_memberships = Counter()
    high_slot_hits = Counter()
    low_degree_samples: dict[str, dict] = {}
    high_degree_samples: dict[str, list[dict]] = defaultdict(list)
    node_mismatches: list[dict] = []
    endpoint_errors: list[dict] = []
    block_results: list[dict] = []
    flags = Counter()
    attributes = Counter()
    unresolved = Counter()
    flags_bits = Counter()
    attribute_bits = Counter()
    unresolved_bits = Counter()
    secondary_cross_endpoints = 0
    sections_pass = 0
    aux_sections = {str(section): {"record_width": width, "rows": 0,
        "populated_blocks": 0, "records_with_first_u16_below_edge_count": 0,
        "records_with_first_u16_below_node_count": 0,
        "records_edge_domain_only": 0, "nondecreasing_key_blocks": 0,
        "layout_errors": 0, "samples": []}
        for section, width in ((7, 7), (8, 11), (9, 13))}

    for block_id, raw in enumerate(blocks):
        offsets, counts = _sections(raw)
        primary_count, secondary_count = counts[0], counts[2]
        node_count, edge_count = counts[4], counts[5]
        if node_count != primary_count or offsets[5] - offsets[4] != 10 * node_count:
            raise ValueError(f"block {block_id}: node table/Section 4 mismatch")
        if offsets[6] - offsets[5] != 14 * edge_count:
            raise ValueError(f"block {block_id}: Section 5 stride mismatch")
        for section, width in ((7, 7), (8, 11), (9, 13)):
            section_stats = aux_sections[str(section)]
            start, end, count = offsets[section], offsets[section + 1], counts[section]
            if end - start != width * count:
                section_stats["layout_errors"] += 1
                raise ValueError(f"block {block_id}: Section {section} stride mismatch")
            if count:
                section_stats["populated_blocks"] += 1
            section_stats["rows"] += count
            keys = [struct.unpack_from("<H", raw, start + i * width)[0] for i in range(count)]
            section_stats["records_with_first_u16_below_edge_count"] += sum(key < edge_count for key in keys)
            section_stats["records_with_first_u16_below_node_count"] += sum(key < node_count for key in keys)
            section_stats["records_edge_domain_only"] += sum(node_count <= key < edge_count for key in keys)
            if keys == sorted(keys):
                section_stats["nondecreasing_key_blocks"] += int(bool(keys))
            for rec_no, key in enumerate(keys):
                if len(section_stats["samples"]) < 4 and node_count <= key < edge_count:
                    rec_pos = start + rec_no * width
                    section_stats["samples"].append({"block": block_id, "record": rec_no,
                        "first_u16": key, "node_count": node_count, "edge_count": edge_count,
                        "record_hex": raw[rec_pos:rec_pos + width].hex()})
        sections_pass += 1
        incidents: list[list[int]] = [[] for _ in range(node_count)]
        edge_rows: list[tuple[int, int, int, int, int, int]] = []
        block_primary_endpoints = 0
        block_secondary_endpoints = 0

        for edge_id in range(edge_count):
            pos = offsets[5] + 14 * edge_id
            edge_flags, attr, opaque, endpoint_a, endpoint_b, length_raw = struct.unpack_from("<5HI", raw, pos)
            flags[edge_flags] += 1
            attributes[attr] += 1
            unresolved[opaque] += 1
            for bit in range(16):
                flags_bits[bit] += (edge_flags >> bit) & 1
                attribute_bits[bit] += (attr >> bit) & 1
                unresolved_bits[bit] += (opaque >> bit) & 1
            a_is_secondary = bool(edge_flags & 0x1000)
            b_is_secondary = bool(edge_flags & 0x2000)
            a_bound = secondary_count if a_is_secondary else primary_count
            b_bound = secondary_count if b_is_secondary else primary_count
            if endpoint_a >= a_bound:
                totals["endpoint_out_of_range"] += 1
                if len(endpoint_errors) < 40:
                    endpoint_errors.append({"block": block_id, "edge": edge_id, "end": "A",
                                            "index": endpoint_a, "table_count": a_bound,
                                            "selected_table": "secondary" if a_is_secondary else "primary"})
            if endpoint_b >= b_bound:
                totals["endpoint_out_of_range"] += 1
                if len(endpoint_errors) < 40:
                    endpoint_errors.append({"block": block_id, "edge": edge_id, "end": "B",
                                            "index": endpoint_b, "table_count": b_bound,
                                            "selected_table": "secondary" if b_is_secondary else "primary"})
            if not a_is_secondary and endpoint_a < node_count:
                incidents[endpoint_a].append(edge_id)
                block_primary_endpoints += 1
            else:
                block_secondary_endpoints += 1
            if not b_is_secondary and endpoint_b < node_count:
                incidents[endpoint_b].append(edge_id)
                block_primary_endpoints += 1
            else:
                block_secondary_endpoints += 1
            if a_is_secondary:
                secondary_cross_endpoints += 1
            if b_is_secondary:
                secondary_cross_endpoints += 1
            edge_rows.append((edge_id, edge_flags, attr, opaque, endpoint_a, endpoint_b))

        node_exact = 0
        node_mismatch = 0
        for node_id, actual_edges in enumerate(incidents):
            pos = offsets[4] + 10 * node_id
            record = raw[pos:pos + 10]
            low_nibble = record[0] & 0x0F
            words = struct.unpack_from("<4H", record, 2)
            degree_rows[low_nibble] += 1
            if low_nibble <= 4:
                refs = list(words[:low_nibble])
                if str(low_nibble) not in low_degree_samples:
                    low_degree_samples[str(low_nibble)] = {
                        "block": block_id, "node": node_id, "record_hex": record.hex(),
                        "byte0_high_nibble": record[0] >> 4, "byte1": record[1],
                        "active_candidate_refs": refs, "actual_primary_incident_edge_ids": actual_edges}
                exact = Counter(refs) == Counter(actual_edges)
                node_exact += int(exact)
                exact_by_degree[low_nibble] += int(exact)
                totals["low_degree_nodes"] += 1
                if not exact:
                    node_mismatch += 1
                    totals["node_to_edge_mismatch"] += 1
                    if len(node_mismatches) < 40:
                        node_mismatches.append({"block": block_id, "node": node_id,
                            "record_hex": record.hex(), "low_nibble": low_nibble,
                            "candidate_edge_ids": refs, "actual_primary_endpoint_edge_ids": actual_edges})
                for edge_id in actual_edges:
                    primary_endpoints_by_degree[low_nibble] += 1
                    if edge_id in refs:
                        primary_link_pass_by_degree[low_nibble] += 1
                    else:
                        primary_link_fail_by_degree[low_nibble] += 1
            else:
                high_degree_rows[low_nibble] += 1
                high_primary_endpoints[low_nibble] += len(actual_edges)
                if len(high_degree_samples[str(low_nibble)]) < 3:
                    high_degree_samples[str(low_nibble)].append({
                        "block": block_id, "node": node_id, "record_hex": record.hex(),
                        "byte0_high_nibble": record[0] >> 4, "byte1": record[1],
                        "four_u16_words_at_plus2_plus4_plus6_plus8": list(words),
                        "actual_primary_incident_edge_ids": actual_edges})
                for edge_id in actual_edges:
                    if edge_id in words:
                        high_word_memberships[low_nibble] += 1
                        high_slot_hits[low_nibble] += sum(value == edge_id for value in words)
                    else:
                        totals["high_degree_primary_endpoint_not_found_in_four_u16_words"] += 1

        totals["nodes"] += node_count
        totals["edges"] += edge_count
        totals["primary_endpoints"] += block_primary_endpoints
        totals["secondary_endpoints"] += block_secondary_endpoints
        totals["blocks"] += 1
        block_results.append({"block": block_id, "nodes": node_count, "edges": edge_count,
                              "primary_endpoints": block_primary_endpoints,
                              "secondary_endpoints": block_secondary_endpoints,
                              "low_nibble_exact_nodes": node_exact,
                              "low_nibble_mismatch_nodes": node_mismatch})

    after_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if after_hash != before_hash:
        raise ValueError("original MP0 changed during read-only audit")

    report = {
        "status": "PASS_WITH_UNRESOLVED_ROUTING_AND_HIGH_DEGREE_LINKS" if not totals["endpoint_out_of_range"] else "FAIL",
        "source": str(source), "source_sha256_before": before_hash, "source_sha256_after": after_hash,
        "source_write_count": 0, "blocks_parsed": totals["blocks"], "section_layout_pass_blocks": sections_pass,
        "nodes": totals["nodes"], "edges": totals["edges"],
        "section5_endpoint_indices_out_of_range": totals["endpoint_out_of_range"],
        "out_of_range_examples": endpoint_errors,
        "endpoint_storage": {"primary_coordinate_table_endpoints": totals["primary_endpoints"],
                              "secondary_coordinate_table_endpoints": totals["secondary_endpoints"],
                              "secondary_flagged_ends": secondary_cross_endpoints,
                              "primary_endpoint_semantics": "mapped to Section-4 node IDs by local primary coordinate index",
                              "secondary_endpoint_semantics": "not node-ID links; cross-block/secondary table ownership unresolved"},
        "section4_low_nibble_0_to4": {
            "rows": sum(v for k, v in degree_rows.items() if k <= 4),
            "rows_by_degree": {str(k): degree_rows[k] for k in range(5)},
            "exact_node_to_edge_multisets_by_degree": {str(k): exact_by_degree[k] for k in range(5)},
            "exact_nodes": sum(exact_by_degree[k] for k in range(5)),
            "identity_mismatch_nodes": totals["node_to_edge_mismatch"],
            "real_record_samples_by_degree": low_degree_samples,
            "primary_edge_endpoint_to_node_link_pass_by_degree": {str(k): primary_link_pass_by_degree[k] for k in range(5)},
            "primary_edge_endpoint_to_node_link_fail_by_degree": {str(k): primary_link_fail_by_degree[k] for k in range(5)},
            "mismatch_examples": node_mismatches,
            "interpretation": "first low_nibble u16 words are candidate edge IDs; exact only for the reported node identities; unused words remain opaque",
        },
        "section4_low_nibble_gt4": {
            "rows_by_low_nibble": {str(k): v for k, v in sorted(high_degree_rows.items())},
            "primary_endpoint_counts_by_low_nibble": {str(k): v for k, v in sorted(high_primary_endpoints.items())},
            "primary_endpoint_memberships_found_anywhere_in_four_words_by_low_nibble": {str(k): v for k, v in sorted(high_word_memberships.items())},
            "duplicate_word_hits_by_low_nibble": {str(k): v for k, v in sorted(high_slot_hits.items())},
            "primary_endpoint_memberships_not_found_in_four_words": totals["high_degree_primary_endpoint_not_found_in_four_u16_words"],
            "real_record_samples_by_low_nibble": dict(high_degree_samples),
            "overflow_semantics": "UNRESOLVED; these counts are raw observations, not a complete adjacency decoder",
        },
        "section5": {
            "flags_unique_values": len(flags), "flags_top20": flags.most_common(20),
            "attributes_unique_values": len(attributes), "attributes_top20": attributes.most_common(20),
            "unresolved_u16_unique_values": len(unresolved), "unresolved_top20": unresolved.most_common(20),
            "set_bit_counts": {"flags": dict(flags_bits), "attributes": dict(attribute_bits), "unresolved": dict(unresolved_bits)},
            "confirmed_bits": {"0x1000": "selects secondary coordinate table for endpoint A",
                               "0x2000": "selects secondary coordinate table for endpoint B",
                               "0x8000": "signals a shape span in Section 10"},
            "road_type_direction_access_semantics": "UNKNOWN; no safe values inferred; flags XOR 0x3000 is not accepted as reverse-direction evidence",
        },
        "sections_7_8_9": {key: {**value,
            "key_interpretation": "first u16 is edge-index-shaped in some records; ownership and semantics unproven"}
            for key, value in aux_sections.items()},
        "block_summaries": block_results,
        "method": "Independent topology pass using topology_v3's standalone zlib/Section decoder; imports no geometry decoder or writer.",
    }
    if write_evidence:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / "connectivity_audit.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = audit_topology()
    compact = {k: result[k] for k in ("status", "source_sha256_before", "source_sha256_after",
        "blocks_parsed", "nodes", "edges", "section5_endpoint_indices_out_of_range",
        "endpoint_storage", "section4_low_nibble_0_to4", "section4_low_nibble_gt4", "section5")}
    compact["section4_low_nibble_0_to4"] = {k: v for k, v in compact["section4_low_nibble_0_to4"].items()
        if k not in ("mismatch_examples",)}
    print(json.dumps(compact, ensure_ascii=False, indent=2))
