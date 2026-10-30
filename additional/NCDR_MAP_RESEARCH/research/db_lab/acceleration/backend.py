"""Optional acceleration discovery behind a small stable interface."""
from __future__ import annotations
from dataclasses import dataclass
import importlib.util
import json
import platform
import subprocess
import time


@dataclass
class BackendInfo:
    name: str
    available: bool
    detail: str
    seconds_per_mb: float | None = None


class Backend:
    def __init__(self):
        self.backends = self.detect()
        self.selected = "CPU"
        self.benchmark()

    @staticmethod
    def detect():
        items = [BackendInfo("CPU", True, f"Python {platform.python_version()}, {platform.machine()}")]
        if importlib.util.find_spec("numpy"):
            items.append(BackendInfo("NumPy", True, "Vectorized CPU arrays"))
        if importlib.util.find_spec("cupy"):
            try:
                import cupy
                items.append(BackendInfo("CUDA", cupy.cuda.runtime.getDeviceCount() > 0, "CuPy CUDA"))
            except Exception as e: items.append(BackendInfo("CUDA", False, str(e)))
        if importlib.util.find_spec("torch"):
            try:
                import torch
                if torch.cuda.is_available(): items.append(BackendInfo("CUDA", True, "PyTorch CUDA"))
                if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                    items.append(BackendInfo("Metal", True, "PyTorch MPS"))
            except Exception as e: items.append(BackendInfo("Torch GPU", False, str(e)))
        if importlib.util.find_spec("pyopencl"):
            try:
                import pyopencl as cl
                if cl.get_platforms(): items.append(BackendInfo("OpenCL", True, "pyopencl device available"))
            except Exception as e: items.append(BackendInfo("OpenCL", False, str(e)))
        return items

    def benchmark(self):
        # Small deterministic XOR workload; backend adapters can replace this when added.
        sample = bytes(range(256)) * 128
        t0 = time.perf_counter()
        for _ in range(12): bytes(x ^ 0x5A for x in sample)
        cpu = (time.perf_counter()-t0) / (len(sample)*12/1_000_000)
        self.backends[0].seconds_per_mb = cpu
        self.selected = "CPU"
        for info in self.backends[1:]:
            if info.available:
                # Detection is reported separately; only implemented CPU execution is eligible.
                info.seconds_per_mb = None
        return self.backends

    def report(self):
        devices=[]
        if platform.system()=="Darwin":
            try:
                raw=subprocess.check_output(["system_profiler","SPDisplaysDataType","-json"],text=True,stderr=subprocess.DEVNULL,timeout=15)
                rows=json.loads(raw).get("SPDisplaysDataType",[])
                for row in rows:
                    if row.get("sppci_device_type")=="spdisplays_gpu" or "gpu" in row.get("_name","").lower():
                        metal=row.get("spdisplays_metal")
                        metal_family=row.get("spdisplays_mtlgpufamilysupport")
                        metal_supported=metal=="spdisplays_supported" or (isinstance(metal_family,str) and metal_family.startswith("spdisplays_metal"))
                        devices.append({"name":row.get("sppci_model") or row.get("_name","Unknown GPU"),"vendor":row.get("spdisplays_vendor","Unknown"),"metal_supported":metal_supported,"metal_family":metal_family,"vram":row.get("spdisplays_vram")})
            except Exception:
                pass
        usable=[b.name for b in self.backends if b.available and b.name in ("CUDA","Metal","OpenCL")]
        return {"selected": self.selected, "benchmark": [vars(b) for b in self.backends],"gpu_devices":devices,"gpu_execution_backends":usable}
