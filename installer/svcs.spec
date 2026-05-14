# -*- mode: python ; coding: utf-8 -*-
"""
installer/svcs.spec  —  PyInstaller config for the SVCS desktop bundle.

Targets folder mode (one-dir, not one-file). One-file produces a single
.exe but pays a 5-10s extraction tax on every launch and breaks
multiprocessing on Windows. Folder mode is what Inno Setup will wrap
for the final installer; it also unblocks debugging because every
bundled file is visible in dist/.

Build commands:
    # From the repo root:
    pyinstaller installer/svcs.spec --noconfirm --clean
    # Output ends up in dist/SVCS/ next to SVCS.exe.

Things to know:
- The hiddenimports list captures modules PyInstaller's static analysis
  misses (mostly ML frameworks and Flask plugins that use dynamic
  imports). When you see a "ModuleNotFoundError" inside the frozen .exe
  but it works in source mode, add the offending name here.
- The excludes list strips ~500 MB of stuff we *never* use (tkinter,
  matplotlib's Qt backends, the Tcl/Tk runtime, paddleocr because we
  ship EasyOCR in the premium bundle, the entire test suite). Without
  these, dist/SVCS/ ends up around 3.5 GB. With them, ~1.5 GB.
- ffmpeg is NOT bundled. We expect users to have it on PATH; the GUI
  detects its absence on launch and shows a download link. We will
  bundle it for the Inno Setup installer later (June milestone).
- yolov8n.pt is bundled if present so first-launch doesn't need to
  hit the internet. RealESRGAN weights are NOT bundled (63 MB, paid
  tier only) — the GUI falls back to bicubic when they're missing.

Author: Bloodawn (KheivenD), 2026-05-14 (installer prep).
"""

import os
import sys
from pathlib import Path

# PyInstaller exposes SPECPATH; resolve repo root relative to it.
REPO_ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH injected by PyInstaller)
SRC = REPO_ROOT / "src"


# ── datas: non-Python files to bundle ─────────────────────────────────────
# Each tuple is (src_on_disk, dest_in_bundle).
datas = [
    # Flask templates — required for the dashboard to render index.html.
    (str(SRC / "gui" / "templates"), "gui/templates"),
]

# YOLOv8-nano: 6 MB, optional. Ships with the bundle so first-run
# detection works offline. ultralytics will auto-download from
# Ultralytics' hub on first miss, but that requires internet.
_yolo_pt = REPO_ROOT / "yolov8n.pt"
if _yolo_pt.exists():
    datas.append((str(_yolo_pt), "."))

# Make sure the LICENSE text travels with the binary — required by AGPL.
_license = REPO_ROOT / "LICENSE"
if _license.exists():
    datas.append((str(_license), "."))


# ── hiddenimports: modules PyInstaller's analyzer doesn't find on its own ──
hiddenimports = [
    # Flask plumbing — Werkzeug pulls in some submodules via getattr.
    "flask",
    "jinja2",
    "jinja2.ext",
    "werkzeug",
    "werkzeug.middleware",
    "werkzeug.middleware.proxy_fix",

    # Our own subpackages. Belt-and-suspenders — PyInstaller usually
    # walks these from the entry point, but explicit listings make
    # build failures more obvious.
    "gui",
    "gui.app",
    "pipeline",
    "pipeline.pipeline",
    "background_subtraction",
    "background_subtraction.background_subtraction",
    "detection",
    "detection.object_filter",
    "enhancement",
    "enhancement.enhancer",
    "utils",
    "utils.paths",
    "utils.logging_config",
    "utils.encryption",
    "utils.db",
    "demo",
    "demo.split_screen",
    "config",

    # Ultralytics ships hundreds of submodules; PyInstaller misses a
    # few because they're imported via string lookup.
    "ultralytics",
    "ultralytics.models",
    "ultralytics.models.yolo",
    "ultralytics.engine",
    "ultralytics.utils",
    "ultralytics.cfg",

    # torch dynamically imports its backends. Without these, frozen
    # builds explode with "No module named torch._C._cpu" on startup.
    "torch",
    "torch._C",
    "torchvision",

    # Cryptography backends. (The old hazmat.backends.openssl path was
    # removed in cryptography >= 42; the default backend is auto-loaded.)
    "cryptography",

    # platformdirs (used by our new utils/paths.py).
    "platformdirs",
    "platformdirs.windows",
    "platformdirs.macos",
    "platformdirs.unix",

    # scikit-image lazily imports its filter / transform submodules.
    "skimage",
    "skimage.metrics",
    "skimage.filters",

    # SciPy hidden submodules.
    "scipy.special.cython_special",
    "scipy.signal",
]


# ── excludes: drop modules we never use to keep dist size sane ────────────
# The first build came in at 4.7 GB before trimming. The big offenders
# transitively pulled by torch + skimage + matplotlib are: numba/llvmlite
# (~600 MB), sympy (~300 MB), matplotlib's full backend set (~200 MB),
# the torch test suite (~400 MB), and the pandas optional plotting/excel
# integrations. None of these are exercised by the GUI path.
excludes = [
    # GUI toolkits we don't use. matplotlib pulls these in by default.
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "wx",

    # Notebook tooling — only needed for dev experimentation, never
    # at runtime. Saves ~300 MB.
    "IPython",
    "notebook",
    "ipykernel",
    "jupyter",
    "jupyter_client",
    "jupyter_core",
    "qtconsole",
    "nbconvert",
    "nbformat",

    # Heavy data science we don't load in the GUI path.
    "sphinx",
    "pytest",
    "_pytest",
    "pytest_cov",

    # PaddleOCR / PaddlePaddle — premium plate reader uses EasyOCR
    # exclusively in the casual edition. Excluding these saves ~600 MB.
    "paddle",
    "paddleocr",
    "paddlepaddle",

    # Numba JIT compiler. skimage uses it as an optional acceleration;
    # without it, skimage falls back to pure NumPy paths which the GUI
    # already exercises during dev. Saves ~600 MB (llvmlite is the bulk).
    "numba",
    "llvmlite",

    # sympy is dragged in by torch.fx for symbolic-shape tracing. The
    # frozen GUI never traces a model — we load YOLO/Real-ESRGAN
    # weights and call them. Saves ~300 MB.
    "sympy",

    # torch's own test machinery — never needed at runtime.
    "torch.testing",
    "torch.utils.tensorboard",

    # Tensorflow has a pre-safe-import hook in PyInstaller's contrib
    # set; explicitly excluding stops the analyzer from probing it.
    "tensorflow",

    # pandas optional extras the GUI doesn't touch.
    "pandas.tests",
    "pandas.io.excel",
    "pandas.io.formats.style",
    "pandas.plotting",

    # matplotlib animation / interactive backends. We selected Agg
    # automatically; the rest is dead weight.
    "matplotlib.tests",

    # Our own test tree — never needed at runtime.
    "tests",
]


# ── Analysis / PYZ / EXE / COLLECT ────────────────────────────────────────
a = Analysis(
    [str(REPO_ROOT / "installer" / "launcher.py")],
    pathex=[str(REPO_ROOT), str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SVCS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # UPX compression sometimes trips AV scanners
    console=True,             # Keep console for v1; will switch to windowed once stable
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=str(REPO_ROOT / "installer" / "svcs.ico"),  # add when we have a real icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SVCS",
)
