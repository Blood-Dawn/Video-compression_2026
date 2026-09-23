# SVCS Mobile v1-beta (1.1.0-beta) - release notes

The first build where the phone does the compressing itself. Earlier mobile
releases were a remote for the desktop server and encoded nothing on the
phone; this one works with no server, no network and no account. Server
Mode (pairing, LIBRARY, LIVE, EVENTS, METRICS) is unchanged and still
optional. Plan and reasoning: `mobile/android/STANDALONE-COMPRESSOR-ROADMAP.md`.

## 1.1.0-beta (2026-09-23): UI refresh

Same features, rebuilt interface. The compressor now follows the SVCS
design system it was always meant to (the fonts were never bundled and
the color scheme was incomplete, so it had been rendering in system fonts
with stray Material purples). Full write-up, with the research behind it:
`mobile/android/UI-REVIEW.md`.

- COMPRESS has a layout per step: pick, configure, running, done. Choose
  QUALITY or SIZE LIMIT and only those options show; the COMPRESS button
  stays pinned at the bottom.
- An estimated result before you start, worded as an upper bound, and a
  warning when the source is already lean enough that a preset can't
  shrink it (it compares against the video's own bitrate).
- Running shows percent, stage, elapsed and time left. Done leads with the
  saving, original vs compressed bars, and Share.
- SAVED: totals, search, filters behind a toggle, rows with savings badges.
- Real icons in the bottom bar; MORE explains that Server Mode is optional
  and credits the open-source pieces and their licenses.

Installs over 1.0.0-beta (versionCode 14).

## Which APK

| File | For |
|---|---|
| `svcs-mobile-v1-beta.apk` | arm64-v8a. Almost every Android phone from the last several years. 12.6 MB. |
| `svcs-mobile-v1-beta-universal.apk` | Every CPU type, including 32-bit phones and x86_64 emulators. 27.5 MB. |
| `SHA256SUMS.txt` | Checksums for both. |

minSdk 29 (Android 10). Release build (R8-minified), self-signed, sideload
install. Package `org.svcs.mobile`, so it installs over earlier SVCS mobile
releases. The first v1-beta upload was a debug build with the package
`org.svcs.mobile.debug`; if that one is on your phone, it shows up as a
second SVCS icon and can be uninstalled. Its SAVED history doesn't carry
over, since it's a separate app as far as Android is concerned.

## What's new

- **COMPRESS tab, fully offline.** Quality presets (High / Medium / Low) or
  fit under a size limit (Discord 10 MB, Discord Nitro 500 MB, WhatsApp
  16 MB, Instagram 100 MB, X 512 MB, email 25 MB, or any exact size typed
  in). H.265 or H.264. Runs as a foreground job with a progress
  notification and a cancel button, on the phone's hardware encoder via
  Jetpack Media3 Transformer. Output lands in `Movies/SVCS`.
- **Share in, share out.** Share a video to SVCS from the gallery or any
  app; the finished file has Share and Play buttons.
- **Remove audio.** With a size limit, the audio budget goes to the
  picture. Sources with no audio track get the same treatment
  automatically.
- **Smart Compress (beta, opt-in).** YOLOv8n runs on the phone through
  LiteRT (3.3 MB INT8 model) over a bounded sample of frames. If no
  people, vehicles or animals show up anywhere, the bitrate is cut 35%;
  if anything does, the file is encoded exactly as requested. It never
  raises the bitrate, so a size limit is never put at risk. This is a
  whole-clip decision, not per-region encoding; that part is still ahead
  (see the roadmap).
- **SAVED tab.** Searchable history of on-device jobs with thumbnails,
  filters (date, codec, mode, fallback, Smart Compress), sorting (newest,
  biggest saving, largest), and play / share / delete.
- **New app icon**, matching the desktop installer.

## Fixed since the first v1-beta upload

- Portrait video was downscaled far too hard: the resolution cap was
  applied to the literal frame height, so a portrait clip on a 720 preset
  came out 406x720 instead of 720x1280 (the field test clip from
  2026-09-22 shows exactly this). The cap now applies to the true short
  side, rotation included, and sources already under the cap are never
  upscaled.
- Size-preset chips ran off the right edge of the screen, so only Discord
  was visible and a blank gap sat where the rest should have been.
- A shared video SVCS couldn't read was accepted anyway and then failed
  with no message. It's now rejected at pick time with an explanation.

## Verified this cycle

- `./gradlew assembleRelease` builds clean; `testDebugUnitTest` 55/56,
  with 18 new tests for size-target math, custom sizes, the portrait and
  rotation cases, and SAVED's search / filter / sort. The one failure is
  the long-standing `ServerSettingsViewModelTest` save case:
  `TokenStore` encrypts through AndroidKeyStore, which Robolectric doesn't
  provide. Test-environment limitation, not a product bug.
- The bundled detector was checked against real photos and blank frames
  on the desktop before shipping: people and animals scored 0.39 to 0.93,
  blank, black and noise frames 0.000 to 0.005.
- End to end on the API 35 emulator with the minified release build:
  install over the existing app, cold launch, share-in, picker, three
  compression jobs (portrait at 720x1280, a person clip kept at full
  bitrate, a no-activity clip cut to 70% of the size), and SAVED listing
  all three. No crashes.
- Not yet verified on a physical phone with this exact build. The first
  v1-beta upload was field-tested on a real device on 2026-09-22.

## Known limits

- The emulator's software HEVC encoder tops out around 512 px, and Media3
  quietly falls back to that size there. Real phones use hardware HEVC
  and aren't affected, but the app doesn't yet tell you when an encoder
  falls back like that.
- Size-limit jobs tend to land somewhat under the limit (the field test
  hit 8 MB on a 10 MB target), because single-pass hardware encoders
  undershoot on calm footage. Safe direction, but it leaves quality on
  the table.
