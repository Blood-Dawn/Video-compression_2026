# SVCS Research Compendium

This document consolidates the research, literature review, benchmarking, and design-note
material produced for SVCS (Surveillance Video Compression System, EGN 4950C Capstone
Group 16, DIU / NIWC Pacific). It merges fifteen separate docs written between March 2026
and July 2026 into a single reference. Each section records where it came from. Measured
numbers, benchmark tables, citations, and the conclusions that decisions were based on are
preserved verbatim in substance; process chatter and pure duplication have been removed.
Where two source documents disagree, both positions are kept and the conflict is called out
(see the final section).

## Table of contents

1. [Compression research: codecs, literature, and the mode hierarchy](#1-compression-research-codecs-literature-and-the-mode-hierarchy)
2. [Detection research: background subtraction algorithms and tuning](#2-detection-research-background-subtraction-algorithms-and-tuning)
3. [Design notes: object memory and night video quality](#3-design-notes-object-memory-and-night-video-quality)
4. [Live stream and compression architecture](#4-live-stream-and-compression-architecture)
5. [Shipped feature: AI license-plate reader](#5-shipped-feature-ai-license-plate-reader)
6. [R4 Phase 1: UI/UX research round](#6-r4-phase-1-uiux-research-round)
7. [R4 Phase 2: better compression algorithms research round](#7-r4-phase-2-better-compression-algorithms-research-round)
8. [R4 Phase 3: competitor apps and gap analysis](#8-r4-phase-3-competitor-apps-and-gap-analysis)
9. [R4 Phase 5: plate-reader solution research round](#9-r4-phase-5-plate-reader-solution-research-round)
10. [R5 Task 5.1: VMAF-targeted rate control](#10-r5-task-51-vmaf-targeted-rate-control)
11. [Known discrepancies between source documents](#11-known-discrepancies-between-source-documents)

---

## 1. Compression research: codecs, literature, and the mode hierarchy

*(consolidated from ai_compression_research.md, compression_literature.md, mode_size_hierarchy.md)*

### 1.1 Motivation and evaluation criteria

The pipeline uses libx264 with dual-CRF selection (foreground CRF 18, background CRF 45).
That approach is proven, hardware independent, and royalty free, which is a hard requirement
for NDAA-compliant government deployment. The sponsor asked whether learned or neural-network
compression codecs could improve the quality-versus-bitrate tradeoff while staying viable on
COTS x86 hardware without a GPU. Research completed 2026-04-06 by Bloodawn (KheivenD).

All candidates were measured against five SOW constraints:

| Criterion | Requirement |
|---|---|
| NDAA compliance | No Chinese-origin software components (Section 889) |
| CPU-only runtime | Raspberry Pi 4 / old x86, no NVIDIA GPU |
| Encode speed | At or above real time at 720p (25 fps or better encode throughput) |
| Decode speed | Decoding must be at or above real time for after-action review |
| Open source / royalty free | No licensing cost; government can inspect source |
| Foreground quality | PSNR 40 dB or better on ROI (zero-tolerance foreground loss) |

### 1.2 Candidate codec families

**Neural end-to-end compression (CompressAI family).** Learned image and video codecs built
on variational autoencoders with hyperprior entropy models. Key papers: Balle et al. 2018
(Scale Hyperprior), Minnen et al. 2018 (Joint Autoregressive and Hierarchical Priors),
Cheng et al. 2020 (attention modules). Reference library:
[CompressAI](https://github.com/InterDigitalInc/CompressAI) (InterDigital, MIT).
State-of-the-art learned codecs beat VVC (H.266) on Kodak/CLIC at matched bitrate by roughly
0.5 to 1.0 dB PSNR and 2 to 5 percent better MS-SSIM. At high-quality settings (lambda 0.045
or higher) they reach the near-lossless behaviour the foreground ROI needs.

CPU throughput (typical measured values):

| Resolution | Encode (CPU) | Decode (CPU) |
|---|---|---|
| 480p | ~0.3 fps | ~1.2 fps |
| 720p | ~0.08 fps | ~0.3 fps |
| 1080p | ~0.02 fps | ~0.08 fps |

That is 30x to 300x below real time. GPU encode reaches roughly 5 to 20 fps at 720p on a
modern NVIDIA card, still borderline against the 25 fps requirement. NDAA: InterDigital is a
French/US company, MIT licensed, compliant. **Verdict: not viable for real-time encoding.**
Suitable only for post-processing (re-encode stored segments overnight at higher quality).

**VVC / H.266.** The ITU-T / ISO-IEC successor to HEVC, finalised 2020. Includes some
machine-learning-informed tools (intra prediction neural networks, affine motion) but is
primarily a classical codec. Reference encoder VVenC (Fraunhofer, BSD). Roughly 25 to 35
percent bitrate saving over HEVC at matched PSNR, roughly 50 percent over H.264. VVenC
`--preset fast` at 720p gives about 0.5 to 2 fps encode and 8 to 15 fps decode (VVdeC).
NDAA compliant (Fraunhofer, German, BSD), but the VVC patent pool is contested and FRAND
licensing applies; legal review is recommended before production use.
**Verdict: not viable for real-time encoding** on low-spec COTS hardware with current
encoders. Decode is fast enough for playback.

**AV1 (AOMedia).** Open, royalty-free codec from the Alliance for Open Media. Encoders:
libaom (reference, slow), SVT-AV1 (Intel, Apache 2.0, production speed), rav1e (Xiph/Mozilla,
MIT). 20 to 30 percent bitrate saving over H.264 at matched PSNR, competitive with HEVC, not
matching learned codecs but clearly better than H.264.

SVT-AV1 at 720p on 8 cores:

| Preset | Encode fps | Decode fps |
|---|---|---|
| 0 (slowest/best) | ~0.1 | ~120 |
| 8 (balanced) | ~10-18 | ~120 |
| 12 (fastest) | ~30-50 | ~120 |
| 13 (real-time) | ~60+ | ~120 |

At preset 12 to 13, SVT-AV1 hits real time on a modern 4-core CPU at 720p. On a Raspberry Pi 4
(ARM Cortex-A72), preset 12 gives about 5 to 8 fps at 720p, below real time. NDAA compliant,
royalty free with explicit patent non-assertion from all AOM members.
**Verdict: conditionally viable.** Real time at 720p is achievable on a modern x86 machine at
preset 12 but not on a Pi 4. A hybrid approach (H.264 on device, re-encode to AV1 on the
retrieval server) is practical.

**HEVC / H.265 with ROI-weighted quantisation.** Not AI as such, but HEVC supports CTU-level
quantisation delta maps (QP offsets) that can be driven by the same foreground mask the
background subtractor already produces. x265 supports `--qpfile` and `--aq-mode 3`. Roughly 20
to 40 percent bitrate reduction over H.264 at matched PSNR, plus an additional 10 to 20 percent
saving on the background from ROI QP deltas with no foreground quality impact. x265
`--preset fast` at 720p: about 8 to 20 fps on a modern 4-core CPU, about 2 to 5 fps on a Pi 4.
NDAA compliant (MulticoreWare, US, GPLv2), but GPLv2 would force derivative software to GPLv2
unless a commercial licence is purchased. **Verdict: good intermediate option**, doubles
compression efficiency over H.264 without AV1's extreme CPU cost at quality presets. Worth
prototyping.

### 1.3 Codec comparison summary

| Codec / method | Bitrate vs H.264 | CPU encode (720p) | Decode (720p) | Royalty free | NDAA ok |
|---|---|---|---|---|---|
| libx264 (current) | baseline | ~120+ fps | ~120+ fps | yes | yes |
| CompressAI (learned) | -50 to -60% | ~0.08 fps (fail) | ~0.3 fps (fail) | yes | yes |
| VVC / VVenC | -50% | ~0.5-2 fps (fail) | ~15 fps (marginal) | patent risk | yes |
| AV1 / SVT-AV1 | -25 to -30% | ~15 fps (marginal) | ~120 fps | yes | yes |
| x265 + ROI QP | -35 to -45% | ~12 fps (marginal) | ~80 fps | GPL concern | yes |

### 1.4 Hallucination risk in SR-assisted compression

GAN-trained super-resolution models (Real-ESRGAN, ESRGAN) can hallucinate textures and details
that were not present in the original frame. This is a forensic integrity concern: a
compressed-then-upscaled frame may show objects, text, or features the camera never recorded.

The rule for government surveillance use: **use MSE-loss SR models** (RealESRNet, ESPCN,
FSRCNN) for forensic chains of custody, and reserve GAN models for non-evidentiary preview
enhancement only. The same concern applies to learned compression codecs, which when trained
with perceptual losses can synthesise plausible but non-existent texture at very low bitrates.
At the near-lossless quality settings required for the ROI this risk is negligible, but it must
be documented.

### 1.5 Codec recommendation and change gate

Short term (M3, due 2026-04-27): **no change to the on-device pipeline.** The current dual-CRF
H.264 approach meets all real-time and quality requirements on target hardware. A new codec
would require re-testing all 46 CDnet scenes and re-validating the data integrity suite, which
is not justified on the timeline.

Medium term (post-capstone / M4 planning):

1. **Prototype AV1 / SVT-AV1 for the retrieval and archive path.** When stored .mp4 segments are
   pulled from the device for review, re-encode as AV1 at preset 8 on a server-class machine.
   Expected roughly 25 percent storage saving with no quality loss.
   FFmpeg: `ffmpeg -i in.mp4 -c:v libsvtav1 -preset 8 out.mp4`
2. **Prototype x265 with ROI QP deltas.** Replace libx264 with libx265 in `roi_encoder.py` and
   pass a QP delta file derived from the foreground mask. Expected 35 to 45 percent bitrate
   reduction. Requires GPL licensing review with NIWC Pacific legal.
3. **CompressAI for still-image forensic export.** For high-value detection events that trigger
   a still-frame export (Mode 3 / object-only), a learned codec at high-quality lambda produces
   a smaller JPEG alternative with better PSNR. Roughly 0.3 fps encode is acceptable for single
   frames.

Any codec change must pass: all 14 `tests/test_data_integrity.py` tests (foreground MAE at or
below 3.0, zero loss events); a CDnet F-measure regression test on 10 or more representative
scenes; a real-time encode gate of 25 fps or better at 720p on target COTS hardware; and NDAA /
legal clearance from the sponsor.

Codec numbers above are from published benchmarks plus informal tests on the lab workstation
(Intel i7-12700, 16 GB RAM, no GPU), current as of April 2026.

### 1.6 Literature review: selective and ROI-based surveillance compression

Prepared 2026-04-29 in response to sponsor feedback from the April 15 meeting. Cody Hayashi
asked whether prior research exists on intentional lossy compression that selectively discards
data without relevant objects, rather than compressing everything uniformly. He noted that a
straight storage-ratio comparison against H.264 is not apples to apples, because SVCS makes a
fundamentally different bet: that non-event frames carry no forensic value.

Conclusion: a body of relevant work exists, but the SVCS approach differs from it in one
important way, which is itself a genuine finding.

**Dual-quality encoding (foreground high, background low).** The most common approach treats
surveillance video as two streams with different importance. The video stays continuous;
nothing is dropped.
- Guo et al., "An Efficient Surveillance Video Coding Scheme for Static Camera Based Captured
  Video Data," IEEE ICCCAS 2019 (DOI: 10.1109/ICCCAS48645.2019.8711754). Background subtraction
  identifies less important regions, differential quantization is applied, every frame present.
- "Fast ROI-based HEVC coding for surveillance videos," IEEE ISCAS 2017
  (DOI: 10.1109/ISCAS.2017.7954496). Automatic ROI mask steers the HEVC encoder to allocate more
  bits where objects are detected. All frames preserved, spatially non-uniform quality.

SVCS Mode 0 does something similar (CRF 18 for ROI, CRF 45 for background) but within a single
FFmpeg pass rather than a custom HEVC parameter map.

**Foreground/background parallel compression with residual encoding.** Fan et al., arXiv:2001.06590
(2020). Encodes foreground and background independently, then uses an interpolation module to
share background across adjacent frames. Reports 69.5 percent fewer bits than H.265 at equivalent
PSNR (36 dB). The full video remains reconstructable. This is the closest prior work to SVCS
Mode 2: background extracted once and shared across frames. The difference is that their system
reconstructs the original frame while SVCS intentionally does not.

**ROI-based smart camera systems.** "Improving video communication in distributed smart camera
systems through ROI-based video analysis and compression," IEEE ICDSC 2012
(DOI: 10.1109/ICDSC.2012.6470145). Reduces camera-to-server bandwidth by transmitting only the
ROI crop plus a compressed full-frame thumbnail. The novelty is bandwidth, not storage. SVCS
Mode 3 is architecturally similar (store only bounding-box crops, black out the rest) but does
it in post-processing on recorded video rather than at the network edge.

**Selective resolution.** "Selective resolution for surveillance video compression," IEEE ISCAS
1996 (DOI: 10.1109/ISCAS.1996.582136). Early paper arguing most of the image outside the ROI can
be stored at reduced resolution without meaningful information loss. Predates deep-learning
detection but establishes the core premise the SVCS modes rely on.

**Background modeling for source compression.** "Surveillance Source Compression with Background
Modeling for Video Big Data," IEEE BigData 2016 (DOI: 10.1109/BigData.2016.7723680). Builds
background pictures using residual gradient and edge differences, then applies background-based
coding optimization at picture and coding-unit levels. Reports improved compression over standard
intra-frame coding for low-motion footage.

**Impact of compression on background subtraction accuracy.** "Assessing the Impact of Video
Compression on Background Subtraction" (ResearchGate, 2020). Tests MOG2 and other subtractors
across compression levels. Standard surveillance CRF values (30 to 35, roughly 1.5 to 2 Mbps)
have measurable but acceptable impact on detection F-score. Below CRF 45 background subtraction
accuracy degrades noticeably. Directly relevant: the SVCS CRF 45 background sits at the edge of
the reliable range. The paper validates the choice and flags it as a threshold to test
empirically.

**Event-based / activity-driven encoding.** "Accelerated Event-Based Feature Detection and
Compression for Surveillance Video Systems," arXiv:2312.08213 (2023). Uses an ADDER (Address,
Decimation, Detection, Reconstruction) representation modeling video as sparse asynchronous
intensity samples rather than frames. Reports 2.5:1 compression at equivalent visual quality.
A fundamentally different paradigm with no frame-rate concept. SVCS Mode 1 (skip frames with no
motion) is a simpler, frame-rate-preserving version of the same intuition, less aggressive but
deployable with standard players and no specialized decoders.

**Where SVCS sits.** The prior work falls into two groups. Group A compresses everything but
unevenly: high-quality ROI, low-quality background, every frame present and fully reconstructable
(papers 1, 2, 3, 5). Group B changes the representation entirely: event cameras, asynchronous
sampling, requiring specialized hardware or decoders (paper 7).

SVCS Modes 1, 2, and 3 are a third thing: **intentional temporal and spatial data elimination**.
The system does not merely encode the background poorly, it either skips entire frames (Mode 1),
freezes the background into a single reference frame (Mode 2), or blacks it out entirely (Mode 3).
The video is intentionally not a complete record of what the camera saw. Riley's framing in the
April 15 meeting was accurate: comparing output size to raw H.264 is not apples to apples because
a different decision has been made about what counts as worth storing.

The claim is not that this approach is better, but that it occupies a different point in the
design space: one that only makes sense when the operator has already decided background pixels
have no value, which is often true for fixed-position cameras on a DoD network watching a known
field of view. This distinction is worth one paragraph in the final report.

**Gaps and limitations to note in the report.**
1. *No ground-truth recovery test.* Prior work is evaluated on PSNR, which measures
   reconstruction fidelity. SVCS cannot be evaluated on PSNR for Modes 2 and 3 by design, since
   data was deleted intentionally. An appropriate metric would be detection recall (does the
   compressed output still let a human or algorithm identify the same events as the original?).
   Not yet run.
2. *No comparison against HEVC ROI coding.* The "Fast ROI-based HEVC" paper uses H.265 with a
   properly tuned ROI map; SVCS uses H.264 with two-pass CRF. A fair comparison would encode the
   same clip both ways and compare file size at equivalent detection accuracy. This is a gap.
3. *CRF 45 background quality.* The compression-vs-detection paper puts CRF 45 at the edge of
   reliable background-subtractor performance. The SVCS pipeline runs MOG2 on the uncompressed
   live frame before encoding, so detection is unaffected, but re-running background subtraction
   on stored Mode 0 output would lose some accuracy in the CRF 45 regions.

Search terms used: "selective video compression surveillance ROI-based static camera"
(IEEE Xplore); "event-driven video encoding background subtraction compression ratio surveillance"
(arXiv); "foreground background differential video compression surveillance background subtraction
CRF" (IEEE Xplore); full abstracts fetched for arXiv:2001.06590 and arXiv:2312.08213.

Additional references collected but not discussed above:
- "A new compression technique for surveillance videos." IEEE, 2016.
  https://ieeexplore.ieee.org/abstract/document/7544020
- "Semantic Maintained Video Compression by Background Blurring in Surveillance Scenarios."
  SpringerLink, 2025. https://link.springer.com/chapter/10.1007/978-981-95-3398-5_38

### 1.7 Mode size hierarchy: honest findings

Added 2026-05-02 after the question "each mode should lower file size incrementally, like
mode 3 < mode 2 < mode 1 < mode 0". `tests/test_mode_size_hierarchy.py` runs the real pipeline
end to end across all four modes and prints measured bytes.

> **Update 2026-05-31 (M0 TASK 0.3): the design changed and the numbers below are historical.**
> Foreground CRF is now progressive (mode0=18, mode1=18, mode2=23, mode3=38), so each mode
> compresses harder than the last. Mode 2 was previously stuck at CRF 18, which is the bug these
> measurements captured. With mode2 at CRF 23 it is no longer "consistently the largest"; it now
> trades a little forensic quality for smaller files. Also, mode3 is a single object-only clip,
> not the per-object `mode3_sparse/` tree referenced below; that rewrite never shipped on `app`.
> Re-run the test to capture fresh numbers when needed.

**TL;DR.** The intuitive ordering mode 3 < mode 2 < mode 1 < mode 0 is **not** what the
architecture delivers. The real ordering depends on the scene:

| Scene type | Smallest | Notes |
|---|---|---|
| Mostly-static backdrop, occasional motion | Mode 0 approximately equals Mode 1 (within ~5%) | libx264 + CRF 45 background is hard to beat |
| Static backdrop, one small moving object | Mode 0 (sparse loses to overhead) | Container headers dominate at small sizes |
| 1080p+, multiple small moving objects | Mode 3 sparse | Per-object .mp4s much smaller than full frames |
| Continuous motion (highway, crowded scene) | Mode 0 | Mode 1 cannot gate; sparse pays for many objects |
| Mostly empty perimeter cam, brief events | Mode 1 | Frame-gating drops 90% of frames |

**Measured on real CDnet 2014 footage (2026-05-02).** Bytes per segment after running the real
pipeline on pre-converted CDnet clips in `data/samples/cdnet_mp4/`, one clip per category.
Smallest in each row marked in the final column.

| Clip | dims | frames | source size | mode0 | mode1 | mode2 | mode3 | smallest |
|---|---|---|---|---|---|---|---|---|
| baseline_highway | 320x240 | 1700 | 5.5 MB | 556 K | 3,465 K | 5,721 K | 5,712 K | mode0 |
| baseline_pedestrians | 320x240 | ~1100 | 2.2 MB | 60 K | 929 K | 1,571 K | 840 K | mode0 |
| intermittentObjectMotion_parking | 320x240 | 2500 | 2.0 MB | 94 K | 132 K | 279 K | 143 K | mode0 |
| shadow_peopleInShade | 380x244 | 1199 | 2.2 MB | 92 K | 992 K | 2,255 K | 574 K | mode0 |
| nightVideos_busyBoulvard | 640x364 | ~1764 | (large) | 304 K | 7,269 K | 5,649 K | 295 K | mode3 |
| cameraJitter_traffic | 320x240 | 1570 | 6.3 MB | 4,532 K | 3,085 K | 3,890 K | 1,771 K | mode3 |
| thermal_park | 352x288 | 600 | 4.7 MB | 2,635 K | 2,098 K | 1,317 K | 592 K | mode3 |

`thermal_park` is the only clip where the strict mode3 < mode2 < mode1 < mode0 hierarchy holds.

What the data shows:
- **Mode 0 wins on 4 of 7 clips.** The dual-CRF baseline (foreground 18 / background 45) is
  extremely efficient on mostly-static, sparse-motion backgrounds, exactly where CDnet baseline,
  shadow, and parking footage lives. libx264's predictive coding does the heavy lifting.
- **Mode 3 sparse wins on 3 of 7 clips.** Win cases: continuous motion that defeats Mode 0's
  static-background optimization (`cameraJitter_traffic`), high-noise sources where every full
  frame costs many bits (`thermal_park`), and clips with heavy global noise but small actual
  targets (`busyBoulvard`).
- **Mode 1 is smallest on 0 of 7 clips.** At CDnet resolutions every event frame still costs
  per-frame headers; gating does not drop enough to overtake Mode 0's compressed-background
  savings.
- **Mode 2 is smallest on 0 of 7 clips** and is consistently largest or near-largest; it
  explicitly trades bytes for forensic context.

The user-expected strict hierarchy does not hold on real surveillance footage. It held in 1 of 7
clips (`thermal_park`), and only because thermal cameras have unusually high per-frame noise that
the sparse encoder dodges entirely.

**Real-data verdict on mode selection.**
- Default to **Mode 0** for storage; it is smallest on the majority of CDnet scenes.
- Switch to **Mode 3 sparse** when (a) the camera has heavy global noise (thermal, low light,
  sensor noise), (b) the frame is constantly busy so Mode 0's CRF-45-background win disappears,
  or (c) the deployment is downstream-CV-pipeline-first and per-object videos are wanted directly.
- Use **Mode 1** for archival-grade event-only retention. Storage is comparable or larger than
  Mode 0 at these resolutions, but the rest of the timeline is genuinely gone, which is a
  different value proposition.
- Use **Mode 2** for forensic context, not for size. Always larger or near-largest.

**On a synthetic clip.** Mode 1 is essentially the same as Mode 0 because the test clip has motion
in 150 of 180 frames. Mode 2 is bigger than Mode 0 because it lifts every frame to CRF 18. Mode 3
sparse is bigger than Mode 0 because per-file `.mp4` container overhead (roughly 10 KB minimum)
plus `manifest.json` exceeds what is saved by skipping background pixels on one small object.

**On real footage the relative numbers shift dramatically.** On the M1 CDnet baseline runs (per
`docs/final_report.md`), Mode 0's effective ratio averaged 6.3x versus naive H.264, meaning about
6x compression even on full-frame output. On clips where vehicles are 0.5 to 2 percent of frame
area at 1080p, Mode 3 sparse is consistently 5 to 20x smaller than Mode 0 because the
`(plate_W x plate_H) / (1920 x 1080)` ratio is microscopic.

**Why the strict hierarchy does not hold.** Each mode optimises for something different.
- *Mode 0* is the storage baseline: dual CRF on full frames. libx264 already eliminates global
  redundancy across frames, so static backgrounds compress to near-zero bits regardless of CRF.
  The CRF 45 versus CRF 18 difference matters only when the background is complex.
- *Mode 1* drops frames with no detected motion. Win condition: long stretches of empty scene.
  Where every frame has motion, Mode 1 approximately equals Mode 0.
- *Mode 2* stores a clean background keyframe plus per-frame foreground patches composited over
  it, for forensic context. Cost: every frame is treated as having targets.
- *Mode 3 sparse* writes per-object `.mp4`s. Win condition: large frames, small objects, few
  objects. Loss condition: small frames with many objects (per-file container overhead dominates)
  or very short segments.

**What the tests do assert.** `tests/test_mode_size_hierarchy.py` enforces only invariants that
hold across all reasonable scenes: every mode runs end to end without raising; every mode produces
output smaller than the uncompressed raw bytes; Mode 3 produces a sparse directory with
`manifest.json` plus at least one `object_*.mp4`; every produced `.mp4` is decodable by OpenCV
(catches FFmpeg pipe truncation regressions); Mode 3 does not blow up beyond 3x Mode 0 (catches
sparse-encoder header-overhead regressions). The suite deliberately does **not** assert
`mode3 < mode2 < mode1 < mode0`, because that is not a true property of the system.

**Sponsor messaging (May 6 capstone).** Modes are not strictly ordered by storage; they are
optimised for different operational tradeoffs. On real surveillance footage with sparse motion in
large frames (the actual sponsor use case) Mode 3 sparse is the storage winner, typically 5 to 20x
smaller than Mode 0. On dense-motion or low-resolution scenes Mode 0 with dual CRF is surprisingly
hard to beat, which is a positive finding: the baseline pipeline is already doing the right thing
there. Mode 2 is the right pick for forensic review, not for storage.

If a strict size hierarchy is what the sponsor wants, the right architectural change is per-mode
CRF tuning (for example lifting Mode 2 background CRF from 18 to 28, or moving Mode 3's manifest
into a single-file binary format). Those are real follow-up items, not session-time fixes.

---

## 2. Detection research: background subtraction algorithms and tuning

*(consolidated from algorithm_comparison.md, detection_tuning.md, detection_tuning_results.md)*

### 2.1 MOG2 versus KNN on CDnet 2014

Author: Jorge Sanchez, 2026-04-11, branch `feature/benchmarking-milestone2`. Compares MOG2 and
KNN across 10 CDnet 2014 scene categories (46 scenes total). Data source:
`outputs/cdnet_batch_results.log`, full 46-scene batch run 2026-03-26.

Average foreground coverage by category:

| Category | MOG2 avg FG% | KNN avg FG% | Winner |
|---|---|---|---|
| turbulence | 1.57% | 1.57% | Tie |
| badWeather | 1.67% | 1.67% | Tie |
| lowFramerate | 3.07% | 3.07% | Tie |
| thermal | 3.17% | 3.17% | Tie |
| intermittentObjectMotion | 3.31% | 3.31% | Tie |
| dynamicBackground | 3.81% | 3.81% | Tie |
| shadow | 4.52% | 4.52% | Tie |
| cameraJitter | 5.03% | 5.03% | Tie |
| nightVideos | 5.66% | 5.66% | Tie |
| baseline | 8.11% | 8.11% | Tie |

**Key finding:** MOG2 and KNN produce identical average foreground coverage across all 10
categories. The difference shows up in edge-case behavior, not average FG%, which is why deeper
analysis was required.

**MOG2 profile.** Models each pixel's background as a mixture of up to 5 Gaussians, automatically
selecting how many each pixel needs. Project parameters: `history=500`, `varThreshold=16` (day) or
`30` (night), `detectShadows=True` (marks shadows as gray 127 rather than white 255). Performance:
roughly 64 fps at 1080p on standard hardware, 15 to 25 fps on Raspberry Pi at 640x480. Handles
gradual lighting changes (sunrise/sunset) well; built-in shadow detection reduces false positives.
Weaknesses: sudden lighting changes (lights switching on or off) can confuse the model temporarily,
and shadow detection adds roughly 10 to 20 percent processing overhead.

**KNN profile.** Stores actual pixel color samples from recent frames and classifies new pixels by
comparing to their K nearest historical neighbors. Roughly 40 to 50 fps on standard hardware
(slower than MOG2), higher memory usage (raw samples rather than compact Gaussian parameters),
better boundary definition on foreground objects, and better handling of non-Gaussian noise
(infrared/thermal). Weaknesses: higher CPU and memory, no built-in shadow detection, less suited
to legacy low-spec hardware.

Tradeoff summary:

| Factor | MOG2 | KNN |
|---|---|---|
| Speed | ~64 fps | ~40-50 fps |
| Memory usage | Low (Gaussian params) | Higher (raw samples) |
| Shadow detection | Built-in | None |
| Edge case FP rate | Lower | Higher |
| Low-light / IR footage | Good | Better |
| Legacy hardware | Excellent | Adequate |
| Average FG% (CDnet) | 3.81% avg | 3.81% avg |

**Production recommendation: use MOG2 as the primary algorithm.** Reasons: identical detection
accuracy on the benchmark so there is no accuracy benefit to KNN for typical daylight footage;
better CPU performance (about 64 fps versus 40 to 50 fps at 1080p), which matters on the legacy
low-spec hardware the sponsor requires; lower memory footprint; built-in shadow handling that
removes the need for extra post-processing; and confirmation from Kheiven's CDnet sweep
(session_log_2026-03-26.md).

Switch to KNN for: thermal or near-infrared footage, scenes with highly non-Gaussian noise, or
when sharper foreground boundaries are needed downstream.

Recommended defaults:

```python
# Daytime
BackgroundSubtractor(method='MOG2', history=500, var_threshold=16, detect_shadows=True)

# Night / low-light
BackgroundSubtractor(method='MOG2', history=500, var_threshold=30, detect_shadows=True)
```

References: Zivkovic, Z. (2004), "Improved adaptive Gaussian mixture model for background
subtraction," ICPR; OpenCV background subtraction documentation; CDnet 2014 benchmark
(www.changedetection.net); team batch results at `outputs/cdnet_batch_results.log` (2026-03-26).

### 2.2 Synthetic-condition tuning sweep (Section 2.7)

Author: Jorge Sanchez (@sanchez-jorge), 2026-04-12, branch `feature/detection-tuning`. Tested MOG2
and KNN across three synthetic lighting conditions: daytime (bright static background,
brightness=120, high-contrast object entry), night (dark noisy background, brightness=25,
noise_std=6, dim object entry), and mixed lighting (background gradually shifts bright to dim,
simulating dusk). Each condition trained the model on 60 background frames, then measured false
positive rate (fraction of pixels flagged foreground on a static scene, acceptance criteria below
2 percent) and false negative rate (fraction of object pixels missed when a person-sized object
enters).

| Condition | Method | varThr | hist | CLAHE | FP% | FN% | Pass? |
|---|---|---|---|---|---|---|---|
| daytime | MOG2 | 16 | 500 | N | 0.00% | 0.07% | Y |
| daytime | MOG2 | 30 | 500 | N | 0.00% | 0.07% | Y |
| daytime | MOG2 | 16 | 200 | N | 0.00% | 0.07% | Y |
| daytime | MOG2 | 40 | 500 | N | 0.00% | 0.07% | Y |
| daytime | MOG2 | 16 | 500 | Y | 0.00% | 0.07% | Y |
| daytime | MOG2 | 30 | 500 | Y | 0.00% | 0.07% | Y |
| daytime | KNN | - | 500 | N | 0.00% | 0.07% | Y |
| daytime | KNN | - | 200 | N | 0.00% | 0.07% | Y |
| daytime | KNN | - | 500 | Y | 0.00% | 0.07% | Y |
| daytime | KNN | - | 500 | Y* | 0.00% | 0.07% | Y |
| night | MOG2 | 16 | 500 | N | 0.00% | 0.07% | Y |
| night | MOG2 | 30 | 500 | N | 0.00% | 0.07% | Y |
| night | MOG2 | 16 | 200 | N | 0.00% | 0.07% | Y |
| night | MOG2 | 40 | 500 | N | 0.00% | 0.07% | Y |
| night | MOG2 | 16 | 500 | Y | 0.01% | 0.12% | Y |
| night | MOG2 | 30 | 500 | Y | 0.00% | 0.12% | Y |
| night | KNN | - | 500 | N | 0.00% | 0.07% | Y |
| night | KNN | - | 200 | N | 0.00% | 0.07% | Y |
| night | KNN | - | 500 | Y | 2.47% | 0.07% | N |
| night | KNN | - | 500 | Y* | 2.47% | 0.07% | N |
| mixed_lighting | MOG2 | 16 | 500 | N | 0.00% | 0.07% | Y |
| mixed_lighting | MOG2 | 30 | 500 | N | 0.00% | 0.07% | Y |
| mixed_lighting | MOG2 | 16 | 200 | N | 0.00% | 0.07% | Y |
| mixed_lighting | MOG2 | 40 | 500 | N | 0.00% | 0.07% | Y |
| mixed_lighting | MOG2 | 16 | 500 | Y | 0.00% | 0.07% | Y |
| mixed_lighting | MOG2 | 30 | 500 | Y | 0.00% | 0.07% | Y |
| mixed_lighting | KNN | - | 500 | N | 50.45% | 0.00% | N |
| mixed_lighting | KNN | - | 200 | N | 50.57% | 0.00% | N |
| mixed_lighting | KNN | - | 500 | Y | 50.03% | 0.00% | N |
| mixed_lighting | KNN | - | 500 | Y* | 50.07% | 0.00% | N |

`Y*` = night_mode=True (CLAHE plus raised varThreshold).

Headline results: MOG2 passes in every tested configuration across all three conditions. KNN fails
at night when CLAHE is applied (2.47% FP, above the 2% bar) and fails catastrophically under mixed
/ transitional lighting (about 50% FP in every configuration, meaning roughly half the frame is
flagged foreground during the dusk transition).

Recommended parameter sets from this sweep:
- **Daytime MOG2:** `varThreshold=16, history=500, detectShadows=True, min_area=500`
- **Daytime KNN:** `history=500, detectShadows=True, min_area=500`
- **Night MOG2:** `varThreshold=30, history=500, detectShadows=True, min_area=500`
  (use `night_mode=True`)
- **Night KNN:** `history=500, detectShadows=True, min_area=500`, no CLAHE, because CLAHE
  increases false positives on a noisy background
- **Mixed / transitional light:** the source document's recommendation section is truncated after
  the heading; the measured data supports MOG2 in any tested configuration and rules out KNN.

### 2.3 Earlier standalone MOG2 tuning pass

A separate, earlier tuning document records a different result. Baseline default MOG2
(`history=500, varThreshold=16, detectShadows=True`) was observed to be very sensitive to small
pixel changes, produced false positives on static scenes, and detected motion quickly but with
noise. The tuned parameters landed on `history=500, varThreshold=50, detectShadows=False`, giving
0 detections (0% false positives) on a static scene, consistent detection across frames on a
moving scene, and detection within roughly 1 to 3 frames after motion begins. Its final
recommendation is `varThreshold=50, detectShadows=False`. This conflicts with sections 2.1 and 2.2;
see section 11.

---

## 3. Design notes: object memory and night video quality

*(consolidated from design_note_object_memory.md, design_note_night_video_quality.md)*

### 3.1 Object memory and reference-based recognition

Status: Proposed. Date 2026-03-24, proposed by Bloodawn (KheivenD), assigned to Victor De Souza
Teixeira (lead) and Riley Roberts (performance/indexing).

**Problem.** The pipeline detects foreground objects and compresses around them, but treats every
detection as a new unknown event. Two downstream problems follow. First, redundant storage: a base
entry camera sees the same 50 authorized vehicles every day, and every pass creates a new
high-quality clip of an already-known plate, wasting storage that could hold genuinely novel
events. Second, hallucination risk in enhancement: applying AI upscaling to a plate it has never
seen means reconstructing detail from learned statistics rather than ground truth, which can look
plausible but be wrong. That is a known forensic liability.

**Proposed solution: an object registry** answering one question before storing a clip, "have I
seen this object before, and does the context match?" Three-branch decision tree:

```
New detection arrives
    |
    +-- Seen before? --> No  --> Store HIGH-QUALITY snapshot + clip, add to registry
    |
    +-- Seen before? --> Yes, same context (same camera, same entry point)
    |                       --> Log the sighting only (timestamp, camera, confidence)
    |                       --> Do NOT store a new clip, saves the storage
    |
    +-- Seen before? --> Yes, DIFFERENT context (different gate, unexpected location)
                            --> ALERT, flag as anomaly, store full clip with priority tag
```

"Seen before" means a feature vector (perceptual hash of the ROI crop) matches an existing registry
entry above a similarity threshold.

**Storage model.** On first sighting: a single high-quality screenshot of the ROI crop is saved to
`outputs/known_objects/<object_id>.jpg`, a short clip of the first sighting to
`outputs/known_objects/<object_id>_first_sighting.mp4`, and a row inserted into a new
`object_registry` SQLite table. On subsequent sightings only a row goes into `object_sightings`
(timestamp, camera, confidence), no new video file. Net result: a 30-second clip at 30 fps becomes
a single JPEG plus a table row.

Estimated reduction for a vehicle passing a gate 3 times per day for 30 days: current pipeline
stores 90 compressed clips; with object memory, 1 reference JPEG plus 1 first-sighting clip plus 90
sighting rows, roughly 89 clip files eliminated per vehicle per month.

Proposed schema addition to `metadata.db`:

```sql
-- One row per unique known object (vehicle, person badge, etc.)
CREATE TABLE IF NOT EXISTS object_registry (
    object_id       TEXT PRIMARY KEY,   -- UUID or perceptual hash
    label           TEXT,               -- "vehicle", "person", "unknown"
    first_seen      TEXT,               -- ISO timestamp
    first_camera    TEXT,               -- camera_id where first detected
    reference_path  TEXT,               -- path to the reference screenshot
    clip_path       TEXT,               -- path to first-sighting clip
    notes           TEXT                -- manual annotations
);

-- One row every time a known object is spotted again
CREATE TABLE IF NOT EXISTS object_sightings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id       TEXT REFERENCES object_registry(object_id),
    timestamp       TEXT NOT NULL,
    camera_id       TEXT,
    confidence      REAL,               -- similarity score vs. reference
    flagged         INTEGER DEFAULT 0,  -- 1 if context anomaly detected
    clip_path       TEXT                -- populated only if flagged=1
);
```

**Hallucination mitigation.** For objects already in the registry, do not apply AI
super-resolution. Return the stored high-quality reference snapshot and composite it over the
enhanced frame for the review UI. A license plate is then never upscaled by a neural network that
could hallucinate digits; it is shown exactly as captured during its first clean sighting. For
objects not in the registry (first sighting or low-confidence match), apply super-resolution with a
visible watermark `[AI-ENHANCED - NOT FORENSIC ORIGINAL]` and log which frames were enhanced with
which model.

**Feature matching approach.** Cheapest viable approach on CPU-only hardware: crop the ROI bounding
box, compute a perceptual hash (pHash via the `imagehash` library) of the crop, compare Hamming
distance against all registry entries, and treat Hamming distance of 10 or less as a match
(empirically tuned, adjust during M2). For higher accuracy on plates specifically, use ORB
(Oriented FAST and Rotated BRIEF) descriptors via OpenCV: royalty free, CPU only, under 5 ms per
frame, storing 500 keypoint descriptors per registered object and matching with BFMatcher plus a
ratio test. pHash handles the common case fast; ORB is the fallback for ambiguous matches.

Milestone assignment: schema migration, pHash extraction and registry lookup, reference screenshot
writer, and anomaly flagging all to Victor at Milestone 2; ORB descriptor matching for plates to
Riley as a Milestone 2 stretch; pipeline integration (hooking detection into the registry) to
Bloodawn (KheivenD) at Milestone 2; and the with-versus-without storage-savings benchmark to
Bloodawn (KheivenD) at Milestone 3.

Open questions: retention policy for registered objects (Navy policy TBD, ask Cody); whether faces
are in scope or only plates and vehicles (privacy implications); and what similarity threshold
should trigger an anomaly alert versus a low-confidence miss. The note was to be reviewed with
sponsor Cody Hayashi before Milestone 2 implementation.

### 3.2 Night video quality and light glare

Status: Observed issue, needs investigation. Date 2026-03-24, reported by Bloodawn (KheivenD),
assigned to Riley Roberts (algorithm tuning) and Bloodawn (KheivenD) (pipeline integration).

**Observation.** During the first demo run on `data/dataset/nightVideos/bridgeEntry/`, the output
comparison images showed noisy and unclear foreground masks at night. Bright point light sources on
the bridge (streetlamps, vehicle headlights) create glare halos that bleed into surrounding pixels.
Both MOG2 and KNN pick this light variation up as foreground even when nothing is moving.

MOG2 and KNN also produced opposite results at night compared to daytime:

| Scene | MOG2 avg FG | KNN avg FG |
|---|---|---|
| highway (day) | 8.76% | 7.10% |
| bridgeEntry (night) | 2.10% | 4.42% |

At night KNN reports MORE foreground than MOG2, the reverse of daytime behavior. Likely
explanation: MOG2's Gaussian model gradually absorbs flickering light sources into the background
model over time and suppresses them, while KNN stores raw pixel samples and stays sensitive to any
pixel-level variation from flicker or glare, treating it as activity even with no real object
present.

**Why it matters.** For the sponsor use case (base entry surveillance) cameras run 24/7. Noisy
night masks cause two problems: false positives inflate storage, because the pipeline flags light
halos as foreground and encodes them at high CRF despite holding no intelligence value; and object
detection becomes unreliable, because a vehicle's headlights may be detected as a large foreground
blob while the vehicle body is lost in the dark background.

**Proposed solutions, in order of feasibility.**

1. **CLAHE preprocessing (implement first, low effort, high impact).** Apply Contrast Limited
   Adaptive Histogram Equalization to each frame before background subtraction to normalize local
   contrast and reduce bloom from point light sources.

   ```python
   # Add to BackgroundSubtractor.apply() as optional preprocessing step
   clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
   lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
   lab[:, :, 0] = clahe.apply(lab[:, :, 0])
   frame_enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
   ```

2. **Increase MOG2 varThreshold for night scenes.** The default 16 is calibrated for daytime. At
   night, sensor grain and compression artifacts raise pixel noise; 25 to 35 reduces static-noise
   false positives without missing real objects.

   ```python
   subtractor_night = BackgroundSubtractor(method="MOG2", var_threshold=30, history=700)
   ```

3. **Use the CDnet thermal dataset for testing.** CDnet 2014 includes a `thermal/` category with IR
   footage; thermal cameras are unaffected by visible light glare and produce clean masks in any
   lighting. The `corridor`, `lakeSide`, and `park` clips are directly applicable.

   ```bash
   python demo_detection.py --input data/dataset/thermal/corridor/ --all-methods --sample-rate 20
   ```

4. **SuBSENSE / LOBSTER algorithms (Milestone 2 stretch).** Pixel-level background subtraction
   designed for challenging conditions including night video, using local binary pattern features
   instead of raw pixel values, making them robust to lighting variation and glare. SuBSENSE paper:
   St-Charles et al., TPAMI 2015. OpenCV does not include these natively; they require `pybgs`.

5. **Nighttime-specific CDnet evaluation.** When reporting night results, note the algorithm flip
   (MOG2 tighter than KNN at night) and flag it as an open research question. The sponsor should be
   made aware that nighttime performance needs a different tuning profile than daytime.

Immediate action items were: add CLAHE preprocessing to `BackgroundSubtractor` (Riley, M1); run the
demo on `thermal/corridor` and `thermal/lakeSide` (Bloodawn); benchmark CLAHE versus no-CLAHE on
bridgeEntry (Riley, M1); add a `--night-mode` flag to `pipeline.py` that sets a higher varThreshold
(Bloodawn, M2).

**Better night video sources for future testing.** CDnet nightVideos category (already downloaded,
6 clips: bridgeEntry, busyBoulvard, fluidHighway, streetCornerAtNight, tramStation, winterStreet);
CDnet thermal category (already downloaded, IR footage, no glare issue); the ATON dataset
(Abandoned Objects at Night); the LASIESTA dataset (indoor and outdoor night sequences with ground
truth); and self-recorded footage (a phone camera pointed at a lit parking lot from a static
position for 2 or more minutes gives clean test data matching the actual use case).

---

## 4. Live stream and compression architecture

*(consolidated from live_stream_and_compression.md)*

Last updated 2026-04-20.

### 4.1 Option A: how the current system works (two independent features)

There are two completely separate systems in the dashboard. They do not share state, threads, or
output. Both can run at the same time from the same source, operating independently.

**Feature 1: HLS live stream (monitoring and preview).** The "Live Stream (HLS)" sidebar section.
Its only job is to let an operator watch a camera feed in the browser with ROI overlays. Nothing is
recorded or saved to disk.

1. The browser POSTs to `/api/hls/start` with input source, camera ID, and mode label.
2. Flask starts `_hls_annotator_thread` as a daemon thread; the route returns immediately.
3. The thread opens the source with `cv2.VideoCapture`. For RTSP it uses a Python-level 10-second
   timeout, because OpenCV's built-in timeout property is ignored on Windows pip builds. Local
   files open instantly.
4. The thread reads `CAP_PROP_FRAME_WIDTH/HEIGHT`. RTSP streams return 0x0 before the first frame,
   so if dimensions are zero it reads frames until one arrives and takes the shape from that frame.
5. FFmpeg is launched as a subprocess receiving rawvideo from stdin:
   ```
   ffmpeg -f rawvideo -pix_fmt bgr24 -s {w}x{h} -r {fps} -i pipe:0
          -c:v libx264 -preset ultrafast -tune zerolatency -an
          -f hls -hls_time 2 -hls_list_size 5
          -hls_flags delete_segments+append_list
          outputs/hls/{camera_id}/playlist.m3u8
   ```
6. On every frame: `BackgroundSubtractor.apply(frame)` updates the MOG2 model and returns the mask;
   after 30 warmup frames `get_foreground_regions(mask)` returns `ForegroundRegion` objects; a green
   rectangle is drawn per region; `_draw_corner_overlay` draws a top-left overlay with mode label
   and elapsed time (for example `MODE 0` / `00:01:23`); the annotated frame is written to
   `proc.stdin` as raw bytes.
7. FFmpeg encodes to H.264 and writes 2-second `.ts` HLS segments, updating `playlist.m3u8` after
   each segment.
8. The browser retries `GET /api/hls/{camera_id}/playlist.m3u8` every 2 seconds until it gets a 200,
   then `hls.js` attaches to the video element and plays.
9. A status poll runs every 1 second for the first 15 seconds (to catch fast connection failures),
   then every 3 seconds. If `running=False` and `error` is set, the dashboard shows "Connection
   failed" or "Stream stopped" depending on the error text.
10. On STOP, Flask sets the stop event, terminates the FFmpeg subprocess directly, and sets
    `running=False`. The thread unblocks, closes stdin, waits for FFmpeg to flush, and exits.

What the HLS stream does **not** do: write segments to `outputs/` (HLS chunks go to `outputs/hls/`
and are auto-deleted by FFmpeg after 5 segments); write anything to `metadata.db`; apply Mode 1
frame-gating (every frame is always shown regardless of the mode label in the overlay); or apply
dual-CRF encoding (FFmpeg uses `-preset ultrafast` for low latency, not the CRF 18/45 split).

**Feature 2: compression pipeline.** The "Pipeline Config" sidebar section. Records, compresses, and
archives footage to disk in real time.

1. The browser POSTs to `/api/start` with the full config.
2. Flask starts `_run_pipeline_thread` as a daemon thread, patching `FrameSource.read()` and
   `ROIEncoder.encode_segment()` to increment the live frame and segment counters in the sidebar.
3. The thread calls `run_pipeline(...)` from `src/pipeline/pipeline.py`, which opens the source with
   `FrameSource`, runs `BackgroundSubtractor` on every frame to build the background model, and
   accumulates frames into a segment buffer (`segment_seconds`, default 60s).
4. **Mode 0:** every frame goes into the buffer; at the end of each 60-second window
   `ROIEncoder.encode_segment()` fires regardless of whether motion was detected.
5. **Mode 1:** only frames where `get_foreground_regions()` returns at least one region are buffered;
   segments with zero motion frames are skipped entirely. This is where the storage savings come
   from on static cameras.
6. When a segment is ready, `ROIEncoder.encode_segment()` runs FFmpeg with dual CRF: foreground ROI
   regions at CRF 18 (high quality, these are the targets) and background at CRF 45 (aggressive, this
   is just context). This is what produces the **16.6x compression ratio at PSNR 41.2 dB**.
7. The encoded `.mp4` is written to `outputs/` and a row inserted into `metadata.db` (timestamp,
   camera ID, ROI count, object type, file size, duration).
8. The dashboard polls `/api/status` every second and updates frame counter, segment counter, FPS,
   and elapsed time.
9. On STOP, the stop event is set and the pipeline exits cleanly after finishing the current segment.

**Compression timing** is neither "wait for space" nor "once per hour". Compression happens
continuously in real time: one segment (60 seconds of footage by default) is compressed and written
to disk every 60 seconds while the pipeline runs. There is no batch step.

**Running both at once.** The HLS stream and the pipeline can run simultaneously from the same
source file or camera; they each open their own `VideoCapture` instance. The stream gives a live
annotated preview while the pipeline records and compresses in the background. They do not
interfere.

### 4.2 Option B: integrated live-stream pipeline (future work)

Today the HLS stream and the compression pipeline are two separate codebases that happen to share a
`BackgroundSubtractor`. Option B merges them so one frame loop drives both live preview and
compression recording.

**Why it matters.** In a real deployment you would not run two OpenCV decode threads against the
same camera; that wastes CPU and doubles network load on the camera. Option B produces one decoded
frame stream fanned out to both outputs. It also makes Mode 1 visually demonstrable in real time:
with no motion the HLS stream shows the static scene but no segment is written, so a viewer sees
motion, then green boxes, then the segment counter ticking up, which is exactly the mechanism the
sponsor cares about.

Current architecture:

```
Camera/File -> VideoCapture #1 -> annotate -> FFmpeg HLS
Camera/File -> VideoCapture #2 -> pipeline -> ROIEncoder -> disk
```

Option B architecture:

```
Camera/File -> VideoCapture (single) -> frame fan-out
                 |-> annotate + pipe to FFmpeg HLS
                 |-> pipeline segment buffer -> ROIEncoder -> disk
```

**What would change.** A new module `src/pipeline/live_pipeline.py` with a `LivePipeline` class
replacing both `_hls_annotator_thread` and `_run_pipeline_thread` in live-integrated mode: it owns a
single `FrameSource`, runs `BackgroundSubtractor` per frame to get ROI regions, writes the annotated
frame to the HLS FFmpeg stdin pipe, feeds the frame into the mode-gated segment buffer, and hands
completed segments to `ROIEncoder` (potentially on a second thread so it does not block the frame
loop). In `src/gui/app.py`, `api_hls_start` would accept an optional `compress=True` flag and start
`LivePipeline` instead of `_hls_annotator_thread`, with the status endpoint returning unified state.
In `index.html`, an "Also compress to disk" checkbox in the HLS section, with the segment counter
and output dir config appearing inline when checked, and the existing segments table updating in
real time.

**What would not change.** `ROIEncoder` (still handles the dual-CRF FFmpeg call),
`BackgroundSubtractor`, the `metadata.db` schema and queries, `hls.js` playback and retry logic, and
all existing tests (the new module would get its own test file).

**Estimated scope:** about 2 to 3 days of focused work for one person.
`src/pipeline/live_pipeline.py` around 150 lines, `app.py` updates around 80 lines, `index.html`
updates around 40 lines, and `tests/test_live_pipeline.py` with around 20 tests following the same
dummy-injection pattern as `test_pipeline.py`. The hardest part is making the `ROIEncoder` segment
write non-blocking so it does not drop frames in the HLS stream; the recommended approach is a
`queue.Queue` where the frame loop enqueues completed segments and a separate encoder thread
dequeues and calls `encode_segment()`. Natural owners are Riley (ROIEncoder/pipeline) and Kheiven
(HLS stream/GUI), coordinating on the `LivePipeline` API before writing code.

---

## 5. Shipped feature: AI license-plate reader

*(consolidated from plate_reader.md)*

Added 2026-05-02 as a post-process AI enhancement upgrade for ROADMAP 5.4 / 6.x. Module:
`src/enhancement/plate_reader.py`. API: `POST /api/enhance/plates`,
`GET /api/enhance/plates/status`. GUI: the "READ PLATES" button on the inline preview player. This
is the document to read when a sponsor or operator asks "how reliable is this?"

### 5.1 What it does

The plate reader runs as a post-process step on a saved video segment. It does not run live.

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

Multi-frame consensus voting is the mechanism that gets past the single-frame ceiling. A 480p
surveillance crop of a plate is below the Nyquist limit for many characters, and no
super-resolution model can recover information that is not there. But surveillance video provides
many frames of the same plate; when 3 or more frames independently OCR to the same text, the read
is far more trustworthy than any single frame.

### 5.2 Library selection and licensing

| Stage | Library | License | Why chosen |
|---|---|---|---|
| Super-resolution | Real-ESRGAN | BSD-3-Clause | Already integrated via `Enhancer`. 35k stars, BSD-3 compatible with the rest of the repo, handles real-world degradations. Mature `RealESRGAN_x4plus` weights. |
| Primary OCR | PaddleOCR | Apache-2.0 | Dedicated lightweight license-plate model (~15-20 MB). 77k stars, actively maintained (April 2026 commits). CPU and GPU. |
| Fallback OCR | EasyOCR | Apache-2.0 | Used when PaddleOCR cannot install (no AVX, no PaddlePaddle wheels for the platform). 29k stars. |

Deliberately not used:

| Library | License | Why excluded |
|---|---|---|
| OpenALPR | AGPL-3.0 | AGPL would force the rest of the project to AGPL. Hard no for the permissive open-source deliverable. |
| fast-plate-ocr | MIT | Permissive and worth a future PR, but the dataset is biased toward US plates and the project is smaller (~550 stars, unproven). Listed as a future addition. |
| WPOD-NET | research code | Limited maintained open-source releases, not a clean drop-in. |
| Vendor APIs (Google Vision, AWS Rekognition, Plate Recognizer) | proprietary | Not open source, require keys, and outbound network calls disqualify them for an air-gapped Navy base. |

Note: the later R4 Phase 5 research round (section 9) revisits fast-plate-ocr and reverses this
call in favour of an ONNX backend built on it. See section 11.

### 5.3 API surface

`GET /api/enhance/plates/status` returns whether the OCR backend is installed and which one will
run; the GUI uses it on page load to enable or disable the READ PLATES button gracefully.

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

When neither PaddleOCR nor EasyOCR is installed, `ocr_backend` is `"none"` and `ocr_available` is
`false`.

`POST /api/enhance/plates` request body:

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

`file_path` is required; everything else is optional and falls back to the defaults shown.
`roi_boxes` lets the GUI pass per-segment vehicle bboxes from the segments DB so SR cycles are not
wasted on empty background.

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
    }
  ],
  "best_read": "ABC1234",
  "warnings": []
}
```

### 5.4 Verdict semantics

The `verdict` field is the operator's plain-English read on whether to trust a plate, and it is
intentionally conservative.

| Verdict | Required | Meaning |
|---|---|---|
| `high` | 3 or more frames agree, average OCR 0.60 or better | Trust this. Same text reproduced across multiple frames at strong per-frame confidence. |
| `medium` | 2 or more frames agree, average OCR 0.50 or better | Trust with operator review. Two frames is a coincidence floor. |
| `low` | 1 or more frames, OCR 0.70 or better | Single-frame strong read. Useful as a starting point; verify against a second frame before acting. |
| `uncertain` | anything else | OCR returned text but it meets neither consensus nor single-strong-read threshold. Do not act on uncertain reads. |

Combined confidence is `0.6 * ocr_avg + 0.4 * consensus_ratio`, where
`consensus_ratio = min(1.0, votes / max(3.0, frames_examined * 0.25))`. Both pieces matter: a great
OCR confidence on a single frame can hallucinate, and weak per-frame OCR on many frames is still
weak.

### 5.5 Honest accuracy limits

1. **Resolution floor.** A 480p frame with a vehicle 50 m away yields a plate crop roughly 25 to 40
   px tall. Even with 4x SR (100 to 160 px), the Shannon-Nyquist limit means many characters were
   never sampled. Real-ESRGAN cannot invent missing detail; at best it removes blur and noise.
   Expected character accuracy on heavily compressed surveillance footage is **60 to 75 percent**
   without domain adaptation. Multi-frame consensus pushes that up but does not eliminate it.
2. **Compression artefacts.** The pipeline encodes background segments at CRF 45 (heavily lossy). If
   the plate is in a no-foreground frame and gets background CRF, artefacts compound. For best
   accuracy, run the reader on Mode 0 segments (full quality) or Mode 1 segments where the plate was
   inside an ROI.
3. **Hallucination risk.** This was the sponsor's original concern at the March 23 kickoff.
   Mitigations: the verdict cap; showing the operator the per-frame vote count; and refusing to
   return text that does not appear in at least one frame's OCR output. The system never confabulates
   a plate from "what looked like the right shape".

### 5.6 Operational recommendations

- Run the reader on Mode 0 or Mode 1 segments for best accuracy. Mode 2 and Mode 3
  background-keyframe and object-only outputs intentionally degrade non-foreground pixels, which can
  include plate edges.
- For long clips, leave `max_frames` at the default 60 and `sample_every_n_frames` at 5, which is a
  12-frame consensus pass on a 60-second segment, enough to flush single-frame hallucinations without
  burning runtime.
- When the segments DB has `roi_count > 0`, pass the per-frame vehicle boxes via `roi_boxes`. This is
  the single biggest speedup on long clips.
- Trust the verdict label. `uncertain` reads should not enter incident reports.

### 5.7 Installation and tests

Both OCR engines are optional extras:

```bash
uv sync --extra plates             # primary: PaddleOCR + paddlepaddle
uv sync --extra plates-fallback    # fallback: EasyOCR
```

If neither is installed the API still answers `200 OK` and returns a `warnings` field naming the
package to install. SR still runs (Real-ESRGAN bicubic fallback) so the operator can at least see an
upscaled clip.

`tests/test_plate_reader.py` covers plate-text normalisation (case, length bounds, punctuation
stripping); verdict scoring decision boundaries; pipeline plumbing on a synthetic .mp4 with a stub
OCR backend (no PaddleOCR install needed for CI); consensus voting picking the repeated read;
low-confidence reads being dropped before voting; `min_consensus_votes` filtering singleton reads;
and `roi_boxes` actually subsetting the frame. The OCR backend itself is not unit tested, because
those tests would require fixed weights, fixture clips, and a model-version pin that fights the
upstream release cadence. Manual validation on real footage is in the team's review checklist.

---

## 6. R4 Phase 1: UI/UX research round

*(consolidated from RESEARCH-UIUX.md)*

Date 2026-07-04. Method: deep-research workflow, 5 search angles, 24 sources fetched, 117 claims
extracted, top 25 adversarially verified with 3 votes each (24 confirmed, 1 refuted). Each verified
finding is recorded with its decision (ADOPT / DEFER / SKIP / PARTIAL).

1. **Determinate progress indicators for waits of 10s or more (NN/g) - ADOPT.** Any action over
   about 1s needs an indicator; spinners are acceptable only for 2 to 10s waits; 10s or more requires
   percent-done or time-remaining; batch work should show "file N of M" with the current item
   highlighted. Sources: nngroup.com/articles/progress-indicators and
   /designing-for-waits-and-interruptions (3-0 x5). Already good: file-input runs show percent, ETA,
   and fps (`status.js` `_friendlyStatus`). Gap: auto-compress batch runs do not surface batch
   position. Action: expose batch position from the autocompress runner status and render it.
2. **Background jobs plus persistent job history (NN/g) - ADOPT.** Long processes should run in the
   background without blocking the app (SVCS already does this; tabs stay usable while compressing)
   and the app should keep a persistent, visible record so operators can resume or audit after
   interruptions. Sources: NN/g waits plus complex-application-design (3-0 x2). Gap: no job history;
   progress is transient and once a run ends the evidence is gone (segments live in the DB but there
   is no per-run record). Action: record every finished run (manual pipeline plus auto-compress) to a
   persistent job log and render a "Recent jobs" panel.
3. **Explicit completion summary, not an auto-fading toast (NN/g) - ADOPT.** After a long wait the
   user has disengaged; completion must be a user-dismissed summary (start, stop, elapsed, files and
   segments, skipped, failed, space saved), not a 4s toast. Source: NN/g waits (3-0). Gap: segment
   saves fire auto-dismiss toasts (`demo.js` `pushNotif`) and run completion has no summary surface.
   Action: a completion summary modal on pipeline finish and auto-compress batch finish, dismissed
   only by the user.
4. **Goal-oriented navigation (Frigate 0.14 rebuild) - DEFER.** Frigate rebuilt its UI around
   operator questions (what is happening now, what happened overnight, was anything missed) instead
   of backend features; SVCS tabs are feature oriented. Source: frigate discussion #11136 (3-0 x2).
   Deferred because a tab reorg churns the whole test surface mid-R4 and Phase 4 (two-exe split) will
   change the shell anyway. Reconsider after Phase 4 with HOME = "now", AUTO-COMPRESS = "overnight",
   LIBRARY = "find a clip".
5. **Frigate review mechanics - DEFER.** Scrollable thumbnail grid synced to a timeline,
   hover/swipe inline preview, watched segments marked reviewed, two-tier alerts-versus-detections
   triage. Sources: frigate #11136 plus docs (3-0 x2). Note: the claim that previewing implicitly
   marks a segment reviewed was REFUTED 0-3. Deferred to Phase 3 so competitor gap analysis can price
   it against other missing features; the Library already has lazy thumbs, filters, and kind
   segmentation.
6. **Deliberately low-res preview assets (Frigate) - PARTIAL / already aligned.** Library thumbnails
   are already lazy static thumbs and full video loads only on click (detail modal). Animated low-fps
   preview clips are a Phase 3 candidate.
7. **Milestone XProtect two-track color-coded timeline - DEFER.** Only relevant if SVCS builds a
   timeline review view. Recorded for Phase 3.
8. **Pico CSS as a no-build styling layer - SKIP.** Verified as a fit for Flask plus vanilla JS in
   general, but SVCS already has a bespoke token system (`:root` in index.html: surfaces, amber
   accent, status colors) and 2600 lines of working CSS. Swapping base stylesheets mid-project is
   regression risk with no user-visible payoff. Caveat from the research: Pico's "accessible" label
   is self-description, and no comparative htmx / Alpine / Web-Components claims survived
   verification anyway.
9. **Empty states: say why it is empty, give contextual help, give a direct CTA (NN/g) - ADOPT.**
   Three guidelines, 3-0 x3, corroborated by IBM Carbon, Atlassian, and GitLab systems: state what
   would appear and why it is empty, use the space as contextual help, and include the CTA that
   populates the area. Qualification: never show "no records" while still loading. Gap: Library,
   segments table, upload list, and AUTO-COMPRESS show blank or terse placeholders, and Library can
   flash empty text during fetch. Action: real empty states with CTAs, and a loading state distinct
   from the empty state.
10. **First-run wizard with navigable sequence map (NN/g) - DEFER.** Current setup is a single-step
    destination chooser so a sequence map does not apply yet. Phase 4's split builds will rework
    first-run; apply then if it grows steps.
11. **Staged disclosure of advanced options (NN/g) - PARTIAL / already aligned.** The sidebar
    already gates advanced settings behind an ADVANCED toggle. No action beyond keeping disclosure
    about 2 levels deep.
12. **Dark theme: dark-gray surfaces, light-gray text, avoid halation (Material) - ADOPT, light
    touch.** Dark gray over pure black; small pure-white text halates (Material specifies white at
    87 percent for high emphasis). SVCS's `--bg` #0a0e14 is near black but brand set, and text tokens
    are already blue-grays rather than pure white. Sources: design.google (3-0 x2). Action: keep the
    palette and instead fix the accessibility debt the frontend audit found: visible `:focus-visible`
    rings (WCAG 3:1 for UI components), consistent disabled states, and no small pure-white text.

**Cross-cutting debt adopted alongside** (from the frontend inventory): one shared modal component,
since help, library-browse, and plates modals each reimplement overlay CSS, with the new completion
modal using it; notification cards are built from innerHTML strings, which is kept, but all new
surfaces route through the shared modal and notif helpers; and no loading feedback during async
fetches, which ties into finding 9.

**Implementation plan for the phase.** (1) `ui.js` plus index.html: shared modal component
(`svcsModal.show/hide`), focus-visible rings, empty-state and skeleton CSS. (2) Backend: persistent
job history (app-data JSON log via a small service) recorded on pipeline finish and per auto-compress
batch, an `/api/jobs/recent` endpoint, and autocompress status exposing batch `current_index`,
`total`, and `current_file`. (3) Frontend: "file N of M" in AUTO-COMPRESS, a Recent-jobs panel on
HOME, a completion summary modal for manual runs and auto-compress batches, and empty states for
Library, segments, upload, and AUTO-COMPRESS. (4) Tests for the new endpoint and runner status
fields, suite green, browser verified.

**Research caveats kept honest.** No claims about Blue Iris, Ubiquiti Protect, Verkada, Rhombus, or
Eagle Eye survived verification, so the VMS pattern set is Frigate plus Milestone only (Phase 3
revisits this). No comparative htmx / Alpine / Web-Components tradeoffs survived, which is irrelevant
since SVCS stays vanilla. No numeric WCAG claims survived; the 4.5:1 and 3:1 thresholds cited are the
standard's own values, applied during implementation rather than being research conclusions. NN/g
thresholds derive from 2014 articles rooted in older perception research (stable but old), and
impact/effort ranks are the synthesizer's judgment.

---

## 7. R4 Phase 2: better compression algorithms research round

*(consolidated from RESEARCH-COMPRESSION.md)*

Date 2026-07-04. Method: deep-research workflow, 6 angles, 109 agents, top 25+ claims adversarially
verified, 3 refuted and excluded. Local capability probe against the bundled FFmpeg
(`tools/ffmpeg`): libx264, libx265, SVT-AV1, libaom, plus h264_nvenc, hevc_nvenc, and av1_nvenc all
functional on this machine's GPU; addroi, hqdn3d, nlmeans, atadenoise, and libvmaf present.

### 7.1 Verified findings and decisions

**1. addroi encoder-level ROI instead of the downscale-composite hack - ADOPT (opt-in v1).**
Verified 12-0 against FFmpeg docs plus `libavcodec/libx264.c`: the addroi filter attaches per-region
quantization metadata consumed by libx264/libx265 as per-macroblock QP offsets (qoffset in [-1,+1];
-1/10 at frame QP around 30 gives the region about QP 24). This is the canonical ROI approach: one
stream, pixels untouched. Verified limits: NOT consumed by libsvtav1 or libaom (a claimed SVT-AV1
`--roi-map-file` was REFUTED 0-3), so ROI-QP is x264/x265 only. The CLI filter's rectangles are fixed
per process and SVCS opens one FFmpeg process per SEGMENT, so boxes can only refresh at segment
boundaries. The v1 design is an activity-grid ROI, opt-in (`roi_qp`): while encoding, accumulate
which grid cells saw foreground regions, and when the next segment's process opens, cells with recent
activity are protected (negative qoffset toward the foreground CRF) while long-static cells degrade
toward `background_crf`. The first segment of a session gets no ROI (full quality), which is the
fail-safe direction. Kept off by default in v1 because per-frame compositing reacts to new motion
instantly while per-segment ROI has up to one segment of lag in fresh areas; documented tradeoff, the
same class as camera "smart codec" dynamic ROI.

**2. Long GOP for static cameras - ADOPT (default on).** Verified 6-0: x264's default keyint is only
250 frames and "infinite" is supported; SVT-AV1's keyint default is about 5s with -1 = infinite
(CRF only), passable via `-svtav1-params`. IPVM measured 90 percent or better bitrate reduction for
camera smart codecs (dynamic GOP plus AQ) on fully static scenes, 20 to 50 percent typical, and about
20 percent at night. Adopted: bounded long GOP as the research's pragmatic middle ground for seekable
archives, keyint = 20s of frames for both encoders, scenecut left on. Infinite GOP was rejected
because archived surveillance must stay seekable.

**3. Capped CRF for storage budgeting - ADOPT.** Verified 3-0: SVT-AV1 `--mbr` (kbps, CRF only, soft
cap, default 50 percent overshoot); x264 capped-CRF = CRF plus `-maxrate`/`-bufsize` (VBV, hard-ish
bound). Adopted: an optional `max_bitrate_kbps` config, with the x264 path getting
`-maxrate`/`-bufsize` (2s buffer) and the SVT-AV1 path getting `mbr=` in svtav1-params.

**4. Hardware encoders as the real-time ingest default when present - ADOPT.** Verified 6-0 at medium
confidence (the study used gaming/UHD CBR content): current QSV/NVENC match or slightly beat
real-time-capable software presets at 1080p (+0.51 and +0.38 VMAF) at roughly half the system power,
and Ada NVENC AV1 gives about 40 percent bitrate savings versus NVENC H.264 (vendor measured). All
three NVENC codecs are verified working on this machine. Adopted: h264_nvenc, hevc_nvenc, and
av1_nvenc as selectable codecs with a runtime probe and automatic fallback to libx264 (the existing
`_ffmpeg_has_encoder` fallback pattern). Auto codec choice still defaults to software (quality first
for archives); NVENC is surfaced for live/RTSP ingest. Note: FFmpeg's nvenc wrapper consumes neither
addroi side data nor qpDeltaMap (verified), so ROI-QP and NVENC are mutually exclusive.

**5. Pre-encode denoising for night and IR footage - ADOPT (opt-in).** Verified 6-0: HandBrake's
NLMeans benchmark cut output 19.5 percent at about 50 percent encode-time cost on a clean source, and
IPVM shows sensor noise makes night footage cost up to 3x daytime bitrate, so the night payoff is
larger. Denoising can soften plate and face detail, so it stays opt-in. Adopted: an optional denoise
stage in the encoder filter chain, `hqdn3d` (cheap, default strength) or `atadenoise` (temporal,
static-camera friendly). Off by default.

**6. VMAF validation - ADOPT (tooling only).** Verified 3-0: NTIA/ITS found VMAF responds only to
compression artifacts even when the reference has camera impairments, so it is valid for surveillance
A/B testing, and libvmaf is in the bundled FFmpeg. Adopted: `compute_vmaf()` in `utils/metrics.py`
shelling to ffmpeg libvmaf, for offline validation of encoder-setting changes, not in the live
pipeline.

**7. NVENC emphasis maps (qpDeltaMap) - DEFER.** Verified 6-0 but requires direct NVENC SDK
integration (PyNvVideoCodec); the FFmpeg wrapper cannot do it. Recorded for a future GPU-ROI effort.

**8. Neural codecs (DCVC-RT) - NOT YET (recorded).** Verified 17-1: DCVC-RT reports about 21 percent
BD-rate savings versus H.266/VTM and 125 fps 1080p encode, but on an A100. A consumer RTX 2080 Ti
gets about 39 fps, it needs CUDA 12.6 plus custom kernel builds, and there is no CPU path and no
FFmpeg integration. Not deployable for the CPU-first Windows audience. Revisit when a CPU/ONNX or
FFmpeg path exists.

### 7.2 Refuted claims (excluded, do not resurface)

- "SVT-AV1 has `--roi-map-file` per-region QP" (0-3). Encoder-level ROI is x264/x265 only in this
  pipeline.
- "HEVC ROI achieves 0.7 to 1.0 Mbit/s 1080p30 at PSNR above 37 dB" (0-3). No verified quantitative
  ROI-versus-composite number exists; do not promise one.
- "Ada NVENC AV1 equals x264 medium quality at 18 versus 30 Mbps at about 500 fps" (1-2).

### 7.3 Implementation plan for the phase

1. `roi_encoder`: long-GOP defaults (keyint=20s both encoders), max_bitrate capped-CRF plumbing,
   NVENC codec support with probe and fallback, an optional denoise filter stage, and opt-in
   activity-grid addroi ROI for x264/x265.
2. Config, pipeline, and GUI plumbing for the new knobs (codec choices plus advanced fields), with
   defaults unchanged except long GOP.
3. `utils/metrics.py` `compute_vmaf`.
4. Tests: arg-construction units (no real encodes), one real tiny encode smoke per new path where
   cheap, and a VMAF test guarded by filter presence.

### 7.4 Honest caveats carried forward

IPVM's 90 percent or better figure is a best-case ceiling (fully static scene); expect 20 to 50
percent. The hardware-encoder study content was gaming/UHD CBR, not surveillance CRF, and did not
test AMD AMF. NVIDIA's 40 percent AV1-versus-H.264 figure is vendor measured. The NLMeans 19.5
percent benchmark is a single clip with no quality metric. SVT-AV1 `--mbr` is a soft cap (50 percent
default overshoot), not a VBV guarantee.

---

## 8. R4 Phase 3: competitor apps and gap analysis

*(consolidated from RESEARCH-COMPETITORS.md)*

Date 2026-07-04. Method: deep-research workflow, 5 angles, 104 agents, 22 sources, 25 claims verified
by 3-vote (24 confirmed, 1 refuted), mapped against the ground-truth SVCS feature inventory
(`docs/SVCS-FEATURE-INVENTORY.md`). The workflow's auto-synthesis field returned a stub, so the source
document is a hand synthesis from the verified claim set plus the source list.

### 8.1 Verified competitor behaviors

- **Retention and auto-purge.** ZoneMinder ships a pre-configured `PurgeWhenFull` filter that deletes
  oldest events by DiskPercent / DiskBlocks thresholds (a ring buffer). Frigate supports separate
  retention TIERS (alerts versus detections versus continuous), each with an independent retain-days
  setting. Sources: wiki.zoneminder.com/PurgeWhenFull (3-0 x2), docs.frigate.video/configuration/record
  (3-0 x2). Retention math of days = disk / bitrate is the standard user-facing model (reolink storage
  calculator).
- **Smart-codec dynamic ROI plus dynamic GOP.** Axis Zipstream and Dahua Smart H.265+ cut bitrate by
  dynamic ROI (encoding motion regions at higher quality) and dynamic GOP (extending the I-frame
  interval on static scenes). Dahua claims 89 to 98 percent reduction (2-1, vendor figure). Sources:
  whitepapers.axis.com and the Dahua Smart H.265+ PDF (3-0 on ROI, 2-1 on the percentage figures).
- **Event and alert pipelines.** Frigate publishes detection events over MQTT and drives Home
  Assistant notifications; On-Guard (a Blue Iris companion) adds AI object detection and multiple
  overlapping zones. Sources: docs.frigate.video (ha_notifications, mqtt, home-assistant, 3-0 x4) and
  the On-Guard GitHub (3-0 x2).
- **Interop.** ONVIF Profile G covers recording and replay; the client (VMS) role retrieves
  recordings; ONVIF Replay Control uses RTSP as the retrieval protocol. Sources: onvif.org profile-g
  plus the replay spec (3-0 x3).
- **Privacy, compliance, and export.** Milestone XProtect offers privacy masking, audit logs, and an
  encrypted and signed evidence export format. Source: doc.milestonesys.com (3-0 x3).
- **Refuted (1-2):** the exact Frigate MQTT topic-namespace claim. The docs do describe
  `frigate/<category>/<camera>/<function>`, but the vote fell short, so it is treated as directional
  rather than load bearing.

### 8.2 Gap analysis versus SVCS (ranked by impact x effort)

**ADOPT NOW: retention, disk budget, auto-purge (table stakes, #1).** The one feature every NVR has
and SVCS has none of. It directly serves the SVCS purpose of bounding 24/7 footage on disk, and
ZoneMinder's PurgeWhenFull is the model. Implemented this phase: a retention policy (max age in days
and/or max total GB) over the auto-compressed output, a background purge that deletes oldest
compressed segments and prunes the index when over budget, a free-disk / bitrate retention estimate
(days of headroom), and GUI controls. Safety first, because it deletes footage: confined to the
resolved `compressed/` subdirectory, media files only, with a freshness window so an in-flight clip is
never touched, originals and encrypted sources never touched, and a no-op when disabled.

**ALREADY DELIVERED (R4 Phase 2): smart-codec dynamic ROI plus dynamic GOP.** The Zipstream / Smart
H.265+ storage lever. SVCS added encoder-level addroi ROI (protect motion, degrade long-static cells)
and long-GOP defaults in Phase 2. No further work; noted so it is not double counted as a gap.

**DEFER: event notifications (webhook / MQTT / Home Assistant).** A real gap versus Frigate and
On-Guard, deferred to keep Phase 3 focused and because a safe outbound webhook needs SSRF guarding
(post-to-internal risk) and MQTT needs a broker dependency the local-first installer avoids.
Recommended next step: a single opt-in outbound webhook (JSON POST on job-complete or purge) with the
URL vetted through the existing `path_safety` host checks. Recorded in BLOCKERS.

**OUT OF SCOPE (would make SVCS a full VMS rather than a compressor):** an ONVIF Profile G recording
and replay server, tiered or cloud storage; a timeline review UI (Phase 1 already deferred this,
revisit post-split); multi-user / RBAC plus built-in HTTPS (the documented answer is to run behind a
reverse proxy, since this is a single-node local-first tool); and encrypted and signed evidence export
plus privacy-mask zones (nice to have but large, and SVCS already has AES-256 at-rest encryption).

### 8.3 Honest caveats

Dahua's 89 to 98 percent and the other smart-codec percentage figures are vendor measured (2-1 votes).
Only Frigate, ZoneMinder, Axis, Dahua, Milestone, and On-Guard claims survived verification; Blue
Iris, Synology, Scrypted, Shinobi, MotionEye, and Ubiquiti produced no verified claims, so the
competitor set is skewed to those six. Retention "days = disk / bitrate" is an estimate from recent
throughput, and real headroom varies with scene activity, since night noise inflates bitrate.

---

## 9. R4 Phase 5: plate-reader solution research round

*(consolidated from RESEARCH-PLATES.md)*

Date 2026-07-04. Method: deep-research workflow, 5 angles, 102 agents, verified claims 3-0. This is
the decision record plus the empirical validation of the one claim the research could not confirm from
metadata alone.

### 9.1 The problem, verified from SVCS's own code

The optional plate reader uses EasyOCR, which (a) depends unconditionally on
`opencv-python-headless` and (b) is a PyTorch CRNN, dragging in torch and torchvision. All four
opencv-python variants share ONE `cv2/` namespace with no plugin architecture, so installing headless
CLOBBERS the core `opencv-contrib-python` and `cv2.bgsegm` / MOG2 disappear. That is why `[plates]`
needs a separate venv: it cannot ship in one env or exe.

### 9.2 Verified findings

1. **Best stack (3-0):** ankandrew's MIT toolkit, `fast-plate-ocr` (ONNX OCR that recognizes CROPPED
   plates) plus `open-image-models` (YOLOv9 ONNX plate detection), optionally wired by `fast-alpr`.
   All MIT, torch free, running on ONNX Runtime which is already a core SVCS dependency. Sources:
   github.com/ankandrew/*.
2. **Hard blocker (3-0):** all three also declare `opencv-python-headless` as a REQUIRED core
   dependency (fast-alpr pins `opencv-python-headless>=4.9.0.80` directly), so a normal `pip install`
   re-creates the clobber. Source: the fast-alpr pyproject plus issue #38.
3. **Root cause (3-0):** the four opencv-python wheels are mutually exclusive, share the same `cv2/`
   namespace, and the upstream instruction is "select only one". Only the contrib variants ship
   bgsegm/MOG2. Source: the opencv/opencv-python README.
4. **The fix (3-0 on facts):** dependency surgery. `pip install --no-deps` the ankandrew packages so
   `opencv-python-headless` is not pulled; the existing `opencv-contrib-python` satisfies their
   runtime `import cv2` because contrib is a superset. Only `onnxruntime` plus `numpy` (both core) and
   the ONNX model files are added. Source: fast-alpr issue #38 names dependency surgery as the fix.
5. **Fallback (3-0):** if `--no-deps` proves fragile, isolate the reader as a separate frozen helper
   exe (`PYINSTALLER_RESET_ENVIRONMENT=1`) fed cropped images over a temp file.
6. **EasyOCR is wrong for a single CPU exe (3-0):** unconditional headless dependency plus
   torch/torchvision.
7. **Temporal voting is essential (medium confidence):** single-frame OCR on night or angled
   surveillance plates is unreliable, and one 2026 arXiv preprint measured EasyOCR mean confidence at
   0.414. SVCS already does multi-frame consensus voting.

### 9.3 Empirical validation

The research could not confirm from metadata that a `--no-deps` install actually runs against
opencv-contrib's cv2, so it was tested locally in a THROWAWAY venv, never the core env. See
`docs/PLATES-VALIDATION.md` for the exact commands and result. The recorded outcome drives whether the
in-process backend ships enabled by default or stays behind the documented recipe.

### 9.4 Decision

- **Add an in-process ONNX ALPR backend** (`_FastPlateOcrBackend`) to
  `src/enhancement/plate_reader.py`, conforming to the existing `_OcrBackend` interface, lazy imported
  and fully optional. Auto-selected FIRST in "auto" mode because it is torch free and coexists, falling
  back to easyocr / paddle / tesseract / none exactly as today. Optionally uses `open-image-models` to
  detect and crop plates in a frame before OCR; without it, it OCRs the ROI or frame it is given, which
  works when the caller passes plate or vehicle ROI boxes, as the pipeline already supports.
- **Ship the install recipe, not a resolver extra.** A normal `uv sync --extra plates` cannot avoid the
  headless clobber, because the extra's dependencies pull it, so the ONNX reader is installed via a
  documented `--no-deps` recipe or helper script into the SAME env. The GUI auto-detects the backend
  when present and hides the plate UI when absent (unchanged behaviour).
- **Keep EasyOCR as a legacy, separate-env option**, demoted below the ONNX path in docs.

### 9.5 Honest caveats carried forward (also in docs/BLOCKERS.md)

`--no-deps` is a maintenance liability: re-audit the cv2 and numpy pins on every fast-plate-ocr or
open-image-models upgrade. The default bundled model weights may carry their own non-MIT license, so
verify before bundling any weights in the installer. Actually running the real ONNX model end to end
(and bundling it in the exe) is owner-run like the other optional AI extras; the code path degrades
gracefully when the package or model is absent, and the tests use a stub.

---

## 10. R5 Task 5.1: VMAF-targeted rate control

*(consolidated from RESEARCH-VMAF-TARGET.md)*

Date 2026-07-16. A research spike written BEFORE coding, the same way RESEARCH-PLATES preceded the
plate reader. Sources are the ones scouted in `docs/CLAUDE-CODE-R5.md`; the measurements below were
taken locally against real sample footage.

### 10.1 The problem with a fixed CRF

SVCS encodes at a fixed CRF per mode or preset (mode0/1 CRF 18, mode3 CRF 38, and so on). A fixed CRF
spends a fixed amount of *effort*, not a fixed amount of *perceived quality*: an easy static scene and
a busy one at the same CRF land at very different VMAF, so every clip is either over-spent (wasted
bytes) or under-spent (avoidable quality loss). Targeting a perceptual score instead makes the file as
small as it can be while still clearing a quality bar.

### 10.2 Measured locally

Re-encoding a 3s cut of `data/samples/parking_input.mp4` (libx264, veryfast), VMAF measured with the
existing `utils.metrics.compute_vmaf` harness:

| CRF | VMAF | size |
|----|------|------|
| 18 | 95.60 | 62 KB |
| 24 | 91.04 | 22 KB |
| 30 | 81.53 | 10 KB |
| 36 | 65.27 | 6 KB |
| 42 | 37.79 | 4 KB |
| 48 | 15.71 | 3 KB |

Two things this establishes. First, **CRF to VMAF is monotonically decreasing** on real surveillance
content (verified, no inversions), which is the assumption the search depends on, so it is asserted in
the unit tests rather than taken on faith. Second, **the headroom is large**: holding VMAF around 91
instead of around 95.6 costs 4.5 VMAF points nobody asked for and saves 2.8x the bytes. The useful
target band (85 to 97) sits in a steep part of the curve, which is exactly where picking the right CRF
pays.

### 10.3 Method: interpolated CRF search over short samples

`ab-av1` searches CRF with svt-av1 plus vmaf to satisfy a `--min-vmaf`, encoding short samples rather
than the whole clip. SVCS does the same:

1. **Sample.** Take N short segments spread across the clip (default 4 x 3s at evenly spaced interior
   points) rather than encoding the whole thing. Extract each with `-c:v copy` so the reference is the
   source's exact bits, falling back to a near-transparent CRF-10 re-encode if stream copy fails on an
   odd container. The sample IS the reference for VMAF, so the score measures only the loss the encode
   adds.
2. **Probe.** Encode the samples at a candidate CRF with the same codec and preset the real encode will
   use, and measure VMAF against the samples.
3. **Interpolate.** Keep every (crf, vmaf) measurement. Once the target is bracketed, linearly
   interpolate between the two nearest points to pick the next candidate; bisect when there is no
   bracket yet. This converges in about 3 to 5 probes instead of the roughly 6 a pure integer bisection
   needs.
4. **Choose.** Return the LARGEST CRF (smallest file) whose measured VMAF still clears the target. The
   target is a quality FLOOR, so the result lands just above it, which is what "smallest file at
   constant perceived quality" means.

**Parameters.** Target VMAF defaults to 93, clamped to [85, 97]: below 85 the artifacts get visible on
the steep part of the curve, and above 97 the bitrate cost explodes for no perceived gain, matching the
useful range noted for ab-av1. The CRF range is clamped to the codec's own scale (x264/x265 0-51, AV1
0-63) and additionally to a sane search window so a pathological probe cannot pick CRF 0. A hard probe
cap prevents a weird clip from searching forever.

### 10.4 Sampling scheme tuned against measurement

Sample VMAF reads slightly LOW versus the full clip, since the samples are about 1 percent of the
frames. That bias matters because it makes the search reject a CRF the full clip would actually pass,
costing file size. Measured on `parking_input.mp4` at CRF 22, where the FULL-clip VMAF is 93.31:

| scheme | sample VMAF | bias | verdict on CRF 22 (target 93) |
|---|---|---|---|
| 3 x 2s | 92.91 | -0.40 | rejects it (search settles on CRF 21) |
| 4 x 3s | 93.03 | -0.28 | accepts it |
| 5 x 4s | 93.04 | -0.27 | accepts it, for 67% more sampling and no gain |

So the default is **4 x 3s**. It halves the bias and recovers a CRF step worth about 20 percent of the
file (CRF 21 = 938 KB versus CRF 22 = 750 KB on this clip), and sampling harder buys nothing
measurable. The residual bias is in the conservative direction: samples under-read, so the search errs
toward spending more bits, never toward shipping under the quality floor.

### 10.5 Caching and fallback

The search costs encode time, so the chosen CRF is cached keyed by
`source signature (path|size|mtime) + codec + preset + target`, mirroring
`utils.compressed_index.signature`. A re-run of the same clip at the same settings is instant.
Replacing the file at the same path changes the signature and invalidates the entry, the same rule the
compressed index uses.

If libvmaf is missing, ffmpeg is missing, sample extraction fails, or the search cannot converge, the
module returns the preset's fixed CRF with a `fallback_reason` and the pipeline logs it. Target mode
NEVER blocks or breaks an encode; it degrades to exactly today's behaviour. This is the same
degrade-gracefully rule the ONNX plate reader follows.

### 10.6 Scope decisions

- **Opt-in per preset.** Existing fixed-CRF modes are untouched; a preset opts into target mode with a
  target value. Default behaviour stays identical and the change stays reviewable.
- **Runs in the worker.** The search is encode work, so it runs in the existing pipeline worker thread,
  never on the UI or request thread.
- **Codec policy unchanged.** The search picks a CRF for whichever codec the mode already selects
  (H.264 for mode0/1, AV1 for mode2/3). No H.265, per the standing decision.
- **LiteVPNet (learned encoder control, arXiv 2510.12379) is NOT adopted.** It targets a quality metric
  with a learned model, which would mean shipping model weights and a torch-adjacent dependency for a
  gain the sample search already captures. Recorded as considered and rejected; the sample search needs
  no model and no extra dependency.

### 10.7 Honest bounds

The search measures VMAF on SAMPLES, so full-clip VMAF can differ from the target by more than the
sample tolerance if the clip is wildly heterogeneous. Sampling across the duration rather than just the
head mitigates this; the acceptance target of about +/-1 is on a representative clip, not a guarantee
for every input. VMAF is a perceptual model, not ground truth, and it is measured against the SOURCE,
so if the source is already heavily compressed a high VMAF means "we added little further loss", not
"this looks great". Sample encodes add wall-clock time on the first run of a clip, which is the cost of
the feature; the cache is what makes it acceptable in practice.

---

## 11. Known discrepancies between source documents

*(cross-cutting; identified while merging all fifteen source documents)*

1. **MOG2 tuned parameters conflict.** `detection_tuning.md` recommends `varThreshold=50,
   detectShadows=False` as the final tuned MOG2 configuration, based on a static-scene / moving-scene
   test that reported 0 percent false positives. `algorithm_comparison.md` and
   `detection_tuning_results.md` both recommend `varThreshold=16` (day) / `30` (night) with
   `detectShadows=True`, based on the CDnet 46-scene batch and the three-condition synthetic sweep
   respectively. The 16/30 with shadows configuration is the one carried into the code snippets in both
   later documents and is the better supported of the two, but the conflict is unresolved in the source
   material. Both are recorded here.

2. **MOG2 versus KNN foreground percentage at night.** `algorithm_comparison.md` (CDnet 46-scene batch,
   2026-03-26) reports MOG2 and KNN producing IDENTICAL average foreground coverage in every category,
   including nightVideos at 5.66 percent for both. `design_note_night_video_quality.md` (2026-03-24)
   reports a clear divergence on specific clips: highway (day) MOG2 8.76 percent versus KNN 7.10
   percent, and bridgeEntry (night) MOG2 2.10 percent versus KNN 4.42 percent, and treats the night
   reversal as a key finding. These are different aggregation levels (per-category average versus
   individual clip), which may explain part of it, but the category-level identity across all ten
   categories is itself suspicious and was never explained in the source docs.

3. **fast-plate-ocr excluded, then adopted.** `plate_reader.md` (2026-05-02) explicitly excludes
   fast-plate-ocr, citing a US-plate-biased dataset and a small unproven project (about 550 stars), and
   selects PaddleOCR as primary with EasyOCR as fallback. `RESEARCH-PLATES.md` (2026-07-04) reverses
   this and selects the ankandrew stack (fast-plate-ocr plus open-image-models) as the best option
   because it is MIT, torch free, and runs on the already-core ONNX Runtime, demoting EasyOCR to a
   legacy separate-env option. This is a genuine decision change over time, not an unresolved
   contradiction, but readers of the older document should be aware of the reversal.

4. **Mode 2 CRF and Mode 3 output shape.** The measured tables in `mode_size_hierarchy.md` were taken
   when Mode 2 encoded every frame at CRF 18 (making it consistently the largest mode) and when Mode 3
   was expected to produce a per-object `mode3_sparse/` tree. As of 2026-05-31, foreground CRF is
   progressive (mode0=18, mode1=18, mode2=23, mode3=38) and Mode 3 ships a single object-only clip; the
   per-object sparse rewrite never shipped on `app`. All Mode 2 and Mode 3 size numbers in section 1.7
   are therefore historical.

5. **H.265 policy.** `ai_compression_research.md` recommends prototyping x265 with ROI QP deltas as a
   medium-term item, and `RESEARCH-COMPRESSION.md` adopts addroi ROI-QP for "x264/x265". However,
   `RESEARCH-VMAF-TARGET.md` states a standing decision of "No H.265". The scope of that standing
   decision (codec selection for modes, versus the addroi capability statement) is not spelled out in
   the sources.
