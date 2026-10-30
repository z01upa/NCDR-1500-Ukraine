# Phase 30 — type-0x06 index-tree reconstruction

`075EB730` is a valid BL_ADDR: sector `0x075EB7`, span `0x30`; its header is `07 5E B7 30 00 08 00 00`, so it is a type-`0x08`, compression-0 record. Its first logical bytes are `00 10 17 FC 00 60 00 00` followed by zeros in the inspected prefix.

The changed leaf header is `07 74 9B 20 00 06 00 00`, giving leaf BL_ADDR `07749B20`. A type-`0x09` record at sector `0x76307` contains that exact BL_ADDR at local logical offset `0x44`, alongside sibling leaf addresses `07743F03`, `07744B29`, `07747427`, and `07744209`.

The root-like type-`0x07` record at sector `0x000003` contains `075EB730` at local offset `0x30`. This proves root/type-07 → type-08 and type-09 → type-06 leaf references separately, but no decoded reference from the type-08 block to sector `0x76307` was established. Therefore a complete root→leaf path is not proven.

The type-06 population is 5,433 records in both A and B; 4,624 have compression 0. The single A→B changed record is the leaf `0x7749B`; no parent record changes in the physical A/B comparison. Type-06 role classification beyond the changed leaf is unresolved.

The log value `ad5` (=2773) is not matched to a proven class count. `600000` (`0x000927C0`) and `10000` (`0x2710`) were not tied to a validated field in the inspected root/leaf context. OUTPUT_C has appended type-06 records, but a leaf split and parent update were not proven.
