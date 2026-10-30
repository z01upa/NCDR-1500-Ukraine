# Next step

The immediate blocker is the **unresolved Siemens `LK-01-05` outer image layout**: the `CE00FF` marker at `0x400` does not yield a standard section table, while the only `ECEC` pointer does not resolve to a ROMHDR+TOC under the standard address mappings.

Next experiment:

1. Obtain a second, independently sourced NK/XIP dump from the same Siemens software version, ideally a bootloader-produced flat image, or documentation for the `LK-01-05` container.
2. Compare the outer header, `CE00FF` area, ECEC context, and module-name cluster to identify the wrapper's section/relocation map. Do not infer record layouts from the marker bytes alone.
3. Require a candidate map to resolve a coherent ROMHDR and TOC: module/file counts fit the image, names point to readable strings, `e32`/`o32` addresses map inside valid region ranges, and the known module-name cluster is explained by those TOC rows.
4. Only then reconstruct the two target modules, verify SH4 architecture from their actual headers, and perform bounded disassembly for file APIs and MP0/RT/RL/topology references.

Until step 3 succeeds, guessing module data ranges around the filename strings is unsafe and cannot produce an independently validated executable.
