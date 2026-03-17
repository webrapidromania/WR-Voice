# WR Voice BETA v1.0

> Local, offline, free speech-to-text for Windows.
> Hold CAPS LOCK → speak → release → text appears at your cursor.
> No window. No UI. Just a tray icon.

![Version](https://img.shields.io/badge/version-v1.0-green)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)
![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- 100% offline — no internet required after install
- Push-to-talk with CAPS LOCK (configurable)
- Works in any focused window (Notepad, browser, IDE, etc.)
- Auto GPU detection (NVIDIA CUDA or CPU fallback)
- 4-level text cleanup (Raw / Balanced / Aggressive / Mega-aggressive)
- Hallucination guards — rejects prompt echoes, YouTube boilerplate, noise
- Voice commands (delete this, select all, cancel, send)
- Quick-fix regex corrections for common Whisper errors
- System tray only — zero UI during dictation

## Requirements

- Windows 10 / 11
- Python 3.9+
- NVIDIA GPU recommended (works on CPU, slower)
- ~5 GB disk space

## Installation

1. Download `WRVoice_BETA_v1.0_Installer.exe` from [Releases](https://github.com/webrapidromania/WR-Voice/releases)
2. Make sure Python 3.9+ is installed with "Add to PATH" checked
3. Run the installer — it detects your GPU automatically
4. Press CAPS LOCK and start speaking

## Available Models

| Model | VRAM | Quality |
|-------|------|---------|
| tiny | <2 GB | Basic |
| base | 2 GB | Good |
| small | 3 GB | Good |
| medium | 5 GB | Very good |
| large-v3 | 8 GB | Best (default) |

## How It Works

1. Hold **CAPS LOCK** → audio recording starts
2. Release **CAPS LOCK** → audio sent to faster-whisper
3. Text is cleaned (4 levels) → pasted at cursor via clipboard

## Stack

faster-whisper · CTranslate2 · pystray · tkinter · sounddevice · keyboard · PyInstaller

## Made by

[WebRapid.ro](https://webrapid.ro) · Vlad
