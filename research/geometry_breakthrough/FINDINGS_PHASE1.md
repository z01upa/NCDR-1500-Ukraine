# Geometry breakthrough — 2026-10-28

## Result and claim boundary
A real partial decoder was recovered from the original EU44420940.82 MP0, not a coordinate scan. It reconstructs endpoint-indexed polylines and their intermediate signed deltas. Independent external road identity has NOT yet been established. No confirmed-road GeoJSON, full Writer, or encoder is claimed.

All work is contained here. Original CDs were opened read-only. No database, Worker, Manager or production Reader was modified or imported for execution. Fixture tests use a separate coordinate-reading implementation. Research scripts import only this local decoder and standard-library modules.

## Reproduced facts
- 8,757 indexed zlib streams: MP0 2,956; MG1 2,167; MG2 2,017; MG3 1,617. Index-directed decoding verifies exact input/output sizes, EOF, SHA-256, and contiguous physical stream coverage through EOF after sorting extents. No signature scanning is needed by the decoder.
- Main coordinate series: MP0 956,071; MG1 602,880; MG2 574,351; MG3 479,217. Total 2,612,519. Every coordinate lies in its indexed bounding box; all section boundaries/counts match.
- Secondary series are structurally decodable, but their geographic interpretation is unresolved.
- Every endpoint index in 3,322,293 edge records is in range when flags select the coordinate table. 3,218,749 edges agree exactly with the limited three-slot adjacency interpretation. This does not fully decode high-degree vertices.
- All 2,956 MP0 blocks have valid shape tables and flag-to-shape counts. They yield 1,090,323 candidate polylines, 3,628,951 vertices including endpoints, and 723,217 edges with stored intermediate geometry.
- Of 1,061,083 edges using only primary coordinates, 1,061,072 agree with length_field * 0.3048 within max(5 metres, 2%). Only 11 primary exceptions. This is strong internal support for feet and the delta reconstruction; it is not external geographic verification.
- 21,545 of 29,240 edges selecting a secondary coordinate have length mismatches. Do NOT export these as validated roads. Overall ratio p99 is enormous for this reason; the overall median ratio is 1.0005639 and median absolute error 0.1423 m.
- Eight tests pass, including independent coordinate readback, source-hash/extent replay, signedness, malformed tables, and independent haversine lengths for three primary segments in each of three fixture blocks. These are nine internal checks, NOT three independently mapped roads.

## Physical index (little endian, offsets in original file)
Header count: u32 at 86. Global bbox: four i32 at 94 (not logical-header offset 90). Level u16 at 110, repeated block count u16 at 112. Index starts 114.
MP0: N records of 24 bytes: bbox i32[4], absolute stream pointer u32, uncompressed length u16, compressed length u16.
MG1–3: N bboxes of 16 bytes, followed by N pointer/length records of 8 bytes in the same order.
The first stream is at 114+28*N in all four files. The extra 4*N-byte area after the 24*N-byte index is not semantically decoded. Pointer order is spatial/index order, not physical stream order.

## Decompressed block
At 0..43: eleven pairs (section_offset u16, count u16). At 44: tail byte length u16. First section begins at 46.
Sections 0 and 2 use coordinate runs: u16 number_of_following_deltas, i32 initial_x, i32 initial_y, followed by that many (u16 dx, i16 dy) pairs. Accumulate x and y; start a new absolute run until the section ends. A run contributes delta_count+1 points. Main points are spatially sorted and MUST NOT be joined in storage order. Units 1e-5 degree are supported by existing geographic headers and length consistency.
Section 4: ten-byte node records, count equals section 0 count. Low nibble of first byte is a tentative degree; u16 edge references at +2,+4,+6 match most edges. The interpretation for degree>3 remains incomplete.
Section 5: fourteen-byte edge records: flags u16 +0; attributes u16 +2; unresolved u16 +4; endpoint A u16 +6; endpoint B u16 +8; length-like u32 +10. Flags 0x1000 and 0x2000 select section 2 instead of section 0 for endpoints A and B respectively. Bounds are confirmed; geographic meaning of secondary endpoints is not.
Section 6 includes variable text-bearing records (e.g. E45, AALBORG, RANDERS N in MP0 block 0), NOT a generic geometry section.
MP0 section 10: count S, tail length L. Contains S+1 u16 offsets relative to this section, first offset 2*(S+1), last L; monotonic offsets; every span is divisible by four. Each span stores signed i16 dx, i16 dy pairs. Consume one span per edge with flags & 0x8000, in edge-record order. Begin at endpoint A, accumulate each delta as an intermediate point, then append endpoint B. Shape count and extents match the whole MP0.
MG tail format is different. Applying MP0 tail parsing to MG is not justified.

## Concrete binary example
EUZ.MP0 block index 0: stream offset 20,703,022, packed 5,549, unpacked 10,333. Node section starts 46, count 128, next section 564. Edge section starts 1887. Edge 0 endpoints 12 and 14, length field 2809. Shape section starts 8879, count124, length1454; offsets 250,258 identify shape0. Raw deltas: `1b0096ff4600d1fd` = (27,-106),(70,-559).
Recovered integer polyline: (997920,5649577), (997947,5649471), (998017,5648912), (998028,5648808). Divide coordinates by100000. Calculated length approximately858m; 2809 feet=856.1832m. This is a candidate road segment in Denmark; road identity has not been externally verified.

## Firmware route and rejected hypotheses
NAVIMAIN is a 9,798-byte SH4 PE with ComMgr/COM imports and Navi process startup strings. Prior report inspection plus fresh bytes support a launcher/client hypothesis, not a proven map parser. No disassembler was available from PATH and no firmware procedure was fully traced in this session.
NK.BIN has `CE00FF` at 0x400 and a `CE` record marker at0x410, after a1024-byte wrapper. `ECEC` at0x9cead3 is inside the still-encoded stream. The full source hashes and exact byte windows are in firmware_evidence.json. ROM addresses must not be naively translated by subtracting a raw-file base. CE stream decompression and module recovery remain future work.
Public source consulted: https://github.com/nlitsme/CompressUtils (legacy WinCE compression wrappers); https://github.com/KodaSec/wince-decompr (explicitly v5+ and older-LZ77 TODO). Neither was downloaded or executed; no algorithm from them is claimed applicable to this image.
Rejected: generic int32 scans as proof; joining sorted main coordinates as roads; treating section6 as shapes; applying MP0 tail layout to MG; treating length field as metres; treating all secondary coordinates as primary geographic positions.

## External validation limitation
An Overpass read request failed DNS in the restricted environment. An elevated retry was rejected by automatic approval review because it would send proprietary-data-derived coordinates to a public server without explicit destination-specific authorization. The request was not retried through another route. Local available OSM data covers Ukraine, not the sampled European segments. Geographic verification remains pending user authorization or a suitable local reference dataset. No road GeoJSON was emitted, in accordance with the request to emit it only when confirmed. No encoder was attempted because the external-verification gate has not passed.

## Evidence and reproduction
Run from this directory with Python3:
`python -B decoder.py`
`python -B graph_audit.py`
`python -B polyline_audit.py`
`python -B length_exceptions.py`
`python -B -m unittest discover -s . -p "test_*.py" -v`
No third-party package is required. Sources are fixed read-only paths under original SW/DB. The audit JSON includes source hashes, block offsets, bounding boxes, decoded hashes and counts; twelve binary fixtures cover the first three blocks of each family. polyline_candidates.json contains nine raw candidate examples, not certified geographic features. Exploratory *_probe.py scripts preserve the derivation and rejected intermediate hypotheses.
