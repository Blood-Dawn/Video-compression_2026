"""
src/gui/routes/plates_bp.py

plates routes blueprint, carved from gui/app.py (TASK 1.3).
Pure relocation: every URL, method, and response shape is unchanged.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

from pathlib import Path
from flask import Blueprint, jsonify, request

try:
    from gui.logging_setup import log
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.logging_setup import log

plates_bp = Blueprint("plates", __name__)

def _import_plate_reader():
    """Lazy import so module loading doesn't pull torch / paddle at startup."""
    try:
        from enhancement.plate_reader import PlateReader  # type: ignore
    except ImportError:
        from src.enhancement.plate_reader import PlateReader  # type: ignore
    return PlateReader


@plates_bp.route("/api/enhance/plates/status")
def api_plate_reader_status():
    """Return install/availability info for the plate-reader UI.

    The GUI calls this on page load to decide whether to enable the
    "Read Plates" button or show a "OCR backend not installed" hint.
    """
    try:
        PlateReader = _import_plate_reader()
        reader = PlateReader()
        return jsonify(reader.status())
    except Exception as exc:  # noqa: BLE001
        log.warning("Plate reader status check failed: %s", exc)
        return jsonify({
            "ocr_backend":   "none",
            "ocr_available": False,
            "sr_backend":    "unknown",
            "sr_available":  False,
            "sr_scale":      4,
            "device_request":"auto",
            "error":         str(exc),
        })


def _import_enhancement_benchmark():
    """Lazy import the benchmark — keeps app startup light."""
    try:
        from enhancement.enhancement_benchmark import benchmark_enhancement  # type: ignore
    except ImportError:
        from src.enhancement.enhancement_benchmark import benchmark_enhancement  # type: ignore
    return benchmark_enhancement


@plates_bp.route("/api/enhance/benchmark", methods=["POST"])
def api_enhance_benchmark():
    """Compare no-SR vs full-frame-SR vs ROI-only-SR on a saved segment.

    POST body (JSON):
        file_path             – absolute path to a .mp4 segment (required)
        roi_box               – [x, y, w, h] ROI in original frame coords (required)
        sample_every_n_frames – stride between sampled frames (default 5)
        max_frames            – cap on total frames sampled (default 20)
        sr_scale              – 2 or 4 (default 4)
        run_ocr               – also report OCR confidence per variant (default false)
        ocr_backend           – "auto" | "paddleocr" | "easyocr" (default auto)
        device                – "cuda" | "mps" | "cpu" | null (auto)

    Returns the full ``BenchmarkResult`` JSON: per-variant sharpness /
    PSNR / SSIM / OCR confidence, deltas, and a plain-English verdict.

    Author: Bloodawn (KheivenD), 2026-05-02
    """
    data = request.get_json(force=True) or {}
    file_path = str(data.get("file_path", "")).strip()
    if not file_path:
        return jsonify({"error": "file_path is required"}), 400

    roi_raw = data.get("roi_box")
    if not roi_raw or not isinstance(roi_raw, list) or len(roi_raw) != 4:
        return jsonify({"error": "roi_box must be a 4-element [x, y, w, h] list"}), 400
    try:
        roi_box = tuple(int(v) for v in roi_raw)
    except (TypeError, ValueError):
        return jsonify({"error": "roi_box values must be integers"}), 400

    src = Path(file_path)
    if not src.exists():
        return jsonify({"error": f"File not found: {file_path}"}), 404
    if src.suffix.lower() == ".enc":
        return jsonify({"error": "Decrypt the segment first; benchmark needs plaintext"}), 400

    try:
        benchmark_enhancement = _import_enhancement_benchmark()
        result = benchmark_enhancement(
            src,
            roi_box=roi_box,
            sample_every_n_frames=int(data.get("sample_every_n_frames", 5)),
            max_frames=int(data.get("max_frames", 20)),
            sr_scale=int(data.get("sr_scale", 4)),
            run_ocr=bool(data.get("run_ocr", False)),
            ocr_backend=str(data.get("ocr_backend", "auto")),
            device=data.get("device") or None,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Enhancement benchmark failed on %s: %s", file_path, exc, exc_info=True)
        return jsonify({"error": f"Benchmark failed: {exc}"}), 500

    return jsonify(result.to_dict())


@plates_bp.route("/api/enhance/plates", methods=["POST"])
def api_plate_reader():
    """Run the plate reader on a saved segment.

    POST body (JSON):
        file_path             – absolute path to a .mp4/.avi/.mov clip (required)
        sample_every_n_frames – stride between sampled frames (default 5)
        max_frames            – cap on total frames sampled (default 60)
        roi_boxes             – optional list of [x, y, w, h] crops to focus on
        min_consensus_votes   – minimum agreeing-frame count (default 1)
        min_ocr_confidence    – per-frame OCR confidence floor (default 0.4)
        device                – "cuda" | "mps" | "cpu" | null (auto)
        ocr_backend           – "auto" | "paddleocr" | "easyocr" (default auto)

    Returns the full ``PlateReadResult`` as JSON, including a ``best_read``
    string (or null) and per-candidate ``verdict`` flags so the operator can
    see which reads are trustworthy.

    Author: Bloodawn (KheivenD)
    """
    data = request.get_json(force=True) or {}
    file_path = str(data.get("file_path", "")).strip()
    if not file_path:
        return jsonify({"error": "file_path is required"}), 400

    src = Path(file_path)
    if not src.exists():
        return jsonify({"error": f"File not found: {file_path}"}), 404
    if src.is_dir():
        return jsonify({"error": "file_path must be a video file, not a directory"}), 400
    if src.suffix.lower() == ".enc":
        return jsonify({"error": "Decrypt the segment first; this endpoint does not handle .enc files"}), 400

    try:
        sample_every  = int(data.get("sample_every_n_frames", 5))
        max_frames    = int(data.get("max_frames", 60))
        consensus_min = int(data.get("min_consensus_votes", 1))
        min_conf      = float(data.get("min_ocr_confidence", 0.40))
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"Invalid numeric parameter: {exc}"}), 400

    roi_raw = data.get("roi_boxes")
    roi_boxes = None
    if isinstance(roi_raw, list) and roi_raw:
        try:
            roi_boxes = [tuple(int(v) for v in r) for r in roi_raw]
        except (TypeError, ValueError):
            return jsonify({"error": "roi_boxes must be a list of [x, y, w, h] integers"}), 400

    device       = data.get("device") or None
    ocr_backend  = str(data.get("ocr_backend", "auto"))

    try:
        PlateReader = _import_plate_reader()
        reader = PlateReader(
            ocr_backend=ocr_backend,
            device=device,
            min_ocr_confidence=min_conf,
        )
        result = reader.read_plates_from_video(
            src,
            sample_every_n_frames=sample_every,
            max_frames=max_frames,
            roi_boxes=roi_boxes,
            min_consensus_votes=consensus_min,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Plate reader failed on %s: %s", file_path, exc, exc_info=True)
        return jsonify({"error": f"Plate reader failed: {exc}"}), 500

    return jsonify(result.to_dict())


# ── Network / LAN info ────────────────────────────────────────────────────────

