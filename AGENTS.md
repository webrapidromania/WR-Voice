# AGENTS.md - WR Voice Project Guide
# WebRapid.ro - Vlad
# Last updated: 2026-03-16 (session 18)

---

## PROJECT OVERVIEW

WR Voice is a Windows speech-to-text desktop application that runs entirely offline and locally.
It dictates text into any focused window via push-to-talk (CAPS LOCK by default), using
faster-whisper (CTranslate2) for fast local inference. It includes a custom Windows installer,
a system tray interface, 4-level text cleanup (local and offline), voice commands,
hallucination guards, and quick_fix with custom corrections.

Fine-tune functionality was removed on 2026-03-14. Do not add smoke tests, menu items,
imports, or docs that expect `app.finetune_ui`, `app.finetune_worker`,
`fix_training_data.py`, or a `training_data/` workflow unless the user explicitly asks for it.

Ollama / Level 5 cleanup was permanently removed on 2026-03-14 (session 7).
Do NOT re-add Ollama integration, Level 5 cleanup, or `wr-voice-ro` model references.

Turbo RO (whisper-large-v3-turbo_ro) was permanently removed on 2026-03-16 (session 17).
Do NOT re-add `RO_MODEL_KEY`, `RO_MODEL_REPO_ID`, `RO_MODEL_LOCAL_DIR`, `is_ro_model_ready`,
`_download_and_convert_ro_model`, `_notify_ro_download_done`, or `turbo-ro` in any model list.
`DEFAULT_MODEL_KEY = "large-v3"` is the sole recommended model.

---

## HARDWARE CONTEXT

- OS: Windows 11 Pro (10.0.26100)
- GPU: NVIDIA RTX 5080 (Blackwell, sm_120, 16GB VRAM)
- CUDA: 12.8
- PyTorch: 2.9.1+cu128
- Python: 3.13.x
- Default model: `large-v3`

RTX 5080 note:
The installer has a PyTorch fallback in `installer/installer.py:check_gpu()`.
`app/gpu_detect.py` still relies on `nvidia-smi`, so runtime GPU detection can fail on some
Blackwell driver states until that fallback is mirrored there.

---

## FULL STACK

| Layer | Technology |
|---|---|
| Speech-to-text | faster-whisper 1.0+ + CTranslate2 |
| Text cleanup (4 levels) | `app/cleanup.py` — regex-based, local, offline |
| Hallucination guards | `app/wr_voice.py` — audio validation + text validation |
| UI - Installer | pywebview + HTML/CSS/JS (glassmorphism) |
| UI - Tray icon | pystray |
| UI - Pill overlay | tkinter |
| Audio capture | sounddevice + soundfile |
| Text paste | pyperclip + ctypes keybd_event |
| Hotkey detection | keyboard |
| Packaging | PyInstaller 6.x + UPX |
| Config | JSON (`config.json`) |
| Registry | winreg |
| GPU detection | nvidia-smi subprocess + installer-side PyTorch fallback |

---

## FOLDER STRUCTURE

