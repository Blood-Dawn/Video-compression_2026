"""
src/enhancement/plate_reader.py

Post-process license-plate reader - runs on a saved segment after recording,
not in the live pipeline. Two-stage architecture matching the standard
academic ALPR pipeline (YOLO/RetinaNet detect -> CRNN/Transformer OCR):

    Frame  -->  Vehicle ROI crop (MOG2-driven, optional)
           -->  Real-ESRGAN x4 super-resolution         (existing Enhancer)
           -->  OCR backend (ONNX ALPR by default)      (MIT)
           -->  Multi-frame consensus voting            (own code)
           -->  PlateRead{ text, confidence, verdict }

Why this shape:

  * Real-ESRGAN is BSD-3 and already loaded in `Enhancer`; reusing it costs
    nothing.
  * The DEFAULT OCR backend is the ONNX ALPR stack (R4 Phase 5, 2026-07-04):
    fast-plate-ocr + open-image-models, both MIT and torch-free, running on the
    core ONNX Runtime. Crucially they install into the SAME environment as
    opencv-contrib-python (via a `--no-deps` recipe), unlike EasyOCR whose
    opencv-python-headless dependency clobbers the contrib cv2 and forced
    [plates] into a separate venv. Validated end-to-end in
    docs/PLATES-VALIDATION.md; the design decision is docs/RESEARCH-PLATES.md.
  * EasyOCR (Apache-2.0) and PaddleOCR (Apache-2.0) remain supported fallbacks
    for existing separate-env installs; the backend auto-detects whichever is
    present. PaddleOCR's paddlepaddle wheel is ~500 MB and fragile on non-AVX
    CPUs, so it is never pulled in by default.
  * OpenALPR is AGPL-3.0 and intentionally NOT used - it would force the
    whole repo to AGPL.
  * Multi-frame consensus is the academic-paper-recommended mitigation for
    the fundamental Nyquist limit of sub-100 px crops: even when each frame
    reads imperfectly, agreement across frames pushes accuracy past the
    single-frame ceiling.

Honest accuracy ceiling (per the May 2 research pass):

  * Heavily compressed surveillance crops below ~80 px tall: 60-75 % char
    accuracy. We surface a `verdict` field so operators don't act on a
    single low-confidence read.

Author: Bloodawn (KheivenD)
Created: 2026-05-02 for ROADMAP "Enhanced AI plate reader" follow-up to 5.4.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PlateRead:
    """One candidate plate text aggregated across one or more frames.

    Fields:
        text:                Normalised plate string (uppercase, no spaces).
        confidence:          Combined score in [0, 1] - see _score_candidate.
        ocr_confidence_avg:  Mean of per-frame OCR confidences for this text.
        votes:               How many frames agreed on this exact text.
        frames:              Indices of supporting frames in the source video.
        verdict:             "high" | "medium" | "low" | "uncertain".
        bbox_first:          (x, y, w, h) of the OCR detection in the
                             upscaled crop on its first supporting frame.
                             Useful if the GUI wants to draw a box on the
                             returned thumbnail.

    Author: Bloodawn (KheivenD)
    """
    text: str
    confidence: float
    ocr_confidence_avg: float
    votes: int
    frames: List[int]
    verdict: str
    bbox_first: Tuple[int, int, int, int]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlateReadResult:
    """End-to-end result returned by ``PlateReader.read_plates_from_video``.

    Fields:
        video_path:        Source clip path (echoed for the caller).
        frames_examined:   Number of frames the OCR engine looked at.
        frames_total:      Total frames in the clip (for context).
        backend:           Which OCR engine actually ran ("paddleocr",
                           "easyocr", or "none" if neither installed).
        sr_backend:        Which SR backend the Enhancer used.
        candidate_plates:  All consensus-grouped reads, sorted by confidence.
        best_read:         Highest-confidence text, or None when nothing was
                           even tentatively read.
        warnings:          Honest caveats - unusual sample size, OCR engine
                           missing, all reads below threshold, etc.
    """
    video_path: str
    frames_examined: int
    frames_total: int
    backend: str
    sr_backend: str
    candidate_plates: List[PlateRead] = field(default_factory=list)
    best_read: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["candidate_plates"] = [p.to_dict() if isinstance(p, PlateRead) else p
                                 for p in self.candidate_plates]
        return d


# ─────────────────────────────────────────────────────────────────────────────
# Plate-text normalisation + scoring
# ─────────────────────────────────────────────────────────────────────────────


# Most US plates: 4-8 alphanumerics. We allow 4-9 for international and
# vanity plates; reject anything outside that range as obvious OCR noise.
_PLATE_LEN_MIN = 4
_PLATE_LEN_MAX = 9
_PLATE_RE = re.compile(r"[A-Z0-9]+")

# Characters PaddleOCR routinely confuses - useful to remember when the
# operator is reading the surfaced result and choosing whether to trust it.
_AMBIGUOUS_PAIRS = {("0", "O"), ("1", "I"), ("1", "L"), ("5", "S"),
                    ("8", "B"), ("2", "Z"), ("6", "G"), ("Q", "0")}


def _normalise_plate_text(raw: str) -> Optional[str]:
    """Squash whitespace, uppercase, strip non-alphanumerics, length-check.

    Returns None when the raw string is too short / too long to be a plate.
    """
    if raw is None:
        return None
    cleaned = "".join(_PLATE_RE.findall(raw.upper()))
    if not (_PLATE_LEN_MIN <= len(cleaned) <= _PLATE_LEN_MAX):
        return None
    return cleaned


def _score_candidate(votes: int, ocr_avg: float, frames_examined: int) -> Tuple[float, str]:
    """Combine per-frame OCR confidence with multi-frame consensus.

    The blend rewards both raw OCR strength and reproducibility: a single
    high-confidence read can still surface (operator may want to see it),
    but the verdict caps at "low" until at least two frames agree.

    Returns (combined_confidence_in_0_1, verdict_label).
    Author: Bloodawn (KheivenD).
    """
    if frames_examined <= 0:
        return 0.0, "uncertain"

    consensus_ratio = min(1.0, votes / max(3.0, frames_examined * 0.25))
    combined = round(0.6 * ocr_avg + 0.4 * consensus_ratio, 3)

    if votes >= 3 and ocr_avg >= 0.60:
        verdict = "high"
    elif votes >= 2 and ocr_avg >= 0.50:
        verdict = "medium"
    elif votes >= 1 and ocr_avg >= 0.70:
        verdict = "low"
    else:
        verdict = "uncertain"

    return combined, verdict


# ─────────────────────────────────────────────────────────────────────────────
# OCR backends - lazy-imported, fully optional
# ─────────────────────────────────────────────────────────────────────────────


class _OcrBackend:
    """Tiny adapter so the PlateReader doesn't care which OCR engine ran.

    Each backend exposes ``ocr(bgr_image) -> list[(text, confidence, bbox)]``.
    bbox is (x, y, w, h) in the input image's coordinates. Confidence is in
    [0, 1] regardless of the underlying engine's native scale.

    Author: Bloodawn (KheivenD)
    """

    name = "none"

    def ocr(self, frame: np.ndarray) -> List[Tuple[str, float, Tuple[int, int, int, int]]]:
        raise NotImplementedError

    @property
    def available(self) -> bool:
        return False


class _FastPlateOcrBackend(_OcrBackend):
    """ONNX ALPR (MIT) - the recommended backend (R4 Phase 5).

    fast-plate-ocr (ONNX OCR) plus, when available, open-image-models (YOLOv9
    ONNX plate detection). Both are MIT-licensed, torch-free, and run on ONNX
    Runtime (already a core SVCS dependency). Crucially, unlike EasyOCR they do
    NOT need to pull opencv-python-headless at RUNTIME - a plain ``import cv2``
    is satisfied by the core opencv-contrib-python. So this backend installs and
    runs in the SAME environment as core (validated: docs/PLATES-VALIDATION.md),
    fixing the separate-venv problem that made [plates] painful to ship.

    Install recipe (into the core env, no headless clobber):
        pip install --no-deps fast-plate-ocr open-image-models
        pip install rich          # the only runtime dep beyond SVCS core

    ocr(frame): if the detector is available, it finds plate boxes in the frame,
    crops each, and OCRs the crop; otherwise it OCRs the whole input (which works
    when the pipeline already passed a plate/vehicle ROI crop - it always can).
    """

    name = "onnx-alpr"

    # A small, global CPU OCR model. char_probs is None for the xs model, so we
    # fall back to a moderate confidence when per-char probabilities are absent.
    _OCR_MODEL = "cct-xs-v1-global-model"
    _DET_MODEL = "yolo-v9-t-384-license-plate-end2end"
    _NO_PROB_CONFIDENCE = 0.80

    def __init__(self, use_gpu: bool = False) -> None:
        self._recognizer = None
        self._detector = None
        try:
            from fast_plate_ocr import LicensePlateRecognizer  # type: ignore
        except ImportError:
            return  # backend simply unavailable; pipeline degrades gracefully
        try:
            self._recognizer = LicensePlateRecognizer(self._OCR_MODEL)
        except Exception as exc:  # noqa: BLE001 - model download / init can throw
            log.warning("fast-plate-ocr init failed: %s.", exc)
            self._recognizer = None
            return
        # Detection is optional: without it we OCR the ROI/frame we are given.
        try:
            from open_image_models import LicensePlateDetector  # type: ignore
            self._detector = LicensePlateDetector(self._DET_MODEL)
        except Exception as exc:  # noqa: BLE001
            log.info("open-image-models detector unavailable (%s); OCR-only mode.", exc)
            self._detector = None

    @property
    def available(self) -> bool:
        return self._recognizer is not None

    def _confidence(self, pred) -> float:
        """Derive a [0,1] confidence from a PlatePrediction's char_probs."""
        probs = getattr(pred, "char_probs", None)
        try:
            vals = [float(p) for p in (probs or []) if p is not None]
            if vals:
                return max(0.0, min(1.0, sum(vals) / len(vals)))
        except (TypeError, ValueError):
            pass
        return self._NO_PROB_CONFIDENCE

    def _detect_boxes(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Plate boxes (x, y, w, h) from the detector, or [] if unavailable."""
        if self._detector is None:
            return []
        try:
            dets = self._detector.predict(frame) or []
        except Exception as exc:  # noqa: BLE001
            log.debug("plate detector.predict raised %s; skipping detection", exc)
            return []
        boxes: List[Tuple[int, int, int, int]] = []
        h, w = frame.shape[:2]
        for d in dets:
            bb = getattr(d, "bounding_box", None)
            if bb is None:
                bb = getattr(d, "bbox", None)
            if bb is None:
                continue
            coords = self._bbox_coords(bb)
            if coords is None:
                continue
            x1, y1, x2, y2 = coords
            x1 = max(0, min(w - 1, x1)); x2 = max(0, min(w, x2))
            y1 = max(0, min(h - 1, y1)); y2 = max(0, min(h, y2))
            if x2 > x1 and y2 > y1:
                boxes.append((x1, y1, x2 - x1, y2 - y1))
        return boxes

    @staticmethod
    def _bbox_coords(bb):
        """(x1, y1, x2, y2) ints from an attribute-style OR sequence-style bbox."""
        # Attribute style (open-image-models BoundingBox: .x1/.y1/.x2/.y2).
        if all(hasattr(bb, a) for a in ("x1", "y1", "x2", "y2")):
            try:
                return (int(bb.x1), int(bb.y1), int(bb.x2), int(bb.y2))
            except (TypeError, ValueError):
                return None
        # Sequence style ([x1, y1, x2, y2]).
        try:
            return (int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3]))
        except (TypeError, IndexError, ValueError):
            return None

    def _read_crop(self, crop: np.ndarray):
        try:
            return self._recognizer.run(crop) or []
        except Exception as exc:  # noqa: BLE001
            log.debug("fast-plate-ocr run raised %s; skipping crop", exc)
            return []

    def ocr(self, frame: np.ndarray) -> List[Tuple[str, float, Tuple[int, int, int, int]]]:
        if self._recognizer is None:
            return []
        results: List[Tuple[str, float, Tuple[int, int, int, int]]] = []
        boxes = self._detect_boxes(frame)
        if boxes:
            for (x, y, bw, bh) in boxes:
                crop = frame[y:y + bh, x:x + bw]
                if crop.size == 0:
                    continue
                for pred in self._read_crop(crop):
                    text = getattr(pred, "plate", None)
                    if text:
                        results.append((str(text), self._confidence(pred), (x, y, bw, bh)))
        else:
            # No detector (or nothing detected): OCR the whole input as a crop.
            h, w = frame.shape[:2]
            for pred in self._read_crop(frame):
                text = getattr(pred, "plate", None)
                if text:
                    results.append((str(text), self._confidence(pred), (0, 0, w, h)))
        return results


class _PaddleOcrBackend(_OcrBackend):
    """PaddleOCR PP-OCRv4 (Apache-2.0) - optional secondary backend.

    Used to be the primary backend up through May 2026, demoted as part
    of the v2 productization to keep the default install small. Still
    fully supported at runtime; install with `pip install paddleocr
    paddlepaddle` if you want the dedicated license-plate model.
    """

    name = "paddleocr"

    def __init__(self, use_gpu: bool = False) -> None:
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except ImportError:
            self._engine = None
            return

        try:
            # use_angle_cls helps with rotated plates; lang='en' is the
            # smallest English-only model. det+rec=True gives both stages.
            self._engine = PaddleOCR(
                use_angle_cls=True,
                lang="en",
                use_gpu=use_gpu,
                show_log=False,
            )
        except Exception as exc:  # noqa: BLE001 - paddle's init can throw anything
            log.warning("PaddleOCR initialisation failed: %s. Falling back.", exc)
            self._engine = None

    @property
    def available(self) -> bool:
        return self._engine is not None

    def ocr(self, frame: np.ndarray) -> List[Tuple[str, float, Tuple[int, int, int, int]]]:
        if self._engine is None:
            return []
        try:
            raw = self._engine.ocr(frame, cls=True)
        except Exception as exc:  # noqa: BLE001
            log.debug("PaddleOCR.ocr raised %s; skipping frame", exc)
            return []

        # PaddleOCR returns nested lists: [[ [points, (text, score)], ... ]]
        results: List[Tuple[str, float, Tuple[int, int, int, int]]] = []
        if not raw:
            return results
        page = raw[0] if isinstance(raw[0], list) else raw
        for item in page or []:
            try:
                points, (text, score) = item
                xs = [int(p[0]) for p in points]
                ys = [int(p[1]) for p in points]
                bbox = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
                results.append((str(text), float(score), bbox))
            except Exception:  # noqa: BLE001
                continue
        return results


class _EasyOcrBackend(_OcrBackend):
    """EasyOCR (Apache-2.0) - fallback when PaddleOCR can't install."""

    name = "easyocr"

    def __init__(self, use_gpu: bool = False) -> None:
        try:
            import easyocr  # type: ignore
        except ImportError:
            self._reader = None
            return
        try:
            self._reader = easyocr.Reader(["en"], gpu=use_gpu, verbose=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("EasyOCR initialisation failed: %s.", exc)
            self._reader = None

    @property
    def available(self) -> bool:
        return self._reader is not None

    def ocr(self, frame: np.ndarray) -> List[Tuple[str, float, Tuple[int, int, int, int]]]:
        if self._reader is None:
            return []
        try:
            raw = self._reader.readtext(frame)
        except Exception as exc:  # noqa: BLE001
            log.debug("EasyOCR.readtext raised %s; skipping frame", exc)
            return []

        results: List[Tuple[str, float, Tuple[int, int, int, int]]] = []
        for entry in raw:
            try:
                points, text, score = entry
                xs = [int(p[0]) for p in points]
                ys = [int(p[1]) for p in points]
                bbox = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
                results.append((str(text), float(score), bbox))
            except Exception:  # noqa: BLE001
                continue
        return results


class _TesseractBackend(_OcrBackend):
    """Tesseract via pytesseract (Apache-2.0) - lightweight CPU fallback.

    Slower per-call than PaddleOCR / EasyOCR but ships in apt and Homebrew
    out of the box, so it's the right choice when the user can't install
    the bigger ML stacks. Plate accuracy is lower than PaddleOCR's
    dedicated plate model, but on clear high-contrast plates it gets the
    job done.

    Author: Bloodawn (KheivenD), 2026-05-03 (added during enhancement test).
    """

    name = "tesseract"

    def __init__(self, use_gpu: bool = False) -> None:  # noqa: ARG002
        try:
            import pytesseract  # type: ignore
            self._pyt = pytesseract
            # Confidence sanity check: if the binary isn't installed we
            # mark ourselves unavailable rather than crashing later.
            self._pyt.get_tesseract_version()
            self._available = True
        except Exception:  # noqa: BLE001
            self._pyt = None
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def ocr(self, frame: np.ndarray) -> List[Tuple[str, float, Tuple[int, int, int, int]]]:
        if not self._available:
            return []
        try:
            data = self._pyt.image_to_data(
                frame, output_type=self._pyt.Output.DICT,
                config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
            )
        except Exception:  # noqa: BLE001
            return []

        out: List[Tuple[str, float, Tuple[int, int, int, int]]] = []
        for i, txt in enumerate(data.get("text", [])):
            txt = (txt or "").strip()
            if not txt:
                continue
            try:
                conf = float(data["conf"][i]) / 100.0
            except (KeyError, ValueError, TypeError):
                conf = 0.0
            if conf < 0.0:
                conf = 0.0
            try:
                x = int(data["left"][i]); y = int(data["top"][i])
                w = int(data["width"][i]); h = int(data["height"][i])
            except (KeyError, ValueError, TypeError):
                x = y = w = h = 0
            out.append((txt, conf, (x, y, w, h)))
        return out


def _select_backend(prefer: str = "auto", use_gpu: bool = False) -> _OcrBackend:
    """Pick the strongest available OCR backend.

    ``prefer`` is one of "auto", "onnx", "easyocr", "paddleocr", "tesseract".
    With "auto" we try the ONNX ALPR stack FIRST (R4 Phase 5): fast-plate-ocr +
    open-image-models are MIT, torch-free, run on the core ONNX Runtime, and -
    unlike EasyOCR - install into the SAME environment as opencv-contrib-python
    (no opencv-python-headless clobber; see docs/PLATES-VALIDATION.md). Then
    EasyOCR (legacy, needs a separate venv), then PaddleOCR if installed
    manually, then Tesseract. If none is installed we return a no-op backend so
    the rest of the pipeline still runs.

    Order rationale: the ONNX stack is the recommended ship for a single CPU
    exe. EasyOCR/PaddleOCR remain supported for existing separate-env installs.

    Author: Bloodawn (KheivenD); R4 Phase 5 (2026-07-04) - ONNX ALPR first.
    """
    prefer = (prefer or "auto").lower()
    if prefer in ("onnx", "onnx-alpr", "fast-plate-ocr", "auto"):
        b = _FastPlateOcrBackend(use_gpu=use_gpu)
        if b.available:
            return b
        if prefer != "auto":
            return b
    if prefer in ("easyocr", "auto"):
        b = _EasyOcrBackend(use_gpu=use_gpu)
        if b.available:
            return b
        if prefer == "easyocr":
            return b
    if prefer in ("paddleocr", "auto"):
        b = _PaddleOcrBackend(use_gpu=use_gpu)
        if b.available:
            return b
        if prefer == "paddleocr":
            return b
    if prefer in ("tesseract", "auto"):
        b = _TesseractBackend(use_gpu=use_gpu)
        if b.available:
            return b
        if prefer == "tesseract":
            return b
    return _OcrBackend()


# ─────────────────────────────────────────────────────────────────────────────
# PlateReader - the public class
# ─────────────────────────────────────────────────────────────────────────────


class PlateReader:
    """Post-process license-plate reader.

    Combines the existing Real-ESRGAN ``Enhancer`` with a permissive-licensed
    OCR backend (PaddleOCR or EasyOCR). Multi-frame consensus voting is the
    accuracy multiplier - single-frame reads from low-resolution footage are
    flagged as uncertain by design.

    Typical use::

        reader = PlateReader()                 # auto device + OCR backend
        result = reader.read_plates_from_video("outputs/seg_001.mp4")
        for plate in result.candidate_plates:
            print(plate.text, plate.verdict, plate.confidence)

    Author: Bloodawn (KheivenD)
    """

    def __init__(
        self,
        enhancer: Optional[Any] = None,
        ocr_backend: str = "auto",
        device: Optional[str] = None,
        sr_scale: int = 4,
        min_ocr_confidence: float = 0.40,
    ) -> None:
        """
        Args:
            enhancer:           Reuse an existing ``Enhancer`` instance, or
                                pass ``None`` to lazily create one with the
                                same device / scale as this PlateReader.
            ocr_backend:        "auto" | "paddleocr" | "easyocr".
            device:             "cuda" | "mps" | "cpu" | None (auto).
                                Forwarded to the Enhancer + OCR backend.
            sr_scale:           Real-ESRGAN scale factor (2 or 4). 4 is
                                strongly recommended for plates.
            min_ocr_confidence: Per-frame OCR reads below this confidence
                                are dropped before consensus voting.
        """
        self._device = device
        self._sr_scale = sr_scale
        self._min_ocr_conf = float(min_ocr_confidence)

        # Lazy enhancer: skip the heavy import unless the caller actually
        # invokes read_plates_from_video. Tests can pass a stub.
        self._enhancer = enhancer
        self._enhancer_lazy = enhancer is None

        # Resolve OCR backend immediately so the GUI can show "Plate reader
        # ready / not installed" without firing an SR pass.
        use_gpu = (device or "").lower() in ("cuda", "mps")
        self._ocr = _select_backend(ocr_backend, use_gpu=use_gpu)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def ocr_backend_name(self) -> str:
        return self._ocr.name

    @property
    def ocr_available(self) -> bool:
        return self._ocr.available

    def status(self) -> Dict[str, Any]:
        """Return install/availability info for the GUI's diagnostic panel."""
        sr_backend = self._sr_backend_name()
        return {
            "ocr_backend":    self._ocr.name,
            "ocr_available":  self._ocr.available,
            "sr_backend":     sr_backend,
            "sr_available":   sr_backend != "bicubic",
            "sr_scale":       self._sr_scale,
            "device_request": self._device or "auto",
        }

    def _sr_backend_name(self) -> str:
        if self._enhancer is None and self._enhancer_lazy:
            return "lazy"
        if self._enhancer is None:
            return "bicubic"
        try:
            return getattr(self._enhancer, "backend", "unknown")
        except Exception:  # noqa: BLE001
            return "unknown"

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def read_plates_from_video(
        self,
        video_path,
        sample_every_n_frames: int = 5,
        max_frames: int = 60,
        roi_boxes: Optional[Sequence[Tuple[int, int, int, int]]] = None,
        min_consensus_votes: int = 1,
    ) -> PlateReadResult:
        """Read plate text from a saved video clip.

        Args:
            video_path:            Path to a .mp4/.avi/.mov clip.
            sample_every_n_frames: Stride between sampled frames.
            max_frames:            Cap on total frames sampled (cost guard).
            roi_boxes:             Optional list of (x, y, w, h) crops to
                                   focus on. When ``None`` the whole frame
                                   is upscaled and OCR'd. Pass the bboxes
                                   from the segments DB to skip empty
                                   background work.
            min_consensus_votes:   Minimum frame agreement for a plate to
                                   be returned at all. 1 means "show every
                                   read"; 2 filters out single-frame noise.

        Returns:
            ``PlateReadResult`` with candidate plates sorted by confidence.

        Author: Bloodawn (KheivenD)
        """
        path = Path(video_path)
        warnings: List[str] = []

        if not path.exists():
            return PlateReadResult(
                video_path=str(path), frames_examined=0, frames_total=0,
                backend=self._ocr.name, sr_backend=self._sr_backend_name(),
                warnings=[f"Video file not found: {path}"],
            )

        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            return PlateReadResult(
                video_path=str(path), frames_examined=0, frames_total=0,
                backend=self._ocr.name, sr_backend=self._sr_backend_name(),
                warnings=[f"OpenCV could not open: {path}"],
            )

        frames_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if not self._ocr.available:
            warnings.append(
                "No OCR backend installed (paddleocr / easyocr). "
                "Run: pip install paddleocr   OR   pip install easyocr"
            )

        # Lazy-load the enhancer the first time we actually need it.
        if self._enhancer is None and self._enhancer_lazy:
            self._enhancer = self._make_enhancer()

        # Walk the video. Group reads by normalised text across frames.
        per_text_frames: Dict[str, List[int]] = defaultdict(list)
        per_text_confs:  Dict[str, List[float]] = defaultdict(list)
        per_text_bboxes: Dict[str, Tuple[int, int, int, int]] = {}

        frame_idx = 0
        examined = 0
        stride = max(1, int(sample_every_n_frames))
        cap_max = max(1, int(max_frames))

        while examined < cap_max:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if frame_idx % stride != 0:
                frame_idx += 1
                continue

            crops = self._crops_for_frame(frame, roi_boxes)
            for crop in crops:
                upscaled = self._upscale(crop)
                for text, ocr_conf, bbox in self._ocr.ocr(upscaled):
                    norm = _normalise_plate_text(text)
                    if norm is None or ocr_conf < self._min_ocr_conf:
                        continue
                    per_text_frames[norm].append(frame_idx)
                    per_text_confs[norm].append(ocr_conf)
                    per_text_bboxes.setdefault(norm, bbox)

            examined += 1
            frame_idx += 1

        cap.release()

        # Aggregate into PlateRead candidates and rank.
        candidates: List[PlateRead] = []
        for text, frames in per_text_frames.items():
            confs = per_text_confs[text]
            ocr_avg = sum(confs) / len(confs)
            votes = len(frames)
            if votes < min_consensus_votes:
                continue
            combined, verdict = _score_candidate(votes, ocr_avg, examined)
            candidates.append(PlateRead(
                text=text,
                confidence=combined,
                ocr_confidence_avg=round(ocr_avg, 3),
                votes=votes,
                frames=sorted(set(frames)),
                verdict=verdict,
                bbox_first=per_text_bboxes[text],
            ))

        candidates.sort(key=lambda p: (p.confidence, p.votes), reverse=True)
        best = candidates[0].text if candidates else None

        if examined == 0:
            warnings.append("No frames could be read from the video.")
        elif not candidates:
            warnings.append(
                "No plate-shaped text passed the confidence threshold. "
                "Try a clip with closer vehicles or lower min_ocr_confidence."
            )

        return PlateReadResult(
            video_path=str(path),
            frames_examined=examined,
            frames_total=frames_total,
            backend=self._ocr.name,
            sr_backend=self._sr_backend_name(),
            candidate_plates=candidates,
            best_read=best,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _make_enhancer(self):
        """Lazy-create an Enhancer with the same device + scale settings."""
        try:
            # Local import: avoids loading torch when the module is just
            # imported for a status check.
            from enhancement.enhancer import Enhancer  # type: ignore
        except ImportError:
            from src.enhancement.enhancer import Enhancer  # type: ignore
        return Enhancer(scale=self._sr_scale, device=self._device)

    def _crops_for_frame(
        self,
        frame: np.ndarray,
        roi_boxes: Optional[Sequence[Tuple[int, int, int, int]]],
    ) -> List[np.ndarray]:
        """Return the regions to OCR from one frame.

        When the caller passes ``roi_boxes`` we crop just those regions and
        skip the rest of the frame - this is dramatically faster on long
        clips and avoids wasting SR cycles on empty background. With no
        boxes we fall back to the full frame.
        """
        if not roi_boxes:
            return [frame]
        h, w = frame.shape[:2]
        crops: List[np.ndarray] = []
        for (x, y, bw, bh) in roi_boxes:
            x1, y1 = max(0, int(x)), max(0, int(y))
            x2, y2 = min(w, int(x + bw)), min(h, int(y + bh))
            if x2 > x1 and y2 > y1:
                crops.append(frame[y1:y2, x1:x2])
        return crops

    def _upscale(self, image: np.ndarray) -> np.ndarray:
        """Upscale via the Enhancer (bicubic when SR is unavailable)."""
        if self._enhancer is None:
            h, w = image.shape[:2]
            return cv2.resize(
                image,
                (w * self._sr_scale, h * self._sr_scale),
                interpolation=cv2.INTER_CUBIC,
            )
        try:
            return self._enhancer.upscale_frame(image, scale=self._sr_scale)
        except Exception as exc:  # noqa: BLE001
            log.debug("Enhancer.upscale_frame failed (%s); falling back to bicubic.", exc)
            h, w = image.shape[:2]
            return cv2.resize(
                image,
                (w * self._sr_scale, h * self._sr_scale),
                interpolation=cv2.INTER_CUBIC,
            )


__all__ = [
    "PlateReader",
    "PlateRead",
    "PlateReadResult",
]
