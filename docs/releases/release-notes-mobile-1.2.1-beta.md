# SVCS Mobile 1.2.1-beta (versionCode 16) - release notes

**Hotfix, prepared 2026-09-24 on `mobile`.** Follows the Mobile section of
`docs/RELEASE-CHECKLIST.md`. Build on the same machine as earlier APKs so
it installs over 1.2.0-beta.

## What's fixed

- **Compression could make a file bigger, not smaller.** A flat quality or
  size-limit preset could request more bitrate than the source video
  already had. On a small or already-compressed clip, that meant the
  encoder was told to spend more bits per second than the original used,
  and the output ended up larger than the input, sometimes far larger. A
  3.5 MB clip could come out around 32 MB instead of shrinking.
- **The fix.** Every compression mode now caps its requested bitrate to the
  source file's own bitrate (leaving room for audio, with a small floor so
  a job never asks for near-zero bits). Explicit target-size and explicit
  bitrate caps you set yourself are never overridden, only unbounded
  "quality preset" requests are capped. The pre-compression "estimated
  result" panel now reflects the same cap, so the estimate is honest too.
- **Desktop had a related, separately-caused gap.** The desktop pipeline's
  CRF-based encoding could also exceed the source bitrate on some
  presets and fast, low-motion content. It now gets the same source-bitrate
  ceiling (skipped for Archive and screen-recording presets, and for live
  camera sources where there is no source file to measure).

## Verified before release (fill in on the phone)

- [ ] Installs over 1.2.0-beta; SAVED history is kept.
- [ ] Compressing a small, low-bitrate clip (the kind that triggered the
      bug) now produces an output smaller than the input.
- [ ] A normal, larger source clip still compresses to roughly the size it
      did before this fix.
- [ ] General smoke test: MORE, a plain COMPRESS job, and SAVED all still
      work.

## What was verified in development

- New JVM unit tests for the bitrate cap (`capToSourceBitrate` in
  `CompressionPresetsTest.kt`), including the exact 3.5 MB reproduction
  case, an already-below-source-rate case, a silent-source case, the floor,
  and the "unknown size or duration" skip case.
- On an emulator: reproduced the bug against the pre-fix release build
  (source inflated by roughly 247%), then confirmed the fixed release
  build compresses the same source down instead (roughly 1% smaller,
  consistent with it already being near-optimally encoded).
- Desktop: new pytest cases in `tests/test_pipeline.py`
  (`TestAutoBitrateCap`) covering the cap, the mode0 exemption, and that
  explicit caps are never overridden.

## Known limits

- Carried over from 1.2.0-beta: region mode is unverified on a real
  `FEATURE_Roi` device, and the desktop pipeline's `libaom-av1` codec still
  has no bitrate-cap support (a pre-existing gap, not addressed here).