```text
WRVoice_Source/
|-- app/
|   |-- wr_voice.py
|   |-- cleanup.py
|   |-- commands.py
|   |-- context.py
|   |-- config.py
|   |-- transcription_models.py
|   `-- gpu_detect.py
|-- installer/
|   |-- installer.py
|   |-- installer.html
|   |-- uninstall.py
|   `-- uninstall.html
|-- scripts/
|   `-- download_turbo_ro.py
|-- assets/
|   `-- logo.ico
|-- dist/
|-- build/
|-- config.json
|-- requirements.txt
|-- WRVoice_Setup.spec
|-- WRVoice_App.spec
|-- WRVoice_Beta.spec
|-- uninstall.spec
|-- AGENTS.md
|-- feature_list.json
`-- README.md
```

---

## KEY ARCHITECTURE NOTES

### Runtime Scope
`app/wr_voice.py` is the main runtime entry point and owns the tray menu, push-to-talk,
overlay state, transcription flow, clipboard paste, and tray rebuild logic.

### Transcription Pipeline
The runtime transcription pipeline in `_process()` is:
1. Audio validation (`_audio_is_valid`) — rejects short/silent clips
2. `model.transcribe()` — faster-whisper with optimized params (beam_size=5, temperature=0, condition_on_previous_text=False)
3. `quick_fix()` — regex corrections for common Whisper misrecognitions
4. `_fix_punctuation()` — comma cleanup
5. `_is_hallucination()` — rejects prompt echoes (>75% similarity), punctuation-only, <2 chars, digits-only, non-Romanian text
6. `_transcript_is_suspicious()` — rejects >5 words/second (hallucination speed)
7. `detect_command()` — voice command interception
8. `clean()` from `cleanup.py` — 4-level filler removal, capitalization, punctuation
9. Clipboard paste via ctypes

### Config Cleanup Level
`config.py` defaults `cleanup_level` to 2. The bundled `config.json` ships with
`cleanup_level` set to 2 and `context` set to `raw`.
Level 5 (Ollama) was permanently removed in session 7 (2026-03-14).

### GPU Detection Gap
If the app ever reports no GPU after install on RTX 5080 hardware, the likely cause is
`app/gpu_detect.py` missing the PyTorch fallback already implemented in the installer.

---

## COLOR PALETTE

```python
BG = "#0a0a0f"
BG2 = "#0f0f1a"
BG3 = "#141420"
GREEN = "#00ff77"
GREEN2 = "#00cc55"
GREEN3 = "#003322"
GREEN_DIM = "#001a0f"
WHITE = "#eeeeff"
GRAY = "#1c1c28"
DIM = "#444466"
DIM2 = "#2a2a3a"
RED = "#ff4466"
YELLOW = "#ffcc00"
FONT_MAIN = ("Consolas", 10)
FONT_BOLD = ("Consolas", 10, "bold")
FONT_BIG = ("Consolas", 18, "bold")
FONT_MED = ("Consolas", 12, "bold")
FONT_SMALL = ("Consolas", 9)
WIN_W = 540
WIN_H = 700
```

---

## BUILD COMMANDS

**CRITICAL ORDER — must build in this sequence:**

```bash
# Step 1: Build the main app EXE (MUST be done first — installer bundles dist/WR Voice.exe)
pyinstaller WRVoice_App.spec --noconfirm

# Step 2: Build uninstaller
pyinstaller uninstall.spec --noconfirm
cp dist/uninstall.exe installer/uninstall.exe

# Step 3: Build installer (bundles fresh WR Voice.exe + Uninstall.exe from dist/)
pyinstaller WRVoice_Setup.spec --noconfirm
cp "dist/WRVoice Setup.exe" ../WRVoice_Setup.exe
cp ../WRVoice_Setup.exe release-beta/WRVoice_Beta_v1.0.exe
```

IMPORTANT: Skipping Step 1 means the installer bundles a stale `WR Voice.exe` with old code.
This was the root cause of the tray icon + Turbo RO bugs in sessions 11-14 testing.

Build time: ~8 min (Step 1) + ~1 min (Step 2) + ~2 min (Step 3) = ~11 min total.

---

## SESSION START CHECKLIST

1. Read `AGENTS.md` (this file).
2. Read `feature_list.json`.
3. If git exists, run:
   `git log --oneline -10`
   `git diff HEAD~1 --stat`
4. Smoke test:
   `python -c "import app.wr_voice; print('imports ok')"`
   `python -c "import app.cleanup; app.cleanup.clean('test', 2); print('cleanup ok')"`
5. Check whether `../WRVoice_Setup.exe` exists and is fresh enough.

---

## SESSION END CHECKLIST

1. Update `feature_list.json`.
2. Leave code clean:
   no debug noise, no dead commented blocks, no stale references.
3. If the changes are significant, rebuild the installer.
4. If git exists and the user asked for it, prepare a commit.

---

## NAMING CONVENTIONS

- Python files: `snake_case.py`
- Functions: `snake_case`
- Private helpers: `_snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Config keys: `snake_case`
- Runtime logs: `[WR Voice] message`

---

## KNOWN ISSUES / GOTCHAS

None — all previously tracked issues have been resolved as of session 13 (2026-03-16).

### Resolved (session 12):
6. ~~Tray icon shows green circle instead of PNG logo~~ — `APP_DIR`/`ROOT_DIR` used `os.path.abspath(__file__)` which resolves against CWD in frozen onefile mode, not `_MEIPASS`. Fixed to use `sys._MEIPASS` when frozen. Also expanded `_find_logo()` search to include exe directory.
7. ~~Desktop shortcut not created by installer~~ — added step 6 in `_run_install()` that creates a `.lnk` shortcut on Desktop via PowerShell `WScript.Shell` COM. Copies `assets/logo.ico` to install dir for shortcut icon. Zero new dependencies.

