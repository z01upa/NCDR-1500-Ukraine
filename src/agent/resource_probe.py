from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
from typing import Any


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def ram_status() -> dict[str, Any]:
    """Read host RAM with the Windows API without depending on CIM/WMI."""
    kernel = getattr(ctypes, "windll", None)
    if kernel is None:
        raise OSError("GlobalMemoryStatusEx is only available on Windows")
    info = _MemoryStatusEx()
    info.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not kernel.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)):
        raise ctypes.WinError()
    return {
        "total_bytes": int(info.ullTotalPhys),
        "available_bytes": int(info.ullAvailPhys),
        "used_bytes": int(info.ullTotalPhys - info.ullAvailPhys),
        "load_percent": int(info.dwMemoryLoad),
    }


def gpu_status() -> dict[str, Any] | None:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return None
    result = subprocess.run(
        [executable, "--query-gpu=name,memory.total,memory.free,memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    line = result.stdout.strip().splitlines()[0]
    name, total, free, used, utilization = [part.strip() for part in line.split(",", 4)]
    return {
        "name": name,
        "memory_total_mib": int(total),
        "memory_free_mib": int(free),
        "memory_used_mib": int(used),
        "utilization_percent": int(utilization),
    }


def resource_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        result["ram"] = ram_status()
    except Exception as exc:  # hardware instrumentation can be unavailable in a restricted runner
        result["ram_error"] = f"{type(exc).__name__}: {exc}"
    try:
        result["gpu"] = gpu_status()
    except Exception as exc:
        result["gpu_error"] = f"{type(exc).__name__}: {exc}"
    return result
