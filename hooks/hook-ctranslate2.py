# -*- coding: utf-8 -*-
"""
PyInstaller hook for ctranslate2 — collects ctranslate2's own DLLs only.
CUDA DLLs from nvidia-* are NOT bundled; they are downloaded on first GPU
launch by cuda_runtime.py to keep the EXE small (~80-100 MB).
"""

import os
from PyInstaller.utils.hooks import collect_dynamic_libs

# Collect ctranslate2's own DLLs (ctranslate2.dll, cudnn64_9.dll, libiomp5md.dll)
# Place them in root "." so _bootstrap_cuda_dll_paths() finds them in _MEIPASS
binaries = []
for src, dst in collect_dynamic_libs("ctranslate2"):
    binaries.append((src, "."))

# DO NOT collect nvidia-* CUDA DLLs (cublas, cublasLt, nvblas, etc.)
# These are ~700+ MB and are now downloaded on demand by cuda_runtime.py

# Block transitive junk that ctranslate2/huggingface_hub pull in
excludedimports = [
    'pyarrow', 'onnxruntime', 'av',
]
