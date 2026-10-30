# DB_0 format status after phases 1–4

## Confirmed

- `DB_0` is framed in 512-byte physical sectors. Bytes 0–2 of a record are its
  uint24 big-endian start sector; byte 3 is its sector span. The 54,010-record
  chain from `0x000002` through `0x078695` validates this rule.
- Every one of the 16,371 successful zlib records has exactly one successful
  zlib stream beginning at record-local byte 8. Thus bytes 4–7 are a four-byte
  pre-zlib subheader for this population. The compressed stream ends within the
  record's declared span.

## Strongly supported

- Bytes 4–7 identify repeatable **class signatures**, but their semantic meaning
  is unknown. The largest uncompressed signatures are `00160000` (8,799),
  `00090000` (5,241), `00060000` (4,623), `00150000` (2,262), and `001c0000`
  (1,698). See `record_class_statistics.txt` for their sizes and examples.
- The zlib class signature is also the exact four-byte pre-zlib area. Examples:
  `00170260` (659), `000e0260` (611), `00100260` (453), and `00040206` (363).
  No stored compressed or uncompressed length field was established from the
  pre-zlib bytes; only record span bounds the compressed data.
- Repeated null-terminated textual content occurs in decompressed payloads.
  `moskva`, `renault`, and `russneft'` occur in the conservative scan, proving
  that text dictionaries are represented inside at least some decompressed
  records. This does not establish their directory or reference format.

## Hypotheses / candidates

- `semantic_candidates.csv` applies only observable heuristic scores. The
  leading routing/index candidates are zlib signatures `00040205`, `00040206`,
  `00040204`, and adjacent `000402xx` variants. This is a priority list for
  decoding, not a class identification.
- `string_index_edges.csv` contains candidates where a BE uint32 can name a
  1024-byte page containing extracted raw text and is immediately followed by
  printable bytes. There are many candidates, but their keys include binary
  noise and no ordering test succeeded; they do not prove a B-tree.

## Rejected / not established

- No string reference representation is confirmed. In particular, the supplied
  absolute byte offsets did not yield reported direct BE absolute-reference
  matches under the conservative dictionary extraction.
- The scan did not establish B-tree/B+tree nodes, key ordering, pointer widths,
  record IDs, subtype meanings, counts, coordinate encoding, geometry, or
  routing topology.

## Method limits

`strings.csv` is capped at 100,000 conservative null-terminated text candidates
(maximum 80 bytes, at least two letter-like bytes). The cap prevents binary
false positives from obscuring the corpus. It is an evidence-oriented sample,
not an exhaustive proof of every string in the image.

## Phase 5 status

The `00040204`–`00040209` family is strongly supported as a family of zlib
records with a shared framing convention. Phase 5 did not confirm fixed-width
elements, cross-record links, coordinate fields, geometry, or a routing graph.
The high number of raw integer values equal to known sector IDs has not been
treated as evidence because the test did not yet compare it with accidental
match rates or demonstrate stable field positions.

## Published-format validation

The published BL_HEAD interpretation is now confirmed for this DB's physical
framing. Its type byte is byte 5; byte 6 value `0x02` means zlib; byte 7 is the
logical uncompressed size in 512-byte units, including the eight-byte header.
Byte 3 separately records the physical stored span in 512-byte sectors.

Published MULCOORD also validates: BE `hlon, hlat` decode with coefficient
5,555,555 and longitude offset −30. Type `0x0A` contains country names, type
`0x0C` administrative/city text, and type `0x10` contains dense valid
coordinate populations consistent with POIs.

## Roads correction

Type `0x16` is UNKNOWN. Frequency is not evidence of geometry. Road analysis
now follows `0x0C → 0x0F → 0x0E`; many exact full-BL_ADDR links from `0x0F` to
`0x0E` exist, but Moscow's individual `ch_roads` field is not yet parsed.

Phase 9 shows that the 185-road Moscow sublist in `0x0E:0x31A0` has 185
unique `extended_info` pointers spaced exactly six bytes apart. For
`1 iy mikrorayon`, the raw six bytes are `54b401010000`. No LIST or FAR_LIST is
confirmed in those six bytes; the first uint16 is only a local-pointer
candidate until its target structure is decoded.

## Phase 11 road-object update

The six-byte MORE_INFO records now resolve field 0 to 483 validated 24-byte
objects. Each object has a MULCOORD anchor and a type-`0x00` BL_ADDR. E/F is
consistent with a packed list reference using `pointer = E & 0x3fff`,
`flags = E >> 14`, and `F` as the item count. The example `0x4df8` therefore
points at `0x0df8` with flag `1` and count `31`.

There are 102 unique type-`0x00` targets. The header-advertised logical extents
validate all 483 references; 21 of the masked pointers extend beyond the bytes
currently available for the still-undecoded compression-`0x01` targets. No
fixed element width, element schema, or road polyline is confirmed yet.
