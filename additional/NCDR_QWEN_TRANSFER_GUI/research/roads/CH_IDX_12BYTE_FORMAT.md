# Type-0x0F CH_IDX 12-byte entry

| Offset | Width | Encoding | Confirmed meaning |
|---:|---:|---|---|
| `+0x00` | 3 | uint24 BE | target sector |
| `+0x03` | 1 | uint8 | target physical span |
| `+0x04` | 1 | byte | character/key byte |
| `+0x05` | 1 | uint8 | flags (semantic name unresolved) |
| `+0x06` | 2 | uint16 BE | target-local LIST pointer |
| `+0x08` | 2 | uint16 BE | target-local LIST count |
| `+0x0A` | 2 | uint16 BE | reserved/alignment; zero in the confirmed Moscow entries |

The Moscow traversal starts from type-0x0F sector `0x1B19`, LIST `0x4A10/30`.
Entries targeting type-0x0F recurse using their LIST pointer/count. This yields
189 reachable CH_IDX entries: 17 type-0x0F branches and 172 type-0x0E road-list
links. The known `0031a01f31010f2000b90000` entry selects
`0x31A0:0x0F20/185`.

## Global validation

All 106 type-0x0F records expose an in-bounds header CH_IDX LIST. Parsing those
declared lists produced 431,632 structurally valid type-0x0E links and zero
invalid CH_IDX entries. Deduplicated road identity yielded 33,381 roads and
95,119 owned objects.

The join to the persisted 10,615 Phase-39 reverse-reference rows is 0%. A
direct Moscow check proves the mismatch is in the oracle key: for example,
`0x31A0:0x65BC` is present as a reverse-reference row but is not one of the
413 offsets owned by the confirmed Moscow MORE_INFO arrays. Per the task stop
rule, no grammar change was made. The first 50 cases are recorded in
`ch_idx_failures.csv`.
