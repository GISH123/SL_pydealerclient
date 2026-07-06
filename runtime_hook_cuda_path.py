# -*- coding: utf-8 -*-
"""
Runtime hook for the frozen app:
 - Provide a shim package 'setuptools._distutils' that redirects to stdlib 'distutils'
   (avoids KeyError when code imports setuptools._distutils.* on setuptools>=69)
 - Prepend our bundled CUDA folder to PATH (works for both onefile: _MEIPASS and onedir)
 - Respect NO_CUDA / CUDA_VISIBLE_DEVICES to simulate CPU-only runs
"""
import os, sys, importlib, types
from importlib.machinery import ModuleSpec

# Quieter TF by default
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

def _install_setuptools_distutils_shim():
    if "setuptools._distutils" in sys.modules:
        return
    try:
        base_pkg = "distutils"
        subs = [
            "__init__", "ccompiler", "errors", "spawn", "sysconfig", "version",
            "_msvccompiler", "unixccompiler", "cygwinccompiler", "text_file", "log"
        ]
        imported = {name: importlib.import_module(f"{base_pkg}.{name}") for name in subs}
        pkg_name = "setuptools._distutils"
        pkg = types.ModuleType(pkg_name)
        pkg.__package__ = pkg_name
        pkg.__path__ = []
        pkg.__spec__  = ModuleSpec(name=pkg_name, loader=None, is_package=True)
        sys.modules[pkg_name] = pkg
        for name, mod in imported.items():
            shim = f"{pkg_name}.{name}" if name != "__init__" else pkg_name
            sys.modules[shim] = mod
    except Exception:
        pass

_install_setuptools_distutils_shim()
os.environ.setdefault("SETUPTOOLS_USE_DISTUTILS", "stdlib")

def _first_existing(paths):
    for p in paths:
        if os.path.isdir(p):
            return p
    return None

try:
    no_cuda = os.environ.get("NO_CUDA", "").lower() in ("1", "true", "yes", "on")
    if no_cuda:
        # Hide all GPUs from TF; don't add CUDA DLL folder
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    else:
        exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
        base    = getattr(sys, "_MEIPASS", exe_dir)

        candidates = [
            os.path.join(base, "_internal", "cuda"),
            os.path.join(exe_dir, "_internal", "cuda"),
        ]
        cuda_dir = _first_existing(candidates)
        if cuda_dir:
            try:
                os.add_dll_directory(cuda_dir)  # Python 3.8+
            except Exception:
                pass
            os.environ["PATH"] = cuda_dir + os.pathsep + os.environ.get("PATH", "")
except Exception:
    pass
