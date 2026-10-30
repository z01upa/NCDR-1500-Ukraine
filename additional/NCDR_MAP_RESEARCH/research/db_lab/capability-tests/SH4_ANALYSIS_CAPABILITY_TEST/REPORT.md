# SH4 analysis capability test

Status: SUPPORTED

Module: `NAVIMAIN.EXE`

Machine: 0x01a6 · Entry RVA `0x00001E24` · file offset `0x00001224`

Backend: Miasm SH4 instruction decoder 0.1.5

## Entry point disassembly
- RVA `0x00001E24` · file `0x00001224` · `862f` · MOV.L      R8, @-R15
- RVA `0x00001E26` · file `0x00001226` · `962f` · MOV.L      R9, @-R15
- RVA `0x00001E28` · file `0x00001228` · `a62f` · MOV.L      R10, @-R15
- RVA `0x00001E2A` · file `0x0000122A` · `b62f` · MOV.L      R11, @-R15
- RVA `0x00001E2C` · file `0x0000122C` · `224f` · STS.L      PR, @-R15
- RVA `0x00001E2E` · file `0x0000122E` · `4368` · MOV        R4, R8
- RVA `0x00001E30` · file `0x00001230` · `536b` · MOV        R5, R11
- RVA `0x00001E32` · file `0x00001232` · `636a` · MOV        R6, R10
- RVA `0x00001E34` · file `0x00001234` · `7369` · MOV        R7, R9
- RVA `0x00001E36` · file `0x00001236` · `f07f` · ADD        0xFFFFFFF0, R15
- RVA `0x00001E38` · file `0x00001238` · `0ad0` · MOV.L      @(PC & 0xFFFFFFFC,0x2C), R0
- RVA `0x00001E3A` · file `0x0000123A` · `0b40` · JSR.L      @R0
- RVA `0x00001E3C` · file `0x0000123C` · `0900` · NOP
- RVA `0x00001E3E` · file `0x0000123E` · `0ad0` · MOV.L      @(PC & 0xFFFFFFFC,0x2C), R0
- RVA `0x00001E40` · file `0x00001240` · `b365` · MOV        R11, R5
- RVA `0x00001E42` · file `0x00001242` · `a366` · MOV        R10, R6
- RVA `0x00001E44` · file `0x00001244` · `9367` · MOV        R9, R7
- RVA `0x00001E46` · file `0x00001246` · `0b40` · JSR.L      @R0
- RVA `0x00001E48` · file `0x00001248` · `8364` · MOV        R8, R4
- RVA `0x00001E4A` · file `0x0000124A` · `0364` · MOV        R0, R4
- RVA `0x00001E4C` · file `0x0000124C` · `04d0` · MOV.L      @(PC & 0xFFFFFFFC,0x14), R0
- RVA `0x00001E4E` · file `0x0000124E` · `0b40` · JSR.L      @R0
- RVA `0x00001E50` · file `0x00001250` · `0900` · NOP
- RVA `0x00001E52` · file `0x00001252` · `107f` · ADD        0x10, R15
- RVA `0x00001E54` · file `0x00001254` · `264f` · LDS.L      @R15+, PR
- RVA `0x00001E56` · file `0x00001256` · `f66b` · MOV.L      @R15+, R11
- RVA `0x00001E58` · file `0x00001258` · `f66a` · MOV.L      @R15+, R10
- RVA `0x00001E5A` · file `0x0000125A` · `f669` · MOV.L      @R15+, R9
- RVA `0x00001E5C` · file `0x0000125C` · `0b00` · RTS
- RVA `0x00001E5E` · file `0x0000125E` · `f668` · MOV.L      @R15+, R8
- RVA `0x00001E60` · file `0x00001260` · `081d` · MOV.L      R0, @(R13,0x20)
- RVA `0x00001E64` · file `0x00001264` · `d41c` · MOV.L      R13, @(R12,0x10)
- RVA `0x00001E68` · file `0x00001268` · `f813` · MOV.L      R15, @(R3,0x20)
- RVA `0x00001E6C` · file `0x0000126C` · `01d0` · MOV.L      @(PC & 0xFFFFFFFC,0x8), R0
- RVA `0x00001E6E` · file `0x0000126E` · `0260` · MOV.L      @R0, R0
- RVA `0x00001E70` · file `0x00001270` · `2b40` · JMP.L      @R0
- RVA `0x00001E72` · file `0x00001272` · `0900` · NOP
- RVA `0x00001E74` · file `0x00001274` · `a830` · SUB        R10, R0
- RVA `0x00001E78` · file `0x00001278` · `01d0` · MOV.L      @(PC & 0xFFFFFFFC,0x8), R0
- RVA `0x00001E7A` · file `0x0000127A` · `0260` · MOV.L      @R0, R0
- RVA `0x00001E7C` · file `0x0000127C` · `2b40` · JMP.L      @R0
- RVA `0x00001E7E` · file `0x0000127E` · `0900` · NOP
- RVA `0x00001E80` · file `0x00001280` · `a430` · DIV1       R10, R0
- RVA `0x00001E84` · file `0x00001284` · `01d0` · MOV.L      @(PC & 0xFFFFFFFC,0x8), R0
- RVA `0x00001E86` · file `0x00001286` · `0260` · MOV.L      @R0, R0
- RVA `0x00001E88` · file `0x00001288` · `2b40` · JMP.L      @R0
- RVA `0x00001E8A` · file `0x0000128A` · `0900` · NOP
- RVA `0x00001E8C` · file `0x0000128C` · `6c30` · ADD        R6, R0
- RVA `0x00001E90` · file `0x00001290` · `01d0` · MOV.L      @(PC & 0xFFFFFFFC,0x8), R0
- RVA `0x00001E92` · file `0x00001292` · `0260` · MOV.L      @R0, R0
- RVA `0x00001E94` · file `0x00001294` · `2b40` · JMP.L      @R0
- RVA `0x00001E96` · file `0x00001296` · `0900` · NOP
- RVA `0x00001E98` · file `0x00001298` · `7030` · CMPEQ      R7, R0
- RVA `0x00001E9C` · file `0x0000129C` · `01d0` · MOV.L      @(PC & 0xFFFFFFFC,0x8), R0
- RVA `0x00001E9E` · file `0x0000129E` · `0260` · MOV.L      @R0, R0
- RVA `0x00001EA0` · file `0x000012A0` · `2b40` · JMP.L      @R0
- RVA `0x00001EA2` · file `0x000012A2` · `0900` · NOP
- RVA `0x00001EA4` · file `0x000012A4` · `7430` · DIV1       R7, R0

## Imports

Named and ordinal import entries: 39

Ordinal-only entries: 27

## Xrefs

Direct calls: 14

Import-call xrefs: 8

String xrefs: 27

No semantic function names are inferred.

## SQLite concurrency

Read-only transaction active during writer registration: PASS.
