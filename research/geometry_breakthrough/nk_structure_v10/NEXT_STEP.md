# Next step

Obtain one of these specific inputs before attempting module extraction:

1. A genuine Windows CE `NK.BIN`/`.bin` positive-control image with known ROMHDR/XIP layout, to validate the B000FF/ROMHDR parser against a real artifact; and
2. Preferably, an **uncompressed or documented LK841 ROM/XIP dump** (or OEM packer/unpacker specification) that includes the address-to-file segment map for this custom `LK-01-05` / `CE00FF` container.

Then validate whether the 48 `CE` records are module descriptors by tracing the `+4` values to mapped bytes and checking the two targets' ranges, headers, and SH4 instructions. Only after that can `+2`, `+8`, `+12`, the variable bytes before `CE`, and the second references be assigned meanings. Until then, extraction is unsafe and no module is emitted.
