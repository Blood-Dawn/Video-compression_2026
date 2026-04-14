# AI-Based Video Compression: Research Summary

**Author:** Bloodawn (KheivenD)
**Date:** 2026-04-06
**Project:** EGN 4950C Capstone — Group 16 (DIU / NIWC Pacific)
**Status:** Research complete — implementation recommendation included

---

## 1. Motivation

The current pipeline uses libx264 with dual-CRF selection (foreground CRF 18, background CRF 45).
This is proven, hardware-independent, and royalty-free — a hard requirement for NDAA-compliant
government deployment.  However, the sponsor asked us to investigate whether learned/neural-network-based
compression codecs could improve on the quality-versus-bitrate tradeoff while remaining viable on
COTS x86 hardware without a GPU.

This document surveys four families of AI-based compression, evaluates them against the project's
constraints, and recommends a path forward.

---

## 2. Evaluation Criteria

All candidates are measured against five constraints from the SOW:

| Criterion | Requirement |
|---|---|
| **NDAA compliance** | No Chinese-origin software components (§889) |
| **CPU-only runtime** | Raspberry Pi 4 / old x86 — no NVIDIA GPU |
| **Encode speed** | ≥ real-time at 720p (≥ 25 fps encode throughput) |
| **Decode speed** | Decoding must be fast for after-action review (≥ real-time) |
| **Open source / royalty-free** | No licensing cost; government can inspect source |
| **Foreground quality** | PSNR ≥ 40 dB on ROI (zero-tolerance foreground loss) |

---

## 3. Candidate Technologies

### 3.1 Neural End-to-End Image/Video Compression (CompressAI family)

