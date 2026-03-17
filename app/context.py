# -*- coding: utf-8 -*-
"""
context.py — WR Voice
Detectează aplicația activă și returnează contextul pentru cleanup.
"""

import ctypes
import ctypes.wintypes


CONTEXT_MAP = {
    # Chat / casual
    "slack.exe": "casual",
    "discord.exe": "casual",
    "whatsapp.exe": "casual",
    "telegram.exe": "casual",
    "signal.exe": "casual",
    "teams.exe": "casual",
    "mattermost.exe": "casual",
    # Email / formal
    "outlook.exe": "formal",
    "thunderbird.exe": "formal",
    # Browsers — default formal, overridden by title checks below
    "chrome.exe": "casual",
    "firefox.exe": "casual",
    "msedge.exe": "casual",
    "opera.exe": "casual",
    "brave.exe": "casual",
    # Documents
    "winword.exe": "document",
    "soffice.exe": "document",
    "notepad.exe": "document",
    "notepad++.exe": "document",
    "wordpad.exe": "document",
    # Code / raw
    "code.exe": "raw",
    "windowsterminal.exe": "raw",
    "cmd.exe": "raw",
    "powershell.exe": "raw",
    "wt.exe": "raw",
    "putty.exe": "raw",
    "conhost.exe": "raw",
    "pycharm64.exe": "raw",
    "idea64.exe": "raw",
    "sublime_text.exe": "raw",
    "rider64.exe": "raw",
}

CONTEXT_LABELS = {
    "casual": "Casual (Slack/WhatsApp)",
    "formal": "Formal (Browser/Email)",
    "document": "Document (Word/Docs)",
    "raw": "Raw (Terminal/VSCode)",
    "auto": "Auto",
}


def get_active_process():
    """Returns (process_name, window_title) for active window."""
    try:
        import psutil

        hwnd = ctypes.windll.user32.GetForegroundWindow()

        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.lower()

        pid = ctypes.wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = psutil.Process(pid.value).name().lower()

        return proc, title
    except Exception:
        return "", ""


def get_context(override=None):
    if override and override != "auto":
        return override

    proc, title = get_active_process()

    # Title-based detection (overrides process-based)
    # Priority order: raw → formal → document → casual

    # Raw: terminals, code editors
    if any(kw in title for kw in [
        "terminal", "powershell", "cmd", "bash", "wsl",
        "codex", "opencode", "cursor",
        "vs code", "visual studio", "pycharm", "intellij",
        "sublime", "rider",
    ]):
        return "raw"

    # Formal: email in any app (including browser)
    if any(kw in title for kw in [
        "gmail", "outlook", "yahoo mail", "mail",
        "inbox", "compose",
    ]):
        return "formal"

    # Document: writing apps
    if any(kw in title for kw in [
        "word", "docs", "notion", "obsidian",
        "onenote", "google docs",
    ]):
        return "document"

    # Casual: chat apps, AI assistants, social
    if any(kw in title for kw in [
        "discord", "slack", "whatsapp", "telegram",
        "messenger", "teams", "zoom", "signal",
        "claude", "chatgpt", "gemini", "copilot",
        "perplexity", "grok",
    ]):
        return "casual"

    # Process-based fallback (default: raw)
    return CONTEXT_MAP.get(proc, "raw")


def get_cleanup_level_for_context(context):
    """Mapează contextul activ la nivelul recomandat de cleanup."""
    if context == "raw":
        return 1
    return 4


def get_effective_cleanup_level(configured_level, context):
    """Nivelul explicit din config are prioritate; contextul este doar fallback."""
    try:
        level = int(configured_level)
    except (TypeError, ValueError):
        level = None

    if level in {1, 2, 3, 4}:
        return level
    return get_cleanup_level_for_context(context)
