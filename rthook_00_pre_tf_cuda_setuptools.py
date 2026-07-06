# rthook_00_pre_tf_cuda_setuptools.py
# This runtime hook MUST execute before any TensorFlow-related runtime hook.
# - Add _internal/cuda to Windows DLL search path (os.add_dll_directory + PATH prepend)
# - Shim setuptools._distutils.compilers to avoid KeyError during TF/TFLite import chain
#
# Debug: set environment variable PYDEALER_PREHOOK_DEBUG=1 to print diagnostics.

import os
import sys
import types
from pathlib import Path

_DEBUG = os.environ.get("PYDEALER_PREHOOK_DEBUG", "").strip() == "1"

def _dprint(*args):
    if _DEBUG:
        try:
            print("[PREHOOK]", *args)
        except Exception:
            pass

# 1) Ensure Windows can find CUDA/CUDNN DLLs under: dist/<APP>/_internal/cuda
try:
    meipass = getattr(sys, "_MEIPASS", None)
    _dprint("sys._MEIPASS =", meipass)

    if meipass:
        cuda_dir = Path(meipass) / "cuda"
        _dprint("cuda_dir =", cuda_dir)

        if cuda_dir.exists():
            # Prefer modern DLL directory API (Python 3.8+)
            try:
                os.add_dll_directory(str(cuda_dir))
                _dprint("os.add_dll_directory OK")
            except Exception as e:
                _dprint("os.add_dll_directory failed:", repr(e))

            # Also prepend PATH for legacy DLL search paths and subprocesses
            old_path = os.environ.get("PATH", "")
            cuda_str = str(cuda_dir)
            if cuda_str.lower() not in old_path.lower():
                os.environ["PATH"] = cuda_str + os.pathsep + old_path
                _dprint("PATH prepended with cuda_dir")
        else:
            _dprint("cuda_dir not found (folder missing)")
except Exception as e:
    _dprint("CUDA dll path setup failed:", repr(e))

# 2) Shim for: KeyError: 'setuptools._distutils.compilers'
try:
    os.environ.setdefault("SETUPTOOLS_USE_DISTUTILS", "stdlib")
    _dprint("SETUPTOOLS_USE_DISTUTILS =", os.environ.get("SETUPTOOLS_USE_DISTUTILS"))
except Exception as e:
    _dprint("SETUPTOOLS_USE_DISTUTILS set failed:", repr(e))

def _ensure_pkg(name: str):
    if name in sys.modules:
        return sys.modules[name]
    m = types.ModuleType(name)
    m.__path__ = []  # mark as package
    sys.modules[name] = m
    return m

try:
    try:
        import setuptools  # noqa: F401
        _dprint("import setuptools OK")
    except Exception as e:
        _dprint("import setuptools failed, stubbing:", repr(e))
        _ensure_pkg("setuptools")

    try:
        import setuptools._distutils as _d  # noqa: F401
        _dprint("import setuptools._distutils OK")
    except Exception as e:
        _dprint("import setuptools._distutils failed, stubbing:", repr(e))
        _ensure_pkg("setuptools._distutils")

    if "setuptools._distutils.compilers" not in sys.modules:
        sys.modules["setuptools._distutils.compilers"] = types.ModuleType("setuptools._distutils.compilers")
        _dprint("stubbed setuptools._distutils.compilers in sys.modules")

except Exception as e:
    _dprint("setuptools shim failed:", repr(e))
