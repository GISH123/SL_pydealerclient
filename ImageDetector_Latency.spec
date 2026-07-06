# -*- mode: python ; coding: utf-8 -*-

import os
import sys
import re
import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules
from PyInstaller.building.datastruct import TOC

# -----------------------------------------------------------------------------
# Robustly locate the folder containing this .spec (avoid __file__/cwd ambiguity)
# -----------------------------------------------------------------------------
def _get_spec_dir() -> Path:
    for a in sys.argv[1:]:
        if isinstance(a, str) and a.lower().endswith(".spec"):
            p = Path(a)
            if not p.is_absolute():
                p = (Path.cwd() / p)
            if p.exists():
                return p.resolve().parent
    return Path.cwd().resolve()

HERE = _get_spec_dir()
sys.path.insert(0, str(HERE))

PROJECT_ROOT = HERE
APP_NAME = "ImageDetector_Latency"

# ------------------------------------------------------------
# Build-time auto version bump + embed version.txt into dist
# Version format: Imagedetector_latency_v<MAJOR>_<MINOR>_<PATCH>
# Rule: 1_2_9 -> 1_3_0 (base-10 carry)
# ------------------------------------------------------------
DISPLAY_VERSION_PREFIX = "Imagedetector_latency_v"
VERSION_TXT = PROJECT_ROOT / "version.txt"

_version_re = re.compile(r"(\d+)[._](\d+)[._](\d+)$")

def _parse_display_version(s: str):
    s = (s or "").strip()
    # accept both: Imagedetector_latency_v1_2_3  OR  1_2_3  OR  1.2.3
    if s.startswith(DISPLAY_VERSION_PREFIX):
        s = s[len(DISPLAY_VERSION_PREFIX):]
        if s.startswith('v'):
            s = s[1:]
    s = s.lstrip('v')
    m = _version_re.search(s)
    if not m:
        return (1, 0, 0)
    return tuple(int(x) for x in m.groups())

def _bump_version(maj: int, minor: int, patch: int):
    patch += 1
    if patch >= 10:
        patch = 0
        minor += 1
    if minor >= 10:
        minor = 0
        maj += 1
    return maj, minor, patch

def _load_bump_write_version(path: Path) -> str:
    try:
        old = path.read_text(encoding='utf-8').strip()
    except Exception:
        old = ''
    maj, minor, patch = _parse_display_version(old)
    maj, minor, patch = _bump_version(maj, minor, patch)
    new = f"{DISPLAY_VERSION_PREFIX}{maj}_{minor}_{patch}"
    try:
        path.write_text(new + "\n", encoding='utf-8')
    except Exception as e:
        print(f"[BUILD][WARN] failed to write version.txt: {e}")
    return new

BUILD_VERSION = _load_bump_write_version(VERSION_TXT)
OUTPUT_NAME = BUILD_VERSION  # exe name + dist folder name
print(f"[BUILD] {APP_NAME} version -> {BUILD_VERSION}")


# ------------------------------------------------------------
# Pre-runtime-hook (MUST run before any TensorFlow runtime hook)
# ------------------------------------------------------------
PREHOOK = str(PROJECT_ROOT / "rthook_00_pre_tf_cuda_setuptools.py")

# ------------------------------------------------------------
# Helper (build-time gather + runtime hook file)
# ------------------------------------------------------------
import cuda_dll_placer_auto as cdp

# build-time: gather CUDA/CUDNN DLLs into dist/<app>/_internal/cuda/
CUDA_BINS = cdp.gather_cuda_binaries(dest_subdir="cuda")

# ------------------------------------------------------------
# datas: include certs folder automatically
# ------------------------------------------------------------
datas = []
cert_dir = PROJECT_ROOT / "certs"
if cert_dir.exists() and cert_dir.is_dir():
    datas.append((str(cert_dir), "certs"))


# include version.txt into dist root
try:
    datas.append((str(VERSION_TXT), '.'))
