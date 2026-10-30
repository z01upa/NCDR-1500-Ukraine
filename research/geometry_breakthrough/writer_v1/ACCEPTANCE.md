# MP0 Writer v1 — acceptance

Date: 2026-10-29  
Overall status: **PASS — full experimental MP0 created and independently read back.**  
Physical Opel compatibility: **NOT TESTED**. This is an experimental file, not a compatible navigation disc.

## Source and output

| Item | Result |
|---|---|
| Read-only source | `${NCDR_SOURCE_ROOT}\SW\DB\EUZ.MP0` |
| Source SHA-256 before and after | `73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e` |
| Source bytes | 30,281,958 |
| New experimental output | `EUZ_MP0_block886_edge1_geometry_experiment.MP0` |
| Output SHA-256 | `f7def93e7a5233c556448aab56b3373b07a078ba6641a7d418de3b15b92be19b` |
| Output bytes | 30,281,957 |

## Controlled edit

**PASS** — block 886, edge 1, intermediate point index 1 changed from `(2226176, 4865541)` to `(2226181, 4865541)` (`dx=+5`, `dy=0`). The edge has no identical geometry copy in another block, so no reciprocal copy was left stale.

**PASS** — decoded shape length changed from 182.616668823 m to 183.090083024 m. `length_raw` changed from 599 to 601 feet; the stored length is 183.1848 m, an error of 0.094716976 m, within the 0.1524 m half-foot rounding bound.

**PASS** — only three decoded bytes changed inside block 886: edge length byte at raw offset 9934 and shape-tail delta bytes at offsets 27689 and 27693. The block raw size stayed 30,061 bytes; its compressed size changed from 17,471 to 17,470 bytes. The complete output shrank by one byte. The physical payload order was retained, and all 164 absolute pointers after the changed stream were rebuilt. Their complete block-index list is in `independent_reader_result.json` and `writer_run.json`.

## Independent validation

| Check | Status / result |
|---|---|
| Full container has 2,956 indexed blocks | **PASS** |
| All 2,956 zlib streams inflate to their indexed sizes | **PASS** |
| Absolute pointers, packed sizes, decoded sizes, physical stream order, and EOF | **PASS** |
| Opaque 11,824-byte pre-payload region preserved byte-for-byte | **PASS** |
| `--dry-run` performs the same full independent verification and leaves no MP0 output | **PASS** |
| Only decoded block 886 changed | **PASS** |
| Other 2,955 decompressed blocks equal the source byte-for-byte | **PASS** |
| Other 2,955 compressed streams equal the source byte-for-byte | **PASS** |
| Other edges in block 886 retain geometry, flags, length, and edge-record bytes | **PASS** |
| Independent raw-file Reader decoded all 1,090,323 edges | **PASS** |
| Independent Reader recovered the requested point and recomputed length | **PASS** |
| Original source hash unchanged after writing and readback | **PASS** |
| Full-file no-op returns a byte-identical original | **PASS** |

Independent verification implementation: `../independent_verify.py`, which imports neither the Writer nor `decoder.py`. Machine-readable records: `writer_run.json` and `independent_reader_result.json`.

## Tests

Command:

```powershell
python -B -m unittest discover -s research/geometry_breakthrough -t research/geometry_breakthrough -p 'test*.py' -v
```

**16 passed, 0 failed.** This includes the corrected signed-secondary fixture test and the new full-container no-op and edit/readback tests. The signed-secondary decoder implementation itself was not changed.

## Restrictions

No original MP0 or CD was written. No SQLite, Manager, Worker, Supervisor, GUI, or scheduler file was changed. This edit does not add a road, synthesize a reverse edge, or infer direction from `XOR 0x3000`. The file is not certified for physical Opel navigation.
