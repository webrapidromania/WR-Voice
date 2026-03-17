# -*- coding: utf-8 -*-
"""WR Voice Setup — pywebview installer with HTML/CSS/JS UI."""

import base64
import ctypes
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import zipfile
from urllib.request import urlopen, Request
from urllib.error import URLError

import webview

VERSION = "1.0 BETA"
APP_EXE = "WR Voice.exe"
UNINSTALL_EXE = "Uninstall.exe"
CREATE_NO_WINDOW = 0x08000000

BASE_DIR = getattr(
    sys, "_MEIPASS",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

if getattr(sys, "frozen", False):
    HTML_PATH = os.path.join(sys._MEIPASS, "installer.html")
else:
    HTML_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "installer.html")

LOGO_PATH = os.path.join(BASE_DIR, "Webrapid-logo-W.png")
ICON_PATH = os.path.join(BASE_DIR, "assets", "logo.ico")
DEFAULT_INSTALL_DIR = os.path.join(
    os.path.expanduser("~"), "Desktop", "WR Voice")

# ── CUDA constants ────────────────────────────────────
CUDA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA",
                   os.path.join(os.path.expanduser("~"),
                                "AppData", "Local")),
    "WRVoice", "cuda",
)
REQUIRED_CUDA_DLLS = ["cublas64_12.dll", "cublasLt64_12.dll"]
CUDA_WHEEL = {
    "url": (
        "https://files.pythonhosted.org/packages/84/f7/"
        "985e9bdbe3e0ac9298fcc8cfa51a392862a46a0ffaccbbd56939b62a9c83/"
        "nvidia_cublas_cu12-12.6.4.1-py3-none-win_amd64.whl"
    ),
    "size_mb": 414.4,
    "sha256": ("9e4fa264f4d8a4eb0cdbd34beadc029f453b3bafae"
               "02401e999cf3d5a5af75f8"),
    "dlls": ["cublas64_12.dll", "cublasLt64_12.dll", "nvblas64_12.dll"],
}


