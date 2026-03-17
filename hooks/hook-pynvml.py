# -*- coding: utf-8 -*-
"""
PyInstaller hook for pynvml (nvidia-ml-py).
pynvml is pure Python — it loads nvml.dll from System32 at runtime
(shipped with every NVIDIA driver). No binaries to bundle.
"""

from PyInstaller.utils.hooks import collect_data_files

# Ensure the pynvml module is fully collected (it's a single .py file)
datas = collect_data_files("pynvml")
