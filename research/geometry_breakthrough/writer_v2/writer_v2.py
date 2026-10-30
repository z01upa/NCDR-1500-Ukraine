"""Fail-closed extension point for adding one MP0 edge.

Writer v1 remains the only MP0 serializer. This module performs a verified
preflight and refuses before calling any serializer until topology and route
field dependencies are known. It never writes a candidate file on refusal.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
GEOMETRY = HERE.parent
TOPOLOGY_V3 = GEOMETRY / "topology_v3"
if str(TOPOLOGY_V3) not in sys.path:
    sys.path.insert(0, str(TOPOLOGY_V3))

from node_link_validator import SOURCE, EXPECTED_SHA256, _read_container, _sections  # noqa: E402
import struct
from topology_validator import audit_topology  # noqa: E402
from routing_file_audit import audit_routing_files  # noqa: E402


class TopologyWriteBlocked(RuntimeError):
    """The evidence does not yet authorize an MP0 topology mutation."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__("MP0 edge insertion refused before file creation")


def preflight_add_edge(source: Path = SOURCE, *, block: int, node_a: int, node_b: int) -> dict[str, Any]:
    if block < 0 or node_a < 0 or node_b < 0 or node_a == node_b:
        raise ValueError("provide one block and two distinct nonnegative existing node IDs")
    # Validate that the requested pair exists in the chosen block; refusal is
    # about unresolved format rules, not malformed candidate indices.
    source = Path(source).expanduser().resolve(strict=True)
    _container, decoded_blocks = _read_container(source)
    if block >= len(decoded_blocks):
        raise IndexError(f"block index {block} outside {len(decoded_blocks)} blocks")
    raw = decoded_blocks[block]
    offsets, counts = _sections(raw)
    node_count, edge_count = counts[4], counts[5]
    if node_a >= node_count or node_b >= node_count:
        raise IndexError(f"candidate node outside block {block} node range 0..{node_count - 1}")
    candidates = []
    for node_id in (node_a, node_b):
        record = raw[offsets[4] + node_id * 10: offsets[4] + (node_id + 1) * 10]
        low = record[0] & 0x0F
        words = struct.unpack_from("<4H", record, 2)
        candidates.append({"node": node_id, "record_hex": record.hex(),
                           "stored_low_nibble": low,
                           "candidate_active_refs": list(words[:low]) if low <= 4 else None,
                           "four_u16_words": list(words)})
    direct_local_edges = []
    for edge_id in range(edge_count):
        edge_at = offsets[5] + edge_id * 14
        edge_flags, _attrs, _opaque, endpoint_a, endpoint_b, _length = struct.unpack_from(
            "<5HI", raw, edge_at)
        if (not edge_flags & 0x1000 and not edge_flags & 0x2000
                and {endpoint_a, endpoint_b} == {node_a, node_b}):
            direct_local_edges.append(edge_id)
    topology = audit_topology(source, write_evidence=False)
    routes = audit_routing_files(write_evidence=False)
    blockers = [
        "The next Section-4 u16 after low-degree links is opaque and nonzero in most records; adding a link would overwrite unknown data.",
        "For low nibble >4, only partial references are identified; the first word at +2 and the missing high-degree links are unresolved.",
        "There are 511 low-degree node-index mismatches at repeated coordinates; coordinates cannot be used to merge those node identities.",
        "Section-5 attributes and unresolved fields, including road class, direction, access, and routing semantics, are unknown.",
        "Sections 7-9 contain edge-index-shaped keys; their row ownership and rekey rules are not proven. Section 6 ownership is also unresolved.",
        "EUZ.RT is a separate type-22 companion container whose relationship to MP0 edges is not established.",
    ]
    if topology["source_sha256_after"] != EXPECTED_SHA256:
        raise ValueError("source hash changed or source differs from the bound original")
    return {
        "status": "REFUSED_BEFORE_MUTATION",
        "source": str(source), "source_sha256": topology["source_sha256_after"],
        "candidate": {"block": block, "node_a": node_a, "node_b": node_b,
                      "block_node_count": node_count, "block_edge_count": edge_count,
                      "node_records": candidates,
                      "existing_primary_local_edges_between_pair": direct_local_edges,
                      "hypothetical_next_edge_id": edge_count},
        "topology_audit_status": topology["status"],
        "routing_file_audit_status": routes["status"],
        "blockers": blockers,
        "output_file_created": False, "source_write_count": 0,
        "routing_compatibility_claim": "NOT_ESTABLISHED",
    }


def write_new_edge(*, source: Path = SOURCE, output: Path, block: int,
                   node_a: int, node_b: int, geometry: list[tuple[int, int]] | None = None,
                   flags: int | None = None, attributes: int | None = None,
                   unresolved: int | None = None) -> dict[str, Any]:
    """Refuse before opening output; never invent route flags or edge bytes."""
    report = preflight_add_edge(source, block=block, node_a=node_a, node_b=node_b)
    report["requested_output"] = str(output)
    report["supplied_geometry_point_count"] = None if geometry is None else len(geometry)
    # Even caller-supplied fields do not resolve the source-format semantics.
    report["supplied_unknown_fields"] = {"flags": flags, "attributes": attributes,
                                         "unresolved": unresolved}
    raise TopologyWriteBlocked(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--block", type=int, required=True)
    parser.add_argument("--node-a", type=int, required=True)
    parser.add_argument("--node-b", type=int, required=True)
    args = parser.parse_args()
    try:
        report = preflight_add_edge(args.source, block=args.block,
                                    node_a=args.node_a, node_b=args.node_b)
    except Exception as exc:
        print(json.dumps({"status": "PREFLIGHT_ERROR", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
