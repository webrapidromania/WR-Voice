# -*- coding: utf-8 -*-
"""
config.py — WR Voice
Citire si scriere configuratie persistenta in config.json.
"""

import json
import os
import sys


APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "..", "config.json")

DEFAULT_CONFIG = {
    "keybind": "caps lock",
    "model": "turbo",
    "cleanup_level": 2,
    "autostart": False,
    "language": "auto",
    "context": "raw",
    "use_vad": False,
    "history": [],
}


def load():
    """Incarca config. Daca nu exista, creeaza cu default."""
    if not os.path.exists(CONFIG_PATH):
        save(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        merged = DEFAULT_CONFIG.copy()
        merged.update(data)
        return merged
    except Exception:
        return DEFAULT_CONFIG.copy()


def save(cfg):
    """Salveaza configuratia pe disk."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump(cfg, file, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"Eroare salvare config: {exc}")


def get(key, default=None):
    cfg = load()
    return cfg.get(key, default)


def set_value(key, value):
    cfg = load()
    cfg[key] = value
    save(cfg)


def add_to_history(text, max_items=5):
    """Adauga transcriere in istoric, pastreaza maxim 5."""
    cfg = load()
    history = cfg.get("history", [])
    if history and history[0] == text:
        return
    history.insert(0, text)
    cfg["history"] = history[:max_items]
    save(cfg)


def set_autostart(enabled: bool):
    """Configureaza auto-start cu Windows via registry."""
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "WRVoice"

        if getattr(sys, "frozen", False):
            launch_cmd = f'"{sys.executable}"'
        else:
            pythonw_path = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            launcher = pythonw_path if os.path.exists(pythonw_path) else sys.executable
            script_path = os.path.join(APP_DIR, "wr_voice.py")
            launch_cmd = f'"{launcher}" "{script_path}"'

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, launch_cmd)
        else:
            try:
                winreg.DeleteValue(key, app_name)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        set_value("autostart", enabled)
    except Exception as exc:
        print(f"Eroare autostart: {exc}")
