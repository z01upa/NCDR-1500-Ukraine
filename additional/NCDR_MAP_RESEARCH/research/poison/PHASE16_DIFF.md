# Phase 16 — POISoN writer differential analysis

## Inputs

All four DB_0 files are 512-byte-sector databases. The validated main chain starts at sector 2 and reaches sector `0x78696`. ORIGINAL, A, and B are 252,521,472 bytes; C is 252,522,496 bytes. The exact file hashes are in `phase16_files.csv`.

## Inventory

The main-chain record count is 54,010 for ORIGINAL/A/B and 54,012 for C. The block-type set is unchanged. Type counts are unchanged between ORIGINAL/A/B; C has +1 type `0x06`, +1 type `0x08`, and +1 type `0x09`. Compression-code counts are unchanged in A and B; C has +2 compression `0x00` records. No new compression code appears.

## Differential results

ORIGINAL→A changes 697 physical records, all type `0x06`, with identical sector positions, spans, types, compression codes, and logical-size fields. This is a no-edit save rewrite of the type-0x06 family, not a whole-DB rebuild. The untouched families remain byte-identical.

A→B changes one in-place type-0x06 record: sector `0x7749B`, span `0x20`, compression `0x00`, advertised logical size `0`. Its header remains `07 74 9b 20 00 06 00 00`; its payload is rewritten. No block is inserted, deleted, or relocated in the validated chain.

A→C and B→C show the two-POI output's family-level rewrite: type `0x06`, type `0x08`, and type `0x09` records differ; C adds two chain records and 1,024 bytes. The stable physical-chain endpoint and unchanged earlier headers show append/allocation within existing DB space plus two extra records, rather than a global rebuild. The exact changed-record and range inventory is summarized in `phase16_blocks.csv`.

## References and compression

The comparison does not establish a BL_ADDR repair wave: the one-POI delta changes the type-0x06 index block only, and no validated relocation of existing target blocks was observed. Unchanged records outside rewritten families remain byte-identical. Newly allocated C records use compression `0x00`; no new POI record with compression `0x02` was observed.

## Coordinate tracing limitation

Using confirmed MULCOORD and BE uint32 floor/ceil/round variants, neither requested coordinate pair occurs verbatim in raw DB_0 or in the decompressed payloads of compression-0x02 records. Therefore this phase cannot honestly assign either point to an exact type/sector/logical offset. The negative search is recorded in `phase16_poi_changes.csv`; no block identity is inferred from a false match.

## Confirmed writer model

POISoN performs family-specific indexing. A no-edit save regenerates type-0x06 records in place. Adding one point selects/re-writes one type-0x06 index record. Adding the second point crosses an allocation/family boundary and causes type-0x08 and type-0x09 changes plus two new records, while preserving the rest of the database. The exact POI payload grammar and downstream reference fields remain unresolved.