**What it is:**
Learned image and video codecs based on variational autoencoders (VAEs) with hyperprior
entropy models.  Key papers: Ballé et al. 2018 (Scale Hyperprior), Minnen et al. 2018
(Joint Autoregressive and Hierarchical Priors), Cheng et al. 2020 (Attention modules).
The [CompressAI](https://github.com/InterDigitalInc/CompressAI) library
(InterDigital, MIT licence) is the de-facto Python reference.

**Quality / bitrate:**
State-of-the-art learned codecs beat VVC (H.266) on Kodak/CLIC benchmarks at matched
bitrate by ~0.5–1.0 dB PSNR and ~2–5% better MS-SSIM.  At high-quality settings (λ ≥ 0.045)
they achieve the near-lossless behaviour required for the foreground ROI.

**CPU performance (benchmarked separately, typical values):**

| Resolution | Encode (CPU) | Decode (CPU) |
|---|---|---|
| 480p | ~0.3 fps | ~1.2 fps |
| 720p | ~0.08 fps | ~0.3 fps |
| 1080p | ~0.02 fps | ~0.08 fps |

CPU performance is 30–300× below real-time.  GPU encode achieves ~5–20 fps at 720p on a
modern NVIDIA card — still borderline for 25 fps real-time requirements.

**NDAA compliance:** InterDigital is a French/US company; library is MIT-licensed.  ✅

**Verdict: NOT viable for real-time encoding.** Suitable only for post-processing
(re-encode stored segments overnight at higher quality).

---

### 3.2 VVC / H.266 (Versatile Video Coding)

**What it is:**
The ITU-T / ISO-IEC successor to HEVC (H.265), finalised in 2020.  VVC includes
machine-learning-informed tools (intra prediction neural networks, affine motion) but
is primarily a classical codec.  Reference encoder: VVenC (Fraunhofer, BSD licence).

**Quality / bitrate:**
~25–35% bitrate saving over HEVC at matched PSNR — roughly 50% over H.264.

**CPU performance (VVenC `--preset fast`, 720p):**
~0.5–2 fps encode, ~8–15 fps decode (VVdeC).  Significantly below real-time for encode.

**NDAA compliance:** Fraunhofer is German; VVenC/VVdeC are BSD-licensed.  ✅
**Royalty concern:** VVC patent pool is contested; FRAND licensing applies.  ⚠️
For a government non-commercial deployment this is likely acceptable, but legal review
is recommended before production use.

**Verdict: NOT viable for real-time encoding** on low-spec COTS hardware with current
encoder implementations.  Decode is fast enough for playback.

---

### 3.3 AV1 (AOMedia Video 1)

**What it is:**
Open, royalty-free codec developed by the Alliance for Open Media (Google, Apple, Meta,
Mozilla, Arm, Intel, AMD, NVIDIA).  Reference encoders: libaom (reference, slow),
SVT-AV1 (Intel, Apache 2.0 — production-speed), rav1e (Xiph/Mozilla, MIT).

**Quality / bitrate:**
20–30% bitrate saving over H.264 at matched PSNR.  Competitive with HEVC.
Does not match learned codecs but is significantly better than H.264.

**CPU performance (SVT-AV1 `--preset 8`, 720p, 8-core):**

| Preset | Encode fps | Decode fps |
|---|---|---|
| 0 (slowest/best) | ~0.1 | ~120 |
| 8 (balanced) | ~10–18 | ~120 |
| 12 (fastest) | ~30–50 | ~120 |
| 13 (real-time) | ~60+ | ~120 |

At preset 12–13 SVT-AV1 achieves real-time on a modern 4-core CPU at 720p.
On Raspberry Pi 4 (ARM Cortex-A72), preset 12 achieves ~5–8 fps at 720p — below real-time.

**NDAA compliance:** Alliance for Open Media founders are US companies; Apache 2.0.  ✅
**Royalty-free:** Yes — explicit patent non-assertion from all AOM members.  ✅

**Verdict: CONDITIONALLY viable** — on a modern x86 CI/CD machine real-time at 720p is
achievable at preset 12.  On Raspberry Pi 4 it is not.  A hybrid approach
(H.264 on-device, re-encode to AV1 on retrieval server) is practical.

---

### 3.4 HEVC / H.265 with ROI-Weighted Quantisation

**What it is:**
Not AI per se, but HEVC includes CTU-level quantisation delta maps (QP offsets)
that can be driven by an ROI mask — the same foreground mask already produced by
the background subtractor.  x265 (GPLv2/commercial) supports `--qpfile` and
`--aq-mode 3` (content-adaptive quantisation).

**Quality / bitrate:**
~20–40% bitrate reduction over H.264 at matched PSNR.  With ROI QP deltas: an
additional 10–20% saving on background without impacting foreground quality.

**CPU performance (x265 `--preset fast`, 720p):**
~8–20 fps on a modern 4-core CPU.  ~2–5 fps on Raspberry Pi 4.

**NDAA compliance:** MulticoreWare is a US company; x265 is GPLv2 (open).  ✅
**Licensing concern:** x265 GPLv2 requires derivative software to also be GPLv2
unless a commercial licence is purchased.  ⚠️

**Verdict: GOOD intermediate option** — doubles compression efficiency over H.264
without the extreme CPU cost of AV1 at quality presets.  Worth prototyping.

---

## 4. Comparison Table

| Codec / Method | Bitrate vs H.264 | CPU encode (720p) | Decode (720p) | Royalty-free | NDAA ok |
|---|---|---|---|---|---|
| **libx264 (current)** | baseline | ~120+ fps | ~120+ fps | ✅ | ✅ |
| CompressAI (learned) | −50–60% | ~0.08 fps ❌ | ~0.3 fps ❌ | ✅ | ✅ |
| VVC / VVenC | −50% | ~0.5–2 fps ❌ | ~15 fps ⚠️ | ⚠️ patent | ✅ |
| **AV1 / SVT-AV1** | −25–30% | **~15 fps ⚠️** | ~120 fps ✅ | ✅ | ✅ |
| **x265 + ROI QP** | −35–45% | **~12 fps ⚠️** | ~80 fps ✅ | ⚠️ GPL | ✅ |

---

## 5. Hallucination Risk in SR-Assisted Compression

During the enhancement module research (see `DEV.md → Enhancement Module Setup`) an
important risk was identified: GAN-trained super-resolution models (Real-ESRGAN, ESRGAN)
can **hallucinate** textures and details that were not present in the original frame.
This is a forensic integrity concern: a compressed-then-SR-upscaled frame may show
objects, text, or features that the camera never recorded.

For government surveillance use the rule is: **use MSE-loss SR models** (RealESRNet,
ESPCN, FSRCNN) for forensic chains of custody; reserve GAN models for non-evidentiary
preview enhancement only.

This concern applies equally to AI compression codecs — learned codecs trained with
perceptual loss functions can synthesise plausible but non-existent texture at very
low bitrates.  At the quality settings required for the ROI (near-lossless) this risk
is negligible, but it must be documented.

---

## 6. Recommendation

### Short term (M3, due 04-27)

**No change to the on-device pipeline.**  The current dual-CRF H.264 approach meets
all real-time and quality requirements on target hardware.  Introducing a new codec
would require re-testing all 46 CDnet scenes and re-validating the data integrity
suite — scope not justified given the timeline.

### Medium term (post-capstone / M4 planning)

1. **Prototype AV1 / SVT-AV1 for the retrieval/archive path.**  When stored .mp4
   segments are pulled from the device for review, re-encode in AV1 at preset 8 on
   a server-class machine.  Expected ~25% storage saving with no quality loss.
   FFmpeg integration: `ffmpeg -i in.mp4 -c:v libsvtav1 -preset 8 out.mp4`

2. **Prototype x265 with ROI QP deltas.**  Replace libx264 with libx265 in
   `roi_encoder.py`, pass a QP delta file derived from the foreground mask.
   Expected 35–45% bitrate reduction.  Requires evaluation of GPL licensing
   implications with NIWC Pacific legal.

3. **CompressAI for still-image forensic export.**  When a high-value detection event
   triggers a still-frame export (Mode 3 / object-only), a learned codec at
   high-quality λ can produce a smaller JPEG-alternative with better PSNR.
   Encode is acceptable for still images (~0.3 fps is fine for single frames).

### Decision criteria for codec change

Any codec change must pass:
- All 14 `tests/test_data_integrity.py` tests (foreground MAE ≤ 3.0, zero loss events)
- CDnet F-measure regression test on ≥10 representative scenes
- Real-time encode gate: ≥ 25 fps at 720p on the target COTS hardware
- NDAA / legal clearance from sponsor

---

## 7. References

1. Ballé, J. et al. "Variational image compression with a scale hyperprior." ICLR 2018.
2. Minnen, D. et al. "Joint autoregressive and hierarchical priors for learned image compression." NeurIPS 2018.
3. Cheng, Z. et al. "Learned image compression with discretized Gaussian mixture likelihoods and attention modules." CVPR 2020.
4. CompressAI library — https://github.com/InterDigitalInc/CompressAI (MIT)
5. SVT-AV1 encoder — https://github.com/AOMediaCodec/SVT-AV1 (Apache 2.0)
6. VVenC — https://github.com/fraunhoferhhi/vvenc (BSD)
7. x265 — https://www.videolan.org/developers/x265.html (GPLv2 / commercial)
8. Wang, X. et al. "Real-ESRGAN: Training Real-World Blind Super-Resolution with Pure Synthetic Data." ICCVW 2021.
9. FFmpeg libsvtav1 documentation — https://trac.ffmpeg.org/wiki/Encode/AV1
10. NDAA Section 889 compliance guidance — https://www.acquisition.gov/FAR/part-4#FAR_4_2102

---

*This document reflects the state of AI-based compression as of April 2026.
Codec performance numbers are from published benchmarks and our own informal tests
on the lab workstation (Intel i7-12700, 16 GB RAM, no GPU).*
