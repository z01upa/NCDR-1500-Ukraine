"""Conservative decoder for one 10-byte MP0 Section-4 node record.

It exposes the inline link candidates established by topology_v2 without
assigning semantics to inactive words or high-degree continuation fields.
"""
from __future__ import annotations

import struct
from collections import Counter
from typing import Any

NODE_RECORD_SIZE = 10
INLINE_LINK_SLOTS = 4


def decode_node_record(record: bytes, *, local_edge_count: int | None = None) -> dict[str, Any]:
    if len(record) != NODE_RECORD_SIZE:
        raise ValueError(f"Section-4 node record must be exactly {NODE_RECORD_SIZE} bytes")
    byte0, byte1 = record[0], record[1]
    degree_nibble = byte0 & 0x0F
    kind_nibble = byte0 >> 4
    words = struct.unpack_from("<4H", record, 2)
    if degree_nibble <= INLINE_LINK_SLOTS:
        active_count = degree_nibble
        candidate_links = list(words[:active_count])
        trailing_words = list(words[active_count:])
        if local_edge_count is None:
            link_status = "CANDIDATE_LINKS_ONLY; EDGE_TABLE_IDENTITY_NOT_CHECKED"
        elif all(link < local_edge_count for link in candidate_links):
            link_status = "CANDIDATE_LINKS_IN_EDGE_RANGE; NODE_IDENTITY_NOT_CHECKED"
        else:
            link_status = "ACTIVE_INLINE_WORD_OUTSIDE_LOCAL_EDGE_RANGE"
    else:
        active_count = None
        candidate_links = []
        trailing_words = list(words)
        link_status = "HIGH_DEGREE_CONTINUATION_UNRESOLVED"
    return {
        "record_hex": record.hex(),
        "byte_0": byte0,
        "byte_1": byte1,
        "low_nibble": degree_nibble,
        "high_nibble": kind_nibble,
        "candidate_active_link_count": active_count,
        "candidate_inline_edge_ids": candidate_links,
        "trailing_u16_words_preserved_opaque": trailing_words,
        "all_four_u16_words": list(words),
        "byte_1_semantics": "UNKNOWN; preserve verbatim",
        "high_nibble_semantics": "UNKNOWN; preserve verbatim",
        "plus8_semantics_when_low_nibble_below4": "UNKNOWN; NOT a free slot",
        "candidate_links_within_local_edge_count": (
            None if local_edge_count is None else all(link < local_edge_count for link in candidate_links)
        ),
        "interpretation_status": link_status,
    }


def validate_inline_links(record: bytes, incident_edge_ids: list[int], *,
                          local_edge_count: int) -> dict[str, Any]:
    """Confirm the inline link rule for this exact record by edge identity.

    Does not merge nodes by coordinates. High-nibble values above four and
    any identity mismatch remain unresolved, not successful guesses.
    """
    decoded = decode_node_record(record, local_edge_count=local_edge_count)
    degree = decoded["low_nibble"]
    if degree > INLINE_LINK_SLOTS:
        return {"status": "UNRESOLVED_HIGH_NIBBLE", "decoded": decoded,
                "incident_edge_ids": list(incident_edge_ids)}
    links = decoded["candidate_inline_edge_ids"]
    if any(edge < 0 or edge >= local_edge_count for edge in incident_edge_ids):
        return {"status": "INVALID_INDEPENDENT_EDGE_ID", "decoded": decoded,
                "incident_edge_ids": list(incident_edge_ids)}
    exact = Counter(links) == Counter(incident_edge_ids)
    return {"status": "CONFIRMED_FOR_RECORD" if exact else "IDENTITY_MISMATCH",
            "decoded": decoded, "incident_edge_ids": list(incident_edge_ids),
            "exact_multiset_match": exact}
