"""Independent structural/topology validator for original Siemens MP0 blocks.

Reads EUZ.MP0 without writing to it. It validates the recovered portions of
sections 4 and 5 and reports unresolved topology instead of guessing.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import os
import struct
import sys
import zlib

HERE = Path(__file__).resolve().parent
GEOMETRY = HERE.parent
if str(GEOMETRY) not in sys.path:
    sys.path.insert(0, str(GEOMETRY))

from decoder import decode_mp0_polylines, decode_runs  # noqa: E402
from encoder import encode_shapes  # noqa: E402
from independent_verify import independent_blocks  # noqa: E402

SOURCE = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3])) / 'SW' / 'DB' / 'EUZ.MP0'
SOURCE_SHA256 = "73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e"
HEADER_SIZE = 114
ENTRY_SIZE = 24
BLOCK_COUNT = 2956


def _u16(buf: bytes, at: int) -> int:
    return struct.unpack_from("<H", buf, at)[0]


def _read_container(path: Path) -> tuple[bytes, list[bytes]]:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError(f"source hash mismatch: {digest}")
    count = struct.unpack_from("<I", data, 86)[0]
    repeated = _u16(data, 112)
    if count != BLOCK_COUNT or repeated != count:
        raise ValueError(f"MP0 block counts disagree: {count}/{repeated}")
    payload_start = HEADER_SIZE + 28 * count
    streams: list[bytes] = []
    extents: list[tuple[int, int, int]] = []
    for block in range(count):
        row = HEADER_SIZE + ENTRY_SIZE * block
        offset, raw_size, packed_size = struct.unpack_from("<IHH", data, row + 16)
        if offset < payload_start or offset + packed_size > len(data):
            raise ValueError(f"block {block}: stream outside MP0")
        dec = zlib.decompressobj()
        raw = dec.decompress(data[offset:offset + packed_size], raw_size + 1)
        if len(raw) > raw_size or dec.unconsumed_tail:
            raise ValueError(f"block {block}: decompressed stream exceeds indexed size")
        raw += dec.flush()
        if not dec.eof or dec.unused_data or dec.unconsumed_tail or len(raw) != raw_size:
            raise ValueError(f"block {block}: invalid zlib extent/size")
        streams.append(raw)
        extents.append((offset, packed_size, block))
    cursor = payload_start
    for offset, packed_size, block in sorted(extents):
        if offset != cursor:
            raise ValueError(f"block {block}: physical payload gap/overlap at {cursor}")
        cursor += packed_size
    if cursor != len(data):
        raise ValueError("unindexed/trailing MP0 bytes")
    return data, streams


def _section_pairs(raw: bytes) -> tuple[list[int], list[int]]:
    if len(raw) < 46:
        raise ValueError("block shorter than MP0 block header")
    offsets, counts = [], []
    for section in range(11):
        offset, count = struct.unpack_from("<HH", raw, 4 * section)
        offsets.append(offset)
        counts.append(count)
    if offsets[0] != 46 or offsets != sorted(offsets):
        raise ValueError("section offsets are not monotonically ordered from byte 46")
    if any(offset > len(raw) for offset in offsets) or offsets[-1] + _u16(raw, 44) != len(raw):
        raise ValueError("section offsets/tail length exceed decoded block")
    return offsets, counts


def _canonical(points: list[tuple[int, int]]) -> tuple[tuple[tuple[int, int], ...], int]:
    forward = tuple(points)
    reverse = tuple(reversed(points))
    return (forward, 1) if forward <= reverse else (reverse, -1)


def validate(source: Path = SOURCE) -> dict:
    data, streams = _read_container(source)
    counts = Counter()
    per_block: list[dict] = []
    degree_matrix = Counter()
    node_exact_examples: list[dict] = []
    edge_bound_examples: list[dict] = []
    high_degree_examples: list[dict] = []
    confirmed_adjacency_examples: dict[str, list[dict]] = defaultdict(list)
    low_degree_mismatch_dup = Counter()
    low_degree_mismatch_ref_geometry = Counter()
    duplicate_node_groups = Counter()
    auxiliary_section_layout = {str(s): Counter() for s in (7, 8, 9)}
    auxiliary_count_relations = Counter()
    trailing_u16_evidence = Counter()
    all_main: dict[tuple[int, int], set[int]] = defaultdict(set)
    secondary_rows: list[tuple[int, tuple[int, int]]] = []
    cross_copy_candidates: dict[tuple, list[dict]] = defaultdict(list)
    attr_values, unresolved_values, flag_values = Counter(), Counter(), Counter()
    edge_flag_bits, attr_bits, unresolved_bits = Counter(), Counter(), Counter()
    source_hash_before = hashlib.sha256(data).hexdigest()

    for block, raw in enumerate(streams):
        try:
            offsets, section_counts = _section_pairs(raw)
            n_nodes, n_edges = section_counts[4], section_counts[5]
            for s in (7, 8, 9):
                byte_size = offsets[s + 1] - offsets[s]
                n_records = section_counts[s]
                if n_records:
                    stride = byte_size // n_records if byte_size % n_records == 0 else "nonintegral"
                    auxiliary_section_layout[str(s)][str(stride)] += 1
                else:
                    auxiliary_section_layout[str(s)]["empty_blocks"] += 1
                auxiliary_count_relations[f"section{s}_count_equals_edges"] += (n_records == n_edges)
                auxiliary_count_relations[f"section{s}_count_equals_nodes"] += (n_records == n_nodes)
            if offsets[5] - offsets[4] != 10 * n_nodes:
                raise ValueError("section 4 is not a 10-byte node table")
            if offsets[6] - offsets[5] != 14 * n_edges:
                raise ValueError("section 5 is not a 14-byte edge table")
            if n_nodes != section_counts[0]:
                raise ValueError("section 4 and primary coordinate counts differ")
            main, _ = decode_runs(raw, offsets[0], offsets[1], section_counts[0])
            secondary, _ = decode_runs(raw, offsets[2], offsets[3], section_counts[2], signed_x=True)
            coord_frequency = Counter(main)
            for xy in main:
                all_main[xy].add(block)
            secondary_rows.extend((block, xy) for xy in secondary)

            nodes = []
            incidents = [[] for _ in range(n_nodes)]
            for node_id in range(n_nodes):
                pos = offsets[4] + 10 * node_id
                rec = raw[pos:pos + 10]
                degree = rec[0] & 0x0F
                refs = struct.unpack_from("<4H", rec, 2)
                nodes.append((degree, refs, rec, pos))
                counts["node_records"] += 1
                degree_matrix[(degree, rec[0] >> 4)] += 1
            edges = []
            edge_geometries = []
            for edge_id in range(n_edges):
                pos = offsets[5] + 14 * edge_id
                flags, attributes, unresolved, a, b, length = struct.unpack_from("<5HI", raw, pos)
                edges.append((flags, attributes, unresolved, a, b, length, pos))
                flag_values[flags] += 1
                attr_values[attributes] += 1
                unresolved_values[unresolved] += 1
                for bit in range(16):
                    if flags & (1 << bit):
                        edge_flag_bits[bit] += 1
                    if attributes & (1 << bit):
                        attr_bits[bit] += 1
                    if unresolved & (1 << bit):
                        unresolved_bits[bit] += 1
                atable = secondary if flags & 0x1000 else main
                btable = secondary if flags & 0x2000 else main
                if a >= len(atable) or b >= len(btable):
                    counts["edge_endpoint_out_of_range"] += 1
                    if len(edge_bound_examples) < 30:
                        edge_bound_examples.append({"block": block, "edge": edge_id,
                                                    "flags": flags, "a": a, "b": b,
                                                    "a_table_count": len(atable), "b_table_count": len(btable)})
                    continue
                edge_geometries.append((atable[a], btable[b]))
                if not flags & 0x1000:
                    incidents[a].append(edge_id)
                else:
                    counts["secondary_a_endpoints"] += 1
                if not flags & 0x2000:
                    incidents[b].append(edge_id)
                else:
                    counts["secondary_b_endpoints"] += 1

            # Use the existing current signed-secondary decoder and shape
            # encoder strictly as a no-op round-trip check on all decoded
            # blocks; the section-4/5 records themselves must remain exact.
            decoded_lines = decode_mp0_polylines(raw)
            reencoded = encode_shapes(raw, decoded_lines)
            if reencoded != raw:
                counts["decode_encode_byte_identity_fail"] += 1
            else:
                counts["decode_encode_byte_identity_pass"] += 1
            if reencoded[offsets[4]:offsets[6]] != raw[offsets[4]:offsets[6]]:
                counts["section4_5_roundtrip_fail"] += 1
            else:
                counts["section4_5_roundtrip_pass"] += 1

            block_exact = block_fail = 0
            block_high = 0
            for node_id, (degree, refs, rec, pos) in enumerate(nodes):
                local = incidents[node_id]
                counts[f"local_primary_degree_{len(local)}"] += 1
                if degree <= 3:
                    for slot in range(degree, 4):
                        value = refs[slot]
                        key = f"degree{degree}_slot{slot}"
                        trailing_u16_evidence[key + "_records"] += 1
                        trailing_u16_evidence[key + "_nonzero"] += (value != 0)
                        trailing_u16_evidence[key + "_within_local_edge_id_range"] += (value < n_edges)
                        trailing_u16_evidence[key + "_is_local_incidence"] += (value in local)
                if degree <= 4:
                    local_refs = [ref for ref in refs[:degree] if ref < n_edges]
                    if Counter(local_refs) == Counter(local):
                        block_exact += 1
                        counts["degree_le4_node_adjacency_exact_pass"] += 1
                        if degree > 0 and len(confirmed_adjacency_examples[str(degree)]) < 3:
                            confirmed_adjacency_examples[str(degree)].append({
                                "block": block, "node": node_id, "record_offset": pos,
                                "record_hex": rec.hex(), "degree_low_nibble": degree,
                                "active_refs": refs[:degree], "local_primary_edges": local,
                                "coordinate": main[node_id],
                            })
                    else:
                        block_fail += 1
                        counts["degree_le4_node_adjacency_exact_fail"] += 1
                        duplicate_n = coord_frequency[main[node_id]]
                        low_degree_mismatch_dup["duplicate_coordinate" if duplicate_n > 1 else "unique_coordinate"] += 1
                        unattached = 0
                        for ref in local_refs:
                            if ref < len(edge_geometries) and main[node_id] in edge_geometries[ref]:
                                unattached += 1
                        low_degree_mismatch_ref_geometry["all_candidate_refs_touch_coordinate"] += (unattached == len(local_refs))
                        low_degree_mismatch_ref_geometry["any_candidate_ref_touches_coordinate"] += (unattached > 0)
                        if len(node_exact_examples) < 40:
                            node_exact_examples.append({"block": block, "node": node_id,
                                                       "record_offset": pos, "record_hex": rec.hex(),
                                                       "stored_degree_low_nibble": degree,
                                                       "local_primary_edges": local,
                                                       "candidate_local_refs": local_refs,
                                                       "coordinate": main[node_id],
                                                       "coordinate_duplicate_count": coord_frequency[main[node_id]],
                                                       "candidate_refs_touching_coordinate": unattached})
                else:
                    block_high += 1
                    counts["degree_gt4_overflow_unresolved_nodes"] += 1
                    counts[f"stored_degree_gt4_local_primary_incidence_{len(local)}"] += 1
                    if len(high_degree_examples) < 40:
                        high_degree_examples.append({"block": block, "node": node_id,
                                                     "record_offset": pos, "record_hex": rec.hex(),
                                                     "stored_degree_low_nibble": degree,
                                                     "local_primary_degree": len(local),
                                                     "local_primary_edges": local,
                                                     "four_u16_slots": list(refs),
                                                     "coordinate": main[node_id]})

            for edge_id, (flags, attributes, unresolved, a, b, length, pos) in enumerate(edges):
                if a < len(secondary if flags & 0x1000 else main) and not flags & 0x1000:
                    degree, refs, rec, node_pos = nodes[a]
                    if degree <= 4:
                        if edge_id in refs[:degree]:
                            counts["primary_endpoint_node_to_edge_reference_pass"] += 1
                        else:
                            counts["primary_endpoint_node_to_edge_reference_fail"] += 1
                if b < len(secondary if flags & 0x2000 else main) and not flags & 0x2000:
                    degree, refs, rec, node_pos = nodes[b]
                    if degree <= 4:
                        if edge_id in refs[:degree]:
                            counts["primary_endpoint_node_to_edge_reference_pass"] += 1
                        else:
                            counts["primary_endpoint_node_to_edge_reference_fail"] += 1

                # Candidate complete duplicate geometry groups are restricted
                # to records that use a secondary endpoint table.
                line = decoded_lines[edge_id]
                if flags & 0x3000:
                    canon, orientation = _canonical(line["coordinates_integer"])
                    key = (canon, length)
                    cross_copy_candidates[key].append({"block": block, "edge": edge_id,
                                                       "orientation": orientation,
                                                       "attributes": attributes,
                                                       "unresolved": unresolved,
                                                       "flags_without_table_selectors": flags & ~0x3000})
            per_block.append({"block": block, "raw_size": len(raw), "node_count": n_nodes,
                              "edge_count": n_edges, "degree_le4_exact_pass": block_exact,
                              "degree_le4_exact_fail": block_fail,
                              "degree_gt4_unresolved": block_high,
                              "decode_encode_byte_identity": reencoded == raw})
            for xy, n_same in coord_frequency.items():
                if n_same > 1:
                    duplicate_node_groups[f"multiplicity_{n_same}"] += 1
        except Exception as exc:
            counts["block_structural_fail"] += 1
            if len(edge_bound_examples) < 30:
                edge_bound_examples.append({"block": block, "kind": "structural",
                                            "error": f"{type(exc).__name__}: {exc}"})
            per_block.append({"block": block, "structural_error": f"{type(exc).__name__}: {exc}"})

    # Verify geometry reconstructed from raw indexes against the independent
    # raw-file parser, which does not import decoder.py or encoder.py.
    independent_edge_pass = independent_edge_fail = 0
    independent_examples = []
    try:
        for block, main, other, lines in independent_blocks(source):
            ours = decode_mp0_polylines(streams[block])
            if len(lines) != len(ours):
                independent_edge_fail += max(len(lines), len(ours))
                continue
            for edge_id, (indep, own) in enumerate(zip(lines, ours)):
                if (indep["flags"] == own["flags"] and
                        indep["length_raw"] == own["length_field"] and
                        indep["points"] == own["coordinates_integer"]):
                    independent_edge_pass += 1
                else:
                    independent_edge_fail += 1
                    if len(independent_examples) < 30:
                        independent_examples.append({"block": block, "edge": edge_id,
                                                     "independent_flags": indep["flags"],
                                                     "current_flags": own["flags"],
                                                     "independent_length": indep["length_raw"],
                                                     "current_length": own["length_field"],
                                                     "independent_points": indep["points"],
                                                     "current_points": own["coordinates_integer"]})
    except Exception as exc:
        counts["independent_reader_error"] += 1
        independent_examples.append({"error": f"{type(exc).__name__}: {exc}"})

    cross_matched = 0
    cross_unmatched = []
    for block, xy in secondary_rows:
        if any(other_block != block for other_block in all_main.get(xy, ())):
            cross_matched += 1
        elif len(cross_unmatched) < 30:
            cross_unmatched.append({"block": block, "coordinate": xy})

    duplicate_groups = []
    for key, rows in cross_copy_candidates.items():
        if len({row["block"] for row in rows}) >= 2:
            duplicate_groups.append(rows)
    duplicate_attr_equal = sum(len({r["attributes"] for r in group}) == 1 for group in duplicate_groups)
    duplicate_unresolved_equal = sum(len({r["unresolved"] for r in group}) == 1 for group in duplicate_groups)
    duplicate_flags_equal = sum(len({r["flags_without_table_selectors"] for r in group}) == 1 for group in duplicate_groups)
    duplicate_orientation_reversed = sum(len({r["orientation"] for r in group}) > 1 for group in duplicate_groups)
    source_hash_after = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    result = {
        "status": "PASS_WITH_TOPOLOGY_UNRESOLVED" if not counts["block_structural_fail"] and not counts["edge_endpoint_out_of_range"] and not independent_edge_fail and not counts["decode_encode_byte_identity_fail"] else "FAIL",
        "source": str(source), "source_sha256_before": source_hash_before,
        "source_sha256_after": source_hash_after,
        "block_count": len(streams), "blocks_with_structural_errors": counts["block_structural_fail"],
        "block_count_pass": len(streams) - counts["block_structural_fail"],
        "exact_decompression_pass": len(streams),
        "section4_10_byte_and_section5_14_byte_stride_pass_blocks": len(streams) - counts["block_structural_fail"],
        "primary_node_count": counts["node_records"],
        "edge_endpoint_out_of_range": counts["edge_endpoint_out_of_range"],
        "primary_endpoint_node_to_edge_reference": {
            "pass": counts["primary_endpoint_node_to_edge_reference_pass"],
            "fail": counts["primary_endpoint_node_to_edge_reference_fail"],
            "scope": "Only endpoints whose stored low-nibble degree is <=4; higher-degree continuation is unresolved.",
        },
        "degree_le4_exact_local_adjacency_nodes": {
            "pass": counts["degree_le4_node_adjacency_exact_pass"],
            "fail": counts["degree_le4_node_adjacency_exact_fail"],
            "fail_coordinate_duplication": dict(low_degree_mismatch_dup),
            "candidate_refs_geometry_relation": dict(low_degree_mismatch_ref_geometry),
            "examples": node_exact_examples,
        },
        "confirmed_low_degree_adjacency_examples": dict(confirmed_adjacency_examples),
        "duplicate_primary_coordinate_groups": dict(duplicate_node_groups),
        "degree_gt4_overflow_unresolved_nodes": counts["degree_gt4_overflow_unresolved_nodes"],
        "stored_degree_gt4_local_primary_incidence_distribution": {
            k.removeprefix("stored_degree_gt4_local_primary_incidence_"): v
            for k, v in counts.items() if k.startswith("stored_degree_gt4_local_primary_incidence_")
        },
        "high_degree_examples": high_degree_examples,
        "section4_trailing_u16_words_when_degree_below_four": dict(trailing_u16_evidence),
        "secondary_coordinate_cross_block_matches": {
            "pass": cross_matched, "fail": len(secondary_rows) - cross_matched,
            "examples": cross_unmatched,
        },
        "decode_encode_graph_roundtrip": {
            "blocks_byte_identical_pass": counts["decode_encode_byte_identity_pass"],
            "blocks_byte_identical_fail": counts["decode_encode_byte_identity_fail"],
            "section4_5_byte_identical_pass": counts["section4_5_roundtrip_pass"],
            "section4_5_byte_identical_fail": counts["section4_5_roundtrip_fail"],
        },
        "independent_reader": {
            "implementation": "research/geometry_breakthrough/independent_verify.py",
            "writer_imported": False, "current_decoder_imported": False,
            "edges_point_for_point_pass": independent_edge_pass,
            "edges_fail": independent_edge_fail,
            "examples": independent_examples,
        },
        "section5_field_statistics": {
            "edge_count": sum(flag_values.values()),
            "flags_top20": flag_values.most_common(20),
            "attributes_top20": attr_values.most_common(20),
            "unresolved_top20": unresolved_values.most_common(20),
            "flags_bit_occurrences": {str(k): v for k, v in sorted(edge_flag_bits.items())},
            "attributes_bit_occurrences": {str(k): v for k, v in sorted(attr_bits.items())},
            "unresolved_bit_occurrences": {str(k): v for k, v in sorted(unresolved_bits.items())},
        },
        "cross_block_exact_geometry_duplicate_groups": {
            "groups": len(duplicate_groups),
            "attributes_identical_groups": duplicate_attr_equal,
            "unresolved_identical_groups": duplicate_unresolved_equal,
            "flags_other_than_coordinate_table_selectors_identical_groups": duplicate_flags_equal,
            "groups_with_reversed_storage_orientation": duplicate_orientation_reversed,
        },
        "auxiliary_sections_7_to_9_layout": {
            "record_size_by_populated_block": {s: dict(c) for s, c in auxiliary_section_layout.items()},
            "count_correlations": dict(auxiliary_count_relations),
            "semantics": "record widths and count correlations only; no edge association inferred",
        },
        "degree_and_high_nibble_distribution": {f"degree_{d}_high_{h}": n for (d, h), n in sorted(degree_matrix.items())},
        "block_details": per_block,
        "interpretation": {
            "confirmed": [
                "Section 4 is a fixed 10-byte-per-record table and section 5 is a fixed 14-byte-per-record table in every MP0 block.",
                "Section 5 endpoint indexes are bounds-valid in the selected coordinate table for every decoded edge.",
                "For the large degree<=4 cohort, low nibble and the first degree u16 slots provide an exact local adjacency representation, with the reported exceptions retained explicitly.",
                "Bits 0x1000 and 0x2000 select the coordinate table for edge endpoints; they do not establish routing direction.",
            ],
            "unresolved": [
                "The role of section 4 byte +1 and high nibble of byte +0.",
                "The continuation/overflow representation for degree>4 and the 511 exact-local-adjacency exceptions.",
                "Semantics of section 5 attributes, unresolved, and non-coordinate flag bits, including routing direction/access.",
                "Whether additional sections 6-9 carry edge-to-routing/name/turn associations required for a new edge.",
            ],
        },
    }
    (HERE / "topology_validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    summary = {
        "status": result["status"],
        "source_sha256_unchanged": source_hash_before == source_hash_after,
        "blocks_structurally_valid": result["block_count_pass"],
        "streams_inflated": result["exact_decompression_pass"],
        "edge_endpoint_out_of_range": result["edge_endpoint_out_of_range"],
        "degree_le4_adjacency_nodes": result["degree_le4_exact_local_adjacency_nodes"]["pass"],
        "degree_le4_adjacency_failures": result["degree_le4_exact_local_adjacency_nodes"]["fail"],
        "stored_degree_gt4_unresolved": result["degree_gt4_overflow_unresolved_nodes"],
        "roundtrip_blocks": result["decode_encode_graph_roundtrip"]["blocks_byte_identical_pass"],
        "independent_edges": result["independent_reader"]["edges_point_for_point_pass"],
        "secondary_cross_block_matches": result["secondary_coordinate_cross_block_matches"]["pass"],
    }
    print(json.dumps(summary, indent=2))
    return result


if __name__ == "__main__":
    validate()
