# NCDR-ASTRA-MODULE-RECOVERY-013 — 2026-10-29

Priority 1: VERIFIED OFFLINE — executable sections of both DLLs recovered and checked against the decoded image/packet sources. All five sections per module recovered, including four compressed data sections in total. ROMHDR/TOC 0x8D2F66CC is structurally coherent with the two 100-byte e32 headers and 24-byte o32 records. 154 TOC entries are retained in the previous stage; no broad module-code scan performed.

| Module | Executable bytes | ROM storage VA | Runtime code VA | Complete PDATA roots | Reachable instruction observations |
|---|---:|---|---|---:|---:|
| NavigationRem.dll | 929,724 | 0x8CBF4000 | 0x02FD1000 | 4054 | 390,457 |
| nmicore_ce.dll | 117,668 | 0x8CD0D000 | 0x02F91000 | 530 | 43,110 |

Zero decode failures and zero direct branch targets outside the respective executable section. 4 NavigationRem exports, 5 nmicore exports, and 9 import descriptors each; names/ordinals and bound addresses are in module.json. Counts exclude the final incomplete PDATA record in each module.

Priority 2: VERIFIED OFFLINE — NavigationRem contains the matching Section 4/5 buffer readers. Dispatch at 0x0304DBE8 selects pair 4 at header +0x10/+0x12 and pair 5 at +0x14/+0x16; calls 0x0304D848 and 0x0304D8A0. Replay of recovered machine instructions through pypcode on original EUZ.MP0 block 0 exactly reproduced 128 ten-byte nodes and 151 fourteen-byte edges expanded to sixteen bytes. See GRAPH_READER_SPEC.md and routing/reader_verification.json. A literal EUZ.MP0 pathname/open-file chain was not found or claimed.

Priority 3: NOT VERIFIED — no defensible direction/access/cost rule yet. Edge bytes +4/+5 remain opaque. They are preserved by the unpacker and forwarded by 0x0301FCD8 to cover structure +0x10/+0x11. The route-expansion candidate 0x030AB4D0 calls 0x030AC04C; source-path references are supporting evidence, not a proven field connection. Neither topology nor offset similarity alone proves a routing rule.

Exact remaining gap: connect the cover structure bytes +0x10/+0x11 to a concrete branch/cost operation in the successor-selection call chain. Other byte+4/+5 loads refer to unrelated structures; routing/attribute_load_candidates.json is an unverified candidate list, not conclusions.

ONE NEXT STEP: trace the produced cover structure from 0x0301FCD8 into successor selection under 0x030AC04C, then replay the identified predicate on real edges while changing one +4/+5 bit at a time. Only after the caller/context and endpoint orientation are proven may that predicate become a Writer rule. Writer remains unchanged and is not yet safe for a routable Ukraine map.

NOT VERIFIED: hardware/Windows runtime, complete callable PE reconstruction, all indirect control flow, original file-open chain, route calculation, dependent access/direction/turn indexes, and production map generation.
