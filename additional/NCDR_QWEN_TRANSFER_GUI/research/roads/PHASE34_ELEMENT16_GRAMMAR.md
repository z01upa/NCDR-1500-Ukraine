# Phase 34 — type-0x00 element grammar

The 101 readable objects were tested using `E & 0x3FFF` and 16-byte neighborhoods. All pointers are 4-byte aligned, but their residues modulo 16 are distributed as: 0=42, 4=15, 8=13, 12=31. Thus there is no single block-global 16-byte alignment. Pointer-to-next-pointer gaps are divisible by 16 for 85/101 objects, but have residues 4, 8, or 12 for the remaining 16.

Repeated 16-byte-looking byte patterns occur locally, especially in compression-0x02 blocks, but no stable run-start/run-end rule holds across all readable objects. The pointer can land at different phases within a local pattern and is not proven to be the first element of a 16-byte table. F has no exact relationship to candidate 16-byte run length; its distribution is broad (F=1 for 39/101, F=2 for 20/101, with values through 20).

The only robust structural field classification remains `E & 0x3FFF` as an in-bounds local-offset candidate. The 16-byte pattern fields have not achieved statistically strong pointer validity or a validated terminator. Same-target groups show multiple pointers/F values selecting different regions of shared payloads, but no exact subrange grammar was proven. A/B/C/D remain unresolved ordered pair-like fields.

No coordinate candidate was tested further because stable element boundaries were not established. No complete polyline was recovered.
