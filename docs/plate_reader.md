# AI License-Plate Reader

**Author:** Bloodawn (KheivenD)
**Added:** 2026-05-02 — post-process AI enhancement upgrade for ROADMAP 5.4 / 6.x.
**Module:** `src/enhancement/plate_reader.py`
**API:** `POST /api/enhance/plates`, `GET /api/enhance/plates/status`
**GUI:** "▤ READ PLATES" button on the inline preview player.

This document explains the design, the licenses of the libraries we picked, and the honest accuracy limits of the system. It is the document to read when a sponsor or operator asks "how reliable is this?"

---

## What it does

The plate reader runs as a **post-process** step on a saved video segment. It does not run live. The pipeline:

```
Saved .mp4 segment
    -> sample frames (every Nth frame, capped at max_frames)
    -> for each frame:
         - optional: crop to vehicle ROIs from segments DB
         - Real-ESRGAN x4 super-resolution      (existing Enhancer)
         - PaddleOCR plate / generic OCR        (Apache-2.0)
    -> aggregate text reads across frames (consensus voting)
    -> rank candidates by combined confidence
    -> emit PlateReadResult JSON
```

Multi-frame consensus voting is the mechanism that gets us above the single-frame ceiling. A 480p surveillance crop of a plate is below the Nyquist limit for many characters; *no super-resolution model can recover information that isn't there*. But surveillance video gives us many frames of the same plate. When 3+ frames independently OCR to the same text, the read is far more trustworthy than any single frame.

## Why these libraries

| Stage | Library | License | Why we picked it |
|---|---|---|---|
| Super-resolution | **Real-ESRGAN** | BSD-3-Clause | Already integrated via `Enhancer`. 35k stars, BSD-3 compatible with the rest of the repo, handles real-world degradations. Mature `RealESRGAN_x4plus` weights. |
| Primary OCR | **PaddleOCR** | Apache-2.0 | Has a dedicated lightweight license-plate model (~15-20 MB). 77k stars, actively maintained (April 2026 commits). CPU and GPU. |
| Fallback OCR | **EasyOCR** | Apache-2.0 | Used when PaddleOCR can't install (no AVX, no PaddlePaddle wheels for the platform). 29k stars. |

### What we deliberately did **not** use

| Library | License | Why excluded |
|---|---|---|
| **OpenALPR** | **AGPL-3.0** | AGPL would force the rest of the project to AGPL. Hard no for the open-source-but-permissive deliverable. |
| **fast-plate-ocr** | MIT | Permissive and worth a future PR, but dataset is biased toward US plates and the project is smaller (~550 stars, unproven). Listed as a future addition. |
| **WPOD-NET** | research code | Limited maintained open-source releases; not a clean drop-in. |
| Vendor APIs (Google Vision, AWS Rekognition, Plate Recognizer) | proprietary | Not open-source; require keys; outbound network calls disqualify them for an air-gapped Navy base. |

## API surface

### Status endpoint

```
GET /api/enhance/plates/status
```

Returns whether the OCR backend is installed and which one will run. Used by the GUI on page load to enable/disable the "READ PLATES" button gracefully.

```json
{
  "ocr_backend":   "paddleocr",
  "ocr_available": true,
  "sr_backend":    "lazy",
  "sr_available":  true,
  "sr_scale":      4,
  "device_request":"auto"
}
```

When neither PaddleOCR nor EasyOCR is installed, `ocr_backend` is `"none"` and `ocr_available` is `false`.

### Run endpoint

```
POST /api/enhance/plates
Content-Type: application/json
```

Request body:

```json
{
  "file_path": "C:/.../outputs/cam_01/seg_20260502T143000Z.mp4",
  "sample_every_n_frames": 5,
  "max_frames": 60,
  "min_consensus_votes": 1,
  "min_ocr_confidence": 0.40,
  "device": null,
  "ocr_backend": "auto",
  "roi_boxes": [[x, y, w, h], ...]
}
```

`file_path` is required. Everything else is optional and falls back to the defaults listed above. `roi_boxes` is the mechanism that lets the GUI pass per-segment vehicle bboxes from the segments DB so we don't waste SR cycles on empty background.

Response:

