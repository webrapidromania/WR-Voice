# -*- coding: utf-8 -*-
"""
wr_voice.py — WR Voice v1.0
WebRapid.ro — Vlad

Entry point principal.
- Tray icon lângă ceas, zero UI
- Push-to-talk: ții apăsat keybind → vorbești → dai drumul → text lipit
- Pill overlay apare deasupra taskbar-ului când înregistrezi
"""

import os, sys

# Register all known CUDA/NVIDIA DLL directories early so CTranslate2 can find
# the runtime on any NVIDIA GPU. If none are available, we fall back to CPU.
import glob

_CUDA_DLL_DIRS = []
_CUDA_DLL_SEEN = set()


def _register_cuda_dll_dir(path):
    if not path or not hasattr(os, "add_dll_directory"):
        return
    if not os.path.isdir(path):
        return

    normalized = os.path.normcase(os.path.normpath(path))
    if normalized in _CUDA_DLL_SEEN:
        return

    try:
        _CUDA_DLL_DIRS.append(os.add_dll_directory(path))
        _CUDA_DLL_SEEN.add(normalized)
        current_path = os.environ.get("PATH", "")
        path_parts = current_path.split(os.pathsep) if current_path else []
        if normalized not in {
            os.path.normcase(os.path.normpath(part))
            for part in path_parts
            if part
        }:
            os.environ["PATH"] = path + os.pathsep + current_path if current_path else path
    except OSError:
        pass


def _bootstrap_cuda_dll_paths():
    _is_frozen = getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')

    if _is_frozen:
        # Frozen/PyInstaller mode: ctranslate2.dll lives in _MEIPASS,
        # but CUDA DLLs (cublas etc.) are downloaded on first launch
        # to LOCALAPPDATA/WRVoice/cuda/ by cuda_runtime.py.
        meipass = sys._MEIPASS
        _register_cuda_dll_dir(meipass)
        # Register downloaded CUDA DLL directory
        _cuda_local = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local")),
            "WRVoice", "cuda",
        )
        _register_cuda_dll_dir(_cuda_local)
    else:
        # Dev mode: scan site-packages for nvidia-* pip packages
        import site
        site_roots = []
        try:
            site_roots.extend(site.getsitepackages())
        except Exception:
            pass
        try:
            user_site = site.getusersitepackages()
            if user_site:
                site_roots.append(user_site)
        except Exception:
            pass

        for root in site_roots:
            for cuda_bin in glob.glob(os.path.join(root, "nvidia", "*", "bin")):
                _register_cuda_dll_dir(cuda_bin)

    # Always check CUDA_PATH* env vars (works in both modes)
    for env_name, env_value in os.environ.items():
        if env_name.startswith("CUDA_PATH") and env_value:
            _register_cuda_dll_dir(os.path.join(env_value, "bin"))


_bootstrap_cuda_dll_paths()

# Path setup pentru import module locale
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    ROOT_DIR = sys._MEIPASS
    APP_DIR = os.path.join(ROOT_DIR, 'app')
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(APP_DIR)
sys.path.insert(0, APP_DIR)
sys.path.insert(0, ROOT_DIR)

import threading
import tempfile
import time
import queue
import random
import re
import math

import pyperclip
import keyboard
import sounddevice as sd
import soundfile as sf
import numpy as np
import tkinter as tk
from PIL import Image, ImageTk, ImageDraw
import pystray

RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS

# ── Fast clipboard + paste via ctypes (zero subprocess, zero CMD) ──────────
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9
VK_CONTROL = 0x11
VK_V = 0x56
ULONG_PTR = wintypes.WPARAM


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_target_hwnd = None


def _clipboard_set(text):
    pyperclip.copy(text)


def _keyboard_input(vk, flags=0):
    return INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(
            wVk=vk,
            wScan=0,
            dwFlags=flags,
            time=0,
            dwExtraInfo=0,
        ),
    )


def _send_inputs(*inputs):
    sent = user32.SendInput(
        len(inputs),
        (INPUT * len(inputs))(*inputs),
        ctypes.sizeof(INPUT),
    )
    if sent != len(inputs):
        raise ctypes.WinError(ctypes.get_last_error())


def _remember_target_window():
    global _target_hwnd
    hwnd = user32.GetForegroundWindow()
    if hwnd:
        _target_hwnd = hwnd


def _restore_target_window(hwnd=None):
    hwnd = hwnd or _target_hwnd
    if not hwnd or not user32.IsWindow(hwnd):
        return False

    current_thread = kernel32.GetCurrentThreadId()
    foreground = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    attached_threads = []

    for thread_id in (foreground_thread, target_thread):
        if thread_id and thread_id != current_thread and thread_id not in attached_threads:
            if user32.AttachThreadInput(current_thread, thread_id, True):
                attached_threads.append(thread_id)

    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
        time.sleep(0.08)
        return user32.GetForegroundWindow() == hwnd
    finally:
        for thread_id in reversed(attached_threads):
            user32.AttachThreadInput(current_thread, thread_id, False)


def _replace_recent_text(raw_text, cleaned_text, target_hwnd=None, char_count=None):
    if not raw_text or not cleaned_text or cleaned_text == raw_text:
        return False
    if "\n" in raw_text or "\r" in raw_text:
        return False
    if not _restore_target_window(target_hwnd):
        return False

    count = max(0, int(char_count if char_count is not None else len(raw_text)))
    time.sleep(0.1)
    for _ in range(count):
        ctypes.windll.user32.keybd_event(0x25, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x25, 0, 2, 0)
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(0x10, 0, 0, 0)
    try:
        for _ in range(count):
            ctypes.windll.user32.keybd_event(0x27, 0, 0, 0)
            ctypes.windll.user32.keybd_event(0x27, 0, 2, 0)
    finally:
        ctypes.windll.user32.keybd_event(0x10, 0, 2, 0)

    _clipboard_set(cleaned_text)
    _send_ctrl_v()
    return True


def _replace_latest_history(original_text, final_text):
    if not final_text:
        return
    try:
        cfg = load_cfg()
        history = list(cfg.get("history", []))
        if history and history[0] == original_text:
            history[0] = final_text
            cfg["history"] = history
            save_cfg(cfg)
            return
    except Exception:
        pass
    add_to_history(final_text)


def _send_ctrl_v():
    """Temporarily unhook the hotkey listener so Ctrl+V is not swallowed."""
    keyboard.unhook_all()
    time.sleep(0.3)
    ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0x56, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(0x56, 0, 2, 0)
    ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)
    time.sleep(0.1)
    register_keybind(load_cfg().get("keybind", "caps lock"))


from app.config import (
    load as load_cfg,
    save as save_cfg,
    set_value,
    add_to_history,
    set_autostart,
)
from app.cleanup import clean, LEVEL_LABELS, _fix_punctuation
from app.context import (
    get_active_process,
    get_context,
    get_effective_cleanup_level,
    CONTEXT_LABELS,
)
from app.commands import detect_command, execute_command, COMMAND_LIST
from app.transcription_models import (
    DEFAULT_MODEL_KEY,
    get_model_display_label,
    get_model_load_target,
    get_model_menu_label,
    get_selectable_model_keys,
    normalize_model_key,
)


def _poll_active_window():
    """Background thread: polls the foreground window every 0.3s.
    Caches the last non-WR-Voice window so the tray always shows the right title
    and on_press() can use it as fallback if GetForegroundWindow() returns 0.
    """
    global _last_active_proc, _last_active_title, _last_active_win_hwnd
    _skip = {"python.exe", "pythonw.exe", "wr_voice.exe", "wrvoice.exe"}
    while True:
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if hwnd:
                proc, title = get_active_process()
                if proc and proc not in _skip:
                    _last_active_proc = proc
                    _last_active_title = title
                    _last_active_win_hwnd = hwnd
        except Exception:
            pass
        time.sleep(0.3)


