# Technical Research Report
## Open Source Selective Video Compression for Static Surveillance Cameras
**Prepared:** March 23, 2026
**Team:** Kheiven D'Haiti, Jorge Sanchez, Ashleyn Montano, Riley Roberts, Victor De Souza Teixeira

---

## Table of Contents

1. Meeting Summary and Sponsor Requirements
2. Background Subtraction Algorithms
3. ROI-Based Selective Compression
4. Open-Source Codec Selection
5. CPU-Based Super-Resolution Enhancement
6. Recommended Architecture
7. References

---

## 1. Meeting Summary and Sponsor Requirements

### Sponsor
Cody Hayashi, Engineer at Naval Information Warfare Center (NIWC) Pacific, Hawaii. Co-mentored with Gina (Jinel Wang Kung), who manages commercial surveillance products on Navy bases.

### Problem Statement
Navy bases have surveillance cameras that store footage for approximately one week before the data is overwritten. Current full-frame compression does not account for the fact that the vast majority of pixels in a static camera feed never change. The sponsor's team ran a preliminary experiment: using YOLO object detection on a walkway camera and saving only frames containing people, they achieved approximately 6x data reduction over 30 minutes of footage. They want a software-only, open-source solution that improves on this approach.

### Confirmed Constraints from Sponsor

- **Static cameras only** - no PTZ (pan-tilt-zoom), no drones, no swiveling cameras
- **Land surveillance only** - not water/port at this time
- **Target objects:** people on foot and people in vehicles at base entry points
- **Background is expendable** - only foreground objects carry intelligence value
- **Open source mandatory** - no paywalled codecs or proprietary tools. Deliverable is a public GitHub repo.
- **CPU-only hardware** - must run on old, cheap, legacy hardware with no modern GPU
- **Enhancement in scope** - AI-based upscaling of compressed footage after offload, but sponsor flagged hallucination risks (especially on license plates and faces)
- **Benchmarking required** - test on at least 3 different video types with varying lighting conditions
- **Encryption mentioned as a nice-to-have** - not required but interesting given Victor's cybersecurity background

### Deliverable
A working GitHub repository with all team members' names. Takes static camera video as input, compresses it selectively, stores it efficiently, and optionally enhances it after offload.

### Schedule
Reports due: March 30, April 13, April 27. Class ends May 6, 2026. Weekly meetings with sponsor (schedule TBD via When2Meet).

---

## 2. Background Subtraction Algorithms

Background subtraction is the foundational step of the pipeline. It determines which pixels are "foreground" (moving objects of interest) and which are "background" (static scene). The quality of this step directly impacts everything downstream: a noisy mask means wasted bits compressing false foreground, and a missed detection means losing intelligence data.

### 2.1 Algorithm Comparison

#### MOG2 (Mixture of Gaussians v2) - RECOMMENDED DEFAULT

MOG2 models each pixel's background as a mixture of multiple Gaussian distributions (typically up to 5). It automatically selects how many Gaussians each pixel needs, which handles multimodal backgrounds (like swaying trees or flickering lights).

**Key parameters:**
- `history` (default 500): Number of recent frames used to build the background model. Higher = more stable but slower adaptation.
- `varThreshold` (default 16): How different a pixel must be from the model to count as foreground. Lower = more sensitive.
- `detectShadows` (default True): Marks shadows as gray (127) instead of white (255) in the mask, which lets you filter them out. Adds ~10-20% processing overhead.
- `learningRate`: How fast the model adapts. Default is automatic. Range 0-1, where 0 = never update, 1 = replace model every frame.

**Performance:** ~64 fps on standard hardware at 1080p. Can handle 4-8 simultaneous 1080p streams on a modern 4-core CPU. On a Raspberry Pi: 15-25 fps at 640x480.

**Strengths:** Best speed-to-accuracy ratio. Handles gradual lighting changes (sunrise/sunset) well. Built-in shadow detection.

**Weaknesses:** Sudden lighting changes (lights switching on/off) can confuse the model temporarily. Shadow detection is imperfect in complex outdoor scenes.

#### KNN (K-Nearest Neighbors)

Instead of fitting Gaussian distributions, KNN stores actual pixel color samples from recent frames and classifies new pixels by comparing them to their K nearest historical neighbors.

**Performance:** ~40-50 fps on standard hardware.

**When to prefer KNN over MOG2:**
- Low-light or infrared camera footage (KNN handles non-Gaussian noise better)
- When you need sharper foreground boundaries (edges)
- Research on near-infrared video showed KNN had "the biggest similarity to human segmentation"

