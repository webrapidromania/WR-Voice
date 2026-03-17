# -*- coding: utf-8 -*-
"""
Helpers for the runtime Whisper model selection flow.
"""

from __future__ import annotations

import os


DEFAULT_MODEL_KEY = "turbo"
SELECTABLE_MODEL_KEYS = ("tiny", "base", "small", "medium", "large-v3", "turbo")
LEGACY_MODEL_KEYS = ("large-v2",)

MODEL_SPECS = {
    "tiny": {
        "display_label": "Whisper Tiny",
        "menu_label": "Whisper Tiny - cel mai rapid",
        "help_text": "cel mai rapid",
        "load_target": "tiny",
    },
    "base": {
        "display_label": "Whisper Base",
        "menu_label": "Whisper Base - rapid",
        "help_text": "rapid",
        "load_target": "base",
    },
    "small": {
        "display_label": "Whisper Small",
        "menu_label": "Whisper Small - echilibrat",
        "help_text": "echilibrat",
        "load_target": "small",
    },
    "medium": {
        "display_label": "Whisper Medium",
        "menu_label": "Whisper Medium - acuratete buna",
        "help_text": "acuratete buna",
        "load_target": "medium",
    },
    "large-v3": {
        "display_label": "Whisper Large v3",
        "menu_label": "Whisper Large v3 - acuratete maxima (recomandat)",
        "help_text": "acuratete maxima (recomandat)",
        "load_target": "large-v3",
    },
    "turbo": {
        "display_label": "Whisper Turbo",
        "menu_label": "Whisper Turbo - viteza",
        "help_text": "viteza",
        "load_target": "turbo",
    },
}

MODEL_ALIAS_MAP = {
    "large_v3": "large-v3",
    "whisper-large-v3": "large-v3",
    "whisper-turbo": "turbo",
}

_APPDATA_ROOT = os.environ.get(
    "LOCALAPPDATA",
    os.path.join(os.path.expanduser("~"), "AppData", "Local"),
)
MODEL_STORAGE_DIR = os.path.join(_APPDATA_ROOT, "WRVoice", "models")


def get_default_model_key():
    return DEFAULT_MODEL_KEY


def get_selectable_model_keys():
    return SELECTABLE_MODEL_KEYS


def normalize_model_key(model_key, default=DEFAULT_MODEL_KEY, allow_legacy=True):
    normalized = str(model_key or "").strip().lower().replace("_", "-")
    if normalized in MODEL_SPECS:
        return normalized
    if normalized in MODEL_ALIAS_MAP:
        return MODEL_ALIAS_MAP[normalized]
    if allow_legacy and normalized in LEGACY_MODEL_KEYS:
        return normalized
    return default


def get_model_display_label(model_key):
    normalized = normalize_model_key(model_key)
    spec = MODEL_SPECS.get(normalized)
    if spec:
        return spec["display_label"]
    return f"{normalized} (legacy)"


def get_model_menu_label(model_key):
    normalized = normalize_model_key(model_key, allow_legacy=False)
    spec = MODEL_SPECS.get(normalized)
    if spec:
        return spec["menu_label"]
    return str(model_key or DEFAULT_MODEL_KEY)


def get_model_help_text(model_key):
    normalized = normalize_model_key(model_key, allow_legacy=False)
    spec = MODEL_SPECS.get(normalized)
    if spec:
        return spec["help_text"]
    return "legacy selection"


def get_model_load_target(model_key, logger=print):
    normalized = normalize_model_key(model_key)
    spec = MODEL_SPECS.get(normalized)
    if spec:
        return spec["load_target"]
    return normalized
