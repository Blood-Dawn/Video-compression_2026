# syntax=docker/dockerfile:1
#
# SVCS dashboard - server-scenario image (M4 TASK 4.2).
#
# Runs the Flask dashboard on the slim ONNX path (post-M2): object detection is
# ONNX Runtime, NOT torch, so the FINAL image is hundreds of MB rather than the
# 4 GB+ a torch image would be. FFmpeg comes from the distro (on PATH -
# utils.ffmpeg resolves it). App dependencies install from the committed
# uv.lock for reproducibility.
#
# Build:  docker build -t svcs:latest .
# Run:    docker run -p 5000:5000 \
#           -e SVCS_DASHBOARD_USER=operator -e SVCS_DASHBOARD_PASSWORD=secret \
#           -v "$PWD/outputs:/app/outputs" svcs:latest
#
# --- yolov8n.onnx (planner TASK 3.16 fix) -----------------------------------
# yolov8n.onnx and yolov8n.pt are both gitignored (*.pt, *.onnx) - neither is
# committed, so a clean `git clone` + `docker build` used to fail at
# `COPY yolov8n.onnx ./` because the file simply didn't exist in the build
# context. Root-caused and fixed here (2026-09-22) with a throwaway builder
# stage: it installs the one-time export toolchain (CPU-only torch +
# ultralytics + onnx/onnxslim, matching docs/build/onnx-models.md), lets
# ultralytics auto-download the small (~6 MB) yolov8n.pt checkpoint from its
# own release assets, exports it to ONNX, and only the resulting ~12 MB
# yolov8n.onnx file crosses into the final image. The final image still has NO
# torch in it. This does mean the FIRST `docker build` (or any build after the
# builder-stage layers are invalidated) downloads the export toolchain, so it
# is slower than a pure-cache rebuild - that is expected and is the tradeoff
# for a build that works unmodified from a genuinely clean checkout.
#
# Author: Bloodawn (KheivenD), 2026-06-03 (TASK 4.2 - Docker image).
# Fix: Bloodawn (KheivenD) + Claude, 2026-09-22 (planner TASK 3.16).

# --- Stage 1: export yolov8n.onnx (discarded after the copy below) ---------
FROM python:3.11-slim AS onnx-builder
WORKDIR /export
# CPU-only torch wheel keeps this throwaway stage from pulling a multi-GB CUDA
# build; only used to run the export, never shipped in the final image.
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
        torch torchvision \
    && pip install --no-cache-dir \
        "ultralytics>=8.0.0" \
        "onnx>=1.16.0,<1.18.0" \
        "onnxslim>=0.1.0"
# Auto-downloads yolov8n.pt (ultralytics fetches it from its own release
# assets when the checkpoint isn't already present), then exports to ONNX -
# same command as docs/build/onnx-models.md's manual dev step.
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx', imgsz=640, simplify=True)"

# --- Stage 2: the actual slim runtime image ---------------------------------
FROM python:3.11-slim

# Runtime system libs: ffmpeg (encode/probe), plus the GL/glib shared libs that
# opencv-contrib-python links against even in headless use.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# uv for fast, reproducible installs from the lockfile.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Pin the toolchain to the system Python so uv doesn't download its own.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

# --- Dependency layer (cached unless the manifests change) -------------------
# Install ONLY the core/slim dependencies (default group from uv.lock - no
# torch, no extras). --no-install-project skips building the app itself here so
# this layer stays cache-friendly and doesn't need the source tree yet.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# --- Application layer -------------------------------------------------------
COPY src/ ./src/
COPY run_gui.py ./
COPY --from=onnx-builder /export/yolov8n.onnx ./

EXPOSE 5000

# The dashboard binds 0.0.0.0 inside the container, so TASK 4.4 REQUIRES Basic
# Auth: provide SVCS_DASHBOARD_USER / SVCS_DASHBOARD_PASSWORD at runtime (see
# docker-compose.yml), or append --no-auth to override on a trusted network.
# --no-sync skips the first-run extras auto-install (already provisioned).
CMD ["uv", "run", "--no-sync", "python", "run_gui.py", \
     "--host", "0.0.0.0", "--no-browser", "--no-sync"]
