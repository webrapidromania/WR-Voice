# -*- coding: utf-8 -*-
"""
gpu_detect.py — WR Voice
Detectează GPU-ul, VRAM-ul și recomandă modelul Whisper optim.
Suportă: NVIDIA (CUDA), AMD/Intel (informational) + CPU fallback.
"""

import ctypes
import subprocess

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

# Modele disponibile în ordine de la mic la mare
MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]

MODEL_INFO = {
    "tiny":     {"vram_gb": 1,  "speed": "instant", "quality": "ok",          "label": "Tiny — rapid, ok"},
    "base":     {"vram_gb": 2,  "speed": "rapid",   "quality": "bun",         "label": "Base — rapid, bun"},
    "small":    {"vram_gb": 3,  "speed": "bun",     "quality": "bun",         "label": "Small — bun"},
    "medium":   {"vram_gb": 5,  "speed": "mediu",   "quality": "foarte bun",  "label": "Medium — echilibrat"},
    "large-v2": {"vram_gb": 8,  "speed": "lent",    "quality": "excelent",    "label": "Large v2 — excelent"},
    "large-v3": {"vram_gb": 10, "speed": "lent",    "quality": "excelent++",  "label": "Large v3 — cel mai bun"},
}


def get_system_ram_gb():
    """Returnează RAM-ul total al sistemului în GB."""
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
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
        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
        return round(mem.ullTotalPhys / (1024 ** 3), 1)
    except Exception:
        return 0


def get_non_nvidia_gpus():
    """Detectează GPU-uri AMD/Intel via WMI (informational)."""
    gpus = []
    try:
        r = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "Name", "/format:list"],
            capture_output=True, text=True, timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("Name="):
                    name = line[5:].strip()
                    lower = name.lower()
                    if "nvidia" not in lower and name:
                        if "amd" in lower or "radeon" in lower or "intel" in lower:
                            gpus.append(name)
    except Exception:
        pass
    return gpus


def get_gpu_info():
    """
    Returnează dict cu info GPU NVIDIA sau None.
    Fallback: nvidia-smi → pynvml → None.
    """
    # Try nvidia-smi first
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                return {
                    "name": parts[0],
                    "vram_gb": round(float(parts[1]) / 1024, 1),
                    "driver": parts[2],
                }
    except Exception:
        pass

    # Fallback: pynvml (lightweight ~100KB, no torch dependency)
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode("utf-8")
        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        driver = pynvml.nvmlSystemGetDriverVersion()
        if isinstance(driver, bytes):
            driver = driver.decode("utf-8")
        pynvml.nvmlShutdown()
        return {
            "name": name,
            "vram_gb": round(mem_info.total / 1024 ** 3, 1),
            "driver": f"{driver} (pynvml)",
        }
    except Exception:
        pass

    return None


def recommend_model(vram_gb=None, ram_gb=None):
    """
    Recomandă modelul optim bazat pe VRAM (GPU) sau RAM (CPU).
    Returnează (model_name, reason_string)
    """
    if vram_gb is None:
        gpu = get_gpu_info()
        vram_gb = gpu["vram_gb"] if gpu else 0

    if vram_gb > 0:
        if vram_gb < 3:
            return "tiny", f"{vram_gb}GB VRAM — tiny e singurul care încape"
        elif vram_gb < 4:
            return "base", f"{vram_gb}GB VRAM — base recomandat"
        elif vram_gb < 6:
            return "small", f"{vram_gb}GB VRAM — small recomandat"
        elif vram_gb < 9:
            return "medium", f"{vram_gb}GB VRAM — medium recomandat ★"
        elif vram_gb < 12:
            return "large-v2", f"{vram_gb}GB VRAM — large-v2 recomandat"
        else:
            return "large-v3", f"{vram_gb}GB VRAM — large-v3 recomandat ★★"
    else:
        if ram_gb is None:
            ram_gb = get_system_ram_gb()
        if ram_gb >= 16:
            return "small", f"CPU ({ram_gb}GB RAM) — small recomandat (viteza + acuratete)"
        elif ram_gb >= 8:
            return "base", f"CPU ({ram_gb}GB RAM) — base recomandat"
        else:
            return "tiny", f"CPU ({ram_gb}GB RAM) — tiny recomandat"


def get_device_info():
    """
    Returnează dict complet cu tot ce trebuie știut pentru setup.
    """
    gpu = get_gpu_info()
    non_nvidia = get_non_nvidia_gpus()
    ram_gb = get_system_ram_gb()
    recommended, reason = recommend_model(
        gpu["vram_gb"] if gpu else 0,
        ram_gb=ram_gb,
    )

    return {
        "gpu": gpu,
        "non_nvidia_gpus": non_nvidia,
        "has_cuda": gpu is not None,
        "ram_gb": ram_gb,
        "recommended_model": recommended,
        "recommendation_reason": reason,
        "device": "cuda" if gpu else "cpu",
        "compute_type": "float16" if gpu else "int8",
    }


if __name__ == "__main__":
    info = get_device_info()
    print("\n=== WR Voice — Detectare Hardware ===")
    if info["gpu"]:
        g = info["gpu"]
        print(f"GPU:      {g['name']}")
        print(f"VRAM:     {g['vram_gb']} GB")
        print(f"Driver:   {g['driver']}")
    else:
        print("GPU:      Nu s-a detectat GPU NVIDIA")
        if info["non_nvidia_gpus"]:
            for name in info["non_nvidia_gpus"]:
                print(f"          Detectat: {name} (fara CUDA)")
        print(f"RAM:      {info['ram_gb']} GB")
        print("          (va rula pe CPU — functional dar mai lent)")
    print(f"\nModel recomandat: {info['recommended_model']}")
    print(f"Motiv: {info['recommendation_reason']}")
    print("=====================================\n")
