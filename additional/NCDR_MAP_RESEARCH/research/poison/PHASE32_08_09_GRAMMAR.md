# Phase 32 — type-0x08 family and 0x09 leaf selection

## Type-0x08 family

The main chain contains 44 type-0x08 records. Around the target, sectors `0x075EB7, 0x075EE7, 0x075F17, 0x075F47, 0x075F77, 0x075FA7, 0x075FD7, 0x076007, 0x076037, 0x076067` are contiguous 0x30-span members; `0x076097` is a 0x21-span tail. Their logical size byte is zero and their common prefix is `00 10 17 FC 00 60`, followed mostly by zeros. This proves a fixed physical family/page sequence, but not whether it is a linked list, array, or overflow chain. The 0x07 root points to the first member `075EB730`; no semantic next-pointer was proven.

## Type-0x09 layout

There are 5,491 type-0x09 records, predominantly one-sector records. Target `0x76307` begins with 44 logical bytes:

`00 14 00 10 00 34 00 06 00 18 00 00 00 34 00 34 00 38 00 3C 00 34 00 34 00 38 00 3C 00 40 00 40 00 44 00 48 00 40 00 40 00 44 00 48`

The strongest count candidate is BE16 at logical `+0x06`: `0x0006`. The six 4-byte BL_ADDRs begin at `+0x2C`: `07743F03`, `07744B29`, `07747427`, `07744209`, `07749B20`, `0774BB2B`. The preceding words look like offset/range boundaries, but their exact semantics are not proven.

## Selection and lookup

The only proven selection operation is: resolve a type-0x09 bucket, read its six 4-byte child BL_ADDRs, validate target headers, then inspect the child leaves. B belongs to `07749B20` because that exact valid BL_ADDR is the fifth child in `0x76307`; no coordinate/range key has been decoded that selects the bucket or fifth child. At least 20 structurally similar nodes were sampled in the inventory, but no uniform key interpretation was established.

## Writer consequence

If a target leaf has space, the leaf payload and its local sorted entries must be rewritten; no parent update is proven. If a leaf splits, the 0x09 child list and upstream type-0x08/0x07 directory structures would potentially need updates, but the split grammar is unresolved.
