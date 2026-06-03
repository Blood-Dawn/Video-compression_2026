# SVCS v2 Roadmap

The v2 product is a consumer / commercial video compression toolkit. It
keeps the AI-aware compression engine from v1 but expands beyond
surveillance to any video and adds a real installer, a mobile app, and
auto-detected presets.

See `ARCHITECTURE.md` for the technical plan and `LICENSE-COMMERCIAL.md`
for the dual-license strategy.

## June 2026 - Desktop installer (Python, on `app` branch)

| Milestone | Done when |
|---|---|
| Audit fixes landed | All items from the May 4 audit are resolved: no `print()`, structured logging, platform-aware app-data dirs, centralized config, `gui/app.py` split into modules |
| Premium branch live | `premium` branch off `app`, builds the commercial-license edition with plate reader and other paid-tier features included |
| PaddleOCR removed | EasyOCR promoted to primary OCR backend on the premium-only plate reader |
| Preset system v1 | 10 presets shipping (Movie, Show, Vlog, Action, Animation, Screen Recording, Surveillance, Music Video, Archive, Mobile) |
| Auto-detect content type | First 30 seconds analyzed, preset recommended |
| Windows installer | `SVCS-Setup-x.y.z.exe` via Inno Setup. Bundles FFmpeg, Python embeddable, all model weights |
| macOS installer | `SVCS-x.y.z.dmg` signed and notarized |
| Linux installer | AppImage |
| Public download page | Hosted on GitHub Pages or similar |
| Crash reporting | Sentry SDK wired with opt-in toggle |

## July 2026 - Rust core MVP (`kdev` branch)

| Milestone | Done when |
|---|---|
| `svcs-core` crate scaffold | `cargo new` done, compiles for all target platforms in CI |
| Encoder module ported | Dual-CRF FFmpeg encoder rewritten in Rust, validated on 19 CDnet clips to match Python output bit-for-bit (or within accepted tolerance) |
| FFI shim | Python wrapper around Rust encoder exposed so `app` branch can use it |
| Background subtraction ported | MOG2 + scene detection in Rust |
| Mode dispatch ported | Per-frame mode decision logic in Rust |
| Tests | 50%+ of the relevant Python tests have Rust equivalents |

## August 2026 - Flutter UI + Android app (`app` branch)

| Milestone | Done when |
|---|---|
| Flutter desktop prototype | Native window opens, file picker works, talks to Rust core via FFI, shows compression progress |
| Preset UI | All 10 presets selectable, auto-recommendation visible |
| Compressed output player | Inline `video_player` widget plays the result |
| Android prototype | Same Flutter code targets Android, ships an APK |
| Background processing on Android | `WorkManager` integration so compression continues with screen off |
| Notification | Progress shown in notification shade |
| Play Store internal track | Closed alpha published to ~10 testers |

## September 2026 - Public beta

| Milestone | Done when |
|---|---|
| Public beta of desktop installer | Tagged v2.0.0-beta on GitHub, link on landing page |
| Public beta of Android app | Play Store open testing |
| Documentation | README v2, user guide, FAQ |
| First commercial license customer (stretch) | One paying customer signed |

## Fall 2026 and beyond (out of scope for this roadmap)

These are noted for awareness but not committed:

- iOS app via the same Flutter + Rust stack
- Hardware acceleration: NVENC, QuickSync, VideoToolbox, AMF
- Cloud-tier hosted compression service
- Plugin / extension API
- Plex and Jellyfin integrations (drop compressed file directly into the
  library)
- Auto-chapter detection
- Auto-subtitle generation via Whisper

## Backlog from v1 (Python pipeline on `dev` branch)

These are leftover team tasks from the FAU capstone that didn't ship by
May 6. They live on `dev` and may ship as a v1.1 Python release for any
sponsor follow-up. Kheiven is taking them over for the summer.

| Task | Original owner | Effort |
|---|---|---|
| Color detection (HSV histogram on ROI center 50%) | Ashleyn | 4 hr |
| Contour-based object classifier rewrite | Ashleyn | 6 hr |
| Adaptive mode controller | Kheiven | 8 hr |
| Background staleness tracking for Mode 2 | Kheiven | 4 hr |
| Demo/concat mode (stitch all session segments) | Riley | 4 hr |
| Extend test_pipeline.py (bicubic enhance, encrypt round-trip, stop event) | Riley | 6 hr |
| Per-segment encryption (store IV/salt in DB row) | Victor | 4 hr |
| Password-protected incident clip export | Victor | 4 hr |
| Per-mode CPU + battery benchmarks | Jorge | 6 hr |
| AV1 benchmark doc | Jorge | 2 hr |
| **Total** | | **~48 hr** |

These get knocked out in week 1 of June before the productization sprint
proper kicks off.
