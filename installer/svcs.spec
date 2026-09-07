# -*- mode: python ; coding: utf-8 -*-
"""
installer/svcs.spec  -  PyInstaller config for the SVCS desktop bundle.

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
  ship EasyOCR instead for the optional plate reader, the entire test
  suite). Without
  these, dist/SVCS/ ends up around 3.5 GB. With them, ~1.5 GB.
- ffmpeg is NOT bundled. We expect users to have it on PATH; the GUI
  detects its absence on launch and shows a download link. We will
  bundle it for the Inno Setup installer later (June milestone).
- yolov8n.pt is bundled if present so first-launch doesn't need to
  hit the internet. RealESRGAN weights are NOT bundled (63 MB, paid
  tier only) - the GUI falls back to bicubic when they're missing.

Author: Bloodawn (KheivenD), 2026-05-14 (installer prep).
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# PyInstaller exposes SPECPATH; resolve repo root relative to it.
REPO_ROOT = Path(SPECPATH).parent  # noqa: F821  (SPECPATH injected by PyInstaller)
SRC = REPO_ROOT / "src"

# ── Build edition (R4 Phase 4) ────────────────────────────────────────────────
# One spec, two builds. SVCS_BUILD_EDITION selects which:
#   "server" (default) -> the full dashboard, exe name "SVCS" (unchanged).
#   "field"            -> offline local-compression-only, exe name "SVCS-Field",
#                         no server surface (the field edition drops RTSP/HLS at
#                         runtime via the bundled edition marker).
# Build the field exe with:  SVCS_BUILD_EDITION=field pyinstaller installer/svcs.spec
_EDITION = (os.environ.get("SVCS_BUILD_EDITION", "server") or "server").strip().lower()
if _EDITION not in ("server", "field"):
    _EDITION = "server"
_APP_NAME = "SVCS" if _EDITION == "server" else "SVCS-Field"

# Write the edition marker that gui/edition.py reads at runtime (via _MEIPASS),
# and bundle it at the frozen root so the build knows which edition it is.
_marker_dir = REPO_ROOT / "build" / "edition_marker"
_marker_dir.mkdir(parents=True, exist_ok=True)
_marker_file = _marker_dir / "edition.txt"
_marker_file.write_text(_EDITION, encoding="utf-8")

# Make our first-party packages importable while this spec executes so
# collect_submodules() below can walk them.
for _p in (str(SRC), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── First-party submodule collection ──────────────────────────────────────
# Our package layout (src/ on sys.path) plus the dual-import fallbacks
# (`try: from gui... except ModuleNotFoundError: from src.gui...`) make the
# frozen importer resolve some submodules under the canonical name (gui.app)
# and others under a `src.`-prefixed name (src.gui.app). PyInstaller's static
# analysis only collects whichever branch it happened to follow, so a module
# like src.gui.app (imported by nothing) went missing and the frozen app died
# at launch with "ModuleNotFoundError: No module named 'gui.app'". Rather than
# whack-a-mole each missing submodule, collect EVERY submodule of each
# first-party package under BOTH the canonical name and the full `src.*`
# mirror, so the import resolves no matter which name the importer derives.
# Author: Bloodawn (KheivenD), 2026-06-02 (frozen-import fix, M1 TASK 1.4).
_FIRST_PARTY_PKGS = (
    "gui", "utils", "pipeline", "detection", "enhancement",
    "background_subtraction", "compression", "demo",
)
_firstparty_hidden = ["config", "src.config"]
for _pkg in _FIRST_PARTY_PKGS:
    _firstparty_hidden += collect_submodules(_pkg)
# Full src.* mirror (src.gui.*, src.utils.*, …) for the prefixed resolutions.
_firstparty_hidden += collect_submodules("src")
_firstparty_hidden = sorted(set(_firstparty_hidden))


# ── datas: non-Python files to bundle ─────────────────────────────────────
# Each tuple is (src_on_disk, dest_in_bundle).
datas = [
    # Flask templates - required for the dashboard to render index.html.
    # Bundled under BOTH gui/templates and src/gui/templates: the frozen app
    # module resolves as `src.gui.app` (see the collect_submodules note above),
    # so Flask derives its template root_path as <bundle>/src/gui and looks for
    # templates there. Shipping both keeps it working whichever name wins.
    # Author: Bloodawn (KheivenD), 2026-06-02 (frozen template-path fix).
    (str(SRC / "gui" / "templates"), "gui/templates"),
    (str(SRC / "gui" / "templates"), "src/gui/templates"),
    # Static assets (the dashboard's JS modules + strings.js, split out of
    # index.html in TASK 1.5). Same dual-path reasoning as templates: Flask's
    # static_folder resolves relative to the app root_path (<bundle>/src/gui),
    # so ship under both gui/static and src/gui/static or the frozen dashboard
    # 404s on /static/js/*.js. Author: Bloodawn (KheivenD), 2026-06-02.
    (str(SRC / "gui" / "static"), "gui/static"),
    (str(SRC / "gui" / "static"), "src/gui/static"),
]

# YOLOv8-nano weights for the ONNX detector (M2 TASK 2.2). The slim build runs
# detection on ONNX Runtime, so it ships yolov8n.onnx (~12 MB), NOT the torch
# yolov8n.pt checkpoint (which is useless without the excluded torch). The
# detector resolves <bundle>/yolov8n.onnx at runtime. If absent, detection
# degrades to pass-through; TASK 2.4 turns these weights into an optional,
# first-run-fetchable installer component. Export once with:
#   yolo export model=yolov8n.pt format=onnx imgsz=640
_yolo_onnx = REPO_ROOT / "yolov8n.onnx"
if _yolo_onnx.exists():
    datas.append((str(_yolo_onnx), "."))

# Vendored FFmpeg (M2 TASK 2.3). build.ps1 fetches a pinned GPL win64 FFmpeg
# into tools/ffmpeg/; bundle it to <app>/ffmpeg/ so src/utils/ffmpeg.py finds
# <_MEIPASS>/ffmpeg/bin/ffmpeg.exe at runtime and the installed app never needs
# a system FFmpeg on PATH. If tools/ffmpeg isn't present (no fetch yet), the
# build still succeeds and the app falls back to PATH.
_ffmpeg_dir = REPO_ROOT / "tools" / "ffmpeg"
if _ffmpeg_dir.exists():
    datas.append((str(_ffmpeg_dir), "ffmpeg"))

# Make sure the LICENSE text travels with the binary - required by AGPL.
_license = REPO_ROOT / "LICENSE"
if _license.exists():
    datas.append((str(_license), "."))

# Edition marker (R4 Phase 4): gui/edition.py reads <bundle>/edition.txt to know
# whether this is the "server" or "field" build. Bundled at the frozen root.
datas.append((str(_marker_file), "."))


# ── hiddenimports: modules PyInstaller's analyzer doesn't find on its own ──
hiddenimports = [
    # Flask plumbing - Werkzeug pulls in some submodules via getattr.
    "flask",
    "jinja2",
    "jinja2.ext",
    "werkzeug",
    "werkzeug.middleware",
    "werkzeug.middleware.proxy_fix",

    # Our own first-party packages - collected programmatically above via
    # collect_submodules() under both the canonical (gui.app, utils.db.schema)
    # and the full src.* mirror, because the frozen importer resolves some
    # submodules under each name (see the comment at the top of this spec).
    # This replaced an explicit hand-maintained list that kept missing one
    # module at a time (gui.app, then utils.db.schema, …).
    *_firstparty_hidden,

    # M2 TASK 2.2: the SLIM default build runs object detection on ONNX
    # Runtime, NOT PyTorch - so ultralytics / torch / torchvision are NO LONGER
    # hiddenimports here and are actively EXCLUDED below. onnxruntime is the
    # inference engine instead. (gui.app imports nothing torch eagerly - the
    # detector/enhancer import torch lazily - so the frozen app starts fine
    # without it; verified by an import audit.) Author: Bloodawn (KheivenD),
    # 2026-06-03.
    "onnxruntime",
    "onnxruntime.capi",
    "onnxruntime.capi._pybind_state",

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

    # Notebook tooling - only needed for dev experimentation, never
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

    # PaddleOCR / PaddlePaddle - the optional plate reader uses EasyOCR
    # exclusively. Excluding these saves ~600 MB.
    "paddle",
    "paddleocr",
    "paddlepaddle",

    # Numba JIT compiler. skimage uses it as an optional acceleration;
    # without it, skimage falls back to pure NumPy paths which the GUI
    # already exercises during dev. Saves ~600 MB (llvmlite is the bulk).
    "numba",
    "llvmlite",

    # sympy is dragged in by torch.fx for symbolic-shape tracing. The
    # frozen GUI never traces a model - we load YOLO/Real-ESRGAN
    # weights and call them. Saves ~300 MB.
    "sympy",

    # ── M2 TASK 2.2: PyTorch + the torch detector/enhancer stack ──────────
    # The slim default build runs detection on ONNX Runtime and ships no torch.
    # Excluding the whole PyTorch + CUDA + ultralytics + Real-ESRGAN stack is
    # what drops the bundle from multi-GB to a few hundred MB. The runtime code
    # imports these only lazily and degrades gracefully (ONNX detection; bicubic
    # enhancement) when absent, so the frozen app starts and serves fine.
    # Author: Bloodawn (KheivenD), 2026-06-03.
    "torch",
    "torchvision",
    "torchaudio",
    "ultralytics",
    "basicsr",
    "realesrgan",
    "gfpgan",
    "facexlib",
    "nvidia",                 # nvidia-* CUDA runtime wheels pulled by CUDA torch
    "triton",
    # torch's own test machinery - never needed at runtime.
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

    # Our own test tree - never needed at runtime.
    "tests",
]


# ── cv2 / OpenCV explicit collection ──────────────────────────────────────
# The opencv-contrib-python 4.x wheel loads its native extension through a
# loader shim (cv2/__init__.py + config.py / config-3.py) rather than a plain
# top-level cv2.pyd. PyInstaller's static analysis followed our first-party
# `import cv2` but did NOT collect the extension binary, the config shims, or
# the cv2/data dir - so the slim build shipped with NO cv2 at all and the
# frozen app died at launch with "No module named 'cv2'" (the build smoke test
# caught it). collect_all pulls the extension binaries + config + data so the
# frozen import resolves. Keeping it explicit means a PyInstaller/opencv version
# bump can't silently drop OpenCV again.
# Author: Bloodawn (KheivenD), 2026-07-16 (frozen cv2 collection fix).
_cv2_datas, _cv2_binaries, _cv2_hidden = collect_all("cv2")
datas += _cv2_datas
hiddenimports += _cv2_hidden


# ── Analysis / PYZ / EXE / COLLECT ────────────────────────────────────────
a = Analysis(
    [str(REPO_ROOT / "installer" / "launcher.py")],
    pathex=[str(REPO_ROOT), str(SRC)],
    binaries=_cv2_binaries,
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
    name=_APP_NAME,          # "SVCS" (server) or "SVCS-Field" (R4 Phase 4)
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
    name=_APP_NAME,          # dist/SVCS (server) or dist/SVCS-Field (R4 Phase 4)
)
