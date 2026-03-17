# -*- coding: utf-8 -*-
"""
commands.py — WR Voice
Detecteaza comenzi vocale si executa actiuni in loc sa lipeasca text.
"""

import ctypes
import re
import time

import keyboard


COMMANDS = {
    "delete": {
        "patterns": [
            r"^(șterge|sterge|delete|erase)$",
        ],
        "action": "delete",
        "description": "Ctrl+Delete",
    },
    "undo": {
        "patterns": [
            r"^(șterge asta|sterge asta|undo|undo that)$",
        ],
        "action": "undo",
        "description": "Ctrl+Z",
    },
    "select_all": {
        "patterns": [
            r"^(selectează tot|selecteaza tot|select all|selectează totul|selecteaza totul)$",
        ],
        "action": "select_all",
        "description": "Ctrl+A",
    },
    "cancel": {
        "patterns": [
            r"^(anulează|anuleaza|anuleza|anulez|cancel|renunță|renunta|las|lasa|never mind|nevermind)$",
        ],
        "action": "cancel",
        "description": "Nu lipește nimic / Don't paste",
    },
    "send": {
        "patterns": [
            r"^(trimite|trimite-mă|trimitema|trimite-ne|trimitene|send|send it|submit)$",
        ],
        "action": "send",
        "description": "Ctrl+Enter",
    },
}


def _key_event(vk_down_list):
    """Send keystroke via keybd_event - simpler and more reliable."""
    for vk in vk_down_list:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.05)
    time.sleep(0.05)
    for vk in reversed(vk_down_list):
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.05)


def execute_command(action, target_hwnd=None, after_callback=None):
    print(f"[WR Voice] execute_command: action={action} hwnd={target_hwnd}")
    keyboard.unhook_all()
    time.sleep(0.15)

    if target_hwnd:
        result = ctypes.windll.user32.SetForegroundWindow(target_hwnd)
        print(f"[WR Voice] SetForegroundWindow result: {result}")
        time.sleep(0.3)
    else:
        print("[WR Voice] WARNING: no target_hwnd saved!")

    if action == "send":
        print("[WR Voice] Sending Ctrl+Enter...")
        _key_event([0x11, 0x0D])
    elif action == "delete":
        print("[WR Voice] Sending Ctrl+Delete...")
        _key_event([0x11, 0x2E])
    elif action == "undo":
        print("[WR Voice] Sending Ctrl+Z...")
        _key_event([0x11, 0x5A])
    elif action == "select_all":
        print("[WR Voice] Sending Ctrl+A...")
        _key_event([0x11, 0x41])
    elif action == "cancel":
        print("[WR Voice] Cancel - nothing sent")

    time.sleep(0.1)
    if after_callback:
        after_callback()
    return True


def detect_command(text):
    if not text:
        return None
    text_clean = text.strip().lower()
    text_clean = re.sub(r"[.!?,;:\-]+", "", text_clean).strip()

    replacements = {
        "ă": "a",
        "â": "a",
        "î": "i",
        "ș": "s",
        "ț": "t",
        "ş": "s",
        "ţ": "t",
    }
    text_nd = "".join(replacements.get(c, c) for c in text_clean)

    for cmd_name, cmd_data in COMMANDS.items():
        for pattern in cmd_data["patterns"]:
            if re.match(pattern, text_clean, re.IGNORECASE):
                return cmd_data["action"]
            if re.match(pattern, text_nd, re.IGNORECASE):
                return cmd_data["action"]

    keyword_map = {
        "anuleaza": "cancel",
        "anuleza": "cancel",
        "anulez": "cancel",
        "cancel": "cancel",
        "trimite": "send",
        "trimitema": "send",
        "trimitene": "send",
        "send": "send",
        "submit": "send",
        "sterge": "delete",
        "delete": "delete",
        "erase": "delete",
        "undo": "undo",
        "selecteaza": "select_all",
    }
    last_word = re.sub(r"[^a-z]", "", text_nd.split()[-1]) if text_nd.split() else ""
    if last_word in keyword_map:
        return keyword_map[last_word]

    return None


COMMAND_LIST = [
    ("șterge / delete", "Ctrl+Delete"),
    ("șterge asta / undo", "Ctrl+Z"),
    ("selectează tot / select all", "Ctrl+A"),
    ("anulează / cancel", "Nu lipește nimic"),
    ("trimite / send", "Ctrl+Enter"),
]
