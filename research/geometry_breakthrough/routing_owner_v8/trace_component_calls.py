"""Reconstruct targeted SH4 COM activation calls without running the firmware."""
from __future__ import annotations

import ctypes
import json
import struct
import uuid
from pathlib import Path
import os

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
NCDR = Path(os.environ.get("NCDR_SOURCE_ROOT", Path(__file__).resolve().parents[3])) / 'SW' / 'LK841' / 'HU_HARDWARE_LOC_0000000001'
NAVIMAIN = NCDR / "HU_MMIDIS_LOC_0130170000" / "WINDOWS" / "NAVIMAIN.EXE"
MMIDIS = NCDR / "HU_MMIDIS_LOC_0130170000" / "WINDOWS" / "MMIDIS.EXE"
SCAN = HERE / "evidence" / "candidate_sh4_scan.json"
DECORATED = "?CreateInstance@MI_CF_RemoteComManager@@QAAJABU_GUID@@PAUIUnknown@@K0PAPAX@Z"


def demangle(name: str) -> str:
    api = ctypes.WinDLL("dbghelp.dll").UnDecorateSymbolName
    api.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32]
    api.restype = ctypes.c_uint32
    buf = ctypes.create_string_buffer(2048)
    count = api(name.encode("ascii"), buf, len(buf), 0)
    if count == 0:
        raise OSError("dbghelp.UnDecorateSymbolName failed")
    return buf.value.decode("ascii", errors="replace")


def pe_image_base(data: bytes) -> tuple[int, int, list[dict]]:
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    opt = pe + 24
    image = struct.unpack_from("<I", data, opt + 28)[0]
    sec_count = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    table = opt + opt_size
    sections = []
    for i in range(sec_count):
        o = table + i * 40
        name = data[o:o + 8].split(b"\0", 1)[0].decode("ascii", errors="replace")
        vsize, va, rawsize, rawptr = struct.unpack_from("<IIII", data, o + 8)
        sections.append({"name": name, "va": va, "raw_size": rawsize,
                         "raw_pointer": rawptr, "virtual_size": vsize})
    return image, pe, sections


def rva_off(va: int, image: int, sections: list[dict]) -> int:
    rva = va - image
    for sec in sections:
        if sec["va"] <= rva < sec["va"] + sec["raw_size"]:
            return sec["raw_pointer"] + rva - sec["va"]
    raise ValueError(f"VA 0x{va:x} is not file-backed")


def word_at_va(data: bytes, va: int, image: int, sections: list[dict]) -> int:
    return struct.unpack_from("<I", data, rva_off(va, image, sections))[0]


def read_utf16z(data: bytes, va: int, image: int, sections: list[dict]) -> str:
    off = rva_off(va, image, sections)
    end = off
    while end + 1 < len(data) and data[end:end + 2] != b"\0\0":
        end += 2
    return data[off:end].decode("utf-16le", errors="replace")


def get_call(scan: dict, filename: str, address: int) -> dict:
    row = next(x for x in scan["candidates"]
               if Path(x["path"]).name.casefold() == filename.casefold())
    return next(x for x in row["import_call_xrefs"] if x["call_va"] == address)


