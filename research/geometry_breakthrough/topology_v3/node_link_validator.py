"""Standalone, read-only Section 4 and Section 7-9 evidence collector.

This intentionally does not import topology_v2, the geometry decoder, or the
Writer. It validates record layouts and node-to-edge candidates against the
actual Section 5 endpoint indexes, while keeping unresolved fields opaque.
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
EXPECTED_SHA256 = "73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e"
ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"
BLOCKS_EXPECTED = 2956


def _read_container(source: Path) -> tuple[bytes, list[bytes]]:
    data = source.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(f"original MP0 SHA-256 mismatch: {digest}")
    count = struct.unpack_from("<I", data, 86)[0]
    if count != BLOCKS_EXPECTED or struct.unpack_from("<H", data, 112)[0] != count:
        raise ValueError("inconsistent MP0 block counts")
    payload_start = 114 + 28 * count
    streams: list[bytes] = []
    extents: list[tuple[int, int, int]] = []
    for block in range(count):
        row = 114 + 24 * block
        offset, raw_size, packed_size = struct.unpack_from("<IHH", data, row + 16)
        if offset < payload_start or offset + packed_size > len(data):
            raise ValueError(f"block {block}: stream pointer out of range")
        dec = zlib.decompressobj()
        raw = dec.decompress(data[offset:offset + packed_size], raw_size + 1)
        raw += dec.flush()
        if (not dec.eof or dec.unused_data or dec.unconsumed_tail
                or len(raw) != raw_size):
            raise ValueError(f"block {block}: invalid compressed stream")
        streams.append(raw)
        extents.append((offset, packed_size, block))
    cursor = payload_start
    for offset, size, block in sorted(extents):
        if offset != cursor:
            raise ValueError(f"block {block}: payload gap/overlap at {cursor}")
        cursor += size
    if cursor != len(data):
        raise ValueError("unindexed/trailing MP0 bytes")
    return data, streams


def _sections(raw: bytes) -> tuple[list[int], list[int]]:
    if len(raw) < 46:
        raise ValueError("short decoded MP0 block")
    offsets, counts = [], []
    for n in range(11):
        offset, count = struct.unpack_from("<HH", raw, n * 4)
        offsets.append(offset)
        counts.append(count)
    tail = struct.unpack_from("<H", raw, 44)[0]
    if offsets[0] != 46 or offsets != sorted(offsets):
        raise ValueError("invalid section offset table")
    if offsets[-1] + tail != len(raw):
        raise ValueError("last section/tail extent mismatch")
    if any(offset > len(raw) for offset in offsets):
        raise ValueError("section offset exceeds block")
    return offsets, counts


def _coords(raw: bytes, start: int, end: int, count: int, signed_x: bool) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    at = start
    while at < end:
        if at + 10 > end:
            raise ValueError("short coordinate run header")
        deltas, x, y = struct.unpack_from("<Hii", raw, at)
        at += 10
        points.append((x, y))
        for _ in range(deltas):
            if at + 4 > end:
                raise ValueError("short coordinate delta")
            dx, dy = struct.unpack_from("<hh" if signed_x else "<Hh", raw, at)
            at += 4
            x += dx
            y += dy
            points.append((x, y))
    if at != end or len(points) != count:
        raise ValueError("coordinate-run count/extent mismatch")
    return points


def validate(source: Path = SOURCE, *, write_evidence: bool = True) -> dict:
    """Check all blocks once; evidence is emitted only after source hash checks."""
    source_hash_before = hashlib.sha256(source.read_bytes()).hexdigest()
    data, streams = _read_container(source)
    if hashlib.sha256(data).hexdigest() != source_hash_before:
        raise ValueError("source changed between integrity read and parse")

    totals = Counter()
    node_nibbles = Counter()
    byte1_values = Counter()
    byte1_by_low_nibble: dict[str, Counter] = defaultdict(Counter)
    byte1_by_high_nibble: dict[str, Counter] = defaultdict(Counter)
    byte1_bits_set = Counter()
    type_degree = Counter()
    degree_rows: dict[str, list[dict]] = defaultdict(list)
    degree_exact = Counter()
    degree_incidence = Counter()
    mismatch_examples: list[dict] = []
    mismatch_all: list[dict] = []
    duplicate_groups = 0
    repeated_coord_nodes = 0
    high_degree_matrix = Counter()
    high_link_matches = Counter()
    high_coord_incidence_matrix = Counter()
    high_degree_samples: dict[str, list[dict]] = defaultdict(list)
    high_degree_slot_identity: dict[str, Counter] = defaultdict(Counter)
    high_tail_link_summary: dict[str, Counter] = defaultdict(Counter)
    high_first_word_location: dict[str, Counter] = defaultdict(Counter)
    active_slot_metrics: dict[str, Counter] = {str(slot): Counter() for slot in range(4)}
    word8_metrics: dict[str, Counter] = {str(degree): Counter() for degree in range(4)}
    word8_by_type: dict[str, Counter] = defaultdict(Counter)
    inactive_word_metrics: dict[str, Counter] = defaultdict(Counter)
    out_of_range_link_examples: list[dict] = []
    block_rows: list[dict] = []
    aux = {str(s): {"rows": 0, "populated_blocks": 0, "layout_errors": 0,
                    "all_key_lt_edge_count_blocks": 0,
                    "all_key_lt_node_count_blocks": 0,
                    "nondecreasing_blocks": 0, "strictly_increasing_blocks": 0,
                    "holdout_populated_blocks": 0, "holdout_all_key_lt_edge_count_blocks": 0,
                    "holdout_nondecreasing_blocks": 0,
                    "records_with_key_only_edge_domain": 0,
                    "records_with_key_only_node_domain": 0,
                    "payload_u16_candidate_comparisons_to_keyed_edge_endpoints": {},
                    "unique_key_total": 0, "edge_ids_missing_total": 0,
                    "sample_records": []}
           for s in (7, 8, 9)}
    for sec in (7, 8, 9):
        aux[str(sec)]["payload_byte_values"] = [Counter() for _ in range({7: 5, 8: 9, 9: 11}[sec])]
    holdout = {"blocks": 0, "nodes_degree_le4": 0, "exact": 0, "mismatch": 0,
               "degree_4_exact": 0, "high_degree_records": 0}
    train = {"blocks": 0, "nodes_degree_le4": 0, "exact": 0, "mismatch": 0}
    high_degree_aux_overlap = {str(s): Counter() for s in (7, 8, 9)}

    for block, raw in enumerate(streams):
        offsets, counts = _sections(raw)
        n_nodes, n_edges = counts[4], counts[5]
        if offsets[5] - offsets[4] != 10 * n_nodes:
            raise ValueError(f"block {block}: Section 4 stride mismatch")
        if offsets[6] - offsets[5] != 14 * n_edges:
            raise ValueError(f"block {block}: Section 5 stride mismatch")
        if n_nodes != counts[0]:
            raise ValueError(f"block {block}: primary coordinate/node count mismatch")
        main = _coords(raw, offsets[0], offsets[1], counts[0], False)
        secondary = _coords(raw, offsets[2], offsets[3], counts[2], True)
        aux_keys_by_section: dict[int, list[int]] = {}
        for aux_sec, aux_width in ((7, 7), (8, 11), (9, 13)):
            if offsets[aux_sec + 1] - offsets[aux_sec] != counts[aux_sec] * aux_width:
                raise ValueError(f"block {block}: Section {aux_sec} stride mismatch")
            aux_keys_by_section[aux_sec] = [
                struct.unpack_from("<H", raw, offsets[aux_sec] + i * aux_width)[0]
                for i in range(counts[aux_sec])]
        actual: list[list[int]] = [[] for _ in range(n_nodes)]
        edges: list[tuple[int, int, int, int]] = []
        coord_endpoint_edges: dict[tuple[int, int], list[tuple[int, int, str]]] = defaultdict(list)
        for edge in range(n_edges):
            pos = offsets[5] + 14 * edge
            flags, _attrs, _opaque, a, b = struct.unpack_from("<5H", raw, pos)
            atable = secondary if flags & 0x1000 else main
            btable = secondary if flags & 0x2000 else main
            if a >= len(atable) or b >= len(btable):
                totals["endpoint_out_of_range"] += 1
                continue
            if not flags & 0x1000:
                actual[a].append(edge)
            if not flags & 0x2000:
                actual[b].append(edge)
            coord_endpoint_edges[atable[a]].append((edge, a, "A"))
            coord_endpoint_edges[btable[b]].append((edge, b, "B"))
            edges.append((edge, flags, a, b))

        coord_nodes: dict[tuple[int, int], list[int]] = defaultdict(list)
        for ni, point in enumerate(main):
            coord_nodes[point].append(ni)
        duplicate_groups += sum(len(group) > 1 for group in coord_nodes.values())
        repeated_coord_nodes += sum(len(group) for group in coord_nodes.values() if len(group) > 1)

        high_degree_incident_edges: set[int] = set()
        for node, incident in enumerate(actual):
            pos = offsets[4] + node * 10
            rec = raw[pos:pos + 10]
            b0, b1 = rec[0], rec[1]
            low, high = b0 & 15, b0 >> 4
            words = struct.unpack_from("<4H", rec, 2)
            node_nibbles[f"low_{low}"] += 1
            node_nibbles[f"high_{high}"] += 1
            byte1_values[b1] += 1
            byte1_by_low_nibble[str(low)][b1] += 1
            byte1_by_high_nibble[str(high)][b1] += 1
            for bit in range(8):
                byte1_bits_set[str(bit)] += (b1 >> bit) & 1
            type_degree[(high, low)] += 1
            totals["nodes"] += 1
            totals[f"degree_{low}"] += 1
            if low <= 4:
                refs = list(words[:low])
                exact = Counter(refs) == Counter(incident)
                for slot in range(low, 4):
                    metrics = inactive_word_metrics[f"degree_{low}_slot_{slot}"]
                    value = words[slot]
                    metrics["records"] += 1
                    metrics["nonzero"] += int(value != 0)
                    metrics["within_edge_index_range"] += int(value < n_edges)
                    metrics["equals_identity_incident_edge"] += int(value in incident)
                    metrics["equals_active_inline_link"] += int(value in refs)
                degree_incidence[str(low)] += len(incident)
                degree_exact[str(low)] += int(exact)
                totals["node_degree_le4"] += 1
                if block % 5 == 0:
                    holdout["nodes_degree_le4"] += 1
                    holdout["exact" if exact else "mismatch"] += 1
                    holdout["degree_4_exact"] += int(low == 4 and exact)
                else:
                    train["nodes_degree_le4"] += 1
                    train["exact" if exact else "mismatch"] += 1
                if not exact:
                    totals["degree_le4_identity_mismatch"] += 1
                    group = coord_nodes[main[node]]
                    item = {"block": block, "node": node, "record_hex": rec.hex(),
                            "byte0_high_nibble": high, "byte0_low_nibble": low,
                            "active_candidate_refs": refs, "section5_primary_incident_edge_ids": incident,
                            "coordinate": main[node], "same_coordinate_node_ids": group,
                            "same_coordinate_count": len(group)}
                    mismatch_all.append(item)
                    if len(mismatch_examples) < 20:
                        mismatch_examples.append(item)
                if low in (0, 1, 2, 3, 4) and len(degree_rows[str(low)]) < 5:
                    degree_rows[str(low)].append({"block": block, "node": node,
                        "record_hex": rec.hex(), "refs_active_by_low_nibble": refs,
                        "actual_primary_endpoint_edges": incident, "exact_identity_match": exact,
                        "coordinate": main[node], "local_edge_count": n_edges})
                if low == 4:
                    totals["degree4_fourth_slot_identity_match"] += int(words[3] in incident)
                    totals["degree4_fourth_slot_records"] += 1
                else:
                    w = words[3]
                    word8_metrics[str(low)]["records"] += 1
                    word8_metrics[str(low)]["nonzero"] += int(w != 0)
                    word8_metrics[str(low)]["within_edge_index_range"] += int(w < n_edges)
                    word8_metrics[str(low)]["is_identity_incident_edge"] += int(w in incident)
                    word8_metrics[str(low)]["within_node_index_range"] += int(w < n_nodes)
                    word8_metrics[str(low)]["equals_this_node_index"] += int(w == node)
                    word8_metrics[str(low)]["equals_any_same_coordinate_node_id"] += int(w in coord_nodes[main[node]])
                    word8_metrics[str(low)]["equals_one_of_active_inline_links"] += int(w in refs)
                    type_key = f"high_{high}_low_{low}"
                    typed = word8_by_type[type_key]
                    typed["records"] += 1
                    typed["nonzero"] += int(w != 0)
                    typed["within_edge_index_range"] += int(w < n_edges)
                    typed["is_identity_incident_edge"] += int(w in incident)
                    typed["equals_one_of_active_inline_links"] += int(w in refs)
                    typed["within_section7_record_count"] += int(w < counts[7])
                    if w < counts[7]:
                        typed["section7_pointed_key_is_incident_edge"] += int(aux_keys_by_section[7][w] in incident)
                    if block % 5 == 0:
                        typed["holdout_records"] += 1
                        typed["holdout_nonzero"] += int(w != 0)
                        typed["holdout_identity_incident_edge"] += int(w in incident)
                    for s in (7, 8, 9):
                        word8_metrics[str(low)][f"within_section{s}_record_count"] += int(w < counts[s])
                        if w < counts[s]:
                            pointed_key = aux_keys_by_section[s][w]
                            word8_metrics[str(low)][f"section{s}_pointed_key_is_incident_edge"] += int(pointed_key in incident)
                            word8_metrics[str(low)][f"section{s}_pointed_key_is_active_inline_link"] += int(pointed_key in refs)
                # Count each active reference against direct index identity, not coordinate equality.
                for slot in range(4):
                    active_slot_metrics[str(slot)]["observed"] += int(slot < low and low <= 4)
                    if slot < low and low <= 4:
                        active_slot_metrics[str(slot)]["matches_incident_multiset"] += int(words[slot] in incident)
                        active_slot_metrics[str(slot)]["within_edge_index_range"] += int(words[slot] < n_edges)
                for slot, value in enumerate(words[:low]):
                    if value >= n_edges and len(out_of_range_link_examples) < 10:
                        out_of_range_link_examples.append({"block": block, "node": node, "slot": slot,
                                                           "value": value, "edge_count": n_edges,
                                                           "record_hex": rec.hex()})
            else:
                totals["high_nibble_gt4_records"] += 1
                high_degree_incident_edges.update(incident)
                high_degree_matrix[(low, len(incident))] += 1
                coordinate_candidates = coord_endpoint_edges[main[node]]
                high_coord_incidence_matrix[(low, len(incident), len(coordinate_candidates))] += 1
                if block % 5 == 0:
                    holdout["high_degree_records"] += 1
                matches = sum(words.count(edge) for edge in set(incident))
                high_link_matches[(low, len(incident), matches)] += 1
                tail_words = words[1:]
                high_tail_link_summary[str(low)]["records"] += 1
                high_tail_link_summary[str(low)]["all_three_tail_words_are_primary_incident_edges"] += int(
                    all(value in incident for value in tail_words))
                high_tail_link_summary[str(low)]["three_tail_words_are_distinct"] += int(
                    len(set(tail_words)) == len(tail_words))
                high_tail_link_summary[str(low)]["tail_word_set_is_subset_of_incident_set"] += int(
                    len(set(tail_words)) == len(tail_words) and set(tail_words).issubset(set(incident)))
                if block % 5 == 0:
                    high_tail_link_summary[str(low)]["holdout_records"] += 1
                    high_tail_link_summary[str(low)]["holdout_tail_word_set_is_subset_of_incident_set"] += int(
                        len(set(tail_words)) == len(tail_words) and set(tail_words).issubset(set(incident)))
                high_tail_link_summary[str(low)]["first_word_is_primary_incident_edge"] += int(words[0] in incident)
                high_first_word_location[str(low)]["word0_within_raw_block"] += int(words[0] < len(raw))
                high_first_word_location[str(low)]["word0_within_section4_byte_extent"] += int(
                    offsets[4] <= words[0] < offsets[5])
                high_first_word_location[str(low)]["word0_within_section5_byte_extent"] += int(
                    offsets[5] <= words[0] < offsets[6])
                high_first_word_location[str(low)]["word0_within_section7_byte_extent"] += int(
                    offsets[7] <= words[0] < offsets[8])
                high_first_word_location[str(low)]["word0_within_section8_byte_extent"] += int(
                    offsets[8] <= words[0] < offsets[9])
                high_first_word_location[str(low)]["word0_within_section9_byte_extent"] += int(
                    offsets[9] <= words[0] < offsets[10])
                for slot, value in enumerate(words):
                    active_slot_metrics[str(slot)]["high_degree_observed"] += 1
                    active_slot_metrics[str(slot)]["high_degree_in_edge_range"] += int(value < n_edges)
                    active_slot_metrics[str(slot)]["high_degree_matches_incident"] += int(value in incident)
                    high_degree_slot_identity[str(low)][f"slot{slot}_matches_incident"] += int(value in incident)
                sample_key = f"low_{low}_incidence_{len(incident)}"
                if len(high_degree_samples[sample_key]) < 5:
                    high_degree_samples[sample_key].append({
                        "block": block, "node": node, "record_hex": rec.hex(),
                        "u16_words": list(words), "section5_primary_incident_edge_ids": incident,
                        "coordinate": main[node], "same_coordinate_node_ids": coord_nodes[main[node]],
                        "local_edge_count": n_edges,
                    })
                if low > 15:
                    raise AssertionError("unreachable nibble range")

        block_rows.append({"block": block, "nodes": n_nodes, "edges": n_edges,
                           "sections_7_8_9_records": [counts[6], counts[7], counts[8]]})
        if block % 5 == 0:
            holdout["blocks"] += 1
        else:
            train["blocks"] += 1

        for sec, width in ((7, 7), (8, 11), (9, 13)):
            payload_len = offsets[sec + 1] - offsets[sec]
            record_count = counts[sec]
            row = aux[str(sec)]
            if payload_len == 0 and record_count == 0:
                continue
            row["populated_blocks"] += 1
            if block % 5 == 0:
                row["holdout_populated_blocks"] += 1
            if payload_len != width * record_count:
                row["layout_errors"] += 1
                continue
            row["rows"] += record_count
            keys: list[int] = []
            for ix in range(record_count):
                rec = raw[offsets[sec] + ix * width: offsets[sec] + (ix + 1) * width]
                key = struct.unpack_from("<H", rec)[0]
                keys.append(key)
                row["records_with_key_only_edge_domain"] += int(key < n_edges and key >= n_nodes)
                row["records_with_key_only_node_domain"] += int(key < n_nodes and key >= n_edges)
                if key < n_edges and key >= n_nodes and len(row.setdefault("key_only_edge_examples", [])) < 12:
                    row["key_only_edge_examples"].append({"block": block, "record_index": ix,
                        "key": key, "node_count": n_nodes, "edge_count": n_edges,
                        "record_hex": rec.hex()})
                aligned = row.setdefault("aligned_u16_payload_candidates", {})
                edge_flags, edge_a, edge_b = edges[key][1], edges[key][2], edges[key][3]
                for field_at in range(2, width - 1, 2):
                    value = struct.unpack_from("<H", rec, field_at)[0]
                    field = aligned.setdefault(str(field_at), {"values_lt_node_count": 0,
                        "values_lt_edge_count": 0, "values_ge_both_counts": 0, "records": 0})
                    field["records"] += 1
                    field["values_lt_node_count"] += int(value < n_nodes)
                    field["values_lt_edge_count"] += int(value < n_edges)
                    field["values_ge_both_counts"] += int(value >= n_nodes and value >= n_edges)
                    comparisons = row["payload_u16_candidate_comparisons_to_keyed_edge_endpoints"]
                    comparison = comparisons.setdefault(str(field_at), {"records": 0,
                        "equals_endpoint_a_numeric_index": 0, "equals_endpoint_b_numeric_index": 0,
                        "equals_either_endpoint_numeric_index": 0,
                        "equals_primary_endpoint_numeric_index": 0,
                        "equals_secondary_endpoint_numeric_index": 0})
                    comparison["records"] += 1
                    match_a, match_b = value == edge_a, value == edge_b
                    comparison["equals_endpoint_a_numeric_index"] += int(match_a)
                    comparison["equals_endpoint_b_numeric_index"] += int(match_b)
                    comparison["equals_either_endpoint_numeric_index"] += int(match_a or match_b)
                    if not edge_flags & 0x1000:
                        comparison["equals_primary_endpoint_numeric_index"] += int(value == edge_a)
                    if not edge_flags & 0x2000:
                        comparison["equals_primary_endpoint_numeric_index"] += int(value == edge_b)
                    if edge_flags & 0x1000:
                        comparison["equals_secondary_endpoint_numeric_index"] += int(value == edge_a)
                    if edge_flags & 0x2000:
                        comparison["equals_secondary_endpoint_numeric_index"] += int(value == edge_b)
                for byte_ix, value in enumerate(rec[2:]):
                    row["payload_byte_values"][byte_ix][value] += 1
                if len(row["sample_records"]) < 8:
                    row["sample_records"].append({"block": block, "record_index": ix,
                                                  "first_u16_le": key, "record_hex": rec.hex()})
            if all(key < n_edges for key in keys):
                row["all_key_lt_edge_count_blocks"] += 1
                if block % 5 == 0:
                    row["holdout_all_key_lt_edge_count_blocks"] += 1
            if all(key < n_nodes for key in keys):
                row["all_key_lt_node_count_blocks"] += 1
            if keys == sorted(keys):
                row["nondecreasing_blocks"] += 1
                if block % 5 == 0:
                    row["holdout_nondecreasing_blocks"] += 1
                if len(keys) == len(set(keys)):
                    row["strictly_increasing_blocks"] += 1
            unique = set(keys)
            row["unique_key_total"] += len(unique)
            row["edge_ids_missing_total"] += n_edges - len(unique & set(range(n_edges)))
            high_degree_aux_overlap[str(sec)]["high_degree_primary_incident_edges"] += len(high_degree_incident_edges)
            high_degree_aux_overlap[str(sec)]["such_edges_with_aux_key"] += len(unique & high_degree_incident_edges)
            high_degree_aux_overlap[str(sec)]["all_local_edge_ids_with_aux_key"] += len(unique & set(range(n_edges)))
            high_degree_aux_overlap[str(sec)]["records_keyed_by_high_degree_primary_incident_edge"] += sum(
                1 for key in keys if key in high_degree_incident_edges)

    # Recount keys outside each candidate domain after per-block statistics;
    # report Section 7-9 fields as candidates, not proven semantics.
    digest_after = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest_after != source_hash_before:
        raise ValueError("source hash changed during read-only validation")
    for sec in (7, 8, 9):
        row = aux[str(sec)]
        row["payload_byte_values"] = [
            {"distinct": len(c), "top_16_values": c.most_common(16)} for c in row["payload_byte_values"]]
        row["semantic_status"] = "EDGE_INDEX_CANDIDATE_ONLY; association/routing meaning unresolved"
    mismatch_count = totals["degree_le4_identity_mismatch"]
    summary = {
        "status": "PASS_WITH_UNRESOLVED_NODE_TYPES_AND_AUXILIARY_FIELDS",
        "source": str(source), "source_sha256_before": source_hash_before,
        "source_sha256_after": digest_after, "original_bytes_written": False,
        "block_count": len(streams), "block_count_pass": sum(len(r) >= 46 for r in streams),
        "nodes": totals["nodes"], "edges": sum(row["edges"] for row in block_rows),
        "section5_endpoint_out_of_range": totals["endpoint_out_of_range"],
        "degree_counts": {str(d): totals[f"degree_{d}"] for d in range(16)},
        "byte0_high_nibble_counts": dict(sorted((int(k[5:]), v) for k, v in node_nibbles.items() if k.startswith("high_"))),
        "byte1_top_32_values": byte1_values.most_common(32),
        "byte1_full_value_histogram": {str(k): v for k, v in sorted(byte1_values.items())},
        "byte1_set_bit_counts": dict(byte1_bits_set),
        "byte1_by_low_nibble_top_values": {
            degree: values.most_common(12) for degree, values in sorted(byte1_by_low_nibble.items(), key=lambda p: int(p[0]))},
        "byte1_by_high_nibble_top_values": {
            kind: values.most_common(12) for kind, values in sorted(byte1_by_high_nibble.items(), key=lambda p: int(p[0]))},
        "high_nibble_by_low_nibble": {f"high={h},low={l}": n for (h, l), n in sorted(type_degree.items())},
        "low_degree_identity_adjacency": {
            "degree_0_to_4_nodes": sum(degree_exact.values()) + mismatch_count,
            "exact_nodes_by_degree": dict(degree_exact),
            "primary_incident_edge_memberships_by_degree": dict(degree_incidence),
            "mismatches": mismatch_count,
            "mismatch_duplicate_coordinate_groups": sum(1 for r in mismatch_all if r["same_coordinate_count"] > 1),
            "mismatch_examples": mismatch_examples,
            "all_mismatch_records": mismatch_all,
            "samples_degree_0_to_4": dict(degree_rows),
            "active_inline_link_out_of_range_examples": out_of_range_link_examples,
        },
        "degree4_fourth_slot": {"records": totals["degree4_fourth_slot_records"],
                                 "matches_actual_primary_endpoint_edge": totals["degree4_fourth_slot_identity_match"]},
        "word_at_plus8_when_low_nibble_below4": {k: dict(v) for k, v in word8_metrics.items()},
        "word_at_plus8_by_high_and_low_nibble": {k: dict(v) for k, v in sorted(word8_by_type.items())},
        "active_u16_slot_observations": {k: dict(v) for k, v in active_slot_metrics.items()},
        "inactive_u16_words_preserved_by_degree_and_slot": {
            k: dict(v) for k, v in sorted(inactive_word_metrics.items())},
        "node_coordinate_identity": {"duplicate_coordinate_groups": duplicate_groups,
                                      "records_in_duplicate_coordinate_groups": repeated_coord_nodes,
                                      "identity_policy": "Section-4 node indices retained; coordinates never used to merge nodes"},
        "high_nibble_gt4_records": {
            "count": totals["high_nibble_gt4_records"],
            "actual_primary_incidence_by_stored_low_nibble_and_incidence": {
                f"low={low},actual_primary_incidence={actual}": n
                for (low, actual), n in sorted(high_degree_matrix.items())},
            "coordinate_only_candidate_incidence_by_low_nibble_primary_incidence_and_count": {
                f"low={low},primary_incidence={primary},coordinate_candidates={coord_count}": n
                for (low, primary, coord_count), n in sorted(high_coord_incidence_matrix.items())},
            "u16_slot_match_observations": {
                f"low={low},actual_primary_incidence={actual},matching_words={matches}": n
                for (low, actual, matches), n in sorted(high_link_matches.items())},
            "matching_by_physical_word_slot": {low: dict(values)
                                                for low, values in sorted(high_degree_slot_identity.items())},
            "tail_three_word_link_checks_by_low_nibble": {low: dict(values)
                                                           for low, values in sorted(high_tail_link_summary.items())},
            "first_word_offset_candidate_checks_by_low_nibble": {low: dict(values)
                                                                  for low, values in sorted(high_first_word_location.items())},
            "real_record_samples": dict(high_degree_samples),
            "conclusion": "Low nibble >4 is not established as local primary degree; overflow/continuation/type semantics remain unresolved.",
        },
        "sections_7_8_9": aux,
        "section7_9_key_overlap_with_edges_touching_high_nibble_gt4_nodes": {
            sec: dict(metrics) for sec, metrics in high_degree_aux_overlap.items()},
        "holdout_blocks_mod5_eq0": holdout,
        "hypothesis_blocks_mod5_ne0": train,
        "independent_holdout_rule": "low-nibble active u16 words equal exact Section-5 primary endpoint IDs as a multiset; holdout block_id % 5 == 0",
        "block_layout_pass": len(streams), "block_layout_fail": 0,
        "method": "Independent standard-library container/Section parser; no project Reader, Writer, or topology_v2 imports.",
    }
    if write_evidence:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / "node_link_validation.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        (EVIDENCE / "block_layout_summary.json").write_text(
            json.dumps(block_rows, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    report = validate()
    compact = {key: report[key] for key in (
        "status", "source_sha256_before", "source_sha256_after", "block_count_pass",
        "nodes", "edges", "section5_endpoint_out_of_range", "low_degree_identity_adjacency",
        "degree4_fourth_slot", "high_nibble_gt4_records", "sections_7_8_9",
        "holdout_blocks_mod5_eq0", "hypothesis_blocks_mod5_ne0")}
    compact["low_degree_identity_adjacency"] = {
        k: v for k, v in report["low_degree_identity_adjacency"].items()
        if k not in ("all_mismatch_records", "samples_degree_0_to_4")}
    compact["sections_7_8_9"] = {
        sec: {k: v for k, v in value.items() if k not in ("payload_byte_values", "sample_records")}
        for sec, value in report["sections_7_8_9"].items()}
    print(json.dumps(compact, ensure_ascii=False, indent=2))
