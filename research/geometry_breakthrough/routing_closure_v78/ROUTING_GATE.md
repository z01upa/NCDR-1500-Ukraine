# Routing gate and result boundary

## Proven local gate

`Section5 row +4/+5 -> 0106886C -> adjacency row +0x10/+0x11 -> 010AC72C R0 -> 010AC192 R11 -> 010AC200 TST -> 010AC202 BF 010AC1DE`.

At the tested branch, a set bit for the current candidate ordinal takes the branch to candidate advance; the current candidate is skipped. The replay executes the actual builder copy, actual candidate-mask function, and actual gate on three original MP0 rows. It records all read/write addresses and SH4 branch outcomes.

An adjacent route-state selection procedure is also visible: `010AC5AC` writes a bitmap at `+0x38`; `010AC610` writes selected ordinal at `+0x3A`, selected bitmap bit at `+0x3C`, and ordinal into dword `+0x44` bits 12–14. These transformations are confirmed; they do not prove that a Section 5 byte controls final route availability.

## Not proven

- Whether an excluded candidate is later reconsidered through another adjacency or search state.
- Whether any mask bit is a legal one-way, turn-prohibition, or access restriction.
- Whether C1F0 is a map-matching filter, a routing filter, or both in all its callers.
- Which full route-state fields and RT/RL records are mandatory for a new edge.
- The upper-level caller's final route result. Static literal-call links now extend `010AB4D0 -> 01098AE8 -> 010718AC -> 0106D104 -> 0107AC78`, but this chain carries status/control values and the runtime/external caller of `0107AC78` plus final route-choice interpretation are unresolved.

Therefore the result is an actual candidate-list exclusion in one examined search loop, not a complete route decision. A new edge is not yet proven to be routable.
