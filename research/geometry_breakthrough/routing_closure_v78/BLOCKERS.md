# Remaining blockers

1. **Live route-state provenance.** The selector (`state+0x38`), predecessor slot (`+0x3A`), candidate count, and candidate list are controlled fixtures, not captured values from an actual route request. Capture one request entering `010AB4D0` / `010AC04C` to verify the exercised path and actual order.
2. **Candidate choice above the local gate.** Static callers now show `010AB4D0 -> 01098AE8 -> 010718AC -> 0106D104 -> 0107AC78`, and the intermediate R0 tests are decoded. The values are handled as local status/control fields; the runtime/external caller of `0107AC78` and the final route-choice/result consumer remain unresolved.
3. **C1F0 pointer/dataflow.** Need one live call chain from the `0101FCD8` output pointer to a C1F0 caller's R4, and its returned R0 through to any routing-state transition. Static direct xrefs are distinct from AC04C.
4. **Cost and auxiliary records.** `010AC610` invokes `01016684` and `00FF8910`; those return values affect candidate selection. The `.58`-stride arrays are mutated, but their semantic sources and Section6–9/RT/RL membership rules are not known.
5. **Route interpretation.** Local set-bit behavior is skip-current-candidate only. Need a differential full route request on an independent route fixture or device/runtime capture before asserting final road/turn availability.

Highest-value next experiment: resolve the runtime caller of `0107AC78`, then instrument one real route request from `010AB4D0` through `010AC04C` and capture pointed route-state memory, return values and final consumer; replay only one matching Section5 mask bit against that captured state.
