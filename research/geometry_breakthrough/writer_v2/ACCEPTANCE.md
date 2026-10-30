# Writer v2 acceptance

**Status: Stage 1 topology audit PASS WITH UNRESOLVED FORMAT RULES. Stage 2 edge insertion BLOCKED. No new MP0 was created.**

## Inputs and integrity

| Input | SHA-256 | Read-only check |
|---|---|---|
| Original `EUZ.MP0` | `73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e` | Before/after hashes identical; zero writes |
| `EUZ.RT` | `eb2fc3e0c431d3eb69dd0cefe23463f0bc5c7d51c9eca86692062115a920c456` | All 2,713 compressed streams decoded |
| `EUZ.RL` | `fbe22e41a41a9cf58a629ebda7036ab8492c3ab52d093bbe199c9559509c53b4` | All 4,960 compressed streams decoded |

Both companion files have structurally valid `zip\x01` containers. Their
logical type IDs are 22 (`RT`) and 21 (`RL`); `RT` header count is zero and `RL`
header count is 249,750. Their mapping to MP0 edge routing is **not proven**.

## Verified topology facts

- The independent pass read all **2,956/2,956** MP0 blocks and **1,090,323**
  Section 5 edge records, with **956,071** Section 4 node records.
- Section 5 endpoint indexes: **0 out of range**. For endpoints selecting the
  primary coordinate table, reciprocal edge references have **0 failures** in
  the decoded low-degree range.
- For low nibbles 0–4, **952,280 / 952,791** node records have exact active
  node→edge multisets. The remaining **511** failures match the standalone
  reader and occur at duplicate-coordinate node identities (511/511). Nodes
  must not be merged by coordinate alone.
- Degree 4 has 33,019 rows; 32,892 have exact adjacency lists. For those
  records, the active four u16 words include the fourth edge at +8/+9.
- There are **3,280** records with low nibble >4. The observed low=5/6/7
  groups explain only a subset of incident edges through the four visible
  u16 words; **4,174** primary endpoint memberships are not found in those
  words. Rows with low=8–15 have no primary Section 5 endpoint incidence in
  this data; their meaning is unresolved. The low nibble is degree-consistent
  only in the confirmed groups; overflow-link storage is unresolved. The high
  nibble of byte +0 and byte +1 remain uninterpreted.
- Below degree 4, the following u16 is not safe free space. It is nonzero in
  most records; for the isolated candidate block 886 nodes 412 and 414 it is
  518 and 271 respectively. Both nodes currently have degree 3, their three
  active references match their incident edges, and no local primary edge
  directly joins the pair.
- Sections 7/8/9 pass widths 7/11/13 bytes with no layout errors. Their first
  u16 is nondecreasing within every populated block and always lies within
  that block's edge-ID range. Values that are edge-domain-only occur 177,977,
  15,140, and 5 times respectively. This establishes edge-index-shaped keys,
  not their ownership or rekey semantics.
- In Section 5, only endpoint coordinate-table selectors 0x1000/0x2000 and
  shape-presence bit 0x8000 are used as confirmed semantics here. Road type,
  direction, access, and other attribute meanings remain unknown. XOR 0x3000
  is not treated as reverse-direction evidence.
- The independent pass counted **29,240** secondary-coordinate endpoints.
  These select the secondary table rather than local Section 4 node IDs; their
  cross-block ownership remains unresolved.
- Existing Writer v1 no-op round-trip returned bytes identical to the source.

## Test results

The Writer v2 automatic suite ran **8 tests: 8 PASS, 0 FAIL**. It covers the
full 2,956-block scan, low-degree reciprocal links and the independent
topology reader, degree-four and overflow observations, Section 5 semantic
limits, Sections 7–9 and RT/RL containers, Writer v1 byte-identical no-op,
fail-closed insertion, and source hashes.
The actual command-line preflight for block 886 / nodes 412 and 414 returned
the expected refusal status (process exit 3) before creating any MP0 output.

Evidence files:

- `evidence/connectivity_audit.json` — all-block counts, mismatch examples,
  edge-field histograms, and Sections 7–9 observations.
- `evidence/independent_topology_result.json` — output of the existing
  standalone topology reader, run independently of Writer v1.
- `evidence/routing_file_audit.json` — complete RT/RL container decode and
  hashes.
- `evidence/edge_insertion_preflight.json` and
  `evidence/edge_insertion_refusal.json` — selected node pair and exact
  fail-closed reasons.
- `evidence/writer_v2_tests.log` — real unittest output.
- `evidence/writer_v2_cli_result.json` — actual CLI preflight and its expected
  refusal status.
- `evidence/SHA256SUMS.json` — hashes of the saved evidence artifacts and the
  source MP0 manifest hash.

## Why no edge was written

The selected pair (block 886, nodes 412 and 414) is a valid local experimental
candidate, not an authorization to mutate. Its active degree-3 slots are
known, but each next node word is already occupied by unknown nonzero data.
Section 5 route attributes/defaults are unassigned, Section 4 high-degree
overflow is incomplete, Sections 6–9 contain unresolved edge-index-shaped
dependencies, and the valid RT sidecar's relationship to routing remains
unknown. A new record would therefore require invented or silently discarded
data. `writer_v2.py` refuses before output creation; it does not claim routing
validity or device compatibility.

No original disc, source MP0, SQLite database, or existing GUI/manager module
was changed by this stage.
