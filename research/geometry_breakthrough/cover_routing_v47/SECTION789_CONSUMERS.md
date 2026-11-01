# Section 7/8/9 lookup consumers

## Confirmed wrapper and callee behavior

- `0x01000E2C` calls the shared lookup at `0x01000E50`. It preserves incoming `r4`; after the call it restores state and returns without testing or changing `r0`.
- `0x01000E40` also calls `0x01000E50`; its delay slot sets `r7=1`. It returns without testing or changing `r0`. This wrapper was statically inspected, not executed in the paired test.
- The lookup initializes a match count to zero, searches Section 7 and proceeds to Section 8 when that table is exhausted; the saved evidence also shows a Section 9 advance. A zero count is returned in `r0`.
- The wrapper evidence does not establish whether an upper layer accepts zero, treats either table as required, or routes successfully without auxiliary records. Do not label Section 7 or Section 8 `REQUIRED` or `OPTIONAL` from these results.

## Paired test and bounded negative search

Astra-021 replayed two existing keys under an explicit loader/output model and observed nonzero counts from different table combinations. The test did not supply a real zero-total counterpart, and its modeled output path limits the conclusion. The edge706 verdict remains `UNKNOWN`.

Astra-022 checked the recovered call/literal indexes and aligned relative `BRA`/`BSR` encodings within the target's bounded branch reach. It found no identified upper caller of `0x01000E2C`; one data occurrence was classified as a PDATA entry, not a caller. Indirect/computed dispatch, other modules, and runtime loader changes were outside scope. This is not proof the function is unreachable.

## Existing evidence

- [Astra-021](../consumer_trace_v21/EVIDENCE.md)
- [Astra-022](../consumer_trace_v22/EVIDENCE.md)
- [Astra-022 read-only verifier](../consumer_trace_v22/verify_references.py)
- [Open dependencies](../../../docs/KNOWN_UNKNOWNS.md)
