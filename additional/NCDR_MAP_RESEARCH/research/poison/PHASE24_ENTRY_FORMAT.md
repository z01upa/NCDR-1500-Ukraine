# Phase 24 — 28-byte sorted POI entry

The six-byte payload begins at entry offset `+0x00`; entries are 28 bytes wide and adjacent at `0x1C` intervals. B neighborhood: previous `261157920024...3B875217...`, test `26425A3D001C...C6F22115F0`, next `266257890024...3B875218...C713240050`. L2/XC neighborhood: previous `266257890025...3B875219...`, test `26995A3D001C...C713240340` (XC uses `27475A3D001C`), successor `292F4942002F...3B8719CE...C713240A20`.

`+0x00..+0x05` are coordinate-related payload bytes. `+0x06..+0x09` are zero in the inserted entry but are not proven flags. In neighboring entries, `+0x0A..+0x0D` contains a recurring `3B87` prefix and changing entry/rank-like data; `+0x18..+0x1B` contains a changing pointer/index-like tail. Exact semantics remain unresolved.

Verified payload bit changes are axis-local: longitude-only changes affect bytes 0–2; latitude-only changes affect bytes 3–5. This supports axis-local payloads but does not prove independent absolute X/Y fields. Direct byte-swizzled X24/Y24 does not fit the XCARRY Q delta. No mixed-radix, shared-bit, Morton, or predecessor-delta mapping is confirmed.

The table is ordered by a longitude-related sort key: unchanged-longitude controls retain rank 2; L2/XCARRY move to rank 3. Whether this is displayed longitude, Qlon, or a transformed key is unresolved. Twenty-neighbor decode validation cannot be completed because the neighboring POISoN-displayed coordinates are not recorded. Maximum error is therefore not established.