**Tradeoff:** Better accuracy at the cost of higher CPU usage and more memory (stores raw pixel samples rather than compact distribution parameters).

#### GMG (Godbehere, Matsukawa, Goldberg)

Uses Bayesian inference with adaptive density estimates. Theoretically more principled but has a long initialization period (default 120 frames of all-black output) and runs at only ~10 fps.

**Verdict:** Too slow and impractical for real-time surveillance. Not recommended for this project.

#### GSOC (Google Summer of Code variant)

An improved RGB-based algorithm that outperforms other OpenCV methods on the CDnet-2012 and CDnet-2014 benchmark datasets. Faster and more robust than GMG or LSBP.

**Verdict:** Worth benchmarking against MOG2 if time permits, but less documented and less widely used.

### 2.2 Post-Processing the Foreground Mask

Raw masks from any algorithm contain noise. Post-processing is essential.

**Morphological operations (in order):**
1. **Opening** (erosion then dilation): Removes small noise dots without significantly changing the size of real objects. Use a 3x3 or 5x5 kernel.
2. **Closing** (dilation then erosion): Fills small holes inside detected objects. A person's arm might have gaps; closing fills them.
3. **Contour filtering:** Extract contours from the cleaned mask and discard any with area below a minimum threshold (e.g., 500 pixels). This removes trivially small detections that survived morphology.

**Shadow handling:** If `detectShadows=True` (MOG2), shadow pixels are marked as 127 in the mask. Threshold the mask at 200+ to keep only true foreground, or at 127+ to include shadows.

### 2.3 Practical Considerations for Static Surveillance

**Day/night transitions:** MOG2 handles gradual changes well with default parameters. For extreme transitions (outdoor cameras at sunset), increase `history` to 1000+ and lower `varThreshold` to 10-12.

**Swaying trees and grass:** MOG2's mixture of Gaussians naturally models cyclical motion as part of the background after a learning period. Reduce the learning rate for regions with persistent dynamic backgrounds.

**When to reset the model:** After power loss, camera repositioning, or when seasonal changes make the background unrecognizable. Call `subtractor = cv2.createBackgroundSubtractorMOG2()` to reinitialize.

**Embedded/legacy hardware:** At 640x480 resolution, MOG2 runs at 15-25 fps even on a Raspberry Pi. For our project targeting old x86 hardware, 1080p MOG2 at 30fps is achievable on any multi-core CPU from the last decade.

---

## 3. ROI-Based Selective Compression

### 3.1 Core Concept

Once background subtraction identifies foreground regions (bounding boxes around people/vehicles), we encode those regions at high quality (low CRF) and everything else at heavy compression (high CRF). Since foreground typically occupies less than 5-10% of pixels in a static camera frame, the storage savings are substantial.

### 3.2 FFmpeg ROI Encoding with libx264

H.264 supports macroblock-level quantization control. Each 16x16 pixel macroblock can have a different QP (quantization parameter) value.

**The `addroi` filter:**
FFmpeg provides the `addroi` filter for marking regions of interest. Combined with adaptive quantization (`aq-mode=2`), this allows per-region quality control:

```bash
ffmpeg -i input.mp4 \
  -vf "addroi=x=100:y=200:w=300:h=400:qoffset=-0.5" \
  -c:v libx264 \
  -x264-params aq-mode=2 \
  -crf 35 \
  output.mp4
```

The `qoffset` value ranges from -1 (highest quality boost) to +1 (most quality reduction). With a base CRF of 35 and a negative qoffset on the ROI, the foreground gets better quality while the background stays heavily compressed.

**CRF values for this project:**
- Foreground ROIs: CRF 18-23 (near-lossless)
- Background: CRF 40-51 (aggressive compression)
- CRF 0 = lossless, CRF 51 = worst quality. Each +6 CRF roughly halves the bitrate.

### 3.3 Alternative Approaches

**Two-stream encoding (foreground/background separation):**
Academic research shows that encoding foreground and background as separate streams, then multiplexing, achieves 69.5% less bits-per-pixel than standard H.265 at the same PSNR (36 dB). This is the most aggressive approach but adds complexity in frame alignment and playback.

**Tile-based encoding (HEVC):**
H.265 natively supports tile-based encoding where the frame is divided into rectangular tiles processed independently. Foreground tiles get more bits; background tiles get fewer. However, H.265 is too CPU-intensive for our legacy hardware constraint.