# ──────────────────────────────────────────────────────────
VERSION = "1.0 BETA"
LANGUAGE_LABELS = {
    "auto": "Auto",
    "ro": "Romana",
    "en": "English",
}
INITIAL_PROMPT_RO = (
    "Transcriere dictare vocală în limba română cu diacritice "
    "corecte și punctuație naturală. Termeni tehnici exacți: "
    "WebRapid, Fastify, Prisma, PostgreSQL, Node.js, TypeScript, "
    "React, Tailwind, Next.js, Vite, Hetzner, Hostico, Cloudflare, "
    "Nginx, PM2, Redis, Docker, VPS, API, endpoint, deploy, "
    "frontend, backend, repository, commit, branch, merge, "
    "pull request, inference, pipeline, fallback, benchmark, "
    "word error rate, system tray, hotkey, push-to-talk, "
    "tray icon, release, build, debug, log, export, dataset, "
    "sample rate, buffer, thread, crash, timeout, VRAM, GPU, CPU, "
    "driver, kernel, registry, cache, batch, watchdog."
)
INITIAL_PROMPT_EN = (
    "Speaking in English. "
    "WebRapid, webrapid.ro, commit, branch, merge, deploy, build, push, pull."
)
INITIAL_PROMPT_AUTO = (
    "Vorbesc \u00een rom\u00e2n\u0103. Transcriere \u00een limba rom\u00e2n\u0103."
)
DEFAULT_HOTWORDS_RO = (
    "WebRapid webrapid contact "
    "commit branch merge rollback deploy build push pull "
    "sterge copiez lipesc anuleaza salveaza "
    "functie variabila parametru server client "
    "Romania Bucuresti interfata aplicatie configurare "
    "intrebare raspuns problema rezolvare "
    "fisier folder director baza date"
)
DEFAULT_HOTWORDS_EN = (
    "WebRapid commit branch merge rollback deploy build push pull "
    "delete copy paste save cancel undo"
)


def _build_initial_prompt(lang):
    """Return the initial prompt for the given language."""
    if lang == "ro":
        return INITIAL_PROMPT_RO
    if lang == "en":
        return INITIAL_PROMPT_EN
    # auto mode — Romanian hint helps turbo model
    return INITIAL_PROMPT_AUTO


QUICK_FIXES = [
    (re.compile(p, re.IGNORECASE), r)
    for p, r in [
        (r"\bondemo\.o\b", "contact@webrapid.ro"),
        (r"\bcontactaround\b", "contact@"),
        (r"\bcontactarond\b", "contact@"),
        (r"\bwebrapid\.com\b", "webrapid.ro"),
        (r"\bWR voce\b", "WR Voice"),
        (r"\bWR Voce\b", "WR Voice"),
        (r"\bwr voce\b", "WR Voice"),
        (r"\b9 a 11-a 1994\b", "09.11.1994"),
        (r"\b9 a 11 a 1994\b", "09.11.1994"),
        (r"\bcomic\b", "commit"),
        (r"\bcomic branch\b", "commit branch"),
        (r"\bmirici\b", "merge"),
        (r"\bmirci\b", "merge"),
        (r"\bbrawler\b", "brawler"),
        (r"\biurea\b", "aiurea"),
        (r"\bstandard\b", "standard"),
        (r"\bshtrand\b", "ștrand"),
        (r"\bshtampila\b", "ștampilă"),
        (r"\bîndemnire\b", "îndemânare"),
        (r"\bneîndemunatic\b", "neîndemânatic"),
        (r"\bîmpreunare\b", "împrejurare"),
        (r"\bghișeuul\b", "ghișeul"),
        (r"\braf trece\b", "raft rece"),
        (r"\bgeamgeu\b", "geamgiu"),
        (r"\bshtard\b", "ștrand"),
        (r"\bwebrapid\.ro\b", "WebRapid"),
        (r"\bweb rapid\b", "WebRapid"),
        (r"\bWeb Rapid\b", "WebRapid"),
        (r"\bwebrabit\b", "WebRapid"),
        (r"\bWebRabbit\b", "WebRapid"),
        (r"\bWebRabit\b", "WebRapid"),
        (r"\bWebRide\b", "WebRapid"),
        (r"\bWebRite\b", "WebRapid"),
        (r"\bcaps loc\b", "Caps Lock"),
        (r"\bcapsloc\b", "Caps Lock"),
        (r"\bExcel\b(?!\s+file|\s+sheet)", "exe"),
        (r"\bsistem\s*3\b", "system tray"),
        (r"\bsistem\s*trei\b", "system tray"),
        (r"\bsistem\s*tray\b", "system tray"),
        (r"\btrai\b(?=\s|$)", "tray"),
        (r"\binterface\b(?=\s+local|\s+engine|\s+model|\s+pipeline)", "inference"),
        (r"\bvocalei\b", "vocale"),
        (r"\bhotchi\b", "hotkey"),
        (r"\bhotel\s+key\b", "hotkey"),
        (r"\bPVPS\b", "pe VPS"),
        (r"\bbenșmarg\b", "benchmark"),
        (r"\buisper\b", "Whisper"),
        (r"\bwisper\b", "Whisper"),
        (r"\bvispăr\b", "Whisper"),
        (r"\bTest-ul\b", "Test"),
        (r"\bvirculele\b", "virgulele"),
        (r"\bminigent\b", "la mine"),
        (r"\bpaid\b(?=\s+pages|\s+page)", "pages"),
        (r"\bvoia\s+mea\b", "vocea mea"),
        (r"\bCloude\b", "Claude"),
        (r"\baplicatii\b", "aplicatie"),
        # Turbo misrecognitions — Romanian voice
        (r"\bvure\s*am\b", "VRAM"),
        (r"\bvuram\b", "VRAM"),
        (r"\bvure am\b", "VRAM"),
        (r"\breghit\b", "regex"),
        (r"\bregx\b", "regex"),
        (r"\breg x\b", "regex"),
        (r"\breg-x\b", "regex"),
        (r"\btishnemon\b", "this and more"),
        (r"\boriolata\b", "oriodată"),
        (r"\bparcca\b", "parcă"),
        (r"\benglez[eă]\b", "engleză"),
        (r"\bvorbesca\b", "vorbească"),
        # Turbo Romanian voice — tech terms
        (r"\bcloud\b", "Claude"),
        (r"\bv-?gram\b", "VRAM"),
        (r"\bviere\s*[Rr][Aa][Mm]\b", "VRAM"),
        (r"\bcu\s*da\b", "CUDA"),
        (r"\brolează\b", "rulează"),
        (r"\bform\s+commit\b", "fă un commit"),
        (r"\bwebrapid\s+liste\b", "WebRapid este"),
        (r"\bcheia\s+de\s+loc\b", "CAPS LOCK"),
        (r"\bthe\s+paste\b", "dă paste"),
        (r"\bfăc\s+linea\b", "fă cleanup"),
        (r"\bpmi\s+la\s+clientele\b", "pe email clientului"),
        (r"\bfisierul\b", "fișierul"),
        (r"\bphone\s+reg[ix]+\b", "fă un regex"),
        (r"\bdescide\b", "deschide"),
        (r"\bfischeru\b", "fișierul"),
        (r"\bfi\s+shirr[aă]\b", "fișierul"),
        (r"\btu\s+comit\b", "dă commit"),
        (r"\bclean\s+up\b", "cleanup"),
        (r"\bghid\s+repo\b", "git repo"),
        (r"\britmi\s+de\s+la\b", "readme"),
        # Turbo Romanian voice — înjurături
        (r"\bbucurei\b", "ba coaie"),
        (r"\bquai\b", "ba coaie"),
        (r"\bbac\s+pula\b", "bag pula"),
        (r"\bda\s+timpul\s+la\s+mea\b", "dă-te-n pula mea"),
        (r"\bterminatul\s+ei\b", "terminatu-le"),
        (r"\bpisea\s+ma[sș]in\b", "pișam-aș în"),
        (r"\bpi[sș]ti\s+d[aă]te\b", "pis dă-te-n"),
        (r"\bfutuzmorți\b", "futu-ți morții"),
        (r"\bfutuzmorti\b", "futu-ți morții"),
    ]
]