```json
{
  "video_path": "...",
  "frames_examined": 12,
  "frames_total": 1800,
  "backend": "paddleocr",
  "sr_backend": "realesrgan-cuda",
  "candidate_plates": [
    {
      "text": "ABC1234",
      "confidence": 0.82,
      "ocr_confidence_avg": 0.71,
      "votes": 5,
      "frames": [3, 8, 12, 15, 19],
      "verdict": "high",
      "bbox_first": [120, 84, 180, 60]
    },
    ...
  ],
  "best_read": "ABC1234",
  "warnings": []
}
```

## Verdict semantics

The `verdict` field is the operator's plain-English read on whether to trust a plate. It is intentionally conservative.

| Verdict | Required | Meaning |
|---|---|---|
| `high` | ≥ 3 frames agree, average OCR ≥ 0.60 | Trust this. Same text reproduced across multiple frames at strong per-frame confidence. |
| `medium` | ≥ 2 frames agree, average OCR ≥ 0.50 | Trust with operator review. Two frames is a coincidence floor. |
| `low` | ≥ 1 frame, OCR ≥ 0.70 | Single-frame strong read. Useful as a starting point — verify against a second frame before acting on it. |
| `uncertain` | anything else | OCR engine returned text but it does not meet either consensus or single-strong-read threshold. **Do not act on uncertain reads.** |

The combined `confidence` score is `0.6 * ocr_avg + 0.4 * consensus_ratio`, where `consensus_ratio = min(1.0, votes / max(3.0, frames_examined * 0.25))`. Both pieces matter: a great OCR confidence on a single frame can hallucinate, and weak per-frame OCR on many frames is still weak.

## Honest accuracy limits

Three things to be honest with the sponsor about:

1. **Resolution floor.** A 480p frame with a vehicle 50 m away yields a plate crop ~25-40 px tall. Even with 4x SR (100-160 px) the Shannon-Nyquist limit means many characters were never sampled. Real-ESRGAN cannot invent the missing detail — at best it removes blur and noise. Expected character accuracy on heavily compressed surveillance footage: **60-75%** without domain adaptation. Multi-frame consensus pushes that up but does not eliminate it.

2. **Compression artefacts.** This pipeline encodes background segments at CRF 45 (heavily lossy). If the plate is in a no-foreground frame and gets background CRF, the artefacts compound. For best plate-reading accuracy, run the reader on Mode 0 segments (full quality) or Mode 1 segments where the plate was inside an ROI.

3. **Hallucination risk.** This was the sponsor's original concern at the March 23 kickoff. The mitigations are: (a) the verdict cap, (b) showing the operator the per-frame vote count, (c) refusing to ever return a text that doesn't appear on at least one frame's OCR output. We never confabulate a plate from "what looked like the right shape."

## Operational recommendations

- Run the reader on **Mode 0 or Mode 1 segments** for best accuracy. Mode 2/3 background-keyframe / object-only outputs intentionally degrade non-foreground pixels, which can include plate edges.
- For long clips, leave `max_frames` at the default 60 and `sample_every_n_frames` at 5 — that's a 12-frame consensus pass on a 60-second segment, enough to flush single-frame hallucinations without burning runtime.
- When the segments DB has `roi_count > 0`, pass the per-frame vehicle boxes via `roi_boxes`. This is the single biggest speedup on long clips.
- Trust the verdict label. `uncertain` reads should not enter incident reports.

## Installation

Both OCR engines are optional extras. Install one (or both, for fallback):

```bash
uv sync --extra plates             # primary: PaddleOCR + paddlepaddle
uv sync --extra plates-fallback    # fallback: EasyOCR
```

If neither is installed, the API still answers `200 OK` and returns a `warnings` field telling the caller which package to install. SR still runs (Real-ESRGAN bicubic fallback) so the operator can at least see an upscaled clip.

## Tests

`tests/test_plate_reader.py` covers:

- Plate-text normalisation (case, length bounds, punctuation stripping).
- Verdict scoring (high / medium / low / uncertain decision boundaries).
- Pipeline plumbing on a synthetic .mp4 with a stub OCR backend (no PaddleOCR install required to run CI).
- Consensus voting picks the repeated read.
- Low-confidence reads are dropped before voting.
- `min_consensus_votes` filters singleton reads.
- `roi_boxes` actually subset the frame.

The OCR backend itself (PaddleOCR / EasyOCR) is **not** unit-tested here. Those tests would require fixed weights, fixture clips, and a model-version pin that fights with the upstream release cadence. Manual validation on real footage is in the team's review checklist.
