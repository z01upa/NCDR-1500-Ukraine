# Next exact experiment

Identify the component created by the observed
`MI_CF_RemoteComManager::CreateInstance` call at `NAVIMAIN.EXE VA 0x116e4` from
the actual call arguments and Windows CE component/service registration, then
inspect only that server module's imports and direct file-reading callers for
EUZ.MP0/Section 5. The code also calls Coredll ordinals 528 and 530 with
`NaviTrace.dll` and `Initialize` at `0x115f2` and `0x115fc`; the exact DLL was
not found in the original NCDR tree, so resolve those ordinal exports and
runtime module location as a bounded side check. Do not assume the trace DLL
contains routing code.

This is the smallest next target supported by evidence: NAVIMAIN's entrypoint
dispatches to manager setup, its reached code enters the MI_CF remote
communication framework, and it requests a named runtime module/export.

Do not proceed to a broad NK.BIN disassembly unless component registration or
the identified server's load path shows that the implementation resides there.
Keep the Section 4 Astra continuation rule as the data-side control when
searching the identified consumer: look for the low-nibble degree decode and
the continuation-record step, while validating every candidate against block
7's known head/continuation bytes from `astra_core_v5`.