def quick_fix(text, custom_corrections=None):
    for pattern, replacement in QUICK_FIXES:
        text = pattern.sub(replacement, text)
    if custom_corrections:
        for wrong, correct in custom_corrections.items():
            text = text.replace(wrong, correct)
    return text


def _find_logo():
    candidates = [
        os.path.join(APP_DIR, "Webrapid-logo-W.png"),
        os.path.join(APP_DIR, "logo.png"),
        os.path.join(ROOT_DIR, "Webrapid-logo-W.png"),
    ]
    # Also check next to the exe itself (install dir)
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "Webrapid-logo-W.png"))
    candidates.append(os.path.join(ROOT_DIR, "assets", "logo.ico"))
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


LOGO_PATH = _find_logo()
SAMPLE_RATE = 16000

# Culori
BG = "#0a0a0f"
GREEN = "#00ff77"
GREEN2 = "#00cc55"
GREEN3 = "#004422"
YELLOW = "#ffcc00"
WHITE = "#eeeeff"
GRAY = "#1c1c28"
DIM = "#2a2a3a"
TRANSP = "#010101"

# State
model = None
active_model_name = None
active_model_source = None
model_load_lock = threading.Lock()
is_recording = False
key_held = False
audio_queue = queue.Queue()
current_state = "idle"
audio_level = 0.0
audio_lock = threading.Lock()
last_transcribed = ""
_target_context = "auto"

# UI
root = None
wave_canvas = None
logo_tk = None
tray_icon = None
_tray_anim_running = False
_tray_anim_thread = None
wave_anim_id = None
loading_anim_id = None
_dot_frame = 0

# Active window cache (background poll — fixes tray display + transcription target)
_last_active_proc = ""
_last_active_title = ""
_last_active_win_hwnd = None

# Pill dimensions
PILL_W = 150
PILL_H = 36
LOGO_SZ = 28
PAD = 6
BARS_X = LOGO_SZ + PAD * 2 + 6
BARS_W = PILL_W - BARS_X - PAD - 2
NUM_BARS = 12

bar_current = [0.0] * NUM_BARS
bar_targets = [0.0] * NUM_BARS
_pulse_phase = 0.0


def _cuda_load_attempts():
    try:
        import ctranslate2
        from app.cuda_runtime import _cublas_loadable

        cuda_devices = ctranslate2.get_cuda_device_count()
        if cuda_devices > 0:
            if _cublas_loadable():
                print(f"[WR Voice] CUDA detectat: {cuda_devices}"
                      f" device(s) + cublas DLLs loadable")
                return [
                    ("cuda", "float16"),
                    ("cuda", "int8_float16"),
                    ("cuda", "int8"),
                    ("cpu", "int8"),
                ]
            print("[WR Voice] GPU detectat dar cublas DLLs"
                  " nu pot fi incarcate — CPU mode")
            return [("cpu", "int8")]
        print("[WR Voice] Nu exista device CUDA disponibil."
              " Pornesc direct pe CPU.")
    except Exception as e:
        print(f"[WR Voice] Verificarea CUDA a esuat: {e}")

    return [("cpu", "int8")]


def _restore_state_after_model_load(previous_state):
    return "disabled" if previous_state == "disabled" else "idle"


def load_model(model_name=None, persist_selection=False):
    global model, active_model_name, active_model_source
    cfg = load_cfg()
    requested_raw = model_name if model_name is not None else cfg.get("model", DEFAULT_MODEL_KEY)
    requested_model = normalize_model_key(requested_raw)
    requested_label = get_model_display_label(requested_model)
    persist_on_success = persist_selection or (
        model_name is None and requested_model != str(requested_raw or "").strip()
    )

    if current_state in ("recording", "processing"):
        print(f"[WR Voice] Schimbarea modelului este blocata cat timp starea este '{current_state}'.")
        rebuild_tray_menu()
        return False

    if requested_model == active_model_name and model is not None and model_name is not None:
        print(f"[WR Voice] Modelul este deja activ: {requested_label}")
        return True

    if not model_load_lock.acquire(blocking=False):
        print("[WR Voice] O incarcare de model este deja in curs.")
        return False

    previous_state = current_state
    previous_model = model
    previous_model_name = active_model_name
    previous_model_source = active_model_source

    try:
        set_state("loading")
        print(f"[WR Voice] Incarc modelul: {requested_label}")
        load_target = get_model_load_target(requested_model, logger=print)
        if os.path.isdir(load_target):
            print(f"[WR Voice] Sursa model local: {load_target}")

        from faster_whisper import WhisperModel
        import numpy as np, soundfile as sf, tempfile

        def _try_load(device, compute):
            print(
                f"[WR Voice] Incerc {requested_label} cu device={device} compute={compute}..."
            )
            try:
                new_model = WhisperModel(load_target, device=device, compute_type=compute)
            except Exception as exc:
                err = str(exc).lower()
                if "cublas" in err or "cannot be loaded" in err:
                    print(f"[WR Voice] cublas DLL missing"
                          f" — skipping all CUDA attempts: {exc}")
                    raise  # bubble up to skip remaining CUDA attempts
                print(f"[WR Voice] Load esuat ({device}): {exc}")
                return None

            print(f"[WR Voice] Warm-up test pe {device.upper()}...")
            tmp_path = None
            try:
                t = np.linspace(0, 0.5, 8000, endpoint=False, dtype=np.float32)
                dummy = 0.02 * np.sin(2 * np.pi * 220 * t)
                dummy += np.random.normal(0, 0.001, size=dummy.shape).astype(np.float32)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                    sf.write(tf.name, dummy, 16000)
                    tmp_path = tf.name
                segments, _ = new_model.transcribe(
                    tmp_path,
                    language=None,
                    beam_size=1,
                    temperature=0.0,
                )
                list(segments)
                print(f"[WR Voice] OK {device.upper()} - warm-up pass")
                return new_model
            except Exception as exc:
                print(f"[WR Voice] FAIL {device.upper()} warm-up: {exc}")
                return None
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

        attempts = _cuda_load_attempts()
        cublas_failed = False
        for device, compute in attempts:
            if cublas_failed and device == "cuda":
                continue
            try:
                loaded_model = _try_load(device, compute)
            except Exception as exc:
                err = str(exc).lower()
                if "cublas" in err or "cannot be loaded" in err:
                    print("[WR Voice] cublas DLL missing"
                          " — falling back to CPU immediately")
                    cublas_failed = True
                    continue
                raise
            if loaded_model is None:
                continue

            model = loaded_model
            active_model_name = requested_model
            active_model_source = load_target
            if persist_on_success:
                set_value("model", requested_model)
            print(f"[WR Voice] Model activ: {requested_label} pe {device.upper()}")
            set_state(_restore_state_after_model_load(previous_state))
            rebuild_tray_menu()
            threading.Thread(target=_show_startup_notification, daemon=True).start()
            return True

        raise RuntimeError("Niciun device compatibil nu a putut porni modelul selectat.")
    except Exception as exc:
        model = previous_model
        active_model_name = previous_model_name
        active_model_source = previous_model_source
        print(f"[WR Voice] EROARE la incarcare pentru {requested_label}: {exc}")
        if previous_model_name:
            print(
                "[WR Voice] Pastrez modelul anterior functional: "
                f"{get_model_display_label(previous_model_name)}"
            )
        else:
            print("[WR Voice] Nu exista un model anterior functional disponibil.")
        if previous_model_source and previous_model_source != active_model_source:
            active_model_source = previous_model_source
        if tray_icon:
            try:
                tray_icon.title = "WR Voice - Model FAILED"
            except Exception:
                pass
        set_state(_restore_state_after_model_load(previous_state))
        rebuild_tray_menu()
        return False
    finally:
        model_load_lock.release()


