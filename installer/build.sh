#!/usr/bin/env bash
#
# installer/build.sh - build a Linux AppImage for SVCS (M5b TASK 5b.2).
#
# Produces a single self-contained dist/SVCS-<arch>.AppImage that runs the
# dashboard on a clean Ubuntu with no Python, FFmpeg, or pip required: it bundles
# a relocatable standalone CPython (via uv), the project on the slim ONNX
# detection path (core deps only, no heavy ML extras), the yolov8n.onnx model,
# and a static FFmpeg.
#
# Linux-only (uses appimagetool). Run on Ubuntu or in the appimage CI job.
#
#   ./installer/build.sh
#
# Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5b.2 - Linux AppImage).
set -euo pipefail

HERE="$(cd "$(dirname "${0}")/.." && pwd)"   # repo root
ARCH="${ARCH:-x86_64}"
PYVER="${PYVER:-3.11}"
APPDIR="${HERE}/dist/SVCS.AppDir"
OUT="${HERE}/dist/SVCS-${ARCH}.AppImage"

echo "==> Building SVCS AppImage (arch=${ARCH}, python=${PYVER})"

command -v uv >/dev/null 2>&1 || { echo "ERROR: uv is required (https://astral.sh/uv)"; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "ERROR: curl is required"; exit 1; }

rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin" "${APPDIR}/usr/share/svcs" \
         "${APPDIR}/usr/share/applications" \
         "${APPDIR}/usr/share/icons/hicolor/256x256/apps"

# 1. Relocatable standalone CPython (uv's managed pythons are relocatable).
echo "==> [1/6] Bundling standalone Python ${PYVER}"
uv python install "${PYVER}"
SRC_PY="$(uv python find "${PYVER}")"            # .../install/bin/python3
SRC_PY_ROOT="$(dirname "$(dirname "${SRC_PY}")")"
cp -a "${SRC_PY_ROOT}" "${APPDIR}/usr/python"

# 2. Virtualenv with the project + core ONNX deps (no heavy ML extras).
echo "==> [2/6] Installing project (slim ONNX path)"
"${APPDIR}/usr/python/bin/python3" -m venv "${APPDIR}/usr/venv"
"${APPDIR}/usr/venv/bin/python" -m pip install --upgrade pip >/dev/null
"${APPDIR}/usr/venv/bin/python" -m pip install "${HERE}"

# 3. App source + entry point + detection model.
echo "==> [3/6] Staging app + model"
cp "${HERE}/run_gui.py" "${APPDIR}/usr/share/svcs/run_gui.py"
cp -r "${HERE}/src" "${APPDIR}/usr/share/svcs/src"
cp "${HERE}/yolov8n.onnx" "${APPDIR}/usr/share/svcs/yolov8n.onnx"

# 4. Static FFmpeg (LGPL/GPL static build, on PATH inside the AppImage).
echo "==> [4/6] Bundling static FFmpeg"
curl -fsSL "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-${ARCH/x86_64/amd64}-static.tar.xz" -o /tmp/ffmpeg.tar.xz
mkdir -p /tmp/ffmpeg && tar -xf /tmp/ffmpeg.tar.xz -C /tmp/ffmpeg --strip-components=1
cp /tmp/ffmpeg/ffmpeg /tmp/ffmpeg/ffprobe "${APPDIR}/usr/bin/"

# 5. AppRun, desktop entry, icon.
echo "==> [5/6] Adding AppRun + desktop + icon"
cp "${HERE}/installer/appimage/AppRun" "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"
cp "${HERE}/installer/appimage/svcs.desktop" "${APPDIR}/svcs.desktop"
cp "${HERE}/installer/appimage/svcs.desktop" "${APPDIR}/usr/share/applications/svcs.desktop"
# A minimal placeholder icon (replace with real branding before GA). 1x1 PNG.
ICON_B64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
echo "${ICON_B64}" | base64 -d > "${APPDIR}/svcs.png"
cp "${APPDIR}/svcs.png" "${APPDIR}/usr/share/icons/hicolor/256x256/apps/svcs.png"
cp "${APPDIR}/svcs.png" "${APPDIR}/.DirIcon"

# 6. Package with appimagetool.
echo "==> [6/6] Packaging with appimagetool"
TOOL="/tmp/appimagetool-${ARCH}.AppImage"
if [ ! -x "${TOOL}" ]; then
    curl -fsSL "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${ARCH}.AppImage" -o "${TOOL}"
    chmod +x "${TOOL}"
fi
# --appimage-extract-and-run lets appimagetool run without FUSE (CI has no FUSE).
ARCH="${ARCH}" "${TOOL}" --appimage-extract-and-run "${APPDIR}" "${OUT}"

echo "==> Built: ${OUT}"
ls -lh "${OUT}"