def main() -> None:
    scan = json.loads(SCAN.read_text(encoding="utf-8"))
    nav = NAVIMAIN.read_bytes()
    nav_image, _, nav_sections = pe_image_base(nav)
    nav_call = get_call(scan, "NAVIMAIN.EXE", 0x116E4)
    nav_literals = {
        "outgoing_second_GUID_pointer": word_at_va(nav, 0x117A8, nav_image, nav_sections),
        "r5_literal_pointer": word_at_va(nav, 0x117BC, nav_image, nav_sections),
        "CreateInstance_IAT_pointer": word_at_va(nav, 0x117CC, nav_image, nav_sections),
    }
    nav_guid_bytes = nav[rva_off(nav_literals["outgoing_second_GUID_pointer"], nav_image,
                                  nav_sections):][:16]
    nav_guid = str(uuid.UUID(bytes_le=nav_guid_bytes))
    nav_first_ptr = nav_literals["r5_literal_pointer"]
    nav_first_guid_bytes = nav[rva_off(nav_first_ptr, nav_image, nav_sections):][:16]
    nav_first_guid = str(uuid.UUID(bytes_le=nav_first_guid_bytes))
    nav_registry_message = read_utf16z(nav, 0x1262C, nav_image, nav_sections)

    mmi = MMIDIS.read_bytes()
    mmi_image, _, mmi_sections = pe_image_base(mmi)
    mmi_call = get_call(scan, "MMIDIS.EXE", 0x11168)
    mmi_literals = {
        "arg1_GUID_pointer": word_at_va(mmi, 0x11280, mmi_image, mmi_sections),
        "arg4_GUID_pointer": word_at_va(mmi, 0x11278, mmi_image, mmi_sections),
    }
    mmi_guid1_bytes = mmi[rva_off(mmi_literals["arg1_GUID_pointer"], mmi_image,
                                   mmi_sections):][:16]
    mmi_guid4_bytes = mmi[rva_off(mmi_literals["arg4_GUID_pointer"], mmi_image,
                                   mmi_sections):][:16]
    report = {
        "navimain_createinstance": {
            "call_va": "0x116e4", "symbol": DECORATED,
            "dbghelp_demangled": demangle(DECORATED),
            "import": nav_call["import"],
            "caller_prologue_va": "0x113f8",
            "this_pointer_origin": "GetInstance@MI_CF_RemoteComManager returns in r0 at 0x116ae; stored to [r14+0x38] at 0x116b2; reloaded into r4 at 0x116d0.",
            "arguments_by_signature_and_observed_setup": [
                {"position": "implicit this / r4", "value": "RemoteComManager instance from prior GetInstance", "evidence": "0x116ae,0x116b2,0x116d0"},
                {"position": "explicit 1 / r5", "declared_type": "const GUID&", "pointer": f"0x{nav_first_ptr:08x}", "raw16_hex": nav_first_guid_bytes.hex(), "guid_bytes_le": nav_first_guid, "role": "UNKNOWN; identifier candidate", "evidence": "literal at 0x117bc; loaded into r5 at 0x116e0"},
                {"position": "explicit 2 / r6", "declared_type": "IUnknown*", "value": "NULL", "evidence": "delay slot 0x116e6: mov #0,r6"},
                {"position": "explicit 3 / r7", "declared_type": "unsigned long", "value": "0x15", "evidence": "0x116dc: mov #0x15,r7"},
                {"position": "explicit 4 / [sp+0x10]", "declared_type": "const GUID&", "pointer": f"0x{nav_literals['outgoing_second_GUID_pointer']:08x}", "raw16_hex": nav_guid_bytes.hex(), "guid_bytes_le": nav_guid, "role": "UNKNOWN; GUID-shaped data, component/interface role not established", "evidence": "literal at 0x117a8 stored to [r15+0x10] at 0x116d6"},
                {"position": "explicit 5 / [sp+0x14]", "declared_type": "void**", "value": "r14+8 (local output location)", "evidence": "0x116d8..0x116da"},
            ],
            "abi_check": {
                "r4_to_r7": "Matches SH-4 argument-register convention.",
                "stack_parameters": "Two overflow arguments are stored at SP+0x10 and SP+0x14; this matches Windows CE SH-4's 16-byte register home area and first stack-argument placement.",
                "type_data_check": "Both GUID references point to 16-byte GUID-shaped data. The nearby 'Navi Registry FAILED' message at VA 0x1262c is a separate string, not either argument.",
            },
            "nearby_registry_message_string": {"va": "0x1262c", "text": nav_registry_message,
                                                  "use_xref": "not found in this bounded reachable instruction listing"},
        },
        "mmidis_mtl_activation": {
            "call_va": "0x11168", "symbol": "?MTLCoCreateInstance@@YAJABU_GUID@@PAUIUnknown@@K0PAPAX@Z",
            "import": mmi_call["import"],
            "arguments_observed": {
                "r4_guid1_ptr": f"0x{mmi_literals['arg1_GUID_pointer']:08x}",
                "r4_guid1_raw16_hex": mmi_guid1_bytes.hex(),
                "r4_guid1_guid_bytes_le": str(uuid.UUID(bytes_le=mmi_guid1_bytes)),
                "r5_IUnknown": "NULL (delay slot at 0x1116a)",
                "r6_flags": "3",
                "r7_guid2_ptr": f"0x{mmi_literals['arg4_GUID_pointer']:08x}",
                "r7_guid2_raw16_hex": mmi_guid4_bytes.hex(),
                "r7_guid2_guid_bytes_le": str(uuid.UUID(bytes_le=mmi_guid4_bytes)),
                "stack_sp_plus_0x10": "address of local output slot (sp+0x1c at 0x1115a..0x11160)",
            },
            "interpretation": "A COM-style activation occurs from MMIDIS.EXE through MTL.dll. The GUIDs identify an activated class/interface candidate, but their human-readable service name and routing role are not recovered.",
        },
        "limits": ["Static caller-side evidence only; no runtime execution or COM registry resolution.",
                   "The component identifier behind NAVIMAIN's failed-registry call is unresolved.",
                   "Neither call proves that the activated object reads MP0 or routes."],
    }
    evidence = HERE / "evidence"
    (evidence / "component_call_trace.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"nav_r5_guid": nav_first_guid, "nav_stack_guid": nav_guid,
                      "nav_registry_message": nav_registry_message,
                      "mmi_guid1": report["mmidis_mtl_activation"]["arguments_observed"]["r4_guid1_guid_bytes_le"],
                      "mmi_guid2": report["mmidis_mtl_activation"]["arguments_observed"]["r7_guid2_guid_bytes_le"],
                      "demangled": report["navimain_createinstance"]["dbghelp_demangled"]}, indent=2))


if __name__ == "__main__":
    main()
