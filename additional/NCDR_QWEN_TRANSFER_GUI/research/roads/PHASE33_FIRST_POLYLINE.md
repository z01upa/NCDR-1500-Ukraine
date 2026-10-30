# Phase 33 — readable type-0x00 road targets

Filtering the existing 483 validated road objects for target compression 0x00 or 0x02 yields 101 readable objects across 23 unique type-0x00 targets. The first inspected example is `1 y arkhivniy pereulok`, object offset `21852`, target sector `214133`, compression 0x02, E=`0x26AC`, masked pointer `0x26AC`, F=1, anchor `37.559185,55.733213`.

The E pointer is confirmed as an in-bounds local offset under `E & 0x3FFF`; it does not yet identify a self-describing geometry header. Around readable pointers, repeated 16-byte-looking records occur. For the first example, bytes at `0x26AC` begin `19 2C 90 0B 00 9E 60 E0 04 20 80 54 8A 16 8C D0`, followed by similarly patterned records at 16-byte intervals. The pointer range continues to the next known pointer at `0x2B4C`, so the record count/terminal grammar is not established.

Across 20 independent readable objects, no fixed-width interpretation of F as vertex count, segment count, byte count, or word count was validated. Signed 8/16/24-bit and obvious packed-delta interpretations were not accepted because no model simultaneously produced structurally bounded, geographically plausible vertices across independent targets. The absolute MULCOORD anchor remains an object-level anchor; repetition inside the target payload was not proven.

No complete road polyline was recovered. A/B/C/D remain ordered pair-like fields with unresolved semantics; existing evidence supports index/range behavior more strongly than a confirmed bounding box. Compression-0x01 remains outside this phase.

Next exact unresolved item: decode the repeated 16-byte type-0x00 element grammar and its terminal framing, then test deltas against the anchor on multiple F>1 objects.
