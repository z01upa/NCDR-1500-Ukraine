# MP0 geometry — verified partial breakthrough, 2026-10-28

## Current result
The byte-to-road barrier is crossed for ONE independently matched road segment, with a reproducible decoder and limited shape encoder. This is not a complete map Writer or certification of every decoded segment. Three independent geographic examples were sought; local coverage yielded only one qualifying example, so that requirement is explicitly incomplete.

EUZ.MP0 block886 / edge1 matches local OpenStreetMap way1295825030, highway primary, road19 / E50 / E58 near the Slovak–Ukrainian border. Original source offset28,578,738; record offset9,924 in the decompressed block; bytes `1483000000008b028c0257020000`.
Decoded points (longitude, latitude):
- (22.26157,48.65529)
- (22.26176,48.65541)
- (22.26274,48.65618)
- (22.26318,48.65654)

Length182.6167m; stored length599 interpreted as feet gives182.5752m. Eleven samples at spacing no greater than20m have median1.041m and maximum2.004m distance to the independent local OSM highway geometry. No translation, rotation, scaling, or coordinate adjustment was fitted. Shifting the decoded line500m east gives median113.352m. This establishes alignment with a real road corridor; lane-level accuracy and unchanged historical road details are not claimed.

## Independence and selection audit
`independent_verify.py` imports neither decoder nor encoder. It reads original-file index entries, decompresses streams, reconstructs coordinates and shapes separately, and uses haversine distances. All1,090,323 resulting polylines match the main decoder point-for-point. No edge is selected or altered according to its stored length.

Across ALL edges with fixed tolerance max(5m,2% of hypothesized stored length):
| Interpretation/control | Matches /1,090,323 |
|---|---:|
| raw length *0.3048 (feet hypothesis) |1,090,198|
| raw length in metres |24|
| cyclically permuted next-edge length, feet |99,069|

Median measured metres/raw-unit is0.3049526566. This strongly supports feet rather than metres; the exact conversion constant has not been traced in firmware. The decoder does not use the stored length to generate coordinates. Primary-only result remains1,061,072/1,061,083. Secondary-endpoint result after fixing signedness is29,126/29,240.
Parity stratification also agrees: even blocks546,729/546,796, odd blocks543,469/543,527. This is a post-hoc stability check, NOT an untouched blinded holdout: the earlier work had already examined all blocks.

