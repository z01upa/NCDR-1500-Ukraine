# BINARY_FINDINGS — NCDR-ASTRA-CORE-005
Date: 2026-10-29

## Pass A conclusion
No genuine MP0-reading procedure was located. No function is claimed on the basis of constants10/14, strings, or incidental references. Existing xref_v4 and topology_v3 scope were read instead of repeating their broad inventories. Fresh exact-source hashes and a small entry/header capture are in evidence/pass_a_binary.json.

NAVIMAIN.EXE: 9798bytes, PE32 machine0x01a6 (SH4), preferred image base0x10000, entry RVA0x1e24 / preferred VA0x11e24 / file offset0x1224. This is an entry ADDRESS, not an identified map-reading function. PE sections and framework/COM imports support a startup-client hypothesis. Ordinal imports remain unresolved. Entry raw bytes are preserved; no invented disassembly or pseudocode is supplied.
SHA256:8bbeb2a919a4b5e470dd1eaaf47dd029dd2ccf12586b1a4ebb0ea9729087fb07.

NK.BIN:11021915bytes, SHA256 d5a626f03cd1ef945d699b17332d57acf8f7c6fd7bbe765fbbcc771e14d90847. Wrapped CE00FF marker at physical0x400, first CE record at0x410. It is not a directly mapped PE. The earlier zero-valid-embedded-PE result does not prove absence of navigation modules. SH4 is established for NAVIMAIN, not independently for every opaque NK payload. ROM/address mapping, codec and module extraction remain unresolved; file offsets cannot be treated as executable virtual addresses.

No analyzeHeadless/ghidra/r2/radare2/llvm-objdump/objdump/java found on PATH; limited directory check also found no Ghidra installation. This is an environment search result, not proof that no copy exists anywhere on disk. No full disassembly was attempted, following the requested budget gate. No Section4/5 or Sections6–9/RT/RL executable consumer is identified.

## Pass A -> Pass B pivot
The first20 MP0 blocks were used to formulate one structural rule: a real degree5..7 head consumes two consecutive Section4 physical records. Its links start at+4 and continue across the next record. The next record's first byte is edge data, not another degree. The rule and exclusion policy were saved to evidence/pass_a_frozen_rule.json BEFORE control evaluation.

Evidence example, original block7:
- head physical ID55: `250cfbc137006c012e00`
- next physical record56: `310038002f003a003700`
- head degree5, inline +4/+6/+8 ->55,364,46
- continuation first two u16 ->49,56
- independently derived Section5 primary-endpoint incidences of node55 ->46,49,55,56,364
- node56 has no primary endpoint incidences. Its apparent degree1 was a false interpretation of edge ID49's low nibble.

This is a NEW verified data mechanism, not a discovered machine-code procedure. Detailed specification, scope and insertion restrictions are in NODE_GRAPH_SPEC.md.
