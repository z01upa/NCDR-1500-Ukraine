# Component-call trace

## `NAVIMAIN.EXE`: `MI_CF_RemoteComManager::CreateInstance`

The named import at image VA `0x116E4` is:

```text
?CreateInstance@MI_CF_RemoteComManager@@QAAJABU_GUID@@PAUIUnknown@@K0PAPAX@Z
```

Windows `dbghelp.dll!UnDecorateSymbolName` produced:

```text
public: long __cdecl MI_CF_RemoteComManager::CreateInstance(
  struct _GUID const &, struct IUnknown *, unsigned long,
  struct _GUID const &, void * *)
```

The SH4 instruction and data evidence is in `evidence/candidate_sh4_scan.json` and `evidence/component_call_trace.json`. At the call site:

```text
VA       bytes  instruction
0x116D0  ee54   mov.l @(0x38,r14),r4
0x116D2  35d1   mov.l 0x117a8,r1       ; [0x117a8] = 0x122cc
0x116D4  08e3   mov #8,r3
0x116D6  141f   mov.l r1,@(0x10,r15)   ; stack argument 4
0x116D8  ec33   add r14,r3
0x116DA  351f   mov.l r3,@(0x14,r15)   ; stack argument 5 = r14+8
0x116DC  15e7   mov #0x15,r7
0x116DE  3bd1   mov.l 0x117cc,r1       ; IAT slot 0x13058
0x116E0  36d5   mov.l 0x117bc,r5       ; [0x117bc] = 0x122fc
0x116E2  1261   mov.l @r1,r1
0x116E4  0b41   jsr @r1
0x116E6  00e6   mov #0,r6              ; delay slot
```

`r4` is the RemoteComManager instance returned in `r0` by `GetInstance` at `0x116AE`; the caller stores it to `[r14+0x38]` at `0x116B2` and reloads it at `0x116D0`. The import's member-function signature plus the SH4 register sequence give this explicit argument map:

| Parameter | Observed value | Evidence / limits |
|---|---|---|
| implicit `this` in `r4` | RemoteComManager instance | `GetInstance` return at `0x116AE`, spill/reload at `0x116B2`/`0x116D0` |
| explicit 1, `const GUID&` in `r5` | pointer `0x122FC`; GUID bytes `20 7b 18 e3 d6 ab d3 11 a8 3a 00 10 5a 6b 05 76` = `e3187b20-abd6-11d3-a83a-00105a6b0576` | GUID-shaped candidate; its service/component name is not resolved |
| explicit 2, `IUnknown*` in `r6` | null | Delay-slot `mov #0,r6` |
| explicit 3, `unsigned long` in `r7` | `0x15` | `mov #0x15,r7`; flag meaning unknown |
| explicit 4, `const GUID&` at `[sp+0x10]` | pointer `0x122CC`; GUID bytes `1f 7b 18 e3 d6 ab d3 11 a8 3a 00 10 5a 6b 05 76` = `e3187b1f-abd6-11d3-a83a-00105a6b0576` | GUID-shaped candidate; its interface/service role is not independently resolved |
| explicit 5, `void**` at `[sp+0x14]` | local output slot at `r14+8` | Set up at `0x116D8–0x116DA` |

The function's prologue at `0x113F8` allocates its frame and outgoing-argument area. Register arguments are in `r4–r7`; overflow arguments are explicitly stored at `SP+0x10` and `SP+0x14`. This agrees with SH-4 register passing and Windows CE SH-4 home-space placement. The ST SH-4 ABI specifies `r4–r7` as parameter registers; Microsoft's SH-4 device-development material documents the argument home locations and stack layout ([ST SH-4 ABI](https://www.st.com/resource/en/reference_manual/rm0197-sh4-generic-and-c-specific-application-binary-interface-stmicroelectronics.pdf), [Microsoft Smart Device Development PDF](https://download.microsoft.com/download/1/6/d/16d24ada-5317-4de1-b2b2-890b51813d6e/VS2005_DeviceDev_en-us.pdf)).

The string `L"Navi Registry FAILED"` starts at VA `0x1262C`, but is **not** the value passed in `r5`; the actual first GUID argument is at `0x122FC`. The message's xref to this call was not established. Therefore the call's arguments are ABI-consistent, but the two GUID roles and the `0x15` flag are still unresolved.

## `MMIDIS.EXE`: MTL activation

At VA `0x11168`, `MMIDIS.EXE` calls its named import `mtl.dll!MTLCoCreateInstance`, whose decorated signature has the same five explicit parameter shapes as COM-style instance creation. The caller passes:

- first GUID pointer `0x120BC`: `c19f8c92-cffd-11d3-ad06-0060085eab3c`;
- `IUnknown* = NULL` in `r5`;
- `r6 = 3`;
- second GUID pointer `0x1206C`: `c19f8c91-cffd-11d3-ad06-0060085eab3c`;
- output pointer in the stack slot at `SP+0x10`.

This confirms that MMIDIS activates an MTL component identified by GUID-shaped values. The class/interface name is not recovered, and this call alone does not show map-file access or route computation. The literal `MTL.dll` also appears in NK.BIN's filename cluster at file offset `0x009ED19B`.

## ABI validation and naming limits

`r4–r7` were interpreted as SH-4 argument registers, not guessed from x86 conventions. The parameter list was recovered from the actual decorated import using the Windows demangler; Microsoft's documentation explains that decorated names encode calling convention and parameter types ([Microsoft decorated names](https://learn.microsoft.com/en-us/cpp/build/reference/decorated-names?view=msvc-170)). The raw call-site setup independently matches that parameter count and the CE SH-4 stack argument offsets.

No CLSID/IID-to-service registry mapping was found in the scanned PE set or the bounded NK string checks. Do not rename either GUID pair to a Siemens service or routing component yet.