except Exception as e:
    print(f"[BUILD][WARN] failed to add version.txt to datas: {e}")

# If you also want to include other folders, add them like this:
# for d in ["models"]:
#     p = PROJECT_ROOT / d
#     if p.exists() and p.is_dir():
#         datas.append((str(p), d))

# ------------------------------------------------------------
# hiddenimports
# ------------------------------------------------------------
def _twisted_filter(name: str) -> bool:
    n = name.lower()
    # avoid collecting twisted tests (causes hypothesis/pytest warnings)
    if n.startswith("twisted.trial"):
        return False
    if ".test" in n or ".tests" in n:
        return False
    return True

hiddenimports = [
    # your dynamic import modules
    "dealerclient",
    "dealerfactory",
    "datamanager",
    "videomanager",
    "detector",
    "latency_round",
    "latency_http_service",

    # fix runtime KeyError: 'setuptools._distutils.compilers' (tflite path)
    "setuptools",
    "setuptools._distutils",
    "setuptools._distutils.compilers",
    "setuptools._distutils.ccompiler",
    "setuptools._distutils.sysconfig",
    "setuptools._distutils.spawn",
    "setuptools._distutils.errors",
    "distutils",
]

hiddenimports += collect_submodules("setuptools._distutils")
hiddenimports += collect_submodules("distutils")
hiddenimports += collect_submodules("twisted", filter=_twisted_filter)

# de-dup hiddenimports
hiddenimports = sorted(set(hiddenimports))

a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=CUDA_BINS,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[
        # IMPORTANT: MUST run before any TensorFlow runtime hook
        PREHOOK,
        # (Optional) keep your existing CUDA dll placer hook
        str(PROJECT_ROOT / "cuda_dll_placer_auto.py"),
    ],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# ------------------------------------------------------------
# Force PREHOOK to run before ANY other runtime hook (e.g. pyi_rth_tensorflow)
# NOTE: different PyInstaller versions store runtime hooks differently;
# we reorder both Analysis.runtime_hooks and the generated scripts TOC.
# ------------------------------------------------------------
def _norm_path(p: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(p))
    except Exception:
        return str(p)

_prehook_norm = _norm_path(PREHOOK)

# 1) Reorder runtime_hooks list (if available)
if hasattr(a, "runtime_hooks"):
    _rh = list(a.runtime_hooks)
    _rh = [PREHOOK] + [h for h in _rh if _norm_path(h) != _prehook_norm]
    a.runtime_hooks = _rh

# 2) Reorder the generated scripts TOC so PREHOOK executes first
try:
    _scripts = list(a.scripts)
    def _entry_path(e):
        try:
            return e[1]
        except Exception:
            return ""
    _pre = [e for e in _scripts if _norm_path(_entry_path(e)) == _prehook_norm]
    _rest = [e for e in _scripts if _norm_path(_entry_path(e)) != _prehook_norm]
    if _pre:
        a.scripts = TOC(_pre + _rest)
except Exception as _e:
    print("WARNING: could not reorder runtime hooks/scripts:", _e)


# ------------------------------------------------------------
# Remove duplicate CUDA DLLs that PyInstaller may drop into _internal root.
# Keep only the ones under "cuda/<dll>".
# ------------------------------------------------------------
cuda_names = {Path(src).name.lower() for (src, _dest) in CUDA_BINS}

filtered = []
for dest, src, typecode in a.binaries:
    dest_norm = dest.replace("\\", "/").lower()
    name = Path(dest).name.lower()

    # If it's a CUDA DLL name but NOT placed under cuda/, drop it.
    if name in cuda_names and not dest_norm.startswith("cuda/"):
        continue

    filtered.append((dest, src, typecode))

a.binaries = TOC(filtered)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=OUTPUT_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(PROJECT_ROOT / "logo.ico") if (PROJECT_ROOT / "logo.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=OUTPUT_NAME,
)