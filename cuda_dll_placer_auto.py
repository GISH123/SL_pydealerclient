# -*- coding: utf-8 -*-
"""
cuda_dll_placer.py

One-file solution used in TWO phases:

1) Build-time (imported by the .spec):
   - Detect CUDA 11 + cuDNN 8 runtime DLLs from the *dev machine* (where CUDA is installed)
   - Return a PyInstaller "binaries" list so files land in: dist/<app>/_internal/cuda/

2) Run-time (executed as a PyInstaller runtime_hook):
   - Ensure dist/<app>/_internal/cuda is added to Windows DLL search path BEFORE TensorFlow loads,
     fixing: "Could not load dynamic library 'cudart64_110.dll'" even when the DLL exists.

Usage:
- Put this file next to your .spec.
- Run: pyinstaller your.spec
- Optional env overrides (dev machine):
    CUDA_DLL_PROFILE = "safe" (default) or "core"
    CUDA_DLL_INCLUDE_NPP = "1" (default for safe) / "0"
    CUDA_DLL_INCLUDE_CUDNN_TRAIN = "0" (default) / "1"
    CUDA_DLL_DEBUG = "1" to print detailed search + copy decisions
"""

from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path
from typing import Iterable, List, Tuple, Optional, Dict

# ---------------------------
# Runtime hook (frozen app)
# ---------------------------

def _runtime_add_cuda_dll_dir() -> None:
    if os.name != "nt":
        return
    if not getattr(sys, "frozen", False):
        return

    # In PyInstaller onedir, sys._MEIPASS usually points to dist/<app>/_internal
    base = Path(getattr(sys, "_MEIPASS", Path(sys.argv[0]).resolve().parent))
    candidates = [
        base / "cuda",                 # most common: <app>/_internal/cuda
        base.parent / "cuda",          # if you ever place cuda beside _internal
        Path(sys.argv[0]).resolve().parent / "_internal" / "cuda",
        Path(sys.argv[0]).resolve().parent / "cuda",
    ]
    for p in candidates:
        if p.exists() and p.is_dir():
            try:
                os.add_dll_directory(str(p))
            except Exception:
                pass
            os.environ["PATH"] = str(p) + os.pathsep + os.environ.get("PATH", "")
            break

# Execute at import-time (only in frozen runtime)
_runtime_add_cuda_dll_dir()

# ---------------------------
# Build-time helpers (.spec)
# ---------------------------

def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip().lower() not in ("0", "false", "no", "off", "")

def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)

def _debug_enabled() -> bool:
    return _env_bool("CUDA_DLL_DEBUG", False)

def _dprint(msg: str) -> None:
    if _debug_enabled():
        print(f"[cuda_dll_placer] {msg}")

def _split_path_env() -> List[Path]:
    out: List[Path] = []
    for part in os.environ.get("PATH", "").split(os.pathsep):
        part = part.strip('"').strip()
        if not part:
            continue
        p = Path(part)
        if p.exists() and p.is_dir():
            out.append(p)
    return out

