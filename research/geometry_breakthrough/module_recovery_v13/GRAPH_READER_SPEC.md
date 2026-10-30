# Confirmed graph reader boundary — not a routing Writer specification

All instruction addresses below are CE runtime VAs. Original link VA = runtime VA - 0x02000000 for these two modules. NavigationRem code ROM storage mapping: `storage = 0x8CBF4000 + (runtime - 0x02FD1000)`.

## Buffer dispatch at 0x0304DBE8
Arguments begin with destination/context r4, section-pair header r5, decompressed block base r6. A guarded branch covers database-kind values 2, 4, 6, 8; the meaning of those values is not established.
- 0x0304DCF4..0x0304DD04: read LE16 count at header+0x12, offset at +0x10; store node table pointer at context+0x2C/count+0x30; call 0x0304D848 with block+offset and count.
- 0x0304DD20..0x0304DD30: read LE16 count at header+0x16, offset at +0x14; store edge table pointer at context+0x34/count+0x38; call 0x0304D8A0 with block+offset and count.
These are exactly section pair indexes 4 and 5 in the independently decoded MP0 header. This is a buffer-level match, not a live file-open trace.

## Section 4 — 0x0304D848
0x0304D884 sets memcpy length 10; source/destination advance by 10 at 0x0304D88A/0x0304D88E. The helper at linked 0x00FF87CC (runtime 0x02FF87CC) uses IAT linked 0x010D701C, COREDLL ordinal 1044. The original COREDLL export table resolves 1044 to memcpy. Only that export metadata was inspected.
This copies physical records, including continuations; it does not itself interpret degrees or direction. Existing topology_v6 semantics were not rerun or strengthened by this copy operation.

## Section 5 — 0x0304D8A0
Inputs r4=destination, r5=count, r6=source. Source advances 14 bytes; destination advances 16.

| Disk bytes | RAM bytes | Proven transformation |
|---|---|---|
| +0..3 | +0..3 | LE32 byte assembly |
| +4 | +4 | byte copied unchanged |
| +5 | +5 | byte copied unchanged |
| +6..7 | +6..7 | LE16 byte assembly |
| +8..9 | +8..9 | LE16 byte assembly |
| none | +10..11 | untouched destination padding |
| +10..13 | +12..15 | LE32 byte assembly |

0x0304D904..0x0304D90C copies the two opaque attribute bytes. 0x0304D91C..0x0304D932 copies two endpoint words. 0x0304D94A..0x0304D968 assembles the final word. No restriction, direction or cost meaning is established by this operation.

## First confirmed consumer of opaque bytes
0x0301FCD8 takes edge ID in r5. At 0x0301FD24..0x0301FD2A it indexes context edge table (+0x34) with stride 16.
- 0x0301FD32 loads edge+5; 0x0301FD34 stores cover+0x11.
- 0x0301FD36 loads edge+4; 0x0301FD38 stores cover+0x10.
- Edge first u32 is copied to cover+4 at 0x0301FD2C/0x0301FD30.
Actual p-code replay of this prefix confirms the mapping. Input attributes are not yet tied to downstream branching. The same numeric offsets in other structures cannot be used as evidence of an edge-field consumer.

## Independent data check
Original EUZ.MP0 SHA-256: `73446b326e83b96c4886a4d4406d24135705876616918e9768ae02aa53769e6e`.
Block 0: compressed file offset 20,703,022, compressed size 5,549, decoded size 10,333. Nodes at raw+607, count 128; edges at raw+1887, count 151.
Recovered SH4 executed through a restricted p-code interpreter: exact node bytes and all expanded edge records match an independent layout oracle. Runtime padding was seeded A5 A5 and remained untouched. Eighteen byte+4/+5 perturbations pass through unchanged. No map bytes were altered; perturbations exist only in emulated RAM.

No new routing rule or Writer change is authorized by these results. Positive edge length is checked by 0x0301B428, but its error path and cost consumers are unresolved; it is not a proven routing cost formula.