## Local geographic comparison and its limits
Read-only reference: `data/osm/ukraine-latest.osm.pbf`; full SHA256 is in `evidence/local_osm_overlap_nodes.json`. Reference attribution: © OpenStreetMap contributors, ODbL 1.0 ([copyright and attribution](https://www.openstreetmap.org/copyright); [license text](https://opendatacommons.org/licenses/odbl/1-0/)). The source existed locally before this research and was not generated from NCDR coordinates. The published OSM extracts and their source details are listed in `OSM_DATA_LICENSE.md`. The PBF scan inspected112,493,890 dense nodes and extracted221,704 nodes in [21.95,48.60,22.4,48.85], then8,843 highway ways intersecting that window. Helpers are supplied in `local_pbf_check.py` and `local_highways.py`.
All main MP0 nodes were screened against a deliberately broad Ukraine bbox; only188 nodes, in block886, overlapped it. The local reference provides only a small fringe of MP0's European coverage. `compare_local.py` considered all42 eligible curves with at least4 vertices, length>=100m, fully inside the reference window. It records EVERY candidate's metric, including nonmatches. Match threshold: max<25m, median<10m, shifted-control median>40m; no length-agreement filter. Only edge1 qualifies. Edge0 also aligns closely but shares the corridor and fails this negative control; it is not counted as an independent confirmation. Lack of reference coverage is not evidence that other decoded roads are wrong.
Road-only reference excludes footways, paths, steps, cycleways, construction and proposed ways. Distance is sampled directed point-to-reference-polyline distance, not a full road-network identity proof. OSM's modern data can differ from the old disc.

## Corrected two-table topology
Section0 main coordinates use unsigned dx and signed dy. Section2 uses SIGNED dx and signed dy. Both use absolute initial i32 x/y and u16 number of following delta pairs per run.
All29,240 secondary coordinates now exactly equal a primary coordinate in another block. This test uses no length fitting. Grouping cross-block edges by unordered endpoint pair gives14,612 two-copy groups and4 four-copy groups. Every two-copy group has identical stored length AND the complete polyline, after orientation normalization. Four-copy groups remain ambiguous parallel/multiple-edge cases and are not silently deduplicated.
The earlier unsigned-secondary decoder is preserved as `decoder_v1_unsigned_secondary.py`. Its output and phase1 reports are historical counterevidence; current `decoder.py` has the signed correction. Old audit scripts explicitly import v1 to retain their original experiment semantics.

## Eleven primary length exceptions
Exact coordinates, raw records and calculations are in `evidence/independent_validation.json`; a concise table is `evidence/eleven_primary_exceptions.json`.
Ten share flags0x834c and long distances. Every one has a final endpoint delta outside signed16 range. They occur at(block,edge): (463,1),(463,34),(963,2),(966,13),(966,14),(1382,164),(1719,327),(1722,1),(1934,5),(2766,0). This isolates a long-edge encoding/semantic issue; it does NOT prove these are ferries or justify wrapping deltas to fit the length. Longer-range coordinate handling, specialized edge semantics, or source generalization remain hypotheses. No coordinates were repaired using the length.
The remaining case is block2043 edge213, flags0x8f38: geometry≈129.57m versus145.3896m from stored length. It is a short-segment discrepancy, separate from the long-edge cluster, and remains unresolved.
There are114 additional secondary-edge mismatches. Do not claim complete format correctness. Original statements that secondary geography was wholly unresolved are superseded by the exact cross-block coordinate and edge matches above.

## Binary format recovered
All values little endian. Physical header count u32@86, bbox i32[4]@94, level u16@110, repeated count u16@112. Index starts114. MP0 entry24bytes: bbox16bytes, absolute pointer u32, decoded size u16, compressed size u16. MG1–3 instead have all bboxes then all8-byte pointer/size entries. First stream114+28*N; the4*N area following index entries remains opaque. Pointer order differs from physical stream order. All8,757 streams have exact sizes and contiguous sorted extents through EOF.
Main coordinate total2,612,519, all inside indexed bboxes. Full source and payload hashes are in coordinate_audit.json.
Decoded header: eleven(offset u16,count u16) pairs at0..43, tail byte length u16@44. Section0 starts46. Coordinate runs: u16 number-of-deltas, i32x, i32y, then dx/dy16-bit pairs; use signedness by table as above. Scale1e-5 degree is independently supported by local OSM alignment.
Section4: node records10bytes; partial adjacency references at+2,+4,+6. Higher-degree handling is incomplete.
Section5: edge records14bytes: flags u16@0, attributes u16@2, unresolved u16@4, endpoint A u16@6, endpoint B u16@8, length-like u32@10. Bits0x1000/0x2000 select secondary coordinates for A/B. Endpoints otherwise reference section0.
Section6 includes variable text records, NOT generic shapes.
MP0 section10 contains S+1 relative u16 offsets and S delta spans. Offset0=2*(S+1), last=tail length. Each span consists of signed(dx,dy)16-bit pairs. Consume one span for each edge with flag0x8000 in edge order. Accumulate from A to get intermediate points; append B. This yields1,090,323 polylines /3,628,951 vertices;723,217 edges have intermediate geometry. All2,956 MP0 blocks satisfy shape-count and offset invariants. MG shape-tail semantics remain different and unresolved.

## Experimental encoder and validation
`encoder.py` encodes MP0 shape tails only, preserving topology and other fields. Exact decode->encode reconstruction matches all2,956 original decompressed blocks byte-for-byte. This is actual intermediate-coordinate serialization, not just zlib repacking.
For independently matched block886 edge1, intermediate point(2226176,4865541) was changed to(2226181,4865541). The changed block was compressed into an isolated ONE-BLOCK TEST ENVELOPE. The independent reader recovered the intended change and all706 edges; encoding the original coordinates restores the exact original block bytes. Evidence: encoder_roundtrip.json, MP0_886.bin, MP0_886_modified.bin, experimental_one_block.MP0.
This envelope is NOT a device-compatible disc/map. The experimental edit leaves length/routing attributes unchanged, so it is not deployable. No claim of complete writer support, cross-file consistency, or navigation readiness is made.
Fourteen tests pass, including all-original independent point readback, source checksums and stream extents, malformed data, encoder overflow rejection, isolated modified-envelope readback and restoration. `test_local_reference_match` checks saved comparison metrics; recompute actual reference distances with compare_local.py.

## Reproduction
From this directory, Python3 standard library only:
```
python -B independent_verify.py
python -B crossblock_audit.py
python -B reciprocal_border.py
python -B investigate_exceptions.py
python -B compare_local.py
python -B encoder_roundtrip.py
python -B -m unittest discover -s . -p "test_*.py" -v
```
To regenerate local-reference extracts, first run local_pbf_check.py then local_highways.py (PBF node scan took about86 seconds here). All outputs stay here. Original CD, reference PBF, production SQLite, Worker and Manager are read-only/unmodified.

## Files and remaining scope
`locally_matched_roads.geojson`: local-only mixed NCDR/OSM output, omitted from the public snapshot pending source separation; the finding and measurements are recorded above.
`local_osm_reference.geojson`: independent reference geometry under ODbL 1.0; see `OSM_DATA_LICENSE.md`.
`candidate_roads_UNCONFIRMED.geojson`: three illustrative curves from different blocks, explicitly not geographically certified.
`FINDINGS_PHASE1.md` / `HANDOFF_PHASE1.md`: historical initial state, superseded by this document.
`MANIFEST.json`: SHA256 evidence/source inventory.
Firmware evidence and initial probes remain available; no firmware parser routine was disassembled or fully recovered. NK.BIN CE00FF@0x400 is still a useful future extraction target. Prior online Overpass attempt was rejected by automatic approval; no bypass was attempted. The successful geographic verification uses local OSM only, so that network limitation did not block this result.
