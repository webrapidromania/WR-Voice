# -*- coding: utf-8 -*-
"""
cuda_runtime.py — WR Voice
Downloads CUDA DLLs from nvidia PyPI wheels on first GPU launch.
CPU-only users never trigger this.
"""

import hashlib
import io
import os
import sys
import threading
import zipfile
from urllib.request import urlopen, Request
from urllib.error import URLError

CUDA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local")),
    "WRVoice",
    "cuda",
)

# DLLs required for CTranslate2 GPU inference
REQUIRED_DLLS = ["cublas64_12.dll", "cublasLt64_12.dll"]

# nvidia-cublas-cu12 wheel on PyPI — contains all required DLLs
_WHEELS = [
    {
        "url": "https://files.pythonhosted.org/packages/84/f7/"
               "985e9bdbe3e0ac9298fcc8cfa51a392862a46a0ffaccbbd56939b62a9c83/"
               "nvidia_cublas_cu12-12.6.4.1-py3-none-win_amd64.whl",
        "name": "nvidia_cublas_cu12-12.6.4.1",
        "size_mb": 414.4,
        "sha256": "9e4fa264f4d8a4eb0cdbd34beadc029f453b3bafae02401e999cf3d5a5af75f8",
        "dlls": ["cublas64_12.dll", "cublasLt64_12.dll", "nvblas64_12.dll"],
    },
]

# Total download size shown to user
TOTAL_DOWNLOAD_MB = sum(w["size_mb"] for w in _WHEELS)

# Set by UI to signal cancellation
_cancel_event = threading.Event()


def _cublas_loadable():
    """Try to actually load cublas DLLs via ctypes.

    This is the real test — get_cuda_device_count() only checks if
    the GPU driver is present, NOT if cublas DLLs are loadable.
    """
    import ctypes as _ct
    for dll in REQUIRED_DLLS:
        try:
            _ct.CDLL(dll)
        except OSError:
            return False
    return True


def cuda_ready():
    """Check if CUDA is available for CTranslate2 GPU inference.

    Tier 0: GPU detected + cublas DLLs actually loadable
    Tier 1: DLLs present in CUDA_DIR (file check)
    """
    # Tier 0: GPU present AND cublas DLLs loadable
    try:
        import ctranslate2
        count = ctranslate2.get_cuda_device_count()
        if count > 0:
            if _cublas_loadable():
                print(f"[WR Voice] CUDA check: tier 0 found"
                      f" — {count} GPU(s) + cublas DLLs loadable")
                return True
            print(f"[WR Voice] CUDA check: tier 0 partial"
                  f" — {count} GPU(s) but cublas DLLs NOT loadable")
        else:
            print("[WR Voice] CUDA check: tier 0"
                  " — no CUDA devices")
    except Exception as e:
        print(f"[WR Voice] CUDA check: tier 0 skipped — {e}")

    # Tier 1: check CUDA_DIR for DLLs
    if all(os.path.exists(os.path.join(CUDA_DIR, dll))
           for dll in REQUIRED_DLLS):
        print(f"[WR Voice] CUDA check: tier 1 found"
              f" — DLLs in {CUDA_DIR}")
        return True
    print(f"[WR Voice] CUDA check: tier 1 not found"
          f" — {CUDA_DIR}")

    return False


