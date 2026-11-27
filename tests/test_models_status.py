"""
tests/test_models_status.py

The Tools tab "AI models" check: reports present/missing model files without
loading or downloading anything, and rides on /api/setup/dependencies.

Author: Bloodawn (KheivenD), 2026-11-27.
"""
from pathlib import Path

import pytest

from gui.services import models_status as ms


def test_missing_files_are_reported_not_raised(tmp_path, monkeypatch):
    from enhancement import enhancer as enh
    from detection import onnx_backend, pose_onnx_backend

    monkeypatch.setattr(enh, "_DEFAULT_MODELS_DIR", tmp_path)
    monkeypatch.setattr(onnx_backend, "_default_model_path", lambda: tmp_path / "yolov8n.onnx")
    monkeypatch.setattr(pose_onnx_backend, "_default_model_path", lambda: tmp_path / "yolov8n-pose.onnx")
    out = ms.models_status()
    assert out["ready"] is False
    assert all(not e["present"] for e in out["detectors"] + out["enhancement"])
    assert {e["key"] for e in out["enhancement"]} >= {"espcn", "fsrcnn", "edsr", "lapsrn", "realesrgan_onnx"}


def test_present_files_report_size_and_ready(tmp_path, monkeypatch):
    from enhancement import enhancer as enh
    from detection import onnx_backend, pose_onnx_backend

    yolo = tmp_path / "yolov8n.onnx"
    yolo.write_bytes(b"x" * 2048)
    monkeypatch.setattr(enh, "_DEFAULT_MODELS_DIR", tmp_path)
    monkeypatch.setattr(onnx_backend, "_default_model_path", lambda: yolo)
    monkeypatch.setattr(pose_onnx_backend, "_default_model_path", lambda: tmp_path / "none.onnx")
    out = ms.models_status()
    assert out["ready"] is True              # pose is optional
    y = next(e for e in out["detectors"] if e["key"] == "yolo")
    assert y["present"] and y["size_bytes"] == 2048


def test_dependencies_route_carries_models():
    from gui.app import app

    body = app.test_client().get("/api/setup/dependencies").get_json()
    assert set(body["dependencies"]) == {"ffmpeg", "ffprobe", "mediamtx", "onnx_model"}
    assert "detectors" in body["models"] and "enhancement" in body["models"]