**Frame relevance compression (FRVC):**
Uses deep learning to determine which frames are relevant. Achieves up to 96.3% redundancy removal on surveillance footage. Interesting research but too computationally expensive for CPU-only deployment.

### 3.4 Expected Compression Ratios

For static surveillance with our ROI approach:
- **4-6x** compression improvement over naive full-frame H.264 is achievable with CRF-based quality zoning
- The sponsor's team achieved ~6x using YOLO detection + frame-dropping, which is a coarser approach than our pixel-level ROI method
- Our approach should meet or exceed 6x because we preserve the full temporal stream (every frame) while compressing the background aggressively, rather than dropping entire frames

### 3.5 Practical Challenges

- **ROI edges:** H.264 macroblocks are 16x16 pixels. ROI boundaries are rounded to macroblock edges. This means quality transitions happen at 16-pixel boundaries, not pixel-precise.
- **Bitrate variability:** Scenes with more motion produce larger files. VBR (variable bitrate) is fine for storage but needs monitoring for buffer management.
- **Playback compatibility:** The output is a standard H.264 file. Any player (VLC, ffplay, browser) can play it. The ROI encoding is invisible to the decoder.

### 3.6 Existing Open-Source Implementations

- **h264-roi** (GitHub: ChaoticEnigma/h264-roi): Applies different QP values to rectangular ROIs using x264. Rounds ROI edges to 16x16 macroblocks.
- **h264_qpblock** (GitHub: Eynnzerr/h264_qpblock): H.264 re-encoding with per-region QP presets.
- **myh264** (GitHub: Alex-q-z/myh264): Incremental x264 encoder designed for video analytics pipelines.

---

## 4. Open-Source Codec Selection

### 4.1 Codec Comparison Table

| Metric | libx264 (H.264) | libx265 (H.265) | SVT-AV1 | VP9 |
|---|---|---|---|---|
| License | GPL v2 | GPL v2 + patents | BSD-3-clause | BSD |
| Compression vs x264 | baseline | 35-50% better | 40-50% better | 35% better |
| 1080p30 CPU speed | 120-180 fps | 15-30 fps | Varies by preset | ~30-50 fps |
| Runs on old hardware? | Yes | No | No | Borderline |
| ROI support in FFmpeg | Yes (macroblock QP) | Limited | Limited | Limited |
| DoD license preference | Acceptable (GPL) | Acceptable but patent risk | Preferred (BSD) | Preferred (BSD) |

### 4.2 Recommendation: libx264

**libx264 is the clear choice for this project.** Here is why:

1. **CPU performance:** Encodes 1080p at 120-180 fps on modern consumer hardware. Even on old/legacy CPUs, the `faster` or `veryfast` preset achieves real-time 1080p at acceptable quality.
2. **ROI support:** The only codec with mature, well-documented macroblock-level QP control in FFmpeg.
3. **Static scene optimization:** H.264's reference frame architecture inherently exploits static backgrounds. Unchanged macroblocks cost nearly zero bits.
4. **Maturity:** ~20 years of development, exhaustive testing, runs everywhere.
5. **Playback compatibility:** Every device, browser, and player supports H.264.
6. **Minimal dependencies:** Compiles on anything with a C compiler.

**Recommended encoding settings for this project:**
- Preset: `fast` or `faster` (balance of speed and quality)
- CRF: 20-22 for overall quality baseline
- Profile: High
- ROI: Via FFmpeg `addroi` filter with macroblock QP offsets
- Threads: auto (use all available cores)

**Why not SVT-AV1?** It achieves better compression ratios (40-50% over x264) and has a BSD license (DoD-preferred), but it is too CPU-intensive for real-time encoding on legacy hardware. It would be an excellent choice for a system with modern multi-core CPUs. Worth noting as a future upgrade path.

**Why not x265?** Better compression than x264 (35-50%) but 3-10x more CPU cycles. Not viable for CPU-only legacy hardware. Also has patent licensing complications.

### 4.3 DoD Open-Source Licensing Notes

Per the January 2022 DoD CIO memo: software developed for non-National Security Systems should be "open-by-default." DoD-preferred licenses:
- Strongly recommended: BSD-3-clause, MIT, ISC, Apache-2.0
- Acceptable: GPL, LGPL

libx264's GPL v2 license is acceptable for DoD use but requires that derivative works also be GPL. Since our entire project is open-source on GitHub, this is not a concern.

---

## 5. CPU-Based Super-Resolution Enhancement

