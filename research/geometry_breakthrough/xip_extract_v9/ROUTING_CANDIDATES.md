# Routing candidate status

## Candidate names

`NavigationRem.dll` and `nmicore_ce.dll` occur as literal strings in the NK image at offsets `0x009FA304` and `0x009FB1C8`. Their names make them search targets only; their roles are **not established**.

## Code analysis status

No target bytes were extracted, so this stage could not inspect:

- SH4 PE/ROM module headers, code or imports/exports;
- file-open APIs or references to `EUZ.MP0`, `.RT`, or `.RL`;
- Section 4 node or Section 5 edge handling;
- the `topology_v6` continuation-record control pattern;
- links to the GUIDs or MI_CF components recorded by `routing_owner_v8`.

The existing `routing_owner_v8` findings about NAVIMAIN/MMIDIS startup and component calls remain separate evidence. They do not prove that either NK string is a route engine or that its bytes are available at the string's surrounding address.

## Status

There is no validated routing-owner module candidate from NK.BIN yet. No disassembly was performed on guessed ranges, and no routing semantics are claimed.
