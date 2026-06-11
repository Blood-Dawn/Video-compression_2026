# B1 form kit - Claude Design setup for SVCS

Paste-ready content for the "Set up your design system" form at claude.ai/design.
Sources: docs/CLAUDE-DESIGN-SETUP.md (field-by-field rationale) and docs/HANDOFF-FABLE.md Part B.
Screenshots captured 2026-06-11 from the running 2.1.0.dev0 app (branch app), 1920x1024 PNG.

Before filling the form: confirm the org picker (lower-left) shows the Bloodawn account.

---

## Field 1 - Company name and blurb

Name: SVCS

Paste:

SVCS (Selective Video Compression System): free, open-source, self-hosted AI-aware video compression for security-camera footage. Desktop app (Windows installer + browser dashboard) today, mobile app planned. Aesthetic: dark surveillance-terminal / command-center. Audience: CCTV operators, home-lab self-hosters, and consumers with security cameras (Ring/Reolink etc.).

## Field 2 - Link code on GitHub

SKIP. Large repos lag the browser (documented limitation). Ours is huge (venvs, dist builds, models, 52 sample clips). Use Field 3 instead.

## Field 3 - Link code from your computer

Attach ONLY this folder (the entire frontend, nothing extraneous):

```
C:\Users\kheiven\Documents\GitHub\Video-compression_2026\src\gui
```

It contains templates/index.html (all CSS tokens + tab markup) and static/js/ (all 16 feature modules).

## Field 4 - Upload a .fig file

SKIP. No Figma file; the codebase is the source of truth.

## Field 5 - Add fonts, logos and assets

Add these 5 screenshots of the real running app:

```
docs\design\screenshots\desktop-home.png
docs\design\screenshots\desktop-metrics.png
docs\design\screenshots\desktop-library.png
docs\design\screenshots\desktop-setup-overlay.png
docs\design\screenshots\desktop-help-overlay.png
```

(Full path prefix: C:\Users\kheiven\Documents\GitHub\Video-compression_2026\)
Add an SVCS logo asset too if one exists.

## Field 6 - Any other notes

Paste:

Dark-first, surveillance command-center aesthetic. Backgrounds: #0a0e14 (bg), #10192a (surface), #162238 (raised surface); borders #2a4466 / #3a5a7a. Primary accent: amber #ffb900 (with a soft amber glow). Secondary accents, used to color-code sections/tabs: teal #1fd4c8, green #2dd6a0, yellow #ffc800, purple #b888ff, red #ff5555 for errors/stop. Text: #d8e8f5 body, #7a8fa8 dim, #f0f8ff bright. Typography: Bebas Neue for display headings (letter-spaced), Space Mono for data/labels/terminal text, Outfit for body. Labels are UPPERCASE with wide letter-spacing (0.1-0.2em). Corners are sharp: 2px radius, never rounded-pill. Subtle CRT scanline overlay on the background. Buttons and cards are flat with 1px borders, glow on the active accent. Status colors: amber = active/primary, green = good/online, red = error/offline. IMPORTANT: never use em-dashes or en-dashes in any text; ASCII hyphens only. Keep the terminal/monospace feel for data, but body copy should stay readable (Outfit).

Then click Continue to generation.

---

## After generation - B2 validation (15 minutes)

Run these in a throwaway project and check the output looks like SVCS (dark navy + amber, Bebas/Space Mono/Outfit, 2px corners, uppercase labels), not generic blue/white:

1. Design the SVCS dashboard home screen: live status cards (frames decoded, segments saved, speed, storage saved), a mode/preset selector, and a recent recordings table.
2. Design a video library screen for SVCS: thumbnail grid of surveillance clips with search, filters, and a detail view with an inline player.
3. Design a first-run setup screen where the user picks where compressed videos are saved (local folder, drive, OneDrive, Google Drive).

If it drifts, correct via Remix/chat ("backgrounds must be #0a0e14, accent #ffb900, no rounded corners, Bebas Neue headings") or add more screenshots and re-extract.

When happy, flip the Published toggle so all new projects use the system.

## Known quirks (research preview)

- Inline comments can vanish before Claude reads them: paste the comment text into chat as backup.
- Compact layout mode can trigger save errors: use full view.
- Keep the repo as the source of truth; Design output is a spec for Claude Code until verified on one screen.