### 5.1 Purpose

After footage is offloaded from local storage, analysts may want to enhance compressed video for review. Super-resolution (SR) upscales low-resolution or heavily compressed images to recover detail. This is especially relevant for foreground ROIs that were compressed at moderate quality, or for legacy footage from low-resolution cameras.

### 5.2 Model Options for CPU Inference

#### Lightweight Models (Recommended for CPU)

| Model | Speed on CPU | Quality | Best For |
|---|---|---|---|
| ESPCN | 1-5 ms per frame | Good | Real-time batch processing |
| FSRCNN | 5-15 ms per frame | Good | Slightly better quality than ESPCN |
| LapSRN | 15-50 ms per frame | Better | Multi-scale upscaling (2x, 4x, 8x) |
| EDSR | 500+ ms per frame | Best (lightweight) | Offline only |

**ESPCN and FSRCNN** are the only models viable for CPU batch processing of surveillance footage. Both are available directly through OpenCV's `dnn_superres` module, making integration trivial:

```python
import cv2
sr = cv2.dnn_superres.DnnSuperResImpl_create()
sr.readModel("ESPCN_x4.pb")
sr.setModel("espcn", 4)
upscaled = sr.upsample(frame)
```

#### Real-ESRGAN (Heavyweight)

Real-ESRGAN produces the best visual quality using a GAN-based architecture (RRDB blocks + adversarial training). However:
- **CPU inference:** 100-500+ ms per frame at HD resolution. Not real-time.
- **Requires `--fp32` flag** for CPU mode (default fp16 is GPU-only).
- **Best use case:** Offline enhancement of high-value footage (faces, license plates) where processing time is not critical.
- Model variants: `RealESRGAN_x4plus` (general), `realesr-general-x4v3` (lighter), `RealESRNet_x4plus` (MSE loss, fewer hallucinations)

### 5.3 Recommendation for This Project

**Two-tier enhancement strategy:**

1. **Tier 1 (batch processing):** Use ESPCN or FSRCNN via OpenCV dnn_superres for fast CPU-based upscaling of all foreground ROIs after offload. Processing at 1-15 ms per frame is fast enough to enhance a week of footage overnight.

2. **Tier 2 (high-value analysis):** Use Real-ESRGAN in fp32 CPU mode (or RealESRNet for fewer hallucinations) for specific frames flagged as containing faces or other high-detail targets. Accept the 100-500 ms per frame cost since this is targeted, not bulk.

### 5.4 Hallucination Risks

The sponsor specifically raised this concern. Key findings:

**Known risks:**
- **License plates:** SR models can fabricate characters on severely degraded plates. Presenting hallucinated characters as evidence violates forensic standards.
- **Faces:** GAN-based SR can alter age features, add details that don't match the original identity, or generate plausible but incorrect facial features ("rejuvenation effect").
- **General:** Any generative model (Real-ESRGAN) can invent texture details that look realistic but are not present in the original data.

**Mitigations we should implement:**
- Apply SR only to foreground ROIs, not background (reduces hallucination surface area)
- Use RealESRNet (MSE loss, non-adversarial) instead of Real-ESRGAN for forensic applications. MSE-trained models blur rather than hallucinate.
- Always store original compressed footage alongside any enhanced version
- Mark enhanced output with metadata indicating it was AI-processed
- Never present SR output as definitive evidence

### 5.5 Video Temporal Consistency

Applying SR frame-by-frame creates flickering artifacts because each frame is processed independently. Solutions:
- **Temporal filtering:** Apply a simple temporal average across 3-5 enhanced frames to smooth flickering
- **Video-aware SR models:** SVRNet uses a separate-process-merge strategy designed for surveillance video
- **For our project:** Frame-by-frame ESPCN with post-hoc temporal smoothing is the most practical CPU approach

### 5.6 Quality Metrics

- **PSNR:** Measures pixel-level fidelity. Above 30 dB is acceptable, above 40 dB is excellent. Good for comparing compression quality but has weak correlation with perceived visual quality for SR.
- **SSIM:** Measures structural similarity. More perceptually meaningful than PSNR. Target: 0.85+ on foreground ROIs. More sensitive to compression artifacts than PSNR.
- **LPIPS:** Learned perceptual metric. Lower = more similar to ground truth. Best correlator with human perception. Use this as the primary quality metric for SR evaluation.
- **VMAF:** Netflix's perceptual quality metric. Good for video. Recommended if time permits.

---

## 6. Recommended Architecture

