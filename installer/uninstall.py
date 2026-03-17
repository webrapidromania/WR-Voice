# -*- coding: utf-8 -*-
"""WR Voice Uninstaller — pywebview UI with glassmorphism design."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import webview

CREATE_NO_WINDOW = 0x08000000

if getattr(sys, "frozen", False):
    INSTALL_DIR = os.path.dirname(os.path.abspath(sys.executable))
    HTML_PATH = os.path.join(sys._MEIPASS, "uninstall.html")
else:
    INSTALL_DIR = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    HTML_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "uninstall.html")

APP_FILES = ["WR Voice.exe", "config.json", "Webrapid-logo-W.png"]
MODEL_CACHE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA",
                   os.path.join(os.path.expanduser("~"),
                                "AppData", "Local")),
    "WRVoice",
)
CUDA_CACHE_DIR = os.path.join(MODEL_CACHE_DIR, "cuda")
HF_CACHE_DIR = os.path.join(
    os.path.expanduser("~"), ".cache", "huggingface")


class UninstallerAPI:
    """Python backend exposed to JS via window.pywebview.api."""

    def __init__(self):
        self.window = None

    def _emit(self, event, data):
        if self.window:
            self.window.evaluate_js(
                f"window.dispatchEvent(new CustomEvent('{event}',"
                f" {{detail: {json.dumps(data)}}}));")

    def get_info(self):
        """Return install dir, language from config, cache sizes."""
        lang = "ro"
        cfg_path = os.path.join(INSTALL_DIR, "config.json")
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                lang = cfg.get("language", "ro")
        except Exception:
            pass

        # Model cache size (excluding cuda/)
        model_size_gb = 0
        try:
            if os.path.isdir(MODEL_CACHE_DIR):
                total = 0
                for dirpath, _, filenames in os.walk(
                        MODEL_CACHE_DIR):
                    if "cuda" in dirpath:
                        continue
                    for fn in filenames:
                        total += os.path.getsize(
                            os.path.join(dirpath, fn))
                model_size_gb = round(total / (1024 ** 3), 1)
        except Exception:
            pass

        # CUDA cache size
        cuda_size_mb = 0
        try:
            if os.path.isdir(CUDA_CACHE_DIR):
                total = sum(
                    os.path.getsize(os.path.join(CUDA_CACHE_DIR, f))
                    for f in os.listdir(CUDA_CACHE_DIR)
                    if os.path.isfile(
                        os.path.join(CUDA_CACHE_DIR, f)))
                cuda_size_mb = round(total / (1024 ** 2))
        except Exception:
            pass

        return {
            "install_dir": INSTALL_DIR,
            "language": lang,
            "model_size_gb": model_size_gb,
            "cuda_size_mb": cuda_size_mb,
            "has_models": os.path.isdir(MODEL_CACHE_DIR),
            "has_cuda": os.path.isdir(CUDA_CACHE_DIR),
        }

    def start_uninstall(self, delete_models, delete_cuda):
        threading.Thread(
            target=self._run_uninstall,
            args=(delete_models, delete_cuda),
            daemon=True,
        ).start()

    def _progress(self, msg, pct, phase="uninstall"):
        self._emit("uninstall-progress", {
            "message": msg, "percent": pct, "phase": phase})

    def _run_uninstall(self, delete_models, delete_cuda):
        try:
            # 1. Kill WR Voice if running
            self._progress(
                "Se opreste WR Voice daca ruleaza...", 5)
            try:
                subprocess.run(
                    ["taskkill", "/f", "/im", "WR Voice.exe"],
                    capture_output=True, timeout=5,
                    creationflags=CREATE_NO_WINDOW)
            except Exception:
                pass
            time.sleep(0.5)
            self._progress("\u2713 Procesat", 10)

            # 2. Delete app files
            for i, fname in enumerate(APP_FILES):
                fpath = os.path.join(INSTALL_DIR, fname)
                self._progress(
                    f"Se sterge {fname}...", 15 + i * 8)
                try:
                    if os.path.exists(fpath):
                        os.remove(fpath)
                except Exception:
                    pass
            self._progress(
                "\u2713 Fisiere aplicatie sterse", 40)

            # 3. Delete assets
            self._progress("Se sterg resursele...", 45)
            assets_dir = os.path.join(INSTALL_DIR, "assets")
            if os.path.isdir(assets_dir):
                shutil.rmtree(assets_dir, ignore_errors=True)

            # 4. Delete desktop shortcuts
            self._progress(
                "Se sterge shortcut de pe Desktop...", 50)
            for desktop_dir in [
                os.path.join(
                    os.path.expanduser("~"), "Desktop"),
                os.path.join(
                    os.environ.get("PUBLIC",
                                   r"C:\Users\Public"),
                    "Desktop"),
            ]:
                lnk = os.path.join(desktop_dir, "WR Voice.lnk")
                try:
                    if os.path.exists(lnk):
                        os.remove(lnk)
                except Exception:
                    pass
            self._progress("\u2713 Shortcut sters", 55)

            # 5. Delete AI models (preserves cuda/ unless delete_cuda)
            if delete_models:
                self._progress("Se sterg modelele AI...", 60)
                if os.path.isdir(MODEL_CACHE_DIR):
                    for item in os.listdir(MODEL_CACHE_DIR):
                        if item == "cuda":
                            continue  # CUDA preserved separately
                        p = os.path.join(MODEL_CACHE_DIR, item)
                        try:
                            if os.path.isdir(p):
                                shutil.rmtree(
                                    p, ignore_errors=True)
                            else:
                                os.remove(p)
                        except Exception:
                            pass
                if os.path.isdir(HF_CACHE_DIR):
                    shutil.rmtree(
                        HF_CACHE_DIR, ignore_errors=True)
                self._progress(
                    "\u2713 Modele AI sterse", 70)

            # 6. Delete CUDA runtime
            if delete_cuda:
                self._progress(
                    "Se sterge CUDA runtime...", 75)
                if os.path.isdir(CUDA_CACHE_DIR):
                    shutil.rmtree(
                        CUDA_CACHE_DIR, ignore_errors=True)
                try:
                    if (os.path.isdir(MODEL_CACHE_DIR)
                            and not os.listdir(MODEL_CACHE_DIR)):
                        os.rmdir(MODEL_CACHE_DIR)
                except Exception:
                    pass
                self._progress(
                    "\u2713 CUDA runtime sters", 85)

            # Done
            self._progress(
                "Gata! WR Voice a fost dezinstalat.",
                100, "done")

        except Exception as e:
            self._progress(
                f"\u2717 Eroare: {e}", -1, "error")

    def close_window(self):
        # Self-delete via batch file (frozen mode)
        if getattr(sys, "frozen", False):
            self_path = sys.executable
            bat_path = os.path.join(
                tempfile.gettempdir(), "wrvoice_cleanup.bat")
            try:
                with open(bat_path, "w", encoding="utf-8",
                          newline="\r\n") as f:
                    f.write("@echo off\n")
                    f.write("timeout /t 2 /nobreak >nul\n")
                    f.write(f'del /f /q "{self_path}"\n')
                    f.write(
                        f'rmdir /s /q "{INSTALL_DIR}" 2>nul\n')
                    f.write(f'del /f /q "{bat_path}"\n')
                subprocess.Popen(
                    ["cmd", "/c", bat_path],
                    creationflags=CREATE_NO_WINDOW)
            except Exception:
                pass
        if self.window:
            self.window.destroy()


def main():
    api = UninstallerAPI()
    window = webview.create_window(
        "WR Voice Uninstall",
        url=HTML_PATH,
        js_api=api,
        width=540,
        height=580,
        resizable=False,
        frameless=True,
        easy_drag=True,
        on_top=True,
        transparent=False,
    )
    api.window = window
    webview.start()


if __name__ == "__main__":
    main()
