"""Refusal-first Section 4 topology edit gate.

No MP0 mutation is currently enabled: Sections 7-9 have edge-index-like
keys, while their complete dependency semantics (and Section 6 consumers)
are not established. The only supported operation here is a byte-exact no-op.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib


class TopologyMutationRefused(RuntimeError):
    pass


@dataclass(frozen=True)
class DependencyAssessment:
    section4_inline_links: str = "confirmed only for low nibble <=4 exact-identity records; 511 exceptions"
    section5_edge_record_semantics: str = "partial; routing/direction attributes unresolved"
    section6_edge_dependencies: str = "unresolved"
    section7_edge_key_semantics: str = "edge-index-like first u16; payload semantics unresolved"
    section8_edge_key_semantics: str = "edge-index-like first u16; payload semantics unresolved"
    section9_edge_key_semantics: str = "edge-index-like first u16; payload semantics unresolved"
    plus8_for_degree_below4: str = "opaque; cannot overwrite"
    high_degree_continuation: str = "unresolved"

    @property
    def mutation_safe(self) -> bool:
        return False


def noop_roundtrip(data: bytes) -> bytes:
    """Return a byte-identical candidate without touching disk."""
    return bytes(data)


def preflight_edge_permutation(*, block: int, edge_a: int, edge_b: int,
                               assessment: DependencyAssessment | None = None) -> dict:
    """Refuse until every record family that can use edge IDs is proven."""
    assessment = assessment or DependencyAssessment()
    blockers = [
        "Section 6 edge/name ownership has not been ruled out or decoded",
        "Section 7/8/9 first-u16 fields are edge-index-like, but payload ownership and rekey rule are unproven",
        "Section 4 +8/+9 may not be overwritten except at confirmed degree-4 links",
        "High-degree continuation and the 511 identity mismatches remain unresolved",
        "Section 5 routing/direction semantics are unresolved",
    ]
    if block < 0 or edge_a < 0 or edge_b < 0 or edge_a == edge_b:
        raise ValueError("permutation requires a block and two distinct nonnegative edge IDs")
    if assessment.mutation_safe:
        raise NotImplementedError("mutation implementation requires a reviewed dependency map")
    return {"status": "REFUSED_BEFORE_MUTATION", "block": block,
            "edge_ids": [edge_a, edge_b], "original_bytes_written": False,
            "blockers": blockers}


def permute_edges(*_args, **_kwargs) -> bytes:
    """Prevent accidental partial edits until the dependency map is complete."""
    raise TopologyMutationRefused(
        "edge permutation refused: Sections 6-9 and high-degree dependencies are not fully proven"
    )


def source_fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
