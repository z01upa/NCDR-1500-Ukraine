# Phase 14 findings

- Readable controls parsed: 3232 (196 raw, 3036 zlib).
- LIST(0x74,3) and root layout are tested separately by compression in TYPE00_PREFIX_FORMAT.md.
- Prefix uint16 validation, section candidates, and fixed-width element census are exported; no semantic field names are asserted without cross-block proof.
- Road-owned pointers are classified conservatively; unknown remains expected because readable controls are not road-owned and compression=0x01 payload equivalence is unresolved.
- No coordinate or graph decoder is claimed.
