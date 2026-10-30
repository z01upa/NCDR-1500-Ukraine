# Acceptance — NCDR-SH4-ROUTING-007

## Result

**Section 5 routing semantics and Section 6–9 / RT / RL consumers were not
located in the statically reached code of `NAVIMAIN.EXE`.** No field meaning is
claimed. The task's required positive routing-field result remains unmet; this
is a tested, address-bounded negative result with a concrete next target.

## Verified scan evidence

- Decoder: `pypcode 4.0.1`, `SuperH4:LE:32:default`.
- Control words passed: `09 00 → nop`, `0b 00 → rts`, `0b 40 → jsr @r0`.
- Existing PE reader still reports SH4. Entry RVA `0x1e24`, preferred VA
  `0x11e24`, file offset `0x1224`.
- Scanned `.text` virtual interval: VA `0x11000–0x11ea8` (exclusive end),
  file offset `0x400`, virtual size 3,752 bytes.
- Followed direct control flow from 45 sorted `.pdata` first-word roots:
  1,339 instruction observations including per-root duplicates, zero decode
  failures, four direct backward branches. Indirect jump-table targets were
  not followed.
- The bounded instruction inventory contains no direct `#0xA` / `#0xE`
  immediate. This only tests those explicit stride markers; it cannot rule out
  computed strides, helpers, hidden indirect targets, or code in another module.
- Entry `0x11e24` loads and calls local routines `0x11cd4`, `0x113f8`, and
  `0x11d08` (literal values at `0x11e64`, `0x11e68`, `0x11e60`).
- At `0x11398`, the reachable code calls the imported
  `commgr.dll!?GetProcessName@MI_CF_ObjectDescription@@QBAPBGXZ`. In routine
  `0x113f8`, calls resolve to `MI_CF_RemoteComManager::GetInstance` at
  `0x116ae`, `MI_CF_CommunicationBroker::GetInstance` at `0x116c0`,
  `RegisterStatusHandler` at `0x116cc`, `MI_CF_RemoteComManager::CreateInstance`
  at `0x116e4`, and `ReleaseInstance` at `0x118a8`. Machine instructions and
  literal/IAT cross-references are in `evidence/bounded_disassembly.txt` and
  `evidence/sh4_scan.json`.
- Entry-point excerpt (VA / bytes / instruction):

  ```text
  0x11e38  0ad0  mov.l 0x11e64,r0   ; literal [0x11e64] = 0x11cd4
  0x11e3a  0b40  jsr @r0
  0x11e3e  0ad0  mov.l 0x11e68,r0   ; literal [0x11e68] = 0x113f8
  0x11e46  0b40  jsr @r0           ; delay: 0x11e48 mov r8,r4
  0x11e4c  04d0  mov.l 0x11e60,r0   ; literal [0x11e60] = 0x11d08
  0x11e4e  0b40  jsr @r0
  ```

  Recovered control-flow pseudocode: `sub_11cd4(r4,r5,r6,r7); r0 =
  sub_113f8(r8,r11,r10,r9); sub_11d08(r0);`. This identifies the entry's
  dispatch structure, not the semantic names of those routines.
- A second, newly confirmed code mechanism is dynamic module/export dispatch
  in routine `0x113f8`: at `0x115f0`, `r4` receives the UTF-16 string
  `NaviTrace.dll`; `0x115f2` calls `coredll.dll` ordinal 528 through its import
  thunk. At `0x115f6`, `r5` receives `Initialize`; `0x115f8` moves the prior
  return value into `r4`; `0x115fc` calls ordinal 530; and `0x11602` calls the
  returned pointer. Pseudocode for the proven data flow (ordinal names remain
  unresolved): `h = ord528(L"NaviTrace.dll"); p = ord530(h, L"Initialize"); p();`.
  The literal strings and call-site/IAT links are saved in the JSON evidence.
  An exact-name search did not find `NaviTrace.dll` under the original NCDR
  tree, so its runtime source/module has not been inspected.
- Across the bounded scan, 107 indirect call sites were linked through the
  image's import thunks to their PE import slots. The six named MI_CF calls and
  the two `NaviTrace.dll` loader/export call sites are separately retained;
  unresolved ordinal names are left as ordinals.
- Astra's data-side control example remains block 7: physical record 55 is
  `250cfbc137006c012e00` (degree 5; refs 55, 364, 46), and following record 56
  is `310038002f003a003700` (continuation refs 49, 56). Section 5 independently
  gives incidences 46, 49, 55, 56, 364. This verifies the data-side search
  template only; there is no corresponding executable MP0-reader procedure
  established here.
- Existing xref evidence reports no ASCII/UTF-16 strings for MP0, EUZ.MP0,
  node, edge, route, graph, or map. The imported Coredll/MFC ordinals remain
  unresolved. No common packer marker was found; custom/runtime unpacking is
  not excluded.
- Original `NAVIMAIN.EXE` SHA-256 before and after: 
  `8bbeb2a919a4b5e470dd1eaaf47dd029dd2ccf12586b1a4ebb0ea9729087fb07`.
- Read-only input hashes for xref_v4 and Astra control evidence are recorded in
  `evidence/sh4_scan.json`.

## Interpretation and limits

The located routines use MI_CF communication-manager interfaces and perform
dynamic module/export dispatch; neither finding identifies a Section 5 field
as a direction, access, or routing flag.
The scan did not identify a Section 4/5 reader or a Section 6–9 / RT / RL
consumer. No MP0 sample was modified or used to infer executable semantics.
No statement is made about `NK.BIN` or the implementation inside dynamically
loaded server modules.

The scan and its bounded result are reproducible with the tests in `tests/`;
**8/8 tests passed** (log: `evidence/tests.log`). The detailed JSON records
exact addresses and decode limits. This stage is **not acceptance of a
route-attribute decoder**.