def _show_startup_notification():
    try:
        from plyer import notification

        notification.notify(
            title="WR Voice v1.0 BETA",
            message="Activ — apasă Caps Lock pentru a dicta",
            app_name="WR Voice",
            timeout=3,
        )
    except Exception:
        pass



_TOOLTIP_LABELS = {
    "idle":       "WR Voice — Gata",
    "loading":    "WR Voice — Incarc...",
    "recording":  "WR Voice — Inregistrare",
    "processing": "WR Voice — Procesez...",
    "done":       "WR Voice — Gata",
    "disabled":   "WR Voice — Dezactivat",
}


def set_state(s):
    global current_state
    current_state = s
    if root:
        root.after(0, lambda: _redraw(s))
    if tray_icon:
        try:
            tray_icon.title = _TOOLTIP_LABELS.get(s, "WR Voice")
        except Exception:
            pass
    if s == "recording":
        _start_tray_animation()
    else:
        _stop_tray_animation(s)


def _redraw(s):
    if not root or not root.winfo_exists():
        return
    _stop_wave()
    _stop_loading()

    if s == "idle":
        root.withdraw()
    elif s == "loading":
        root.deiconify()
        _start_loading()
    elif s == "recording":
        root.deiconify()
        _start_wave()
    elif s == "processing":
        root.deiconify()
        _start_loading()
    elif s == "done":
        root.withdraw()


# ──────────────────────────────────────────────────────────
#  PILL DRAW
# ──────────────────────────────────────────────────────────
def _pill_base(border="#141420"):
    wave_canvas.delete("all")
    bg = "#0a0a0a"
    r = PILL_H // 2
    # Body
    wave_canvas.create_oval(0, 0, PILL_H, PILL_H, fill=bg, outline="")
    wave_canvas.create_oval(
        PILL_W - PILL_H, 0, PILL_W, PILL_H, fill=bg, outline="")
    wave_canvas.create_rectangle(
        r, 0, PILL_W - r, PILL_H, fill=bg, outline="")
    # Border
    wave_canvas.create_arc(
        1, 1, PILL_H - 1, PILL_H - 1,
        start=90, extent=180, outline=border, width=1, style="arc")
    wave_canvas.create_arc(
        PILL_W - PILL_H + 1, 1, PILL_W - 1, PILL_H - 1,
        start=270, extent=180, outline=border, width=1, style="arc")
    wave_canvas.create_line(
        r, 0, PILL_W - r, 0, fill=border, width=1)
    wave_canvas.create_line(
        r, PILL_H - 1, PILL_W - r, PILL_H - 1, fill=border, width=1)


def _draw_logo(color=None):
    c = color or GREEN
    if logo_tk:
        wave_canvas.create_image(
            PAD + LOGO_SZ // 2 + 2, PILL_H // 2,
            image=logo_tk, anchor="center")
    else:
        wave_canvas.create_text(
            PAD + LOGO_SZ // 2 + 2, PILL_H // 2,
            text="W", fill=c,
            font=("Consolas", 22, "bold"))


def _draw_idle_bars():
    _pill_base("#1a1a2a")
    _draw_logo(DIM)


def _draw_done():
    _pill_base(GREEN)
    _draw_logo()
    cx = BARS_X + BARS_W // 2
    display = last_transcribed[:28] + "..." if len(
        last_transcribed) > 28 else last_transcribed
    if not display:
        display = "\u2713 Gata"
    wave_canvas.create_text(
        cx, PILL_H // 2, text=display,
        font=("Consolas", 8), fill=GREEN, width=BARS_W)


def _draw_bars():
    _pill_base(GREEN3)
    _draw_logo()
    bw = 3
    gap = (BARS_W - NUM_BARS * bw) / (NUM_BARS + 1)
    for i in range(NUM_BARS):
        x1 = BARS_X + gap + i * (bw + gap)
        x2 = x1 + bw
        h = max(2, bar_current[i] * (PILL_H - 8))
        y1 = (PILL_H - h) / 2
        y2 = (PILL_H + h) / 2
        wave_canvas.create_rectangle(
            x1, y1, x2, y2, fill=GREEN, outline="")


def _draw_processing():
    global _pulse_phase
    _pulse_phase += 0.08
    t_pulse = (math.sin(_pulse_phase) + 1) / 2  # 0..1
    bright = int(t_pulse * 0xff)
    dim_val = int(0x44 + t_pulse * 0x44)
    logo_color = f"#{0:02x}{bright:02x}{int(bright * 0.53):02x}"
    border_c = f"#{0:02x}{dim_val:02x}{int(dim_val * 0.4):02x}"
    _pill_base(border_c)
    _draw_logo(logo_color)
    # Dim idle bars — gives "alive" feeling during processing
    bw = 3
    gap = (BARS_W - NUM_BARS * bw) / (NUM_BARS + 1)
    t = time.time()
    for i in range(NUM_BARS):
        speed = 1.5 + i * 0.4  # 1/3 of recording speed
        phase = i * 0.7
        wave = math.sin(t * speed + phase)
        h = max(2, (0.12 + wave * 0.06) * (PILL_H - 8))
        x1 = BARS_X + gap + i * (bw + gap)
        x2 = x1 + bw
        y1 = (PILL_H - h) / 2
        y2 = (PILL_H + h) / 2
        # 15% opacity green → mix with black bg (#0a0a0a)
        wave_canvas.create_rectangle(
            x1, y1, x2, y2, fill="#003316", outline="")


# ──────────────────────────────────────────────────────────
#  ANIMATIONS
# ──────────────────────────────────────────────────────────
def _start_wave():
    global wave_anim_id
    if wave_anim_id is None:
        _anim_wave()


def _stop_wave():
    global wave_anim_id
    if wave_anim_id:
        root.after_cancel(wave_anim_id)
        wave_anim_id = None


def _anim_wave():
    global wave_anim_id
    if current_state != "recording":
        # Fade bars down smoothly then hand off to processing anim
        any_active = False
        for i in range(NUM_BARS):
            bar_current[i] += (0.0 - bar_current[i]) * 0.3
            if bar_current[i] > 0.01:
                any_active = True
        if any_active:
            _draw_bars()
            wave_anim_id = root.after(33, _anim_wave)
        else:
            wave_anim_id = None
        return
    with audio_lock:
        level = audio_level
    t = time.time()
    for i in range(NUM_BARS):
        # Each bar has its own speed and phase
        speed = 5.0 + i * 1.3
        phase = i * 0.7
        wave = math.sin(t * speed + phase) * 0.3
        center_boost = 1.0 - abs(i - NUM_BARS / 2) / (
            NUM_BARS / 2) * 0.25
        bar_targets[i] = max(0.15, min(
            1.0, (level * center_boost + wave)
            * random.uniform(0.9, 1.1)))
    for i in range(NUM_BARS):
        bar_current[i] += (
            bar_targets[i] - bar_current[i]) * 0.22
    _draw_bars()
    wave_anim_id = root.after(33, _anim_wave)


def _start_loading():
    global loading_anim_id
    if loading_anim_id is None:
        _anim_loading()


def _stop_loading():
    global loading_anim_id
    if loading_anim_id:
        root.after_cancel(loading_anim_id)
        loading_anim_id = None


