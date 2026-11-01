# UNKNOWN BLOCKERS

- Full route acceptance and the domain meaning of the two selected attribute bits: not established by this local consumer. It proves bit-test → caller return only.
- `0x02FFBB00` has two callsites in `0x03060FA0`; their downstream effects beyond the inspected function remain untraced.
- The 76 reachable indirect call sites have nearest textual r4/r5 definitions in `CALLERS.md`; only the `0x0306F484` path has complete output-to-consumer evidence here. Computed function pointers without a matching literal and caller paths through other modules/runtime tables may be unresolved.
- `context+0x3C` and `context+0x40` callback implementations are indirect; their consumption of the separate `0x0301FCD8` output fields is UNKNOWN.
- `0x02FD676C` candidate's `r9+4` object provenance is UNKNOWN and not shown aliased to either producer buffer.
- Replayer models lock/unlock as no-op, block loader as prepared-block return, length helper `0x0301B428` as 100 and division helper `0x02FF8910` as 1. Those stubs can affect geometry/other output fields; they do not synthesize the tested attribute bytes or consumer result. Pypcode execution here is not a CE/OS emulator.
- No hardware or physical NCDR 1500 test. No MP0, Writer, or original binary was modified.
