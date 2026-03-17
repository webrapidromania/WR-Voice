# -*- mode: python ; coding: utf-8 -*-
# WR Voice Setup — pywebview installer that bundles the app + uninstaller

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

webview_datas = collect_data_files('webview')
webview_imports = collect_submodules('webview')

a = Analysis(
    ['installer\\installer.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('dist\\WR Voice.exe', '.'),
        ('dist\\Uninstall.exe', '.'),
        ('Webrapid-logo-W.png', '.'),
        ('Webrapid-logo-Webrapid.png', '.'),
        ('assets\\logo.ico', 'assets'),
        ('config.json', '.'),
        ('installer\\installer.html', '.'),
        *webview_datas,
    ],
    hiddenimports=webview_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'torchvision', 'torchaudio',
        'transformers', 'tensorflow', 'keras',
        'numpy', 'scipy', 'pandas', 'matplotlib',
        'faster_whisper', 'ctranslate2',
        'sounddevice', 'soundfile',
        'keyboard', 'pyperclip', 'pystray', 'plyer',
        'IPython', 'jupyter', 'notebook',
        'pytest', 'unittest',
        'setuptools', 'pip', 'wheel',
        'tkinter', 'PIL', 'lib2to3',
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WRVoice Setup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\logo.ico'],
)
