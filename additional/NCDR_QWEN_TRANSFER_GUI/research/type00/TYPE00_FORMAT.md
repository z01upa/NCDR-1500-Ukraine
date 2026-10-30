# Phase 14 readable type-0x00 format status

- 3,232 transparent type-0x00 logical views were parsed: 196 compression `0x00` and 3,036 compression `0x02`.
- Compression `0x02` zlib views were validated against the advertised logical sizes.
- Under the current logical-view convention, the literal `LIST(0x0074,3)` signature was not found at offset `0x74` in the readable controls: `0/196` raw and `0/3036` zlib.
- Therefore the previously observed compression-`0x01` structure is not yet proven to be shared at the same logical offsets by readable controls.
- Prefix candidates, provisional section boundaries, structural matches, and conservative road-pointer classifications are exported separately.
- No coordinate, graph, or semantic section decoder is confirmed.