def _discover_cuda_roots() -> List[Path]:
    roots: List[Path] = []

    # Common env vars
    for k, v in os.environ.items():
        if k.upper().startswith("CUDA_PATH") and v:
            p = Path(v)
            if p.exists() and p.is_dir():
                roots.append(p)

    # Standard install location
    base = Path(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA")
    if base.exists():
        for d in base.iterdir():
            if d.is_dir() and d.name.lower().startswith("v11"):
                roots.append(d)

    # Deduplicate, prefer higher versions (v11.8 > v11.7)
    def _ver_key(p: Path) -> tuple:
        m = __import__("re").match(r"v(\d+)\.(\d+)", p.name.lower())
        if m:
            return (int(m.group(1)), int(m.group(2)))
        return (0, 0)

    uniq: Dict[str, Path] = {}
    for r in roots:
        uniq[str(r).lower()] = r
    roots = list(uniq.values())
    roots.sort(key=_ver_key, reverse=True)
    return roots

def _candidate_search_dirs() -> List[Path]:
    dirs: List[Path] = []
    # CUDA roots
    for root in _discover_cuda_roots():
        for sub in ("bin", r"lib\x64"):
            p = root / sub
            if p.exists():
                dirs.append(p)

    # Conda/venv typical DLL dirs (in case cuDNN lives there)
    try:
        sp = Path(sys.prefix)
        for p in (sp / "Library" / "bin", sp / "DLLs"):
            if p.exists():
                dirs.append(p)
    except Exception:
        pass

    # PATH dirs last
    dirs.extend(_split_path_env())

    # Deduplicate, preserve order
    seen = set()
    out: List[Path] = []
    for d in dirs:
        key = str(d).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out

def _find_first(name: str, dirs: Iterable[Path]) -> Optional[Path]:
    for d in dirs:
        p = d / name
        if p.exists():
            return p
    return None

def _find_all(patterns: Iterable[str], dirs: Iterable[Path]) -> List[Path]:
    found: List[Path] = []
    for d in dirs:
        try:
            for pat in patterns:
                for p in d.glob(pat):
                    if p.exists() and p.is_file():
                        found.append(p)
        except Exception:
            continue
    # de-dupe by filename, prefer first in search order
    by_name: Dict[str, Path] = {}
    for p in found:
        key = p.name.lower()
        if key not in by_name:
            by_name[key] = p
    return list(by_name.values())

def gather_cuda_binaries(dest_subdir: str = "cuda") -> List[Tuple[str, str]]:
    """
    Return PyInstaller binaries list: [(absolute_path_to_dll, 'cuda'), ...]
    The dest_subdir becomes dist/<app>/_internal/<dest_subdir>/ in onedir builds.
    """
    if os.name != "nt":
        return []

    profile = _env_str("CUDA_DLL_PROFILE", "safe").strip().lower()
    include_npp = _env_bool("CUDA_DLL_INCLUDE_NPP", profile == "safe")
    include_cudnn_train = _env_bool("CUDA_DLL_INCLUDE_CUDNN_TRAIN", False)

    search_dirs = _candidate_search_dirs()
    _dprint("Search dirs:\n  " + "\n  ".join(str(p) for p in search_dirs[:30]) + ("..." if len(search_dirs) > 30 else ""))

    # Core CUDA 11 runtime deps typically required by TF GPU
    must = [
        "cudart64_110.dll",
        "cublas64_11.dll",
        "cublasLt64_11.dll",
        "cufft64_10.dll",
        "curand64_10.dll",
        "cusolver64_11.dll",
        "cusparse64_11.dll",
    ]

    # Common extras that sometimes are dynamically loaded
    nice = [
        "nvrtc64_112_0.dll",
        "nvrtc-builtins64_118.dll",
        "cuinj64_118.dll",
        "nvjpeg64_11.dll",
        "nvblas64_11.dll",
        "zlibwapi.dll",
    ]

    # cuDNN 8 (inference). Many installs use split DLLs; include all *infer* by default.
    cudnn_must = ["cudnn64_8.dll"]
    cudnn_infer_patterns = [
        "cudnn_*_infer64_8.dll",
        "cudnn_*_infer64_8.dll",
        "cudnn_ops_infer64_8.dll",
        "cudnn_cnn_infer64_8.dll",
        "cudnn_adv_infer64_8.dll",
    ]
    cudnn_train_patterns = [
        "cudnn_*_train64_8.dll",
        "cudnn_ops_train64_8.dll",
        "cudnn_cnn_train64_8.dll",
        "cudnn_adv_train64_8.dll",
    ]

    # NPP set (can be big-ish, but far smaller than full toolkit; enables some GPU image ops)
    npp = [
        "nppc64_11.dll",
        "nppial64_11.dll",
        "nppicc64_11.dll",
        "nppidei64_11.dll",
        "nppif64_11.dll",
        "nppig64_11.dll",
        "nppim64_11.dll",
        "nppist64_11.dll",
        "nppisu64_11.dll",
        "nppitc64_11.dll",
        "npps64_11.dll",
    ]

    selected: List[Path] = []

    # MUST core
    missing: List[str] = []
    for name in must:
        p = _find_first(name, search_dirs)
        if p is None:
            missing.append(name)
        else:
            selected.append(p)
    if missing:
        print("[cuda_dll_placer] WARNING: Missing core CUDA DLL(s) on build machine:\n  " + "\n  ".join(missing))

    # cuDNN infer
    cudnn_added = False
    for name in cudnn_must:
        p = _find_first(name, search_dirs)
        if p:
            selected.append(p)
            cudnn_added = True
    infer = _find_all(cudnn_infer_patterns, search_dirs)
    if infer:
        selected.extend(infer)
        cudnn_added = True
    if include_cudnn_train:
        train = _find_all(cudnn_train_patterns, search_dirs)
        selected.extend(train)

    if not cudnn_added:
        print("[cuda_dll_placer] WARNING: cuDNN DLLs not found on build machine (cudnn64_8.dll etc). GPU may fall back to CPU on production.")

    # Nice-to-have (only if found)
    for name in nice:
        p = _find_first(name, search_dirs)
        if p:
            selected.append(p)

    # NPP optional
    if include_npp:
        for name in npp:
            p = _find_first(name, search_dirs)
            if p:
                selected.append(p)

    # De-dupe by filename (prefer earlier)
    by_name: Dict[str, Path] = {}
    for p in selected:
        key = p.name.lower()
        if key not in by_name:
            by_name[key] = p

    # Avoid CUDA12 libs accidentally (cudart64_12*.dll etc) if they appear in PATH
    final: List[Path] = []
    for p in by_name.values():
        if p.name.lower().startswith(("cudart64_12", "cublas64_12", "cublaslt64_12", "cudnn64_9")):
            continue
        final.append(p)

    # Emit binaries list
    bins: List[Tuple[str, str]] = [(str(p), dest_subdir) for p in final]
    _dprint("Selected DLLs:\n  " + "\n  ".join(Path(a).name for a, _ in bins))

    return bins
