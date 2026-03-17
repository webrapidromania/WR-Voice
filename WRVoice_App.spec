# -*- mode: python ; coding: utf-8 -*-
# WR Voice — standalone app exe (CUDA DLLs downloaded on first GPU launch)

from PyInstaller.utils.hooks import collect_data_files
fw_datas = collect_data_files('faster_whisper')

a = Analysis(
    ['app\\wr_voice.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('app\\Webrapid-logo-W.png', 'app'),
        ('app\\logo.png', 'app'),
        ('assets\\logo.ico', 'assets'),
        ('config.json', '.'),
        *fw_datas,
    ],
    hiddenimports=[
        'faster_whisper',
        'ctranslate2',
        'huggingface_hub',
        'sounddevice',
        'soundfile',
        'numpy',
        'pyperclip',
        'keyboard',
        'PIL',
        'pystray',
        'plyer.platforms.win.notification',
        'psutil',
        'pynvml',
        'av',
        'av.audio',
        'av.audio.stream',
        'av.container',
        'av.container.input',
        'av.container.output',
        'onnxruntime',
        'onnxruntime.capi',
        'onnxruntime.capi._pybind_state',
    ],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'torchvision', 'torchaudio',
        'transformers',
        'tensorflow', 'keras',
        'matplotlib', 'scipy', 'pandas',
        'IPython', 'jupyter', 'notebook',
        'pytest', 'unittest',
        'setuptools', 'pip', 'wheel',
        'tkinter.test', 'lib2to3',
        # Transitive junk from huggingface_hub / ctranslate2
        'pyarrow',
        'cryptography', 'bcrypt', 'paramiko',
        'uvicorn', 'fastapi', 'starlette',
        'pygments', 'rich',
        # CUDA DLLs excluded — downloaded on first GPU launch by cuda_runtime.py
        'nvidia',
    ],
    noarchive=False,
    optimize=2,
)

# Strip any nvidia CUDA DLLs that leaked through dependency scanning
_CUDA_DLL_PREFIXES = ('cublas', 'cublaslt', 'nvblas', 'cudart', 'cufft', 'curand',
                       'cusolver', 'cusparse', 'nvrtc', 'nvjitlink', 'cudnn')
a.binaries = [
    (name, src, typecode)
    for name, src, typecode in a.binaries
    if not any(name.rsplit('\\', 1)[-1].rsplit('/', 1)[-1].lower().startswith(p)
               for p in _CUDA_DLL_PREFIXES)
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WR Voice',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=['ctranslate2.dll'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\logo.ico'],
)
