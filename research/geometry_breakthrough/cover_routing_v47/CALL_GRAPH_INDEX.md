# Call graph metadata index

`call_graph_metadata.jsonl.gz` is a filtered projection of the recovered static call records. It is not the original `reachable.jsonl.gz` output.

## Coverage

| Module | Function rows | Call edges | Direct resolved | Resolved indirect in source export | Unresolved indirect |
|---|---:|---:|---:|---:|---:|
| `NavigationRem.dll` | 4,054 | 22,168 | 3,034 | 0 | 19,134 |
| `nmicore_ce.dll` | 530 | 5,156 | 154 | 0 | 5,002 |
| **Total** | **4,584** | **27,324** | **3,188** | **0** | **24,136** |

The scanner did not resolve any indirect targets in this export. A separate bounded literal-pool scan resolved 11 call sites to `0x0308C1F0`; those are documented in [consumer call graph](CONSUMER_CALL_GRAPH.md), but are not added to this scanner-derived export. The export does not assert that indirect calls are unreachable.

## JSONL schema

Each line contains only these allowlisted fields:

- `module`
- `source_function_va`, `source_function_end_va`
- `callsite_va`
- `call_kind` (`direct` or `indirect`)
- `resolution` (`static_target` or `unresolved_indirect`)
- `target_va` (hex string for direct calls, otherwise null)
- `target_register` (register name for unresolved indirect calls)

The export contains no instruction bodies, bytes, literal values, buffers, source paths, or raw `reachable` records. Addresses are link-time metadata. Regenerate only from locally held analysis files and preserve this field allowlist.
