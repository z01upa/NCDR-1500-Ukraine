# Phase 23 — POI item identity before coordinate decoding

## Identity and sorted-table tracking

The editable table is a 28-byte-entry sequence. The six-byte coordinate-like item begins at entry offsets `0x0C66`, `0x0C82`, `0x0C9E`, `0x0CBA`, `0x0CD6`, etc. Identity is established by the unchanged neighboring entries, not by offset alone.

| output | previous item | inserted item | next item | rank (1-based, local sequence) | record | offset |
|---|---|---|---|---:|---|---|
| B | `261157920024` @ `0x0C66` | `26425A3D001C` | `266257890024` @ `0x0C9E` | 2 | `0x06/0x7749B` | `0x0C82` |
| L1 | `261157920024` @ `0x0C66` | `264B5A3D001C` | `266257890024` @ `0x0C9E` | 2 | `0x06/0x7749B` | `0x0C82` |
| T1 | same as B | `26425A46001C` | same as B | 2 | `0x06/0x7749B` | `0x0C82` |
| T2 | same as B | `26425A94001C` | same as B | 2 | `0x06/0x7749B` | `0x0C82` |
| YCarry | same as B | `26425B42001C` | same as B | 2 | `0x06/0x7749B` | `0x0C82` |
| L2 | `266257890025` @ `0x0C9E` | `26995A3D001C` | `292F4942002F` @ `0x0CD6` | 3 | `0x06/0x7749B` | `0x0CBA` |
| XCarry | `266257890025` @ `0x0C9E` | `27475A3D001C` | `292F4942002F` @ `0x0CD6` | 3 | `0x06/0x7749B` | `0x0CBA` |

Thus the point follows the sorted table. L1 remains at the original rank; L2 and XCARRY move one entry later. The Phase 22 XCARRY raw item `266257890024` was a neighboring existing POI and is invalidated as the edited item. The Phase 22 B and YCARRY items were correct; its XCARRY comparison was not.

## Model tests

On the verified items, direct `[X24][Y24]` and the Phase 21 byte-permutation candidates do not produce one constant-origin mapping. Interleaved bitfields and Morton/Z-order are not supported by the unchanged-axis controls: the Y field changes in T1/T2/YCARRY while X bytes remain fixed, and L1/L2/XCARRY move the whole entry when longitude changes. A coarse-cell/local or sorted-key-plus-payload representation remains possible, but is not uniquely identified.

The neighbor-delta hypothesis is not confirmed: the predecessor changes from `261157920024` (B neighborhood) to `266257890025` (moved neighborhood), while the inserted six-byte values do not yield a common delta-lon/delta-lat rule under the confirmed Q grid. The strongest confirmed representation is a 28-byte sorted-table entry containing a six-byte coordinate-related payload, not two proven independent coordinates.

Next experiment: obtain the displayed coordinates and raw six-byte values for the immediate predecessor and successor POIs in both neighborhoods, then solve the complete 28-byte entry schema and its sort key jointly.
