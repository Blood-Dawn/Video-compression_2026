"""
tests/test_appimage_build.py

Guards the Linux AppImage build artifacts (M5b TASK 5b.2).

The AppImage builds and is smoke-tested on a Linux CI runner (the agent's host is
Windows). These static checks ensure the recipe is present and coherent: a
Linux-only build.sh on the slim ONNX path that bundles Python + ffmpeg + the
model, an AppRun launcher, a .desktop entry, and a CI workflow that builds +
smoke-tests on ubuntu without auto-publishing.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5b.2).
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
BUILD_SH = ROOT / "installer" / "build.sh"
APPRUN = ROOT / "installer" / "appimage" / "AppRun"
DESKTOP = ROOT / "installer" / "appimage" / "svcs.desktop"
WORKFLOW = ROOT / ".github" / "workflows" / "appimage.yml"


def test_artifacts_exist():
    for p in (BUILD_SH, APPRUN, DESKTOP, WORKFLOW):
        assert p.is_file(), f"missing {p}"


def test_build_bundles_python_ffmpeg_and_model():
    body = BUILD_SH.read_text(encoding="utf-8")
    assert "appimagetool" in body
    assert "uv python" in body          # relocatable standalone python
    assert "ffmpeg" in body             # static ffmpeg bundled
    assert "yolov8n.onnx" in body       # detection model bundled


def test_build_is_slim_no_torch():
    body = BUILD_SH.read_text(encoding="utf-8").lower()
    assert "torch" not in body          # slim ONNX path, like the Docker image


def test_apprun_launches_run_gui():
    body = APPRUN.read_text(encoding="utf-8")
    assert "run_gui.py" in body
    # ffmpeg is put on PATH inside the image
    assert "usr/bin" in body


def test_desktop_entry_is_valid():
    body = DESKTOP.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in body
    assert "Exec=AppRun" in body
    assert "Type=Application" in body


def test_workflow_builds_on_ubuntu_and_does_not_publish():
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "ubuntu-latest" in body
    assert "installer/build.sh" in body
    assert "upload-artifact" in body
    # CI must not auto-publish a Release (that's the owner's gated step).
    low = body.lower()
    assert "softprops/action-gh-release" not in low
    assert "create release" not in low


def test_build_script_has_no_crlf():
    # A shell script with CRLF line endings won't run on Linux.
    assert b"\r\n" not in BUILD_SH.read_bytes(), "build.sh must use LF line endings"
    assert b"\r\n" not in APPRUN.read_bytes(), "AppRun must use LF line endings"
