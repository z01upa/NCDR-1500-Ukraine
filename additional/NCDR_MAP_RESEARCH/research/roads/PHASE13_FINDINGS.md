# Phase 13 findings

- Mapped 413 unique road-owned pointers (483 owner rows) against 457 provisional descriptor/root ranges across 79 target blocks.
- Inside known ranges: 297/483 (61.5%); exact descriptor targets: 0/483 (0.0%).
- E flags do not by themselves establish a root/section selector; pointers are best treated as absolute local offsets into type-0x00 blocks until section-relative encoding is proven.
- F remains unresolved after grouping: same-section pointer spacing and F values do not establish a uniform record model.
- Compression inventory is recorded separately; compression=0x01 section-level behavior is not confirmed by this mapping alone.
- No geometry was emitted. Remaining blocker: exact terminal framing and the compression=0x01 payload grammar.
