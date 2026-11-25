"""Real-ESRGAN General (ONNX) backend: tiling, scale and fallback.

A stand-in ONNX graph (nearest-neighbour x4 resize) exercises the same
loading, tiling and stitching code the real model goes through.

Author: Bloodawn (KheivenD), 2026-11-25.
"""
import numpy as np
import pytest

onnx = pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")
from onnx import TensorProto, helper

from enhancement.enhancer import Enhancer


def _write_stub(path):
    scales = helper.make_tensor("scales", TensorProto.FLOAT, [4], [1, 1, 4, 4])
    roi = helper.make_tensor("roi", TensorProto.FLOAT, [0], [])
    node = helper.make_node("Resize", ["x", "roi", "scales"], ["y"], mode="nearest")
    g = helper.make_graph(
        [node], "stub",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, None, None])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 3, None, None])],
        initializer=[scales, roi],
    )
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 13)])
    m.ir_version = 8
    onnx.save(m, str(path))


def test_onnx_backend_upscales_across_tiles(tmp_path):
    _write_stub(tmp_path / "realesr-general-x4v3.onnx")
    enh = Enhancer(model="realesrgan_onnx", models_dir=str(tmp_path))
    assert enh.backend == "realesrgan_onnx-cpu"
    assert enh.active_scale == 4
    rng = np.random.default_rng(1)
    frame = rng.integers(0, 256, (150, 210, 3), dtype=np.uint8)   # more than one 128 tile each way
    out = enh.upscale_frame(frame)
    assert out.shape == (600, 840, 3)
    assert np.array_equal(out, np.repeat(np.repeat(frame, 4, 0), 4, 1))


def test_onnx_backend_falls_back_to_bicubic_without_weights(tmp_path):
    enh = Enhancer(model="realesrgan_onnx", models_dir=str(tmp_path))
    assert enh.backend == "bicubic"
    assert enh.upscale_frame(np.zeros((10, 10, 3), np.uint8)).shape == (40, 40, 3)
