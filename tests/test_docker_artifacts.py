"""
tests/test_docker_artifacts.py

Validates the Docker server-image artifacts (M4 TASK 4.2).

These are static checks on the Dockerfile / docker-compose.yml / .dockerignore
so CI can guard the image's shape without a Docker daemon: it builds on the slim
ONNX path (no torch), ships the detection model, binds for the server scenario,
and wires the TASK 4.4 auth credentials through. An opt-in integration test
actually builds + runs the image when SVCS_TEST_DOCKER=1 and Docker is present.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 4.2 — Docker image).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE = ROOT / "docker-compose.yml"
DOCKERIGNORE = ROOT / ".dockerignore"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── Dockerfile ───────────────────────────────────────────────────────────────

def test_dockerfile_exists():
    assert DOCKERFILE.is_file()


def test_dockerfile_uses_slim_python_base():
    assert "FROM python:3.11-slim" in _text(DOCKERFILE)


def test_dockerfile_installs_ffmpeg_and_opencv_libs():
    body = _text(DOCKERFILE)
    for pkg in ("ffmpeg", "libgl1", "libglib2.0-0"):
        assert pkg in body, f"Dockerfile should apt-install {pkg}"


def test_dockerfile_installs_deps_from_lockfile():
    body = _text(DOCKERFILE)
    assert "uv sync --frozen" in body  # reproducible install from uv.lock


def test_dockerfile_is_slim_path_no_torch():
    """The whole point of post-M2: no torch/CUDA in the server image."""
    body = _text(DOCKERFILE).lower()
    assert "--extra torch" not in body
    assert "pip install torch" not in body
    assert "nvidia" not in body


def test_dockerfile_ships_detection_model():
    assert "yolov8n.onnx" in _text(DOCKERFILE)


def test_dockerfile_binds_server_scenario():
    body = _text(DOCKERFILE)
    assert "--host" in body and "0.0.0.0" in body
    assert "EXPOSE 5000" in body


# ── docker-compose.yml ───────────────────────────────────────────────────────

def test_compose_exists_and_defines_service():
    body = _text(COMPOSE)
    assert "services:" in body
    assert "svcs:" in body
    assert "build: ." in body


def test_compose_maps_port_5000():
    assert "5000:5000" in _text(COMPOSE)


def test_compose_passes_auth_credentials():
    body = _text(COMPOSE)
    assert "SVCS_DASHBOARD_USER" in body
    assert "SVCS_DASHBOARD_PASSWORD" in body


def test_compose_mounts_outputs_volume():
    assert "/app/outputs" in _text(COMPOSE)


def test_compose_has_healthcheck():
    assert "healthcheck:" in _text(COMPOSE)


# ── .dockerignore ────────────────────────────────────────────────────────────

def test_dockerignore_trims_context_but_keeps_model():
    body = _text(DOCKERIGNORE)
    assert ".git" in body
    assert ".venv" in body
    assert "!yolov8n.onnx" in body  # model is re-included despite *.mp4/data rules


# ── opt-in real build ────────────────────────────────────────────────────────

@pytest.mark.skipif(
    os.environ.get("SVCS_TEST_DOCKER") != "1" or shutil.which("docker") is None,
    reason="Set SVCS_TEST_DOCKER=1 with Docker installed to build+run the image.",
)
def test_image_builds_and_serves():  # pragma: no cover - heavy, opt-in
    subprocess.run(["docker", "build", "-t", "svcs:test", "."],
                   cwd=ROOT, check=True, timeout=900)
    cid = subprocess.check_output(
        ["docker", "run", "-d", "-p", "5057:5000",
         "-e", "SVCS_DASHBOARD_USER=ci", "-e", "SVCS_DASHBOARD_PASSWORD=ci",
         "svcs:test"],
        cwd=ROOT, text=True, timeout=60,
    ).strip()
    try:
        import time
        import urllib.request

        ok = False
        for _ in range(30):
            try:
                urllib.request.urlopen("http://localhost:5057/", timeout=2)
            except urllib.error.HTTPError as e:
                if e.code == 401:  # auth challenge => server is up and guarded
                    ok = True
                    break
            except Exception:
                pass
            time.sleep(1)
        assert ok, "container did not serve an authenticated dashboard"
    finally:
        subprocess.run(["docker", "rm", "-f", cid], check=False, timeout=30)
