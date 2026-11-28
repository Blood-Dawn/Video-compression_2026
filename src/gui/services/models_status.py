"""
src/gui/services/models_status.py

Which AI model files this install can find, for the Tools tab "AI models" card.

Read-only: it looks at the same paths the detectors and the enhancer load from
and reports present/missing plus the file size. Nothing is downloaded or
loaded, so the check is instant and safe to call at any time.

  * Detectors (YOLO objects, YOLO pose): needed for Modes 1 to 3 and the
    camera search. Missing means those modes cannot pick out targets.
  * Enhancement models: optional. Without them the enhancer falls back to
    bicubic scaling, so a missing one lowers quality but never breaks a run.

Author: Bloodawn (KheivenD), 2026-11-27.
"""
from __future__ import annotations

from pathlib import Path


def _entry(key: str, label: str, role: str, path: Path, *, required: bool) -> dict:
    try:
        present = path.is_file()
        size = path.stat().st_size if present else 0
    except OSError:
        present, size = False, 0
    return {
        "key": key,
        "label": label,
        "role": role,
        "file": path.name,
        "present": present,
        "size_bytes": int(size),
        "required": required,
    }


def models_status() -> dict:
    """{"detectors": [...], "enhancement": [...], "models_dir": str, "ready": bool}.

    ``ready`` is true when every required detector file is present.
    """
    try:
        from detection.onnx_backend import _default_model_path as yolo_path
        from detection.pose_onnx_backend import _default_model_path as pose_path
        from enhancement import enhancer as enh
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.detection.onnx_backend import _default_model_path as yolo_path
        from src.detection.pose_onnx_backend import _default_model_path as pose_path
        from src.enhancement import enhancer as enh

    detectors = [
        _entry("yolo", "Object detector (YOLOv8 nano)",
               "Finds people and vehicles for Modes 1 to 3 and search.",
               Path(yolo_path()), required=True),
        _entry("pose", "Pose detector (YOLOv8 nano pose)",
               "Used by the pose and fall checks.",
               Path(pose_path()), required=False),
    ]

    models_dir = Path(enh._DEFAULT_MODELS_DIR)
    enhancement = []
    for mid, spec in enh._DNN_SR_MODELS.items():
        scale = max(spec["scales"])
        name = spec["filename"].format(s=scale)
        enhancement.append(_entry(
            mid, mid.upper(), f"Upscaler, x{scale} weights.",
            models_dir / name, required=False))
    for mid, spec in enh._ONNX_SR_MODELS.items():
        enhancement.append(_entry(
            mid, "Real-ESRGAN general (ONNX)", "Best quality upscaler, runs on ONNX Runtime.",
            models_dir / spec["filename"], required=False))

    sizes = []
    try:
        base = Path(yolo_path())
        try:
            import onnxruntime as ort
            dims = ort.InferenceSession(str(base), providers=["CPUExecutionProvider"]).get_inputs()[0].shape
            native = int(dims[2]) if isinstance(dims[2], int) else 640
        except Exception:  # noqa: BLE001
            native = 320
        labels = {320: "Fastest", 416: "Fast", 512: "Balanced", 640: "Best quality",
                  960: "Maximum", 1280: "Maximum (very slow)"}
        for size, label in labels.items():
            f = base.with_name(f"{base.stem}_{size}{base.suffix}")
            installed = f.is_file() or (base.is_file() and size == native)
            sizes.append({"size": size, "label": label, "installed": bool(installed)})
    except Exception:  # noqa: BLE001
        sizes = []

    return {
        "detector_sizes": sizes,
        "detectors": detectors,
        "enhancement": enhancement,
        "models_dir": str(models_dir),
        "ready": all(d["present"] for d in detectors if d["required"]),
    }
