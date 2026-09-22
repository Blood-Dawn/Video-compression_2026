# Standalone Compressor Roadmap

Fall 2026. This is a for-fun project now, not capstone-gated — EGN4950C is
satisfied by the desktop app, which is done. Nothing here has a deadline.
The point of this document is to answer one question with real research
instead of guessing: **can the mobile app stop depending on the desktop
server and become a real, independent Android video compressor**, and if
so, what does building that actually look like.

Short answer: yes, but not by porting the desktop pipeline. The desktop's
FFmpeg + libx264 approach is the wrong engine for Android in 2026, for
reasons that are now well-documented (below) rather than assumed. The right
engine is Android's own hardware codec path via Jetpack Media3 Transformer
— which is also exactly what the app we're benchmarking against uses.

## 0. The competitive bar: Compressor by JoshAtticus

You pointed at this app specifically, so it's worth being precise about
what it actually is, since it sets the bar for what "a real Android
compressor app" looks like in 2026.

[Compressor](https://github.com/JoshAtticus/Compressor) is 100% Kotlin,
built entirely on `androidx.media3:media3-transformer` — Google's own
hardware-accelerated transcoding library — with **zero third-party
libraries and no bundled FFmpeg**. Its README brands this explicitly: "not
another slow, bulky FFmpeg wrapper." That's the whole thesis of the app,
and it's the reason it's fast:

- **APK size:** 16.7MB, under 10MB installed. No native `.so` files beyond
  what Media3/AndroidX already ships.
- **Permissions:** only `WAKE_LOCK` and a notification-receiver flag. No
  storage, no internet, no camera permission at all.
- **Speed:** the developer's own published benchmark (Pixel 8 Pro) has it
  doing a 4K60 transcode in 10.55s versus the nearest native competitor
  ("Squeezio") at 14.11s, and an FFmpeg-wrapper competitor ("Panda")
  outright failing/erroring on the same heavy test cases.
- **Controls:** quality presets (High/Medium/Low), a target-file-size
  slider, resolution/framerate pickers, codec choice (H.264/H.265/AV1 where
  the device supports it), and app-specific size presets (Discord,
  WhatsApp, Instagram limits).
- **What it does *not* do:** anything algorithmically smart. No scene
  detection, no per-region quality, no ML of any kind. It wins purely on
  hardware-accelerated speed, tiny footprint, and zero ads/telemetry — not
  on compression sophistication.
- **Monetization:** completely free. No ads, no IAP, no subscription.
  Funded only by optional donations (Buy Me a Coffee / crypto). Rating was
  4.7-4.8 stars on ~156 Play reviews at research time (your 4.9 may reflect
  a slightly newer snapshot - it's climbing).
- **Distribution:** simultaneously on Google Play, IzzyOnDroid (an
  F-Droid-compatible repo), and GitHub Releases — possible with zero
  license friction specifically *because* there's no GPL code involved.

The broader market (Panda Video Compressor: 10M+ installs, 4.7 stars,
ad-heavy with a paid tier; VidCompact: 10M+ installs, 4.4 stars, ~60
pounds/yr subscription; InShot: 500M+ installs, compression is a secondary
feature inside a full editor suite) is dominated by ad-and-subscription
apps where compression is often bolted onto something bigger. Compressor's
gap in that market is exactly "fast, free, private, does one thing well"
which is a very achievable bar, and a good one to aim at.

## 1. Why not port the desktop pipeline

The desktop's `roi_encoder.py` gets its per-region quality shaping from
FFmpeg's `addroi` filter feeding libx264's software (CPU) encoder — CRF 18
on foreground, CRF 40+ on long-static background, degraded per grid cell.
That's a genuinely good desktop design. It does not transplant to Android,
for three independent, converging reasons the research turned up:

**FFmpeg-on-Android's ecosystem collapsed.** `ffmpeg-kit` (the library
basically every hobbyist FFmpeg-on-Android/Flutter app used to wrap) was
retired by its own maintainer, with binary packages pulled starting
February 2025 and the GitHub repo archived in mid-2026. The real reason —
confirmed from the maintainer's own "Saying Goodbye to FFmpegKit" post,
correcting an earlier assumption — was **years of unpaid maintenance
burden plus IP-law-firm advice following MPEG LA's 2023 acquisition by
Via-LA**, not a Google Play rejection over GPL (GPL apps do ship on Play
today — `brarcher/video-transcoder` is live proof). A community
continuation (`ffmpegkit-maintained`) and an official source-only successor
(`ffmpeg-kit-next`) exist, but both mean *you* now own a native build
pipeline indefinitely, and neither was a going concern before this
research — this project would be an early adopter of unproven successors.

**Android hardware encoders can't do what the desktop algorithm needs.**
CRF/constant-quality encoding (`BITRATE_MODE_CQ`) is confirmed unreliable
or entirely unsupported on Exynos and even Google's own AV1 hardware
encoder — compression has to be driven by bitrate/size targets, not a
quality dial. True two-pass VBR doesn't exist on Android hardware encoders
at all; they're real-time ASICs built for camera capture, not offline
transcode. And per-region quality control — the actual core of
`roi_encoder.py` — exists on Android only as a **Qualcomm-exclusive vendor
extension** historically, with a real, standardized, cross-vendor
equivalent (`MediaCodec.PARAMETER_KEY_QP_OFFSET_MAP`/`_RECTS`) landing only
in **Android 15**, gated behind an OEM-optional `FEATURE_Roi` capability
flag that's explicitly "best effort." It may silently do nothing on a
given device. (More on this below — it's not a dead end, just not a
foundation.)

**Bundling FFmpeg's native binaries adds compliance debt the alternative
doesn't have.** Any app shipping native `.so` code that targets Android
15+ must be 16KB-memory-page-size compliant to publish updates on Play by
**February 1, 2027**. A pure-Kotlin Media3 app has zero native libraries
and is unaffected by default; a bundled FFmpeg build has to be rebuilt and
re-verified for this.

Put together: the desktop pipeline is the right design for a desktop CPU.
Android's actual native primitives point somewhere else, and that
somewhere else is also what the best-reviewed competitor already validated
in production.

## 2. The engine: Jetpack Media3 Transformer

[`androidx.media3:media3-transformer`](https://developer.android.com/media/media3/transformer)
is Google's own actively-maintained transcoding/editing library, built
directly on `MediaCodec`, with an OpenGL effects pipeline and automatic
transmux-when-possible (skips re-encoding entirely when the input already
matches the target format/codec). It's the same library Compressor is
built on. No bundled native code, no licensing question, benchmarked by
Google at roughly 1.3s to transcode a 10s 720p clip to H.265/AAC on a
Pixel 9 Pro XL.

It inherits every MediaCodec limitation above rather than solving them —
that's fine, it's the same ceiling every competitor in this space is
working under, including the one you're benchmarking against. Concretely,
this means the compression UX should be built around **bitrate/resolution
presets and target-file-size estimation**, not a CRF slider — with an
opportunistic "Quality mode" toggle only on devices where
`EncoderCapabilities.isBitrateModeSupported(BITRATE_MODE_CQ)` actually
returns true (Compressor has an open feature request for exactly this —
it's a known, unsolved gap in the whole category, not something we'd be
behind on).

Default output codec: **H.265/HEVC**, broadest reliable hardware encode
support across vendors. H.264 as the universal fallback for old/low-end
devices. AV1 encode marked experimental/opt-in — Google's own Pixel AV1
encoder path has documented "broken output" reports, this isn't safe as a
default yet.

One robustness item to build in from day one, not as polish: a documented
real failure (`androidx/media` issue #2751) shows both hardware and
software H.264 decoders on a mid-range device (Redmi 8A) rejecting a
common odd resolution/framerate combination outright, killing the pipeline
before encoding even starts. The compression flow needs a decode-failure
fallback (retry scaled down, or a clear user-facing error) as a first-class
path, not an edge case.

## 3. What stays from the current app, what's new

The current mobile app (`mobile/android/app/src/main/java/org/svcs/mobile/`)
is a thin remote client — every function in `net/SvcsApi.kt` is a call to
the desktop server; there's no capture, detection, or encoding on-device
anywhere in it. None of that needs to be thrown away, and most of it is
worth keeping:

- **Keep as-is, becomes a secondary mode:** everything under `net/` and
  the `Library`/`Live`/`Events`/`Metrics`/`ServerSettings` screens — this
  is a legitimately useful "control my home SVCS box" feature once the
  standalone engine exists alongside it, not instead of it. Reframe it in
  the UI as "Server Mode" rather than the app's whole identity.
  `JobNotifier.kt`'s notification patterns and the WorkManager design
  already written for chunked upload (`mobile/android/UPLOAD-WORKER-
  DESIGN.md`, Fall 3.3) generalize directly to the new compression worker
  below — same `CoroutineWorker` + foreground-service shape, different
  payload.
- **Keep as-is:** the Compose UI shell, theming (`ui/theme/`), navigation
  (`ui/SvcsApp.kt`), and the `qa` build-variant/logging setup from Week 3.
- **New, and the actual point of this roadmap:** a standalone compression
  engine that needs zero network, zero desktop pairing, built on Media3
  Transformer, plus (Phase 2) a port of the existing on-device detection
  work the desktop already has.

This also answers "do we scrap most of the mobile app" — no. The remote
client is maybe 15% of the eventual app's surface area and none of it
conflicts with adding a standalone engine alongside it.

## 4. Phased roadmap

### Phase 1 - MVP: match the table stakes

Goal: ship the same core loop Compressor ships, entirely offline, before
touching anything "smart." This is deliberately unambitious - it's the
floor the whole category is judged on, per the research, and skipping it
to chase the ML differentiator first would mean shipping something novel
on top of a pipeline nobody's validated yet.

- Pick a video via the system share-sheet or a document picker (`Intent.
  ACTION_GET_CONTENT` / `ACTION_OPEN_DOCUMENT`, or receive a share-in from
  another app) - not a broad-storage-permission file browser.
- Read via `MediaStore.Video.Media` / the picked `content://` URI directly;
  no `READ_EXTERNAL_STORAGE` needed for user-picked files, `READ_MEDIA_
  VIDEO` (API 33+) only if we ever add a "browse my library" mode.
- Compress via `Transformer` with: quality presets (High/Medium/Low ->
  bitrate targets, not CRF), a target-file-size slider (the thing
  Compressor's own backlog shows users specifically ask for), resolution/
  framerate caps, and app-size presets (Discord 10MB/25MB, WhatsApp,
  Instagram).
- Write output via `MediaStore.Video.Media.insert()` with `IS_PENDING=1`,
  `RELATIVE_PATH = "Movies/SVCS"`, stream the encode, flip `IS_PENDING`
  to 0 on success - this also means a killed job just leaves an invisible
  pending row instead of a corrupt visible file, for free.
- Run the job as a `CoroutineWorker` promoted to a foreground service with
  `foregroundServiceType = FOREGROUND_SERVICE_TYPE_MEDIA_PROCESSING` (new
  in Android 15 specifically for this use case - our `targetSdk` is
  already 35, so no version gap here) plus a persistent progress
  notification with a cancel action, generalizing the pattern already
  designed in `UPLOAD-WORKER-DESIGN.md`. Implement `onTimeout()`
  defensively (a compression job should never approach the 6h budget, but
  the OS gives only seconds to `stopSelf()` once it's hit, or it's a fatal
  crash). **Never** request `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` - it's
  not an approved use case for this category and risks a Play policy flag;
  a running foreground service is already exempt from Doze while active.
- Decode-failure fallback path (see section 2) as part of MVP, not polish.

Exit criteria: compress a video, entirely offline, with a result
competitive on speed and size with Compressor's on the same device.

### Phase 2 - Smart Compress (the actual differentiator)

This is the part that's genuinely novel: the research found **no existing
Android app - including every competitor surveyed - that uses on-device
object detection to guide compression quality or bitrate allocation.**
Compressor's own backlog shows zero interest in this direction. This is
where the desktop's actual IP (detection-driven ROI compression) has a
real mobile equivalent to aim for, even though it can't be a literal port.

- **Detection model:** port the existing `yolov8n.onnx` (already 13MB,
  already the slim/torch-free path per `src/detection/onnx_backend.py`) to
  **LiteRT/TFLite rather than ONNX Runtime Mobile.** This is a direct
  reversal of what I'd have assumed going in, and it's worth stating why:
  Android's NNAPI - the low-level accelerator API both runtimes have
  historically depended on - is **officially deprecated as of Android 15**,
  and Google is steering the whole platform toward LiteRT's new
  `CompiledModel` API, which treats GPU/NPU as a config flag with
  first-party support across Tensor/Snapdragon/MediaTek/Samsung silicon.
  ONNX Runtime Mobile still works, but its fast path (Qualcomm's QNN
  execution provider) is Snapdragon-only with no equivalent unified NPU
  story. Ultralytics supports a direct YOLO->LiteRT export
  (`format='litert'`, INT8 quantization), which is a materially lower-
  friction conversion than ONNX->TFLite.
- **Quantize.** INT8/w8a8, not float - roughly a 3-5x latency and a much
  larger power-efficiency improvement (one cross-hardware benchmark found
  NPU inference ~47x more inferences-per-watt-hour than CPU). Real data
  points: sub-1ms per frame on flagship NPUs (Qualcomm AI Hub, quantized),
  roughly 15-50ms on CPU for a comparable nano-detector on mid-range
  hardware. Real-time full-frame detection on every frame is risky on
  mid-range devices without this.
- **Don't detect every frame.** Sample (every Nth frame, once per GOP, or
  a fixed 2-4x/sec) to build a region map, then apply it across nearby
  frames. Bounds the power/thermal cost and sidesteps the mid-range
  real-time risk above.
- **ROI integration point:** `MediaCodec.PARAMETER_KEY_QP_OFFSET_MAP` (a
  per-16x16-block QP offset, -51..+51) or `_RECTS` (rectangle-based),
  standardized in Android 15 - this is the literal mobile analogue of
  `roi_encoder.py`'s `addroi` filter. **Query `FEATURE_Roi` support at
  runtime and degrade gracefully** where it's absent (which will be most
  devices for a while - this only just standardized and is OEM-optional):
  fall back to a coarser strategy, e.g. picking a higher or lower bitrate
  preset based on whether *any* detection occurred in the scene at all,
  rather than true per-region QP.
- Ship this as an opt-in "Smart Compress" mode layered on top of the
  Phase 1 pipeline once that's stable - not a Phase 1 blocker, and not
  something to over-promise given the OEM fragmentation above.

Exit criteria: "Smart Compress" measurably beats a flat preset on typical
security/handheld footage (more bits where the detector fires, fewer where
it doesn't) on at least Android 15 devices with `FEATURE_Roi`, with a
documented, tested fallback everywhere else.

### Phase 3 - Store-ready

- **Play Console foreground-service declaration:** for `mediaProcessing`,
  Play now requires a written functionality description, a "what breaks if
  deferred" justification, and a short screen-recording of a user
  triggering the feature - budget real time for this, it's a submission
  gate, not paperwork.
- **Closed testing gate:** new personal developer accounts (created after
  Nov 2023) must run a closed test with **12 continuously-opted-in testers
  for 14 uninterrupted days** before applying for production access
  (~7-day review after). This is time-bound and can't be compressed -
  start the developer account and recruit testers (teammates, classmates)
  as soon as there's any installable Phase 1 build, so the 14 days run in
  parallel with Phase 2 work instead of blocking launch at the end.
- **August 2026 developer verification:** Google is rolling out mandatory
  identity verification for apps to install normally on certified devices.
  A free "limited distribution" tier exists for students/hobbyists (up to
  20 devices, no ID/fee) - track this as a hard external deadline either
  way.
- **Distribution:** Play Store as primary (reach, trust, update mechanics).
  F-Droid/IzzyOnDroid is realistic as a secondary channel specifically
  *because* Phase 1/2 are FFmpeg-free - a bundled FFmpeg would mean
  maintaining a from-source build in F-Droid's pipeline (doable, NewPipe
  does it, but real ongoing work a MediaCodec-only app skips entirely).
- **Monetization:** given the "started for fun, capstone already shipped"
  framing, the donation-only model (Buy Me a Coffee / GitHub Sponsors, no
  ads, no IAP) matches both the project's actual motivation and is the
  fastest path through Play policy review - no ads/IAP review surface, no
  subscription-cancellation complaints like the ad-heavy competitors draw
  in their own reviews. Also worth flagging concretely: **going full GPL
  FFmpeg later would obligate open-sourcing the whole app** under GPL and
  complicates bundling any ad/analytics SDK - another point in favor of
  staying on the native MediaCodec/Media3 path if a paid tier is ever
  considered down the line.

### Phase 4 - Live capture (explicit stretch, not v1)

The research compared "compress an existing picked file" against "capture
live from the camera and compress/detect in real time," and the gap is
large enough that it belongs in its own deferred phase rather than folded
into the MVP:

- CameraX (over raw Camera2) remains the right abstraction if this is ever
  built, but combining `VideoCapture` + `ImageAnalysis` + `Preview`
  concurrently is genuinely fragile - Google's own docs describe
  device-dependent "stream sharing" fallbacks with real latency/battery
  cost, and there's a live GitHub issue thread of developers hitting
  "too many use cases bound" errors on exactly this combination.
- A real measurement found camera capture itself (ISP autofocus/exposure/
  noise reduction) is often the *single largest* energy cost in an
  on-device detection pipeline - bigger than the ML inference - so a
  live-capture mode would need its own frame-rate throttling strategy
  independent of the detection-sampling work in Phase 2.
- By contrast, "pick an existing file and compress it" (Phase 1/2) is a
  mature, low-risk pattern with no camera-session lifecycle to manage.

Recommendation: defer this entirely. It's a real product direction (closer
to what the desktop actually does - continuous surveillance capture) but
it roughly doubles the engineering surface (camera session management,
device-matrix QA, a second battery/thermal budget) for a feature that
isn't what any of the competitive set actually ships. Revisit after Phase
1-3 are live and there's real signal on whether people want that.

## 5. Open risks to track, not solve now

- `FEATURE_Roi` OEM adoption is unknown and will only become clear as
  Android 15+ devices reach real market share through 2026-27 - Phase 2's
  fallback path is not optional polish, it's how most users will actually
  experience "Smart Compress" for a while.
- AV1 hardware encode reliability (including on Pixel) is still shaky per
  multiple independent reports - keep it experimental/opt-in, don't
  promise it in marketing copy.
- `ffmpeg-kit-next` / `ffmpegkit-maintained` are unproven successors to a
  now-archived project - this roadmap deliberately avoids depending on
  either, but if a future feature (e.g. an obscure container format) ever
  seems to need FFmpeg, treat that as a real build-vs-buy decision with a
  maintenance cost, not a quick dependency add.
- The 16KB native-library page-size deadline (Feb 1, 2027) only matters if
  a native dependency gets added later (a custom codec, some third-party
  SDK) - worth a periodic APK Analyzer check at each milestone so nothing
  sneaks in via a transitive dependency.

## Sources

Research conducted via a parallel multi-agent sweep (competitor landscape,
FFmpeg-on-Android state, hardware encoding ceilings, on-device ML runtime
choice, Android platform constraints, distribution/monetization, capture
architecture), cross-validated across independent runs. Primary sources
cited inline above; full source lists per topic:

- github.com/JoshAtticus/Compressor, blog.joshattic.us (Aug 28 2026
  benchmark post), IzzyOnDroid/F-Droid listing, Google Play listing
- tanersener.medium.com/saying-goodbye-to-ffmpegkit-33ae939767e1,
  github.com/tanersener/ffmpeg-kit (archived), github.com/arthenica/
  ffmpeg-kit-next, github.com/ffmpegkit-maintained/ffmpeg,
  github.com/brarcher/video-transcoder, appfair.org/blog/gpl-and-the-app-
  stores
- developer.android.com/media/media3/transformer, android-developers.
  googleblog.com/2025/03 (Media3 Transformer perf post), codecs.wiki
  (Exynos/AV1 CQ-mode support notes), androidx/media issues #2273, #1992,
  #1707, #2751, docs.qualcomm.com MediaCodec vendor extensions
- developer.android.com/media/camera/camerax/architecture,
  android/camera-samples issue #414, par.nsf.gov/servlets/purl/10199522
  (on-device detection energy study), mvpfactory.io CameraX+TFLite case
  studies
- Google's NNAPI deprecation / NDK migration guide, LiteRT (ai.google.dev)
  docs, Qualcomm AI Hub YOLOv8 benchmark numbers, Ultralytics LiteRT export
  docs
- developer.android.com foreground-service-types and long-running-workers
  docs, Play Console policy pages on foreground service declarations and
  battery-optimization exemptions, MediaStore/scoped-storage docs
- Google Play Console new-developer-account closed-testing requirements,
  Android developer verification (Aug 2026 rollout) announcements, Adapty
  2026 mobile monetization report, F-Droid Inclusion Policy
