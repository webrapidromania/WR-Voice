# -*- mode: python ; coding: utf-8 -*-
# WR Voice Uninstaller — pywebview UI

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

webview_datas = collect_data_files('webview')
webview_imports = collect_submodules('webview')

a = Analysis(
    ['installer\\uninstall.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('installer\\uninstall.html', '.'),
        *webview_datas,
    ],
    hiddenimports=webview_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'transformers', 'numpy', 'scipy',
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
    name='Uninstall',
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