Based on all research findings, here is the recommended end-to-end pipeline:

```
[Static Camera Feed]
      |
      v
[Frame Reader] -- OpenCV VideoCapture (USB, IP, or file)
      |
      v
[Background Subtraction] -- OpenCV MOG2 (default) or KNN
      |                      Parameters: history=500, varThreshold=16, detectShadows=True
      v
[Mask Post-Processing] -- Morphological opening (3x3 kernel)
      |                    Morphological closing (5x5 kernel)
      |                    Contour filtering (min area = 500 px)
      v
[Bounding Box Extraction] -- cv2.findContours + cv2.boundingRect
      |
      v
[ROI Encoder] -- FFmpeg + libx264
      |           Foreground ROIs: CRF 20, preset "fast"
      |           Background: CRF 45, preset "fast"
      |           ROI via addroi filter + aq-mode=2
      v
[Metadata Writer] -- SQLite: timestamp, camera_id, targets_detected,
      |               roi_count, file_size, duration, file_path
      v
[Local Storage] -- Compressed .mp4 segments, ~60 seconds each
      |             Retention: ~1 week
      v
[Offload]
      |
      v
[Enhancement (Optional)] -- Tier 1: ESPCN/FSRCNN via OpenCV dnn_superres
                             Tier 2: Real-ESRGAN fp32 for high-value targets
                             Always keep original alongside enhanced version
```

### Technology Stack Summary

| Component | Technology | License | CPU-Only? |
|---|---|---|---|
| Background subtraction | OpenCV MOG2/KNN | Apache 2.0 | Yes |
| Video encoding | FFmpeg + libx264 | LGPL/GPL | Yes |
| Metadata | SQLite (Python stdlib) | Public Domain | Yes |
| Enhancement (Tier 1) | OpenCV dnn_superres (ESPCN) | Apache 2.0 | Yes |
| Enhancement (Tier 2) | Real-ESRGAN / RealESRNet | BSD | Yes (fp32) |
| Pipeline orchestration | Python 3.9+ | PSF | Yes |
| Quality metrics | scikit-image (PSNR, SSIM) | BSD | Yes |
| Testing | pytest | MIT | Yes |

All components are open source, royalty-free, and run on CPU-only hardware.

---

## 7. References

### Background Subtraction
- Zivkovic, Z. (2004). "Improved adaptive Gaussian mixture model for background subtraction." ICPR.
- OpenCV Documentation: Background Subtraction - https://docs.opencv.org/4.x/d1/dc5/tutorial_background_subtraction.html
- Background Subtractor Comparisons - https://github.com/AhadCove/Background-Subtractor-Comparisons
- BGSLibrary (C++ multi-algorithm library) - https://github.com/andrewssobral/bgslibrary

### ROI Compression
- h264-roi (macroblock QP control) - https://github.com/ChaoticEnigma/h264-roi
- "A Foreground-background Parallel Compression with Residual Encoding for Surveillance Video" - https://arxiv.org/abs/2001.06590
- FFmpeg Codecs Documentation - https://ffmpeg.org/ffmpeg-codecs.html
- CRF Guide - https://slhck.info/video/2017/02/24/crf-guide.html
- Rate Control Modes - https://slhck.info/video/2017/03/01/rate-control.html

### Codecs
- x264 Licensing - https://x264.org/licensing/
- SVT-AV1 Codec Wiki - https://wiki.x266.mov/docs/encoders/SVT-AV1
- DoD FOSS Policy - https://dodcio.defense.gov/portals/0/documents/foss/dodfoss_pdf.pdf
- Code.mil: How to Open Source Code - https://code.mil/how-to-open-source.html
- NIST IR 8161: CCTV Digital Video Export Profile - https://nvlpubs.nist.gov/nistpubs/ir/2019/NIST.IR.8161r1.pdf

### Super-Resolution
- Real-ESRGAN Official Repo - https://github.com/xinntao/Real-ESRGAN
- BSRGAN (ICCV 2021) - https://github.com/cszn/BSRGAN
- OpenCV dnn_superres - https://docs.opencv.org/4.x/d9/de0/group__dnn__superres.html
- SwinIR (Transformer-based restoration) - https://github.com/JingyunLiang/SwinIR
- "Hallucination Score in Super-Resolution" - https://arxiv.org/html/2507.14367v2

### Metrics
- VMAF (Netflix) - https://github.com/Netflix/vmaf
- LPIPS - https://github.com/richzhang/PerceptualSimilarity