def _anim_loading():
    global loading_anim_id
    if current_state not in ("loading", "processing"):
        loading_anim_id = None
        return
    _draw_processing()
    loading_anim_id = root.after(50, _anim_loading)


# ──────────────────────────────────────────────────────────
#  PUSH-TO-TALK
# ──────────────────────────────────────────────────────────
def on_press():
    global is_recording, key_held, _target_hwnd, _target_context
    if key_held or model is None or current_state in ("loading", "processing"):
        return
    # Drain stale audio from previous recordings
    while not audio_queue.empty():
        try:
            audio_queue.get_nowait()
        except Exception:
            pass
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    _target_hwnd = hwnd if hwnd else _last_active_win_hwnd
    _target_context = get_context(load_cfg().get("context", "auto"))
    print(f"[WR Voice] on_press: context={_target_context} hwnd={_target_hwnd}")
    key_held = True
    is_recording = True
    set_state("recording")
    threading.Thread(target=_record_loop, daemon=True).start()


def on_release():
    global is_recording, key_held
    if not key_held:
        return
    key_held = False
    is_recording = False
    # Show processing pill immediately (W pulse) while audio is validated + transcribed
    set_state("processing")
    threading.Thread(target=_process, daemon=True).start()


def _record_loop():
    global audio_level
    frames = []

    def cb(indata, n, t, st):
        global audio_level
        with audio_lock:
            audio_level = min(1.0, float(np.sqrt(np.mean(indata**2))) * 120)
            audio_level = max(0.3, audio_level)
        frames.append(indata.copy())

    with sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=cb
    ):
        while is_recording:
            time.sleep(0.03)

    with audio_lock:
        audio_level = 0.0

    if frames:
        audio_queue.put(np.concatenate(frames, axis=0))


def _transcript_is_suspicious(text, duration_s):
    """Detect probable hallucination: >5 words/second is abnormal."""
    words = len(text.split())
    if duration_s <= 0:
        return True
    wps = words / duration_s
    if wps > 5.0:
        print(f"[WR Voice] Suspicious transcript: {words} words / {duration_s:.2f}s = {wps:.1f} w/s (>5.0) — halucinatie probabila")
        return True
    return False


# ── Hallucination guards ────────────────────────────────────────────────
_RE_ONLY_PUNCT = re.compile(r"^[\s\W]+$")
_RE_ONLY_DIGITS = re.compile(r"^[\d\s]+$")
_RE_ROMANIAN_CHARS = re.compile(r"[a-zA-ZăâîșțĂÂÎȘȚ]")

_RE_YOUTUBE_PHRASES = re.compile(
    r"(Îți mulțumesc pentru vizionare"
    r"|Nu uita să dai subscribe"
    r"|Să ne vedem la următoarea"
    r"|Like și share"
    r"|Apasă pe clopoțel)",
    re.IGNORECASE,
)


def _similarity_ratio(a: str, b: str) -> float:
    """Character-level similarity ratio (0.0–1.0) via SequenceMatcher."""
    if not a or not b:
        return 0.0
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _is_hallucination(text: str, initial_prompt: str) -> bool:
    """Return True if the transcript looks like a Whisper hallucination."""
    if not text:
        return True

    stripped = text.strip()

    # c) Text under 2 characters
    if len(stripped) < 2:
        print(f"[WR Voice] Hallucination guard: text sub 2 caractere — ignorat")
        return True

    # b) Only punctuation or special characters
    if _RE_ONLY_PUNCT.match(stripped):
        print(f"[WR Voice] Hallucination guard: doar punctuatie/caractere speciale — ignorat")
        return True

    # a) Too similar to initial_prompt (>80%)
    if initial_prompt:
        sim = _similarity_ratio(stripped, initial_prompt)
        if sim > 0.75:
            print(f"[WR Voice] Hallucination guard: similaritate cu initial_prompt {sim:.0%} > 75% — ignorat")
            return True

    # d) Only digits or no Romanian/Latin characters
    if _RE_ONLY_DIGITS.match(stripped):
        print(f"[WR Voice] [WARN] Hallucination guard: doar cifre — ignorat")
        return True
    if not _RE_ROMANIAN_CHARS.search(stripped):
        print(f"[WR Voice] [WARN] Hallucination guard: fara caractere romanesti/latine — ignorat")
        return True

    # e) YouTube boilerplate phrases (Whisper hallucinates these from silence)
    m = _RE_YOUTUBE_PHRASES.search(stripped)
    if m:
        print(f"[WR Voice] [WARN] Hallucination guard: fraza YouTube detectata ({m.group()!r}) — ignorat")
        return True

    return False


def _audio_is_valid(audio_data):
    """Check audio quality. Returns (bool, reason_string)."""
    duration_s = len(audio_data) / SAMPLE_RATE
    rms = float(np.sqrt(np.mean(audio_data ** 2)))
    peak = float(np.max(np.abs(audio_data)))
    print(f"[WR Voice] Audio check: duration={duration_s:.2f}s, rms={rms:.4f}, peak={peak:.4f}")

    if duration_s < 0.35:
        return False, f"Clip prea scurt ({duration_s:.2f}s < 0.35s) — tap accidental"
    if peak < 0.015:
        return False, f"Peak prea mic ({peak:.4f} < 0.015) — zgomot de fond pur"
    if rms < 0.004:
        return False, f"RMS prea mic ({rms:.4f} < 0.004) — aproape-silenta"
    if duration_s < 0.8 and rms < 0.012:
        return False, f"Clip scurt + silentios ({duration_s:.2f}s, rms={rms:.4f}) — combinat reject"
    print(f"[WR Voice] Audio check: PASS rms={rms:.4f}")
    return True, "OK"


def _process():
    global last_transcribed
    try:
        audio_data = audio_queue.get(timeout=5)

        # ── Gardă anti-halucinaţii: validare audio ───────────────────────
        valid, reason = _audio_is_valid(audio_data)
        if not valid:
            print(f"[WR Voice] Audio rejected: {reason}")
            set_state("idle")
            return
        duration_s = len(audio_data) / SAMPLE_RATE
        # ───────────────────────────────────────────────────────────────────

        set_state("processing")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio_data, SAMPLE_RATE)
            path = tmp.name

        cfg = load_cfg()
        lang = cfg.get("language", "auto")
        if lang not in LANGUAGE_LABELS:
            lang = "auto"
        use_vad = cfg.get("use_vad", False)
        # auto → None (Whisper auto-detects), otherwise pass lang code
        whisper_lang = None if lang == "auto" else lang
        initial_prompt = _build_initial_prompt(lang)

        print(
            f"[WR Voice] Transcribing: lang={lang}, "
            f"model={active_model_name}, beam_size=2, VAD=ON"
        )

        # Hotwords: defaults + user-customizable from config
        if lang == "ro":
            default_hw = DEFAULT_HOTWORDS_RO
        elif lang == "en":
            default_hw = DEFAULT_HOTWORDS_EN
        else:
            default_hw = DEFAULT_HOTWORDS_RO + " " + DEFAULT_HOTWORDS_EN
        user_hw = cfg.get("hotwords", "")
        hotwords_str = (default_hw + " " + user_hw).strip() if user_hw else default_hw

        transcribe_kwargs = dict(
            language=whisper_lang,
            beam_size=2,
            temperature=0.0,
            initial_prompt=initial_prompt,
            hotwords=hotwords_str,
            condition_on_previous_text=False,
            word_timestamps=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=400,
                threshold=0.35,
            ),
        )

        t0 = time.time()
        segments, _ = model.transcribe(path, **transcribe_kwargs)
        raw = " ".join(s.text for s in segments).strip()
        print(f"[WR Voice] Transcription time: {time.time()-t0:.2f}s")
        custom_corrections = cfg.get("custom_corrections", {})
        raw = quick_fix(raw, custom_corrections)
        raw = raw.strip().lstrip(",.").strip()
        raw = _fix_punctuation(raw)
        print(f"[WR Voice] Raw: '{raw}'")

        try:
            os.unlink(path)
        except Exception:
            pass

        # ── Hallucination guards ──────────────────────────────────────────
        if _is_hallucination(raw, initial_prompt):
            set_state("idle")
            return

        if _transcript_is_suspicious(raw, duration_s):
            set_state("idle")
            return

        if not raw:
            print("[WR Voice] Empty transcription - nothing to paste")
            set_state("idle")
            return

        command = detect_command(raw)
        if command:
            last_transcribed = raw
            print(f"[WR Voice] Comanda: {command}")
            execute_command(
                command,
                target_hwnd=_target_hwnd,
                after_callback=lambda: register_keybind(
                    load_cfg().get("keybind", "caps lock")
                ),
            )
            set_state("idle")
            rebuild_tray_menu()
            return

        context = _target_context
        cleanup_level = get_effective_cleanup_level(cfg.get("cleanup_level", 2), context)
        print(
            f"[WR Voice] Cleanup: context={context} level={cleanup_level}"
        )

        cleaned = clean(raw, cleanup_level, language=lang)
        print(f"[WR Voice] Cleaned: '{cleaned}'")
        last_transcribed = cleaned

        add_to_history(cleaned)

        _restore_target_window(_target_hwnd)
        _clipboard_set(cleaned)
        print("[WR Voice] Clipboard OK (pyperclip)")
        _send_ctrl_v()
        print("[WR Voice] Paste sent (Ctrl+V)")

        set_state("idle")
        rebuild_tray_menu()

    except Exception as e:
        import traceback

        print(f"[WR Voice] PROCESS ERROR: {e}")
        traceback.print_exc()

    finally:
        # ALWAYS reset state so pill never stays stuck
        if current_state == "processing":
            set_state("idle")
        # Drain stale audio
        while not audio_queue.empty():
            try:
                audio_queue.get_nowait()
            except Exception:
                pass


