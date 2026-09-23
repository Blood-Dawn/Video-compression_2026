# SVCS Mobile - UI review and redesign (2026-09-23)

Why: after 1.0.0-beta the compressor worked, but it didn't feel good to use.
This records what was researched, what was actually wrong (from screenshots
of the real app on the API 35 emulator), what changed, and what's still open.

## Research

- **The benchmark app.** Compressor by JoshAtticus runs a four-step flow:
  select, settings, compressing, done (with a share-or-save panel). It sells
  itself on being clean, ad-free and fast, uses Material You / Material 3
  Expressive, and has a dark theme. Nothing exotic, just no clutter.
- **What people complain about in other compressors.** Ads before, during
  and after a job, paywalled basics, and redesigns that bury the core
  action behind a "little bitty button". The recurring praise is
  "intuitive to use and swift".
- **What the popular ones offer.** An estimated output size before
  compressing, a short preview, side-by-side playback of original vs
  compressed, a batch queue, custom resolution and custom target size.
- **Material 3 Expressive.** The expressive components (ButtonGroup,
  SplitButton, FloatingToolbar, ToggleButton, wavy progress,
  LoadingIndicator) only exist in `compose-material3` 1.5.0 alpha; stable is
  1.4.0, and the loading and wavy-progress ones were moved back to
  experimental in alpha19. This app is on the 2024.12.01 BOM (material3
  1.3.x). Decision: don't ship alpha UI libraries in a release; apply the
  principles (clear emphasis, one obvious action, motion between states)
  with stable APIs, and revisit when 1.5 goes stable.
- **SVCS already has a design system.** Imported from a Claude Design
  project in commit 4558c5e (`mobile/design/`, later dropped from this
  branch but recoverable from history): a "dark-first surveillance
  terminal" with surface panels, 1px borders, a 2px accent rule on top,
  2px corners, UPPERCASE Space Mono labels with wide tracking, Bebas Neue
  numbers, Outfit body text, an amber START button with a glow, pill mode
  chips, and a 60px bottom bar with thin line icons. The compressor
  screens followed none of it.

## What was wrong (before)

Captured on the emulator with the (new, opt-in) screenshot build.

1. **Stray purple everywhere.** The theme set about a dozen Material color
   roles; Material filled the rest (selected chips, cards, switch tracks,
   the nav indicator) from its baseline purple palette.
2. **Placeholder fonts.** The three design families were never bundled
   (the old theme said so), so everything rendered in system Roboto.
3. **Bottom bar with no icons.** `icon = {}` left an empty indicator pill
   above each label, which reads as broken.
4. **The main action was buried.** COMPRESS sat below 3 quality chips, 6
   size chips, a text field, 2 format chips and 2 switches. Quality and
   size-limit were both on screen at once although only one applies.
5. **No sense of the result.** No estimate before compressing, a thin bar
   during, and the result appeared underneath all the settings after.
6. **SAVED was all filters.** Four rows of chips filled the first screen.
7. **MORE opened onto SERVER ADDRESS / ACCESS TOKEN** with no word that
   Server Mode is optional, which is now the common case.

## What changed

- **Theme:** every Material 3 color role mapped to SVCS tokens; Bebas
  Neue, Space Mono and Outfit bundled under `res/font` (about 475 KB, all
  SIL OFL 1.1, license texts in `assets/licenses/`); type scale taken from
  `tokens/typography.css`; 2px corners from `tokens/spacing.css`.
- **Components** (`ui/components/`): panel with accent rule, mono section
  label, amber primary button with glow, outlined and danger buttons, pill
  chip, sharp segmented control, stat tile, switch row, status pill with a
  live blink, progress bar, tag. Plus a line-icon set drawn to the mockup's
  own SVG paths (24px grid, 1.6 stroke), instead of pulling in
  material-icons-extended.
- **COMPRESS**, one layout per state, animated between them:
  - Empty: one large PICK A VIDEO target, lifetime stats (videos, space
    saved), and a pick / choose / share hint.
  - Configure: the source with thumbnail, size, length, resolution and
    orientation; a QUALITY | SIZE LIMIT switch that shows only the relevant
    options (and remembers the last choice on each side); a plain-language
    description of each quality preset; an estimated result; format as a
    segmented control; options with icons; COMPRESS pinned to the bottom.
  - Running: big percent, stage (checking for activity / encoding),
    elapsed and time left, a red cancel, and a note that it keeps going in
    the background.
  - Done: the saving as a big number, original vs compressed bars, the
    Smart Compress outcome, SHARE as the main action, then Play and New
    video.
  - Failed: what happened and a way back.
- **The estimate is honest.** The first version said "about X" and warned
  "likely bigger" off the estimate. Tested, it said 10.6 MB for a file that
  came out at 6.7 MB, because encoders treat the bitrate as a ceiling (the
  Sep 22 field test landed 8 MB on a 10 MB target the same way). It now
  says "up to X" and "-N% or more", and the warning compares the preset's
  bitrate with the source's own average bitrate: "The original is only
  about 7.8 Mbps, and this preset allows 10.1 Mbps. It may barely shrink."
  Size limits read in decimal MB to match the preset names.
- **SAVED:** stats up top, search, filters folded behind a FILTERS toggle
  with an active count, a one-tap sort, rows with thumbnail and play
  overlay, the saving as a badge, and codec/preset/Smart Compress tags.
- **Bottom bar:** icons, amber active state, and labels only on the active
  tab once there are more than five tabs (eight when a server is paired).
- **MORE:** a short "Server Mode - optional" explainer, and an About panel
  with the version, license, source link and credits (Media3, LiteRT,
  YOLOv8n, the three fonts).
- **Screenshot build flag:** `-PsvcsAllowScreenshots=true` turns off
  FLAG_SECURE for UI review and store screenshots only. Default is off;
  verified that the release build's screenshot is still fully black.

Checks: 59 JVM tests, 58 pass (the one failure is the long-standing
Robolectric/AndroidKeyStore limit in `ServerSettingsViewModelTest`).
Minified release build runs on the emulator. Every text color passes WCAG
AA on every surface it's used on; the lowest is secondary text on panels
at 4.8:1.

## Still open (ranked)

1. **Too many tabs when paired.** Eight bottom-bar items is past Material's
   three-to-five guidance. Recommended: fold HOME, LIBRARY, LIVE, EVENTS
   and METRICS into one SERVER tab with its own top tabs, leaving COMPRESS,
   SAVED, SERVER, MORE.
2. **Compare original vs compressed** side by side (ExoPlayer is already a
   dependency). The most-cited feature in the category after size estimates.
3. **Batch queue:** pick several videos, one preset.
4. **Trim before compressing:** cutting length is the biggest size lever.
5. **Server Mode screens** (HOME, LIBRARY, LIVE, EVENTS, METRICS) got the
   new colors and fonts for free but still use their old layouts; move them
   onto the shared components.
6. **Material 3 Expressive** loading and progress indicators, once
   `compose-material3` 1.5 is stable.
7. **Store screenshots:** now possible with the screenshot flag; still to be
   taken on a real phone.

## Sources

- JoshAtticus/Compressor README and site: github.com/JoshAtticus/Compressor,
  compressor.joshattic.us
- JoshAtticus blog, 2026-08-28 benchmark post: blog.joshattic.us
- "Compress Video Size Compressor" Play listing and reviews:
  play.google.com/store/apps/details?id=com.video_converter.video_compressor
- Compose Material 3 release notes:
  developer.android.com/jetpack/androidx/releases/compose-material3
- SVCS design import: commit 4558c5e, `mobile/design/`
