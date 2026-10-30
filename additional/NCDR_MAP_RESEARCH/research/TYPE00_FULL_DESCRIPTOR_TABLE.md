# Type-0x00 full descriptor table

- Table start: raw +0x82. Pair count before first impossible/non-pointer value: 3: 17, 4: 17, 5: 18, 6: 21, 7: 4, 8: 2.
- Values resolving as valid local pointers: 379/458 (82.8%).
- Duplicate/reused targets occur; decreases are retained as descriptors and are not termination.
- Confirmed termination: first impossible/non-pointer value after the variable pointer sequence; success 79/79.
- Root-extent containment and target ranks are recorded per pair; no separate explicit count or sentinel was confirmed.
- Next unresolved structure: decode the first non-pointer pair following each variable descriptor sequence.
