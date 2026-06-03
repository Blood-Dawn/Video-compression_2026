# FFmpeg bundling & licensing (M2 TASK 2.3)

Author: Bloodawn (KheivenD), 2026-06-03.

The packaged installer **vendors an FFmpeg binary** so the app is self-contained
(no "install FFmpeg first" step). At runtime the app resolves FFmpeg in this
order (`src/utils/ffmpeg.py`):

1. the **bundled** binary (`<app>/ffmpeg/bin/ffmpeg(.exe)`),
2. a binary on **PATH**,
3. the bare name `ffmpeg` as a last resort.

A dev clone keeps using whatever FFmpeg is on PATH; the bundled binary only
matters in the frozen build.

## Which build do we ship, and why GPL (not LGPL) for this app

| Codec (per-mode policy, TASK 1.6) | FFmpeg encoder | License of that encoder | In an LGPL FFmpeg? | In a GPL FFmpeg? |
|---|---|---|---|---|
| Mode 0 / 1 → H.264 | `libx264` | **GPL-2.0-or-later** | ❌ no | ✅ yes |
| Mode 2 / 3 → AV1 | `libsvtav1` (SVT-AV1) | BSD-3 | ✅ yes | ✅ yes |
| (not used) HEVC | `libx265` | GPL-2.0-or-later | ❌ no | ✅ yes |
| (fallback) H.264 | `libopenh264` | BSD (Cisco) | ✅ yes | ✅ yes |

The per-mode codec gate (RESOLVED 2026-06-01) chose **libx264** for Mode 0/1
(universal playback + a clean royalty position vs HEVC). **libx264 is GPL**, so
an LGPL FFmpeg build does *not* contain it — an LGPL bundle would leave Mode 0/1
with no x264 encoder. Therefore, for **this** edition we bundle a **full GPL
FFmpeg** (x264 + SVT-AV1, x265 present but unused).

This is licence-compatible: the app is **AGPL-3.0**, and AGPL-3.0 is compatible
with GPL-2.0-or-later code, so shipping GPL FFmpeg alongside the AGPL app is
fine. (We do NOT use `libx265`/HEVC — its patent licensing is fragmented and not
royalty-free — even though the GPL build technically contains it.)

H.265/HEVC is never selected by the app (no `libx265` codepath), so its presence
in the binary is irrelevant to what we actually encode.

## Readiness for a possible future (non-GPL) fork

If a future commercial fork needs to avoid GPL (e.g. to distribute under a
proprietary licence), the seam is:
- swap the bundle to an **LGPL FFmpeg** build, and
- change the Mode 0/1 default from `libx264` to **`libopenh264`** (BSD) — an
  LGPL FFmpeg includes it. SVT-AV1 (Mode 2/3) needs no change (BSD, in LGPL).

That keeps the entire bundled stack permissive (LGPL FFmpeg + BSD encoders) with
no GPL code. This doc is the readiness note for that path (PLAN-V2 §13); it is
not in force for the open-source AGPL edition.

## Pinned build

The build (`installer/build.ps1`) fetches a **pinned** FFmpeg release and places
`ffmpeg.exe` + `ffprobe.exe` under `tools/ffmpeg/bin/`, which
`installer/svcs.spec` bundles into the app. `tools/` is gitignored (the binary
is a build artifact, never committed). See `build.ps1` for the pinned version
and download URL; update both together and re-record here when bumping.

- Source: BtbN FFmpeg-Builds (reproducible per-tag GPL win64 builds).
- Pinned tag: see `$FFmpegVersion` in `installer/build.ps1`.
