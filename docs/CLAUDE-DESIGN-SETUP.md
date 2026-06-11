# Setting up the SVCS design system in Claude Design

Claude Design (claude.ai/design, Anthropic Labs research preview, included in your Max plan) extracts a reusable design system - colors, typography, components, layout patterns - from assets you give it, then every project you create uses that system automatically. This doc is the exact, field-by-field setup for SVCS, plus how to use it afterward for the desktop redesign and the future mobile app.

Why this is a good fit for us: the SVCS dashboard already has a strong, consistent identity (dark navy surveillance-terminal look, amber accent, three deliberate fonts), and it lives in code Claude Design can read. We feed it the real frontend, it extracts the system, and from then on every mockup, prototype, slide deck, or mobile concept comes out looking like SVCS.

---

## Part 1 - One-time setup (the "Set up your design system" form)

Open Claude Design, make sure the org picker (lower-left) shows the account you want (Bloodawn), and click **Set up design system**. Fill the form exactly like this:

### Field 1: "Company name and blurb"

Paste:

> SVCS (Selective Video Compression System): free, open-source, self-hosted AI-aware video compression for security-camera footage. Desktop app (Windows installer + browser dashboard) today, mobile app planned. Aesthetic: dark surveillance-terminal / command-center. Audience: CCTV operators, home-lab self-hosters, and consumers with security cameras (Ring/Reolink etc.).

### Field 2: "Link code on GitHub" - SKIP IT, use the folder attach instead

Do NOT link the whole repo. A documented Claude Design limitation: linking very large repositories causes lag and browser issues, and the docs recommend attaching a frontend-focused subfolder. Our repo is huge (venvs, dist/ builds, models, 52 sample videos). The GitHub link would drag all of that in.

### Field 3: "Link code from your computer" - attach the frontend subfolder

Drag in this folder (this is the entire frontend: all CSS variables, the tab system, every component, all 16 feature JS modules):

```
C:\Users\kheiven\Documents\GitHub\Video-compression_2026\src\gui
```

That contains `templates/index.html` (all the CSS tokens and component markup) and `static/js/` (the feature modules). It is exactly what Claude Design needs and nothing it does not.

### Field 4: "Upload a .fig file" - skip

We have no Figma file. The codebase is our source of truth.

### Field 5: "Add fonts, logos and assets" - add screenshots

Add 3-5 screenshots of the real running app (run `uv run python run_gui.py`, open localhost:5000, and capture): the HOME tab with the sidebar, the METRICS tab, the LIBRARY tab, the Setup overlay, and the Help overlay. The help docs say real examples beat specs - screenshots tell it how the system actually composes. If you have any SVCS logo asset, add it too.

### Field 6: "Any other notes" - paste the design tokens

Paste this (it is the extracted truth from `src/gui/templates/index.html`):

> Dark-first, surveillance command-center aesthetic. Backgrounds: #0a0e14 (bg), #10192a (surface), #162238 (raised surface); borders #2a4466 / #3a5a7a. Primary accent: amber #ffb900 (with a soft amber glow). Secondary accents, used to color-code sections/tabs: teal #1fd4c8, green #2dd6a0, yellow #ffc800, purple #b888ff, red #ff5555 for errors/stop. Text: #d8e8f5 body, #7a8fa8 dim, #f0f8ff bright. Typography: Bebas Neue for display headings (letter-spaced), Space Mono for data/labels/terminal text, Outfit for body. Labels are UPPERCASE with wide letter-spacing (0.1-0.2em). Corners are sharp: 2px radius, never rounded-pill. Subtle CRT scanline overlay on the background. Buttons and cards are flat with 1px borders, glow on the active accent. Status colors: amber = active/primary, green = good/online, red = error/offline. IMPORTANT: never use em-dashes or en-dashes in any text; ASCII hyphens only. Keep the terminal/monospace feel for data, but body copy should stay readable (Outfit).

Then click **Continue to generation** and let it build the UI kit.

---

## Part 2 - Validate the extracted system (15 minutes)

Per the official guide, test it with prompts in a throwaway project and check the output actually looks like SVCS:

1. "Design the SVCS dashboard home screen: live status cards (frames decoded, segments saved, speed, storage saved), a mode/preset selector, and a recent recordings table."
2. "Design a video library screen for SVCS: thumbnail grid of surveillance clips with search, filters, and a detail view with an inline player."
3. "Design a first-run setup screen where the user picks where compressed videos are saved (local folder, drive, OneDrive, Google Drive)."

Check: dark navy + amber (not generic blue/white), Bebas Neue headings, Space Mono data, 2px corners, uppercase labels. If it drifts, use the Remix/chat to correct ("backgrounds must be #0a0e14, accent #ffb900, no rounded corners") or add more screenshots and re-extract. Iterate until the test outputs pass.

Then flip the **Published** toggle so every new project uses the system.

---

## Part 3 - How we actually use it (the SVCS workflow)

### A. Desktop app redesign (highest value now)

The current dashboard is functional but engineer-built. Use Claude Design to redesign screen by screen, then hand the results to Claude Code to implement:

1. One project per screen (or one project with pages): Home, Upload, Library, Metrics, Search, Tools, Encrypt, Setup overlay, Help.
2. Prompt with the REAL feature list for that screen (copy the controls from the current app so nothing gets lost in the redesign). Iterate with inline comments and the adjustment knobs (spacing/color/layout).
3. When a screen is right: export/screenshot the final design plus any generated markup, drop them in `docs/design/` in the repo, and write a short FIXES round doc (like R1/R2) telling Claude Code "match this design for the X tab; keep all routes/IDs/handlers and the test suite green."
4. Claude Code implements against the existing blueprint/JS structure; the route guards and browser verification keep it honest.

### B. Mobile app concept (before any mobile code)

The roadmap defers mobile until the desktop is solid, but Claude Design lets us design it NOW for free: prompt for "SVCS mobile app: home (camera status + recent clips), library (thumbnail grid), clip detail with player and compress action, settings (save destination, presets)". A clickable prototype that looks like SVCS is exactly what we want in hand before deciding the Flutter work, and it is great for showing the team/sponsor.

### C. Slides and one-pagers (free bonus)

Claude Design also does slide decks and one-pagers in your design system. Capstone presentations, the download-page hero, README banner art - all come out on-brand with zero extra effort.

---

## Known quirks (from Anthropic's docs and early reviews)

- Inline comments occasionally disappear before Claude reads them - paste the comment text into the chat as backup.
- Compact layout mode can trigger save errors - switch to full view and retry.
- Large repos lag the browser - which is why we attach `src/gui` only, never the whole repo.
- It is a research preview: expect rough edges; keep the repo as the source of truth and treat Design output as specs for Claude Code, not direct code drops, until we have verified its generated markup quality.