### Resolved (session 11):
1. ~~`app/gpu_detect.py` fallback~~ — was already fixed in session 8 (stale entry removed).
2. ~~`uninstall.exe` must exist before installer build~~ — `WRVoice_Setup.spec` now references `dist\` directly; build chain: uninstall.spec → WRVoice_Setup.spec.
3. ~~CAPS LOCK blocked on exit~~ — added `_quit_app()` that calls `keyboard.unhook_all()` before `os._exit(0)`.
4. ~~Frameless installer lost behind windows~~ — added `self.attributes("-topmost", True)` to `InstallerApp.__init__`.
5. ~~Hallucination prompt echo threshold~~ — lowered similarity threshold from 80% to 75% for extra safety with longer `INITIAL_PROMPT_RO`.

---

## CHANGELOG SESIUNI

- **Session 4** (2026-03-14): Fine-tune removal (finetune_ui.py, finetune_worker.py, fix_training_data.py deleted).
- **Session 7** (2026-03-14): Removed Ollama/Level 5 cleanup + emoji system; added tiny/base/small/medium models to tray; fixed window detection.
- **Session 8** (2026-03-14): Fixed gpu_detect.py PyTorch fallback; removed dead config keys; pre-compiled all regex patterns.
- **Session 9** (2026-03-16):
  - `INITIAL_PROMPT_RO` extended with developer context and tech terms (Fastify, Prisma, PostgreSQL, etc.)
  - Added `_is_hallucination()` with `difflib.SequenceMatcher` — catches prompt echoes, punctuation-only, <2 chars, digits-only, non-Romanian
  - Added `clean_transcript()` then **removed it** after overlap analysis: 80%+ duplicated `cleanup.py` levels 2-3. Moved unique fillers (`mmm`, `ăm`, `eem`, `eee`, `cumva`) into `cleanup.py` `_FILLERS_RO` instead.
  - Deleted `scripts/cleanup_level5_smoke.py` (dead test for removed Level 5)
  - AGENTS.md brought fully up to date
- **Session 10** (2026-03-16):
  - Fixed Turbo RO model: removed broken manual CTranslate2 conversion from `transcription_models.py` (crashed on RTX 5080 sm_120). Set `load_target` to HuggingFace repo ID — faster-whisper handles download+conversion natively via `WhisperModel()`.
  - Deleted 6 functions + 7 constants from `transcription_models.py` (ensure_ro_model_ready, _download_ro_source, _convert_ro_source, _write_ro_metadata, _is_valid_ct2_model_dir, _has_required_ct2_files, and all RO_* constants).
  - Simplified `get_model_load_target()` — all models use same code path now.
  - Added `scripts/download_turbo_ro.py` for offline pre-conversion via `ct2-transformers-converter`.
  - Added QUICK_FIX: "Excel" → "exe".
  - Removed dead imports (json, shutil, tempfile, threading, time) from transcription_models.py.
- **Session 11** (2026-03-16):
  - Resolved ALL 5 known issues (see above).
  - Added `_quit_app()` in `wr_voice.py` — clean exit: `keyboard.unhook_all()` + `tray_icon.stop()` before `os._exit(0)`.
  - Installer now always-on-top (`-topmost` attribute) — frameless window can no longer be lost behind other windows.
  - `WRVoice_Setup.spec` updated: data paths changed from `release-beta\` to `dist\` for self-contained build chain.
  - Hallucination guard similarity threshold lowered from 80% to 75%.
  - Fixed SyntaxWarning in `scripts/download_turbo_ro.py` (unescaped backslash in docstring).
  - `feature_list.json` fully cleaned: removed 15+ stale Ollama/Level5/Emoji/fine-tune entries, updated installer/uninstaller descriptions to match current standalone-EXE flow, added hallucination guards + audio validation + quick_fix entries.
  - Built fresh `Uninstall.exe` (9.9 MB) and `WRVoice Setup.exe` (166 MB) — lightweight installer confirmed.
- **Session 12** (2026-03-16):
  - Fixed tray icon: `APP_DIR`/`ROOT_DIR` now use `sys._MEIPASS` in frozen builds instead of `os.path.abspath(__file__)` which resolved against CWD. `_find_logo()` also searches next to exe.
  - Added desktop shortcut creation to installer: step 6 in `_run_install()` uses PowerShell `WScript.Shell` COM to create `WR Voice.lnk` on Desktop with proper icon. Zero new dependencies.
  - Rebuilt `Uninstall.exe` (9.8 MB) and `WRVoice Setup.exe` (165 MB).
- **Session 13** (2026-03-16):
  - Fixed Turbo RO not loading from tray. Root cause: `get_model_load_target()` always returned the HuggingFace repo ID (`TransferRapid/whisper-large-v3-turbo_ro`) even when the local CTranslate2 model was already converted. `WhisperModel()` received an HF repo ID pointing to safetensors (Transformers format) instead of the local CTranslate2 `model.bin`.
  - Fix in `transcription_models.py`: added `RO_MODEL_LOCAL_DIR` constant + `is_ro_model_ready()` function. `get_model_load_target()` now returns the local CTranslate2 path when the model is ready, HF repo ID otherwise.
  - Fix in `wr_voice.py`: added download+conversion block in `load_model()` — if Turbo RO is selected and local model doesn't exist yet, downloads from HF and converts via CTranslate2 in background with tray tooltip "Se descarca modelul RO...". Notifies user via plyer when done, then loads from local path. Added `_download_and_convert_ro_model()`, `_notify_ro_download_done()`, and "downloading" tooltip state.
  - Local CTranslate2 model confirmed present and loads correctly: `WhisperModel(RO_MODEL_LOCAL_DIR, device="cuda", compute_type="int8_float16")` → OK.
- **Session 14** (2026-03-16):
  - Rebuilt `Uninstall.exe` (9.9 MB) and `WRVoice Setup.exe` (166 MB) with all fixes from sessions 11-13.
  - Created `release-beta/` folder in REPO root.
  - **BUG:** Step 1 (`WRVoice_App.spec`) was omitted — installer bundled old `WR Voice.exe` (Mar 15) without sessions 12-13 fixes. This caused tray icon + Turbo RO bugs to persist in the tested build.
- **Session 15** (2026-03-16):
  - Root cause found for BOTH reported bugs: `dist/WR Voice.exe` was stale (built Mar 15, before session 12). Installer always bundled this old EXE because `WRVoice_App.spec` was never run. With old code: `APP_DIR = os.path.abspath(__file__)` resolved against CWD in frozen mode → `_find_logo()` couldn't find PNG → tray showed green circle. Same EXE lacked session 13 Turbo RO fix.
  - Fixed build chain in AGENTS.md: `WRVoice_App.spec` is now **Step 1** (mandatory).
  - Full rebuild: `WR Voice.exe` (140 MB, Mar 16 01:47) → `Uninstall.exe` (9.9 MB) → `WRVoice Setup.exe` (166 MB).
  - `release-beta/WRVoice_Beta_v1.0.exe` (166 MB) updated — now contains the correct `WR Voice.exe` with all session 12+13 fixes.
- **Session 16** (2026-03-16): QUICK_FIXES overhaul — see changelog above.
- **Session 18** (2026-03-16):
  - Added 7 new QUICK_FIXES: `Test-ul→Test`, `virculele→virgulele`, `minigent→la mine`, `paid pages→pages pages`, `voia mea→vocea mea`, `Cloude→Claude`, `aplicatii→aplicatie`.
  - Added YouTube hallucination guard (`_RE_YOUTUBE_PHRASES`): Whisper sometimes hallucinates YouTube boilerplate ("Îți mulțumesc pentru vizionare", "Nu uita să dai subscribe", "Să ne vedem la următoarea", "Like și share", "Apasă pe clopoțel") from silence/noise — now caught by check (e) in `_is_hallucination()` with `[WARN]` print.
  - Full rebuild: `WR Voice.exe` (140 MB) → `Uninstall.exe` (9.9 MB) → `WRVoice Setup.exe` (166 MB, Mar 16 21:28).
  - `release-beta/WRVoice_BETA_v1.0.exe` (166 MB) created.
- **Session 17** (2026-03-16): **Turbo RO removed permanently.**
  - Deleted from `transcription_models.py`: `RO_MODEL_KEY`, `RO_MODEL_REPO_ID`, `RO_MODEL_LOCAL_DIR`, `is_ro_model_ready()`, `_RO_REQUIRED_FILES`, all turbo-ro entries from `SELECTABLE_MODEL_KEYS`, `MODEL_SPECS`, `MODEL_ALIAS_MAP`.
  - Deleted from `wr_voice.py`: imports of `RO_MODEL_KEY/REPO_ID/LOCAL_DIR/is_ro_model_ready`, `_download_and_convert_ro_model()`, `_notify_ro_download_done()`, Turbo RO intercept block in `load_model()`, `"downloading"` key from `_TOOLTIP_LABELS`.
  - Deleted `scripts/download_turbo_ro.py`.
  - `DEFAULT_MODEL_KEY` remains `"large-v3"` — sole recommended model.
  - Full rebuild: `WR Voice.exe` (140 MB) → `Uninstall.exe` (9.9 MB) → `WRVoice Setup.exe` (166 MB, Mar 16 02:48). `release-beta/WRVoice_Beta_v1.0.exe` updated.
