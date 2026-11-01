# Evidence withheld from this publication

The following inputs and high-detail artifacts remain local. They were not uploaded because distribution rights are unconfirmed, they contain original map/firmware content, or they expose raw instruction/data traces.

| Material | Publication status | Reason |
|---|---|---|
| Original `EUZ.MP0` | Withheld | Original map image; distribution rights not confirmed |
| Original `NK.BIN`, `NAVIMAIN.EXE` | Withheld | Firmware/executable originals; distribution rights not confirmed |
| `NavigationRem.dll` / `nmicore_ce.dll` section images and recovered `.bin` data | Withheld | Binary-derived code/data; raw images are outside this evidence packet |
| Raw `reachable.jsonl.gz` files | Withheld | Contain instruction records and encoded bytes; replaced by a strict call-edge metadata projection |
| Full `DIFFERENTIAL_REPLAY.json` | Withheld | Contains instruction traces, registers, buffers, and source-derived record details; replaced by aggregate results |
| Research `.venv` and generated temporary outputs | Withheld | Environment/cache or run-specific artifacts; not required for the published evidence |

See the repository's [deferred materials register](../../../docs/DEFERRED_MATERIALS.md) for existing source inventory and publication rationale. The metadata-only call graph and short decoded function excerpt contain no encoded machine bytes. No original binary or firmware file is included in this PR.