# ──────────────────────────────────────────────────────────
#  KEYBIND MANAGEMENT
# ──────────────────────────────────────────────────────────
_current_hotkey = None


def register_keybind(key):
    global _current_hotkey
    try:
        if _current_hotkey:
            try:
                keyboard.remove_hotkey(_current_hotkey)
            except Exception:
                pass
        keyboard.on_press_key(key, lambda e: on_press(), suppress=True)
        keyboard.on_release_key(key, lambda e: on_release(), suppress=True)
        _current_hotkey = key
        print(f"[WR Voice] Keybind setat: {key.upper()}")
    except Exception as e:
        print(f"[WR Voice] Eroare keybind: {e}")


def change_keybind(new_key):
    set_value("keybind", new_key)
    register_keybind(new_key)
    rebuild_tray_menu()


# ──────────────────────────────────────────────────────────
#  TRAY MENU
# ──────────────────────────────────────────────────────────
def rebuild_tray_menu():
    if tray_icon is None:
        return
    new_menu = _build_menu()

    # pystray API: assign .menu directly (update_menu() no longer takes args)
    def _do_update():
        try:
            tray_icon.menu = new_menu
        except Exception:
            pass

    if root:
        root.after(0, _do_update)
    else:
        _do_update()


def _make_model_setter(m):
    def setter(icon, item):
        threading.Thread(
            target=lambda: load_model(m, persist_selection=True),
            daemon=True,
        ).start()

    return setter


def _make_cleanup_setter(lvl):
    def setter(icon, item):
        set_value("cleanup_level", lvl)
        rebuild_tray_menu()

    return setter


def _make_context_setter(ctx):
    def setter(icon, item):
        set_value("context", ctx)
        rebuild_tray_menu()

    return setter


def _make_lang_setter(lang):
    def setter(icon, item):
        set_value("language", lang)
        rebuild_tray_menu()

    return setter


def _make_history_copier(text):
    def copier(icon, item):
        pyperclip.copy(text)

    return copier


def _quit_app():
    """Clean shutdown: unhook keyboard, stop tray, exit."""
    try:
        keyboard.unhook_all()
    except Exception:
        pass
    try:
        if tray_icon:
            tray_icon.stop()
    except Exception:
        pass
    os._exit(0)


def _toggle_enabled(icon, item):
    global current_state
    if current_state == "disabled":
        set_state("idle")
        cfg = load_cfg()
        register_keybind(cfg.get("keybind", "caps lock"))
        print("[WR Voice] Activat — keybind inregistrat")
    else:
        keyboard.unhook_all()
        set_state("disabled")
        print("[WR Voice] Dezactivat — CapsLock liber")
    rebuild_tray_menu()


def _toggle_autostart(icon, item):
    cfg = load_cfg()
    new_val = not cfg.get("autostart", False)
    set_autostart(new_val)
    rebuild_tray_menu()


