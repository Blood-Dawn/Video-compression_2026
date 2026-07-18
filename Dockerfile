# syntax=docker/dockerfile:1
#
# SVCS dashboard - server-scenario image (M4 TASK 4.2).
#
# Runs the Flask dashboard on the slim ONNX path (post-M2): object detection is
# ONNX Runtime, NOT torch, so this image is hundreds of MB rather than the 4 GB
# a torch image would be. FFmpeg comes from the distro (on PATH - utils.ffmpeg
# resolves it). Dependencies install from the committed uv.lock for
# reproducibility.
#
# Build:  docker build -t svcs:latest .
# Run:    docker run -p 5000:5000 \
#           -e SVCS_DASHBOARD_USER=operator -e SVCS_DASHBOARD_PASSWORD=secret \
#           -v "$PWD/outputs:/app/outputs" svcs:latest
#
# Author: Bloodawn (KheivenD), 2026-06-03 (TASK 4.2 - Docker image).

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
COPY yolov8n.onnx ./

EXPOSE 5000

# The dashboard binds 0.0.0.0 inside the container, so TASK 4.4 REQUIRES Basic
# Auth: provide SVCS_DASHBOARD_USER / SVCS_DASHBOARD_PASSWORD at runtime (see
# docker-compose.yml), or append --no-auth to override on a trusted network.
# --no-sync skips the first-run extras auto-install (already provisioned).
CMD ["uv", "run", "--no-sync", "python", "run_gui.py", \
     "--host", "0.0.0.0", "--no-browser", "--no-sync"]