def cuda_available():
    """Comprehensive CUDA check — includes cuda_ready() + extra tiers.

    Used by installer. Falls back through PATH-based searches
    if cuda_ready() (tier 0+1) fails.
    """
    # Tiers 0+1 via cuda_ready()
    if cuda_ready():
        return True

    # Tier 2: find python.exe in PATH → derive site-packages
    try:
        for p in os.environ.get("PATH", "").split(os.pathsep):
            p = p.strip()
            if not p:
                continue
            py_exe = os.path.join(p, "python.exe")
            if not os.path.isfile(py_exe):
                continue
            py_root = os.path.dirname(py_exe)
            if py_root.lower().endswith("scripts"):
                py_root = os.path.dirname(py_root)
            cublas_bin = os.path.join(
                py_root, "Lib", "site-packages",
                "nvidia", "cublas", "bin")
            if all(os.path.exists(os.path.join(cublas_bin, dll))
                   for dll in REQUIRED_DLLS):
                print(f"[WR Voice] CUDA check: tier 2 found"
                      f" — {cublas_bin}")
                return True
    except Exception:
        pass

    # Tier 3: %CUDA_PATH%\bin\ and versioned variants
    for key, val in os.environ.items():
        if key.upper().startswith("CUDA_PATH"):
            cuda_bin = os.path.join(val, "bin")
            if all(os.path.exists(os.path.join(cuda_bin, dll))
                   for dll in REQUIRED_DLLS):
                print(f"[WR Voice] CUDA check: tier 3 found"
                      f" — {cuda_bin}")
                return True

    # Tier 4: System32
    sys32 = os.path.join(
        os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32")
    if all(os.path.exists(os.path.join(sys32, dll))
           for dll in REQUIRED_DLLS):
        print(f"[WR Voice] CUDA check: tier 4 found — System32")
        return True

    # Tier 5: all PATH entries
    for p in os.environ.get("PATH", "").split(os.pathsep):
        p = p.strip()
        if p and all(os.path.exists(os.path.join(p, dll))
                     for dll in REQUIRED_DLLS):
            print(f"[WR Voice] CUDA check: tier 5 found — {p}")
            return True

    print("[WR Voice] CUDA check: not found in any tier")
    return False


def cancel_download():
    """Signal the download thread to stop."""
    _cancel_event.set()


def _extract_dlls_from_wheel(wheel_bytes, dll_names):
    """Extract only .dll files from a wheel (which is a zip)."""
    extracted = []
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as zf:
        for entry in zf.namelist():
            basename = entry.rsplit("/", 1)[-1].lower()
            if basename.endswith(".dll") and basename in {d.lower() for d in dll_names}:
                data = zf.read(entry)
                dest = os.path.join(CUDA_DIR, basename)
                with open(dest, "wb") as f:
                    f.write(data)
                extracted.append(basename)
    return extracted


def download_cuda_runtime(progress_callback=None):
    """
    Download nvidia wheels from PyPI, extract DLLs to CUDA_DIR.
    progress_callback(percent: float, message: str) is called for UI updates.
    Returns True on success, raises on failure.
    Checks _cancel_event between chunks — raises RuntimeError("cancelled") if set.
    """
    _cancel_event.clear()
    os.makedirs(CUDA_DIR, exist_ok=True)

    total_bytes = int(TOTAL_DOWNLOAD_MB * 1024 * 1024)
    downloaded_total = 0

    for wheel_info in _WHEELS:
        url = wheel_info["url"]
        pkg_name = wheel_info["name"]
        dll_names = wheel_info["dlls"]

        if _cancel_event.is_set():
            raise RuntimeError("cancelled")

        if progress_callback:
            progress_callback(
                downloaded_total / total_bytes * 100,
                f"Se conecteaza la PyPI...",
            )

        req = Request(url, headers={"User-Agent": "WRVoice/1.0"})
        try:
            resp = urlopen(req, timeout=10)
        except (URLError, OSError) as e:
            raise RuntimeError(f"Nu s-a putut conecta la PyPI: {e}") from e

        # Read with progress — 256KB chunks, check cancel between each
        chunks = []
        chunk_downloaded = 0

        while True:
            if _cancel_event.is_set():
                raise RuntimeError("cancelled")
            try:
                chunk = resp.read(256 * 1024)
            except (URLError, OSError) as e:
                raise RuntimeError(f"Eroare retea la descarcarea {pkg_name}: {e}") from e
            if not chunk:
                break
            chunks.append(chunk)
            chunk_downloaded += len(chunk)
            downloaded_total += len(chunk)
            if progress_callback:
                pct = min(downloaded_total / total_bytes * 100, 99.0)
                mb_done = downloaded_total / (1024 * 1024)
                progress_callback(pct, f"Se descarca... {mb_done:.0f} / {TOTAL_DOWNLOAD_MB:.0f} MB")

        wheel_bytes = b"".join(chunks)

        # Verify SHA256
        expected_hash = wheel_info.get("sha256")
        if expected_hash:
            actual_hash = hashlib.sha256(wheel_bytes).hexdigest()
            if actual_hash != expected_hash:
                raise RuntimeError(
                    f"SHA256 mismatch pentru {pkg_name}: "
                    f"expected {expected_hash[:16]}..., got {actual_hash[:16]}..."
                )

        # Extract DLLs
        if progress_callback:
            progress_callback(99.0, f"Se extrag DLL-urile din {pkg_name}...")

        if _cancel_event.is_set():
            raise RuntimeError("cancelled")

        extracted = _extract_dlls_from_wheel(wheel_bytes, dll_names)
        if not extracted:
            raise RuntimeError(f"Nu s-au gasit DLL-uri in {pkg_name}")

    if progress_callback:
        progress_callback(100.0, "CUDA runtime instalat cu succes!")

    return True


def register_cuda_dir():
    """Register CUDA_DIR so ctranslate2 can find the DLLs."""
    if not os.path.isdir(CUDA_DIR):
        return False
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(CUDA_DIR)
        except OSError:
            pass
    # Also add to PATH for fallback
    current_path = os.environ.get("PATH", "")
    norm = os.path.normcase(os.path.normpath(CUDA_DIR))
    path_parts = current_path.split(os.pathsep) if current_path else []
    if norm not in {os.path.normcase(os.path.normpath(p)) for p in path_parts if p}:
        os.environ["PATH"] = CUDA_DIR + os.pathsep + current_path
    return True
