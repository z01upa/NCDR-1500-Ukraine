"""Second, standalone MP0 Section 4/5 check; imports no project decoder/writer."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import os
import struct
import zlib

SOURCE = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3])) / 'SW' / 'DB' / 'EUZ.MP0'
EXPECTED_SHA256 = "73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e"
HERE = Path(__file__).resolve().parent


def _read_coordinates(raw: bytes, start: int, end: int, count: int, *, signed_x: bool) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    at = start
    while at < end:
        if at + 10 > end:
            raise ValueError("truncated coordinate run header")
        deltas, x, y = struct.unpack_from("<Hii", raw, at)
        at += 10
        out.append((x, y))
        for _ in range(deltas):
            if at + 4 > end:
                raise ValueError("truncated coordinate delta")
            fmt = "<hh" if signed_x else "<Hh"
            dx, dy = struct.unpack_from(fmt, raw, at)
            at += 4
            x += dx
            y += dy
            out.append((x, y))
    if at != end or len(out) != count:
        raise ValueError("coordinate run extent/count mismatch")
    return out


def validate_independently(source: Path = SOURCE) -> dict:
    data = source.read_bytes()
    digest_before = hashlib.sha256(data).hexdigest()
    if digest_before != EXPECTED_SHA256:
        raise ValueError(f"original MP0 SHA-256 mismatch: {digest_before}")
    block_count = struct.unpack_from("<I", data, 86)[0]
    if block_count != 2956 or struct.unpack_from("<H", data, 112)[0] != block_count:
        raise ValueError("inconsistent top-level MP0 block counts")
    payload_start = 114 + 28 * block_count
    block_streams = []
    payload = []
    for block in range(block_count):
        row = 114 + 24 * block
        offset, raw_size, packed_size = struct.unpack_from("<IHH", data, row + 16)
        if offset < payload_start or offset + packed_size > len(data):
            raise ValueError(f"block {block}: invalid absolute stream extent")
        inflater = zlib.decompressobj()
        raw = inflater.decompress(data[offset:offset + packed_size], raw_size + 1)
        raw += inflater.flush()
        if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail or len(raw) != raw_size:
            raise ValueError(f"block {block}: invalid compressed stream")
        block_streams.append(raw)
        payload.append((offset, packed_size, block))
    cursor = payload_start
    for offset, packed_size, block in sorted(payload):
        if offset != cursor:
            raise ValueError(f"block {block}: physical stream order has a gap/overlap")
        cursor += packed_size
    if cursor != len(data):
        raise ValueError("physical payload does not end at EOF")

    node_total = edge_total = endpoint_oob = 0
    exact_nodes = mismatched_nodes = high_stored_degree = 0
    mismatch_duplicate_coordinates = 0
    endpoint_ref_pass = endpoint_ref_fail = 0
    secondary_points: list[tuple[int, tuple[int, int]]] = []
    primary_by_coord: dict[tuple[int, int], set[int]] = {}
    mismatch_examples = []
    block_counts = []

    for block, raw in enumerate(block_streams):
        pairs = list(struct.iter_unpack("<HH", raw[:44]))
        if len(pairs) != 11 or pairs[0][0] != 46:
            raise ValueError(f"block {block}: invalid section header")
        sec = [pair[0] for pair in pairs]
        cnt = [pair[1] for pair in pairs]
        if sec != sorted(sec) or sec[-1] + struct.unpack_from("<H", raw, 44)[0] != len(raw):
            raise ValueError(f"block {block}: section bounds invalid")
        if sec[5] - sec[4] != 10 * cnt[4] or sec[6] - sec[5] != 14 * cnt[5] or cnt[4] != cnt[0]:
            raise ValueError(f"block {block}: Section 4/5 stride or node count invalid")
        main = _read_coordinates(raw, sec[0], sec[1], cnt[0], signed_x=False)
        other = _read_coordinates(raw, sec[2], sec[3], cnt[2], signed_x=True)
        coord_counts = Counter(main)
        for point in main:
            primary_by_coord.setdefault(point, set()).add(block)
        secondary_points.extend((block, point) for point in other)
        actual = [[] for _ in range(cnt[4])]
        edge_records = []
        for edge in range(cnt[5]):
            pos = sec[5] + 14 * edge
            flags, attrs, unresolved, a, b, length = struct.unpack_from("<5HI", raw, pos)
            atable = other if flags & 0x1000 else main
            btable = other if flags & 0x2000 else main
            if a >= len(atable) or b >= len(btable):
                endpoint_oob += 1
                continue
            if not flags & 0x1000:
                actual[a].append(edge)
            if not flags & 0x2000:
                actual[b].append(edge)
            edge_records.append((edge, flags, attrs, unresolved, a, b, length))
        for node, local_edges in enumerate(actual):
            pos = sec[4] + node * 10
            rec = raw[pos:pos + 10]
            stored_degree = rec[0] & 0x0F
            refs = struct.unpack_from("<4H", rec, 2)
            node_total += 1
            if stored_degree > 4:
                high_stored_degree += 1
                continue
            local_refs = [ref for ref in refs[:stored_degree] if ref < cnt[5]]
            if Counter(local_refs) == Counter(local_edges):
                exact_nodes += 1
            else:
                mismatched_nodes += 1
                mismatch_duplicate_coordinates += coord_counts[main[node]] > 1
                if len(mismatch_examples) < 20:
                    mismatch_examples.append({"block": block, "node": node,
                                              "record_hex": rec.hex(),
                                              "stored_degree_low_nibble": stored_degree,
                                              "local_edges_from_section5": local_edges,
                                              "candidate_refs": local_refs,
                                              "coordinate": main[node],
                                              "same_coordinate_nodes": coord_counts[main[node]]})
        for edge, flags, attrs, unresolved, a, b, length in edge_records:
            if not flags & 0x1000:
                degree = raw[sec[4] + 10 * a] & 0x0F
                refs = struct.unpack_from("<4H", raw, sec[4] + 10 * a + 2)
                if degree <= 4:
                    if edge in refs[:degree]: endpoint_ref_pass += 1
                    else: endpoint_ref_fail += 1
            if not flags & 0x2000:
                degree = raw[sec[4] + 10 * b] & 0x0F
                refs = struct.unpack_from("<4H", raw, sec[4] + 10 * b + 2)
                if degree <= 4:
                    if edge in refs[:degree]: endpoint_ref_pass += 1
                    else: endpoint_ref_fail += 1
        edge_total += cnt[5]
        block_counts.append({"block": block, "nodes": cnt[4], "edges": cnt[5]})

    cross_matches = sum(any(other != block for other in primary_by_coord.get(point, ()))
                        for block, point in secondary_points)
    digest_after = hashlib.sha256(source.read_bytes()).hexdigest()
    report = {
        "status": "PASS_WITH_REPORTED_UNRESOLVED_CASES" if endpoint_oob == 0 else "FAIL",
        "source_sha256_before": digest_before, "source_sha256_after": digest_after,
        "blocks": block_count, "blocks_inflated": len(block_streams),
        "nodes": node_total, "edges": edge_total,
        "edge_endpoint_out_of_range": endpoint_oob,
        "degree_le4_local_adjacency_exact": {"pass": exact_nodes, "fail": mismatched_nodes,
                                             "failures_at_duplicate_coordinates": mismatch_duplicate_coordinates,
                                             "examples": mismatch_examples},
        "stored_low_nibble_gt4_records_unresolved": high_stored_degree,
        "primary_endpoint_reference_membership_for_degree_le4": {"pass": endpoint_ref_pass,
                                                                  "fail": endpoint_ref_fail},
        "secondary_coordinates_matching_primary_in_other_blocks": {
            "pass": cross_matches, "fail": len(secondary_points) - cross_matches},
        "method": "Standalone struct/zlib parser; no project decoder, encoder, topology validator, or Writer imports.",
    }
    (HERE / "independent_topology_result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = validate_independently()
    print(json.dumps({k: result[k] for k in (
        "status", "source_sha256_before", "source_sha256_after", "blocks", "blocks_inflated",
        "nodes", "edges", "edge_endpoint_out_of_range", "degree_le4_local_adjacency_exact",
        "stored_low_nibble_gt4_records_unresolved", "primary_endpoint_reference_membership_for_degree_le4",
        "secondary_coordinates_matching_primary_in_other_blocks")}, indent=2))