class InstallerAPI:
    """Python backend exposed to JS via window.pywebview.api."""

    def __init__(self):
        self.window = None
        self._cancel = threading.Event()
        self._cuda_needed = False
        self._install_dir = DEFAULT_INSTALL_DIR
        self._gpu_name = ""
        self._vram_gb = 0.0
        self._ram_gb = 0
        self._recommended_model = "large-v3"

    # ── JS communication ──────────────────────────

    def _emit(self, event, data):
        if self.window:
            self.window.evaluate_js(
                f"window.dispatchEvent(new CustomEvent('{event}',"
                f" {{detail: {json.dumps(data)}}}));")

    # ── System checks (called one by one from JS) ─

    def get_default_path(self):
        return DEFAULT_INSTALL_DIR

    def get_logo_base64(self):
        if os.path.exists(LOGO_PATH):
            with open(LOGO_PATH, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
        return ""

    def check_os(self):
        ver = platform.version()
        release = platform.release()
        return {"ok": release in ("10", "11"),
                "version": f"Windows {release}", "detail": ver}

    def check_ram(self):
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
            ctypes.windll.kernel32.GlobalMemoryStatusEx(
                ctypes.byref(mem))
            gb = round(mem.ullTotalPhys / (1024 ** 3))
            self._ram_gb = gb
            return {"ok": gb >= 4, "gb": gb}
        except Exception:
            return {"ok": False, "gb": 0}

    def check_gpu(self):
        # nvidia-smi (tier 1)
        try:
            r = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
                creationflags=CREATE_NO_WINDOW,
            )
            if r.returncode == 0 and r.stdout.strip():
                parts = r.stdout.strip().split("\n")[0].split(",")
                name = parts[0].strip()
                vram = round(float(parts[1].strip()) / 1024, 1)
                self._gpu_name = name
                self._vram_gb = vram
                self._recommended_model = self._recommend(vram)
                return {"ok": True, "name": name, "vram_gb": vram,
                        "recommended": self._recommended_model}
        except Exception:
            pass

        # wmic fallback (any GPU)
        try:
            r = subprocess.run(
                ["wmic", "path", "win32_VideoController",
                 "get", "Name", "/format:list"],
                capture_output=True, text=True, timeout=5,
                creationflags=CREATE_NO_WINDOW,
            )
            if r.returncode == 0:
                for line in r.stdout.strip().split("\n"):
                    line = line.strip()
                    if line.startswith("Name=") and line[5:].strip():
                        name = line[5:].strip()
                        self._gpu_name = name
                        self._recommended_model = self._recommend(0)
                        return {"ok": False, "name": name,
                                "vram_gb": 0,
                                "recommended": self._recommended_model}
        except Exception:
            pass

        self._recommended_model = self._recommend(0)
        return {"ok": False, "name": "", "vram_gb": 0,
                "recommended": self._recommended_model}

    def check_cuda(self):
        """Silent CUDA check — no CMD windows, no popups.

        Tier 0: ctranslate2.get_cuda_device_count() — definitive
        Tier 1: %LOCALAPPDATA%\\WRVoice\\cuda\\
        Tier 2: PATH python.exe → site-packages nvidia\\cublas\\bin\\
        Tier 3: %CUDA_PATH%\\bin\\
        Tier 4: System32
        Tier 5: PATH entries
        """
        # Tier 0: ctranslate2 — definitive runtime check
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                self._cuda_needed = False
                return {"ok": True, "location": "ctranslate2",
                        "needs_download": False}
        except Exception:
            pass

        # Tier 1: WRVoice local cuda dir
        if all(os.path.exists(os.path.join(CUDA_DIR, dll))
               for dll in REQUIRED_CUDA_DLLS):
            self._cuda_needed = False
            return {"ok": True, "location": CUDA_DIR,
                    "needs_download": False}

        # Tier 2: find python.exe in PATH → site-packages
        try:
            for p in os.environ.get("PATH", "").split(
                    os.pathsep):
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
                if all(os.path.exists(
                        os.path.join(cublas_bin, dll))
                       for dll in REQUIRED_CUDA_DLLS):
                    self._cuda_needed = False
                    return {"ok": True,
                            "location": cublas_bin,
                            "needs_download": False}
        except Exception:
            pass

        # Tier 3: %CUDA_PATH%\bin\ and versioned variants
        for key, val in os.environ.items():
            if key.upper().startswith("CUDA_PATH"):
                cuda_bin = os.path.join(val, "bin")
                if all(os.path.exists(
                        os.path.join(cuda_bin, dll))
                       for dll in REQUIRED_CUDA_DLLS):
                    self._cuda_needed = False
                    return {"ok": True,
                            "location": cuda_bin,
                            "needs_download": False}

        # Tier 4: System32
        sys32 = os.path.join(
            os.environ.get("SYSTEMROOT", r"C:\Windows"),
            "System32")
        if all(os.path.exists(os.path.join(sys32, dll))
               for dll in REQUIRED_CUDA_DLLS):
            self._cuda_needed = False
            return {"ok": True, "location": sys32,
                    "needs_download": False}

        # Tier 5: all PATH entries
        for p in os.environ.get("PATH", "").split(os.pathsep):
            p = p.strip()
            if p and all(os.path.exists(
                    os.path.join(p, dll))
                         for dll in REQUIRED_CUDA_DLLS):
                self._cuda_needed = False
                return {"ok": True, "location": p,
                        "needs_download": False}

        self._cuda_needed = True
        return {"ok": False, "location": "",
                "needs_download": True}

    def check_disk(self, path=None):
        check_path = path or DEFAULT_INSTALL_DIR
        drive = os.path.splitdrive(check_path)[0] or "C:"
        try:
            free = shutil.disk_usage(drive + "\\").free
            gb = round(free / (1024 ** 3), 1)
            return {"ok": gb >= 2, "free_gb": gb}
        except Exception:
            return {"ok": True, "free_gb": 0}

    def check_model(self):
        """Check if a Whisper model is already downloaded."""
        model_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "WRVoice", "models")
        hf_cache = os.path.join(
            os.path.expanduser("~"), ".cache",
            "huggingface", "hub")
        # Check WRVoice local models dir
        if os.path.isdir(model_dir):
            for item in os.listdir(model_dir):
                if os.path.isdir(
                        os.path.join(model_dir, item)):
                    return {"found": True,
                            "name": item,
                            "hint": "~1.5 GB"}
        # Check HuggingFace cache for faster-whisper models
        if os.path.isdir(hf_cache):
            for item in os.listdir(hf_cache):
                if "whisper" in item.lower():
                    return {"found": True,
                            "name": item.replace(
                                "models--", "").replace(
                                "--", "/"),
                            "hint": "~1.5 GB"}
        return {"found": False, "name": "",
                "hint": "~1.5 GB"}

    def _recommend(self, vram_gb):
        if vram_gb >= 10:
            return "large-v3"
        if vram_gb >= 5:
            return "medium"
        if vram_gb >= 3:
            return "small"
        if vram_gb >= 2:
            return "base"
        if self._ram_gb >= 16:
            return "small"
        if self._ram_gb >= 8:
            return "base"
        return "tiny"

    # ── File dialogs ─────────────────────────────

    def browse_folder(self):
        result = self.window.create_file_dialog(
            webview.FOLDER_DIALOG,
            directory=os.path.dirname(DEFAULT_INSTALL_DIR),
        )
        if result and len(result) > 0:
            return result[0]
        return ""

    # ── Install ──────────────────────────────────

    def start_install(self, install_path, language):
        self._cancel.clear()
        threading.Thread(
            target=self._run_install,
            args=(install_path, language),
            daemon=True,
        ).start()

    def cancel(self):
        self._cancel.set()

    def _progress(self, msg, pct, phase="install"):
        self._emit("install-progress", {
            "message": msg, "percent": pct, "phase": phase})

    def _run_install(self, install_path, language):
        install_dir = os.path.normpath(
            install_path.strip() or DEFAULT_INSTALL_DIR)
        self._install_dir = install_dir

        try:
            # 1. Create directory
            self._progress("Creez folderul de instalare...", 5)
            os.makedirs(install_dir, exist_ok=True)
            self._progress("\u2713 Folder creat", 10)

            # 2. Copy app EXE
            app_src = os.path.join(BASE_DIR, APP_EXE)
            if os.path.exists(app_src):
                sz = os.path.getsize(app_src) / (1024 * 1024)
                self._progress(
                    f"Copiez {APP_EXE} ({sz:.0f} MB)...", 12)
                shutil.copy2(
                    app_src, os.path.join(install_dir, APP_EXE))
                self._progress(f"\u2713 {APP_EXE} copiat", 35)
            else:
                self._progress(
                    f"\u2717 {APP_EXE} negasit in pachet!", 35,
                    "error")

            # 3. Copy uninstaller
            unsrc = os.path.join(BASE_DIR, UNINSTALL_EXE)
            if os.path.exists(unsrc):
                self._progress(f"Copiez {UNINSTALL_EXE}...", 38)
                shutil.copy2(
                    unsrc, os.path.join(install_dir, UNINSTALL_EXE))
                self._progress(
                    f"\u2713 {UNINSTALL_EXE} copiat", 42)

            # 4. Write config.json
            self._progress("Scriu config.json...", 44)
            cfg = {
                "keybind": "caps lock",
                "model": self._recommended_model,
                "language": language,
                "cleanup_level": 2,
                "context": "auto",
                "use_vad": False,
                "autostart": False,
                "hotwords": "",
                "custom_corrections": {},
                "debug_console": True,
                "history": [],
            }
            with open(os.path.join(install_dir, "config.json"),
                       "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            self._progress("\u2713 config.json salvat", 48)

            # 5. Copy assets (icon + logo)
            self._progress("Copiez resurse...", 50)
            ico_src = os.path.join(BASE_DIR, "assets", "logo.ico")
            ico_dir = os.path.join(install_dir, "assets")
            if os.path.exists(ico_src):
                os.makedirs(ico_dir, exist_ok=True)
                shutil.copy2(
                    ico_src, os.path.join(ico_dir, "logo.ico"))
            logo_src = os.path.join(
                BASE_DIR, "Webrapid-logo-W.png")
            if os.path.exists(logo_src):
                shutil.copy2(
                    logo_src,
                    os.path.join(install_dir,
                                 "Webrapid-logo-W.png"))
            self._progress("\u2713 Resurse copiate", 52)

            # 6. CUDA download (if needed)
            if self._cuda_needed:
                self._progress(
                    "Se descarca CUDA runtime (414 MB)...",
                    53, "download")
                try:
                    self._download_cuda()
                except RuntimeError as e:
                    msg = str(e)
                    if msg == "cancelled":
                        self._progress(
                            "\u26a0 Descarcare CUDA anulata \u2014 "
                            "se va descarca la prima rulare", 82)
                    else:
                        self._progress(
                            f"\u26a0 CUDA: {msg} \u2014 "
                            f"se va descarca la prima rulare", 82)

            # 7. Desktop shortcut
            self._progress("Creez shortcut pe Desktop...", 85)
            self._create_shortcut(install_dir)
            self._progress("\u2713 Shortcut desktop creat", 90)

            # 8. Verify
            self._progress(
                "Verific integritatea fisierelor...", 93)
            ok = (os.path.exists(
                      os.path.join(install_dir, APP_EXE))
                  and os.path.exists(
                      os.path.join(install_dir, "config.json")))
            if ok:
                self._progress("\u2713 Verificare OK", 97)

            self._progress("Gata!", 100, "done")

        except Exception as e:
            self._progress(f"\u2717 Eroare: {e}", -1, "error")

    def _download_cuda(self):
        os.makedirs(CUDA_DIR, exist_ok=True)
        total = int(CUDA_WHEEL["size_mb"] * 1024 * 1024)

        req = Request(CUDA_WHEEL["url"],
                      headers={"User-Agent": "WRVoice/1.0"})
        try:
            resp = urlopen(req, timeout=10)
        except (URLError, OSError) as e:
            raise RuntimeError(
                f"Nu s-a putut conecta: {e}") from e

        chunks = []
        downloaded = 0
        while True:
            if self._cancel.is_set():
                raise RuntimeError("cancelled")
            try:
                chunk = resp.read(256 * 1024)
            except (URLError, OSError) as e:
                raise RuntimeError(
                    f"Eroare retea: {e}") from e
            if not chunk:
                break
            chunks.append(chunk)
            downloaded += len(chunk)
            pct = min(downloaded / total * 100, 99)
            mb = downloaded / (1024 * 1024)
            install_pct = 53 + int(pct * 25 / 100)
            self._progress(
                f"Se descarca CUDA... {mb:.0f} / "
                f"{CUDA_WHEEL['size_mb']:.0f} MB",
                install_pct, "download")

        data = b"".join(chunks)

        actual = hashlib.sha256(data).hexdigest()
        if actual != CUDA_WHEEL["sha256"]:
            raise RuntimeError("SHA256 mismatch — fisier corupt")

        self._progress("Extrag fisierele CUDA...", 79)
        if self._cancel.is_set():
            raise RuntimeError("cancelled")

        targets = {d.lower() for d in CUDA_WHEEL["dlls"]}
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for entry in zf.namelist():
                name = entry.rsplit("/", 1)[-1].lower()
                if name.endswith(".dll") and name in targets:
                    with open(os.path.join(CUDA_DIR, name),
                              "wb") as out:
                        out.write(zf.read(entry))

        self._progress("\u2713 CUDA runtime instalat", 82)

    def _create_shortcut(self, install_dir):
        try:
            desktop = os.path.join(
                os.path.expanduser("~"), "Desktop")
            lnk = os.path.join(desktop, "WR Voice.lnk")
            target = os.path.join(install_dir, APP_EXE)
            ico = os.path.join(
                install_dir, "assets", "logo.ico")
            ps = (
                '$ws = New-Object -ComObject WScript.Shell; '
                f'$s = $ws.CreateShortcut("{lnk}"); '
                f'$s.TargetPath = "{target}"; '
                f'$s.WorkingDirectory = "{install_dir}"; '
            )
            if os.path.exists(ico):
                ps += f'$s.IconLocation = "{ico}"; '
            ps += '$s.Save()'
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception:
            pass

    # ── Post-install ─────────────────────────────

    def launch_app(self):
        try:
            exe = os.path.join(self._install_dir, APP_EXE)
            if os.path.exists(exe):
                subprocess.Popen(
                    [exe], creationflags=CREATE_NO_WINDOW)
        except Exception:
            pass
        self.close_window()

    def close_window(self):
        if self.window:
            self.window.destroy()


def main():
    api = InstallerAPI()
    window = webview.create_window(
        "WR Voice Setup",
        url=HTML_PATH,
        js_api=api,
        width=540,
        height=680,
        resizable=False,
        frameless=True,
        easy_drag=True,
        on_top=True,
        transparent=True,
    )
    api.window = window
    webview.start()


if __name__ == "__main__":
    main()
