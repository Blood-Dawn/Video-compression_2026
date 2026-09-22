# RESEARCH: better compression algorithms (R4 Phase 2)

Date: 2026-07-04. Method: deep-research workflow (6 angles, 109 agents; top 25+
claims adversarially verified, 3 refuted and excluded). Local capability probe
against the bundled FFmpeg (tools/ffmpeg): libx264/libx265/SVT-AV1/libaom,
h264_nvenc + hevc_nvenc + av1_nvenc ALL functional on this machine's GPU,
addroi / hqdn3d / nlmeans / atadenoise / libvmaf present.

## Verified findings and decisions

### 1. addroi encoder-level ROI instead of the downscale-composite hack - ADOPT (opt-in v1)
Verified 12-0 against FFmpeg docs + libavcodec/libx264.c: the addroi filter
attaches per-region quantization metadata consumed by libx264/libx265 as
per-macroblock QP offsets (qoffset in [-1,+1]; -1/10 at frame QP ~30 gives the
region ~QP 24). The canonical ROI approach: one stream, pixels untouched.
LIMITS (verified): NOT consumed by libsvtav1/libaom (a claimed SVT-AV1
--roi-map-file was REFUTED 0-3), so ROI-QP is x264/x265-only. The CLI filter's
rectangles are fixed per process, and SVCS opens one FFmpeg process per
SEGMENT, so boxes can refresh only at segment boundaries.
- v1 design: activity-grid ROI, opt-in (`roi_qp`). While encoding, accumulate
  which grid cells saw foreground regions; when the NEXT segment's process is
  opened, cells with recent activity are protected (negative qoffset toward
  the foreground CRF) and long-static cells degrade toward background_crf.
  First segment of a session gets no ROI (full quality) - fail-safe direction.
- Kept OFF by default in v1: per-frame compositing reacts to NEW motion
  instantly, per-segment ROI has up to one segment of lag in fresh areas.
  Documented tradeoff; same class as camera "smart codec" dynamic ROI.

### 2. Long GOP for static cameras - ADOPT (default on)
Verified 6-0: x264 default keyint is only 250 frames; "infinite" is supported.
SVT-AV1 keyint default is ~5s; -1 = infinite (CRF only), passable via
-svtav1-params. IPVM measured 90%+ bitrate reduction for camera smart codecs
(dynamic GOP + AQ) on fully static scenes, 20-50% typical, ~20% at night.
- Adopted: bounded long GOP (research's pragmatic middle ground for seekable
  archives): keyint = 20s of frames for both encoders, scenecut left on.
  Infinite GOP rejected: archived surveillance must stay seekable.

### 3. Capped CRF for storage budgeting - ADOPT
Verified 3-0: SVT-AV1 --mbr (kbps, CRF-only, soft cap, default 50% overshoot);
x264 capped-CRF = CRF + -maxrate/-bufsize (VBV, hard-ish bound).
- Adopted: optional max_bitrate_kbps config; x264 path gets
  -maxrate/-bufsize (2s buffer), SVT-AV1 path gets mbr= in svtav1-params.

### 4. Hardware encoders as the real-time ingest default when present - ADOPT
Verified 6-0 (medium confidence; study used gaming/UHD CBR content): current
QSV/NVENC match or slightly beat real-time-capable software presets at 1080p
(+0.51 / +0.38 VMAF) at roughly half the system power; Ada NVENC AV1 ~40%
bitrate savings vs NVENC H.264 (vendor-measured). This machine: all three
NVENC codecs verified working.
- Adopted: h264_nvenc / hevc_nvenc / av1_nvenc as selectable codecs with
  runtime probe + automatic fallback to libx264 (the existing
  _ffmpeg_has_encoder fallback pattern). Auto codec choice still defaults to
  software (quality-first for archives); NVENC is surfaced for live/RTSP
  ingest. NOTE: FFmpeg's nvenc wrapper consumes neither addroi side data nor
  qpDeltaMap (verified), so ROI-QP and NVENC are mutually exclusive.

### 5. Pre-encode denoising for night/IR footage - ADOPT (opt-in)
Verified 6-0: HandBrake's NLMeans benchmark cut output 19.5% at ~50% encode
time cost on a CLEAN source; IPVM shows sensor noise makes night footage cost
up to 3x daytime bitrate, so the night payoff is larger. Denoising can soften
plate/face detail - stays opt-in.
- Adopted: optional denoise stage in the encoder filter chain: "hqdn3d"
  (cheap, default strength) or "atadenoise" (temporal, static-camera
  friendly). Off by default.

### 6. VMAF validation - ADOPT (tooling only)
Verified 3-0: NTIA/ITS found VMAF responds only to compression artifacts even
when the reference has camera impairments, so it is valid for surveillance
A/B testing. libvmaf is in the bundled FFmpeg.
- Adopted: compute_vmaf() in utils/metrics.py shelling to ffmpeg libvmaf, for
  offline validation of encoder-setting changes (not in the live pipeline).

### 7. NVENC emphasis maps (qpDeltaMap) - DEFER
Verified 6-0 but requires direct NVENC SDK integration (PyNvVideoCodec); the
FFmpeg wrapper cannot do it. Recorded for a future GPU-ROI effort.

### 8. Neural codecs (DCVC-RT) - NOT YET (recorded)
Verified 17-1: DCVC-RT reports ~21% BD-rate savings vs H.266/VTM and 125 fps
1080p encode - on an A100. Consumer RTX 2080 Ti: ~39 fps; CUDA 12.6 + custom
kernel builds; NO CPU path, no FFmpeg integration. Not deployable for SVCS's
CPU-first Windows audience. Revisit when a CPU/ONNX or FFmpeg path exists.

## Refuted claims (excluded, do not resurface)
- "SVT-AV1 has --roi-map-file per-region QP" (0-3): encoder-level ROI is
  x264/x265-only in this pipeline.
- "HEVC ROI achieves 0.7-1.0 Mbit/s 1080p30 at PSNR>37dB" (0-3): no verified
  quantitative ROI-vs-composite number exists; do not promise one.
- "Ada NVENC AV1 = x264 medium quality at 18 vs 30 Mbps at ~500fps" (1-2).

## Implementation plan (this phase)
1. roi_encoder: long-GOP defaults (keyint=20s both encoders), max_bitrate
   capped-CRF plumbing, NVENC codec support w/ probe + fallback, optional
   denoise filter stage, opt-in activity-grid addroi ROI for x264/x265.
2. config/pipeline/GUI plumbing for the new knobs (codec choices + advanced
   fields), defaults unchanged except long GOP.
3. utils/metrics.py compute_vmaf.
4. Tests: arg-construction units (no real encodes), one real tiny encode
   smoke per new path where cheap, VMAF test guarded by filter presence.

## Honest caveats carried forward
- IPVM's 90%+ is a best-case ceiling (fully static scene); expect 20-50%.
- The hardware-encoder study content was gaming/UHD CBR, not surveillance CRF,
  and did not test AMD AMF.
- NVIDIA's 40% AV1-vs-H.264 figure is vendor-measured.
- The NLMeans 19.5% benchmark is a single clip with no quality metric.
- SVT-AV1 --mbr is a soft cap (50% default overshoot), not a VBV guarantee.