def _build_menu():
    cfg = load_cfg()
    current_model = cfg.get("model", "large-v3")
    current_key = cfg.get("keybind", "caps lock")
    current_lang = cfg.get("language", "auto")
    if current_lang not in LANGUAGE_LABELS:
        current_lang = "auto"
    autostart = cfg.get("autostart", False)
    history = cfg.get("history", [])
    enabled = current_state != "disabled"
    short_title = _last_active_title[:30] + "..." if len(_last_active_title) > 30 else _last_active_title
    if not short_title:
        short_title = _last_active_proc or "(necunoscuta)"

    model_items = []
    recommended = DEFAULT_MODEL_KEY
    for model_name in get_selectable_model_keys():
        label = get_model_menu_label(model_name)
        if model_name == recommended:
            label += " *"
        if model_name == current_model:
            label = "> " + label
        model_items.append(pystray.MenuItem(label, _make_model_setter(model_name)))

    lang_items = [
        pystray.MenuItem(
            ("> " if current_lang == "auto" else "  ") + "Auto",
            _make_lang_setter("auto"),
        ),
        pystray.MenuItem(
            ("> " if current_lang == "ro" else "  ") + "Romana",
            _make_lang_setter("ro"),
        ),
        pystray.MenuItem(
            ("> " if current_lang == "en" else "  ") + "English",
            _make_lang_setter("en"),
        ),
    ]

    history_items = []
    if history:
        for item_text in history[:5]:
            short = item_text[:45] + "..." if len(item_text) > 45 else item_text
            history_items.append(pystray.MenuItem(short, _make_history_copier(item_text)))
    else:
        history_items.append(pystray.MenuItem("(gol)", None, enabled=False))

    command_items = []
    for trigger, description in COMMAND_LIST:
        command_items.append(pystray.MenuItem(f"{trigger} -> {description}", None, enabled=False))

    cleanup_level_cfg = cfg.get("cleanup_level", 2)
    context_cfg = cfg.get("context", "auto")

    cleanup_items = []
    for lvl in range(1, 5):
        lvl_label = ("> " if lvl == cleanup_level_cfg else "  ") + LEVEL_LABELS.get(lvl, str(lvl))
        cleanup_items.append(pystray.MenuItem(lvl_label, _make_cleanup_setter(lvl)))

    context_items = []
    for ctx in ["auto", "casual", "formal", "document", "raw"]:
        ctx_label = ("> " if ctx == context_cfg else "  ") + CONTEXT_LABELS.get(ctx, ctx.capitalize())
        context_items.append(pystray.MenuItem(ctx_label, _make_context_setter(ctx)))

    toggle_label = "|| Dezactiveaza" if enabled else "> Activeaza"

    state_display = {
        "idle": "Gata",
        "loading": "Se incarca...",
        "recording": "Inregistrare...",
        "processing": "Procesez...",
        "done": "Gata",
        "disabled": "Dezactivat",
    }
    status_label = f"WR Voice - {state_display.get(current_state, 'Gata')}"

    return pystray.Menu(
        pystray.MenuItem("Afiseaza / Ascunde", _toggle_pill, default=True, visible=False),
        pystray.MenuItem(status_label, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"WR Voice v{VERSION}", None, enabled=False),
        pystray.MenuItem(f"Keybind: {current_key.upper()}", None, enabled=False),
        pystray.MenuItem(
            f"Model: {get_model_display_label(current_model)}",
            pystray.Menu(*model_items),
        ),
        pystray.MenuItem(
            f"Limba: {LANGUAGE_LABELS.get(current_lang, 'Auto')}",
            pystray.Menu(*lang_items),
        ),
        pystray.MenuItem(
            f"Cleanup: {LEVEL_LABELS.get(cleanup_level_cfg, str(cleanup_level_cfg))}",
            pystray.Menu(*cleanup_items),
        ),
        pystray.MenuItem(
            f"Context: {CONTEXT_LABELS.get(context_cfg, context_cfg.capitalize())}",
            pystray.Menu(*context_items),
        ),
        pystray.MenuItem(f"Fereastra: {short_title}", None, enabled=False),
        pystray.MenuItem("Comenzi vocale", pystray.Menu(*command_items)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Istoric", pystray.Menu(*history_items)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(toggle_label, _toggle_enabled),
        pystray.MenuItem(
            "Pornire cu Windows " + ("[x]" if autostart else "[ ]"),
            _toggle_autostart,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Inchide", lambda i, m: _quit_app()),
    )

# ──────────────────────────────────────────────────────────
#  TRAY ICON
# ──────────────────────────────────────────────────────────
def _make_tray_icon(state="idle"):
    _STATE_COLORS = {
        "idle":       (0, 255, 119, 255),
        "recording":  (255, 80,  80,  255),
        "recording_dim": (120, 30, 30, 255),
        "loading":    (0,  180, 255, 255),
        "processing": (0,  180, 255, 255),
        "done":       (0,  255, 119, 255),
        "disabled":   (60,  60,  80,  255),
    }
    border = _STATE_COLORS.get(state, _STATE_COLORS["idle"])
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([1, 1, size - 2, size - 2], fill=(10, 10, 18, 255))
    d.ellipse([1, 1, size - 2, size - 2], outline=border, width=3)
    dot_r = 5
    d.ellipse([size - dot_r * 2 - 3, 3, size - 4, dot_r * 2 + 3], fill=border)
    try:
        from PIL import ImageFont
        font = ImageFont.truetype("C:\\Windows\\Fonts\\consola.ttf", 20)
    except Exception:
        font = ImageFont.load_default()
    try:
        bbox = d.textbbox((0, 0), "WR", font=font)
        tx = (size - (bbox[2] - bbox[0])) // 2 - bbox[0]
        ty = (size - (bbox[3] - bbox[1])) // 2 - bbox[1] - 2
    except Exception:
        tx, ty = 14, 22
    d.text((tx, ty), "WR", fill=border, font=font)
    return img


def _get_tray_image(state="idle"):
    if (
        state in ("idle", "done", "disabled")
        and LOGO_PATH
        and LOGO_PATH.endswith(".png")
        and os.path.exists(LOGO_PATH)
    ):
        try:
            img = Image.open(LOGO_PATH).convert("RGBA")
            img = img.resize((64, 64), RESAMPLE)
            return img
        except Exception:
            pass
    return _make_tray_icon(state)


def _make_recording_overlay(bright=True):
    """PNG logo with a pulsing red recording dot overlay."""
    if LOGO_PATH and LOGO_PATH.endswith(".png") and os.path.exists(LOGO_PATH):
        try:
            base = Image.open(LOGO_PATH).convert("RGBA")
            base = base.resize((64, 64), RESAMPLE)
            d = ImageDraw.Draw(base)
            dot_color = (255, 80, 80, 255) if bright else (120, 30, 30, 255)
            d.ellipse([44, 2, 60, 18], fill=dot_color)
            return base
        except Exception:
            pass
    return _make_tray_icon("recording" if bright else "recording_dim")


def _start_tray_animation():
    global _tray_anim_running, _tray_anim_thread
    if _tray_anim_running:
        return
    _tray_anim_running = True

    def _anim():
        toggle = True
        while _tray_anim_running and tray_icon:
            try:
                tray_icon.icon = _make_recording_overlay(bright=toggle)
            except Exception:
                pass
            toggle = not toggle
            time.sleep(0.5)

    _tray_anim_thread = threading.Thread(target=_anim, daemon=True)
    _tray_anim_thread.start()


def _stop_tray_animation(state="idle"):
    global _tray_anim_running
    _tray_anim_running = False
    try:
        if tray_icon:
            tray_icon.icon = _get_tray_image(state)
    except Exception:
        pass


def _toggle_pill(icon, item):
    if root:
        def _do():
            if root.winfo_ismapped():
                root.withdraw()
            else:
                root.deiconify()
        root.after(0, _do)


def create_tray():
    global tray_icon
    img = _get_tray_image("idle")
    tray_icon = pystray.Icon("WRVoice", img, "WR Voice — Gata", _build_menu())
    tray_icon.run()


# ──────────────────────────────────────────────────────────
#  UI — Pill overlay
# ──────────────────────────────────────────────────────────
def build_ui():
    global root, wave_canvas, logo_tk

    root = tk.Tk()
    try:
        ico_path = os.path.join(ROOT_DIR, "assets", "logo.ico")
        if os.path.exists(ico_path):
            root.iconbitmap(ico_path)
        else:
            img = Image.open(LOGO_PATH).convert("RGBA")
            size = max(img.size)
            square = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            square.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
            ico_path = os.path.join(ROOT_DIR, "assets", "logo.ico")
            os.makedirs(os.path.dirname(ico_path), exist_ok=True)
            square.save(
                ico_path,
                format="ICO",
                sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
            )
            root.iconbitmap(ico_path)
        print("[WR Voice] Iconita taskbar setata")
    except Exception as e:
        print(f"[WR Voice] Iconita taskbar error: {e}")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-transparentcolor", TRANSP)
    root.configure(bg=TRANSP)
    root.geometry(f"{PILL_W}x{PILL_H}")
    root.withdraw()  # Ascuns la start

    # Pozitionare: centrat orizontal, deasupra taskbar (~100px de jos)
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - PILL_W) // 2
    y = sh - PILL_H - 80
    root.geometry(f"{PILL_W}x{PILL_H}+{x}+{y}")

    wave_canvas = tk.Canvas(
        root, width=PILL_W, height=PILL_H, bg=TRANSP, highlightthickness=0
    )
    wave_canvas.pack()

    # Drag pentru mutare
    _d = {}

    def ds(e):
        _d["x"] = e.x
        _d["y"] = e.y

    def dm(e):
        root.geometry(
            f"+{root.winfo_x() + e.x - _d['x']}+{root.winfo_y() + e.y - _d['y']}"
        )

    wave_canvas.bind("<ButtonPress-1>", ds)
    wave_canvas.bind("<B1-Motion>", dm)

    # Logo
    try:
        if LOGO_PATH:
            img_raw = Image.open(LOGO_PATH).convert("RGBA")
            img_raw.thumbnail((LOGO_SZ - 2, LOGO_SZ - 2), RESAMPLE)
            logo_tk = ImageTk.PhotoImage(img_raw)
        else:
            logo_tk = None
    except Exception:
        logo_tk = None

    root.protocol("WM_DELETE_WINDOW", lambda: None)


# ──────────────────────────────────────────────────────────
#  CUDA DOWNLOAD DIALOG (shown from background thread via root.after)
# ──────────────────────────────────────────────────────────
_cuda_download_done = threading.Event()
_cuda_download_ok = [False]  # mutable flag — True if DLLs ready


def _show_cuda_download_dialog(gpu_name):
    """Create the CUDA download dialog on the main thread. Returns (dlg, status_var, pct_var, bar_canvas, bar_fill)."""
    from app.cuda_runtime import TOTAL_DOWNLOAD_MB, cancel_download

    dlg = tk.Toplevel()
    dlg.title("WR Voice — CUDA Runtime")
    dlg.configure(bg=BG)
    dlg.geometry("440x210")
    dlg.resizable(False, False)
    dlg.attributes("-topmost", True)
    dlg.overrideredirect(True)
    dlg.update_idletasks()
    sx = (dlg.winfo_screenwidth() - 440) // 2
    sy = (dlg.winfo_screenheight() - 210) // 2
    dlg.geometry(f"+{sx}+{sy}")

    tk.Label(
        dlg, text=f"GPU NVIDIA detectat: {gpu_name}",
        bg=BG, fg=GREEN, font=("Consolas", 10, "bold"),
    ).pack(padx=16, pady=(16, 4), anchor="w")

    tk.Label(
        dlg, text=f"Se descarca CUDA runtime (~{TOTAL_DOWNLOAD_MB:.0f} MB, o singura data)...",
        bg=BG, fg=WHITE, font=("Consolas", 9),
    ).pack(padx=16, pady=(0, 8), anchor="w")

    # Progress bar
    bar_frame = tk.Frame(dlg, bg=GRAY, height=22)
    bar_frame.pack(fill="x", padx=16, pady=(0, 4))
    bar_frame.pack_propagate(False)
    bar_canvas = tk.Canvas(bar_frame, bg=GRAY, highlightthickness=0, height=20)
    bar_canvas.pack(fill="both", expand=True)
    bar_fill = bar_canvas.create_rectangle(0, 0, 0, 20, fill=GREEN, outline="")

    status_var = tk.StringVar(value="Se conecteaza...")
    tk.Label(dlg, textvariable=status_var, bg=BG, fg=DIM, font=("Consolas", 8)).pack(
        padx=16, anchor="w",
    )

    # Bottom row: percentage + cancel button
    bottom = tk.Frame(dlg, bg=BG)
    bottom.pack(fill="x", padx=16, pady=(4, 8))

    pct_var = tk.StringVar(value="0%")
    tk.Label(bottom, textvariable=pct_var, bg=BG, fg=GREEN, font=("Consolas", 10, "bold")).pack(
        side="left",
    )

    def _on_cancel():
        cancel_download()
        status_var.set("Anulat — se porneste pe CPU...")

    cancel_btn = tk.Button(
        bottom, text="Anuleaza (CPU)", command=_on_cancel,
        bg=GRAY, fg=WHITE, relief="flat", font=("Consolas", 9, "bold"),
        activebackground=DIM, activeforeground=WHITE, cursor="hand2", padx=8, pady=2,
    )
    cancel_btn.pack(side="right")

    return dlg, status_var, pct_var, bar_canvas, bar_fill


def _ensure_cuda_and_load_model(keybind):
    """Background thread: check GPU → download CUDA if needed → load model → register keybind."""
    from app.gpu_detect import get_gpu_info
    from app.cuda_runtime import cuda_ready, download_cuda_runtime, register_cuda_dir, CUDA_DIR

    gpu = get_gpu_info()
    need_download = False

    if gpu is None:
        print("[WR Voice] Niciun GPU NVIDIA detectat — pornire pe CPU.")
    elif cuda_ready():
        print("[WR Voice] CUDA disponibil — se inregistreaza caile")
        register_cuda_dir()
    else:
        need_download = True
        print(f"[WR Voice] GPU detectat: {gpu['name']}"
              f" — CUDA DLLs lipsesc, se descarca...")

    if need_download:
        # Ask main thread to show the download dialog
        dlg_holder = [None, None, None, None, None]  # dlg, status_var, pct_var, bar_canvas, bar_fill
        dialog_ready = threading.Event()

        def _create_dialog():
            result = _show_cuda_download_dialog(gpu["name"])
            dlg_holder[0], dlg_holder[1], dlg_holder[2], dlg_holder[3], dlg_holder[4] = result
            dialog_ready.set()

        root.after(0, _create_dialog)
        dialog_ready.wait(timeout=5)

        dlg, status_var, pct_var, bar_canvas, bar_fill = dlg_holder

        def _progress(percent, message):
            def _update():
                try:
                    bar_canvas.update_idletasks()
                    w = bar_canvas.winfo_width()
                    bar_canvas.coords(bar_fill, 0, 0, int(w * percent / 100), 20)
                    pct_var.set(f"{percent:.0f}%")
                    status_var.set(message)
                except Exception:
                    pass
            try:
                root.after(0, _update)
            except Exception:
                pass

        try:
            download_cuda_runtime(progress_callback=_progress)
            print(f"[WR Voice] CUDA runtime descarcat in {CUDA_DIR}")
            register_cuda_dir()
        except Exception as e:
            err_msg = str(e)
            if "cancelled" in err_msg.lower():
                print("[WR Voice] Download CUDA anulat de utilizator — se porneste pe CPU.")
            else:
                print(f"[WR Voice] EROARE descarcare CUDA: {e}")
                print("[WR Voice] Download esuat — se porneste pe CPU.")
                # Show error briefly
                def _show_error():
                    try:
                        status_var.set(f"Download esuat — se porneste pe CPU")
                    except Exception:
                        pass
                try:
                    root.after(0, _show_error)
                except Exception:
                    pass
                time.sleep(2)

        # Close dialog from main thread
        def _close_dlg():
            try:
                if dlg:
                    dlg.destroy()
            except tk.TclError:
                pass
        try:
            root.after(0, _close_dlg)
        except Exception:
            pass

    # Now load model (CUDA or CPU — load_model handles fallback)
    load_model()
    cfg = load_cfg()
    print(f"[WR Voice] Modelul încărcat. Înregistrez keybind: {keybind.upper()}")
    register_keybind(keybind)


# ──────────────────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────────────────
def main():
    # Beta debug console — opens a real Windows console for print() output
    cfg_early = load_cfg()
    if cfg_early.get("debug_console", False) and getattr(sys, "frozen", False):
        import ctypes as _ct
        _ct.windll.kernel32.AllocConsole()
        sys.stdout = open("CONOUT$", "w")
        sys.stderr = open("CONOUT$", "w")

        # Intercept console close to avoid Intel Fortran runtime crash
        # (PyAV's ffmpeg DLLs include Intel runtime that crashes on
        #  CTRL_CLOSE_EVENT if not handled gracefully)
        @_ct.WINFUNCTYPE(_ct.c_bool, _ct.c_ulong)
        def _console_handler(event):
            if event in (0, 2):  # CTRL_C_EVENT, CTRL_CLOSE_EVENT
                os._exit(0)
            return False
        _ct.windll.kernel32.SetConsoleCtrlHandler(_console_handler, True)

        print("[WR Voice] Beta debug console active")

    build_ui()

    cfg = load_cfg()
    keybind = cfg.get("keybind", "caps lock")

    # Tray first — user can see app is running and close via tray
    threading.Thread(target=create_tray, daemon=True).start()

    print("=" * 50)
    print(f"  WR Voice v{VERSION} — WebRapid.ro")
    print(f"  Sistem: {sys.platform}")
    print(f"  Python: {sys.version.split()[0]}")
    print(
        f"  Keybind: {keybind.upper()} (se înregistrează după încărcarea modelului)"
    )
    print("=" * 50)

    # Start background window tracking
    threading.Thread(target=_poll_active_window, daemon=True).start()

    # Background: GPU check → CUDA download if needed → model load → keybind
    threading.Thread(target=_ensure_cuda_and_load_model, args=(keybind,), daemon=True).start()

    root.mainloop()


if __name__ == "__main__":
    main()