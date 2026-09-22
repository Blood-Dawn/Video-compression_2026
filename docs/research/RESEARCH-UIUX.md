# RESEARCH: better UI/UX designs (R4 Phase 1)

Date: 2026-07-04. Method: deep-research workflow (5 search angles, 24 sources fetched,
117 claims extracted, top 25 adversarially verified with 3 votes each: 24 confirmed,
1 refuted). This document is the review record: each verified finding, the decision
(ADOPT / DEFER / SKIP), and where it lands in the codebase.

## Verified findings and decisions

### 1. Progress indicators must be determinate for waits >= 10s (NN/g) - ADOPT
Any action over ~1s needs an indicator; spinners are acceptable only for 2-10s waits;
anything >= 10s requires percent-done or time-remaining, and batch work should show
"file N of M" with the current item highlighted.
Sources: nngroup.com/articles/progress-indicators, /designing-for-waits-and-interruptions (3-0 x5).
- Already good: file-input runs show percent + ETA + fps (`status.js` `_friendlyStatus`).
- Gap: AUTO-COMPRESS batch runs do not surface "file N of M" batch progress in the UI.
- Action: expose batch position from the autocompress runner status and render it.

### 2. Background jobs + persistent job history (NN/g) - ADOPT
Long processes should run in the background without blocking the rest of the app
(SVCS already does this: tabs stay usable while compressing), AND the app should keep
a persistent, visible record of jobs so operators can resume/audit after interruptions.
Sources: NN/g waits + complex-application-design (3-0 x2).
- Gap: no job history. Progress is transient; once a run ends the evidence is gone
  (segments live in the DB but there is no per-run record).
- Action: record every finished run (manual pipeline + auto-compress) to a persistent
  job log; render a "Recent jobs" panel.

### 3. Explicit completion summary, not an auto-fading toast (NN/g) - ADOPT
After a long wait the user has disengaged; completion must be a user-dismissed summary
(start time, stop time, elapsed, what happened: files/segments, skipped, failed, space
saved), not a 4s toast. Source: NN/g waits (3-0).
- Gap: segment saves fire auto-dismiss toasts (`demo.js` `pushNotif`); run completion
  has no summary surface at all.
- Action: completion summary modal on pipeline finish and auto-compress batch finish,
  dismissed only by the user.

### 4. Goal-oriented navigation (Frigate 0.14 rebuild) - DEFER
Frigate rebuilt its UI around operator questions (what is happening now / what happened
overnight / was anything missed) instead of backend features. SVCS tabs are
feature-oriented. Source: frigate discussion #11136 (3-0 x2).
- Decision: DEFER. A tab reorg churns the whole test surface mid-R4; Phase 4 (two-exe
  split) will change the shell anyway. Reconsider after Phase 4 with: HOME = "now",
  AUTO-COMPRESS = "overnight", LIBRARY = "find a clip".

### 5. Frigate review mechanics (hover previews, reviewed-state, alerts vs detections) - DEFER
Scrollable thumbnail grid synced to a timeline, hover/swipe inline preview, watched
segments marked reviewed, two-tier alerts/detections triage. Sources: frigate #11136 +
docs (3-0 x2). NOTE: the claim that previewing implicitly marks reviewed was REFUTED 0-3.
- Decision: DEFER to Phase 3 (competitor gap analysis will price this against other
  missing features). The Library already has lazy thumbs, filters, kind segmentation.

### 6. Deliberately low-res preview assets (Frigate) - PARTIAL / already aligned
Library thumbnails are already lazy static thumbs; full video loads only on click
(detail modal). Animated low-fps preview clips are a Phase 3 candidate, not now.

### 7. Milestone XProtect two-track color-coded timeline - DEFER
Only relevant if/when SVCS builds a timeline review view. Recorded for Phase 3.

### 8. Pico CSS as a no-build styling layer - SKIP
Verified fit for Flask + vanilla JS in general, but SVCS already has a bespoke token
system (`:root` in index.html: surfaces, amber accent, status colors) and 2600 lines of
working CSS. Swapping base stylesheets mid-project is regression risk with no user-visible
payoff. Caveat from research: Pico's "accessible" label is self-description, and no
comparative htmx/Alpine/Web-Components claims survived verification anyway.

### 9. Empty states: say why it is empty + contextual help + direct CTA (NN/g) - ADOPT
Three guidelines, 3-0 x3, corroborated by IBM Carbon/Atlassian/GitLab systems: state
what would appear and why it is empty; use the space as contextual help; include the
CTA that populates the area. Qualification: never show "no records" while still loading.
- Gap: Library, segments table, upload list, and AUTO-COMPRESS show blank or terse
  placeholders; Library can flash empty text during fetch.
- Action: real empty states with CTAs; loading state distinct from empty state.

### 10. First-run wizard with navigable sequence map (NN/g) - DEFER
Current setup is a single-step destination chooser, so a sequence map does not apply
yet. Phase 4's split builds will rework first-run; apply then if it grows steps.

### 11. Staged disclosure of advanced options (NN/g) - PARTIAL / already aligned
The sidebar already gates advanced settings behind an ADVANCED toggle. No action beyond
keeping disclosure ~2 levels deep.

### 12. Dark theme: dark-gray surfaces, light-gray text, avoid halation (Material) - ADOPT (light touch)
Dark gray over pure black; small pure-white text halates (Material: white at 87% for
high-emphasis). SVCS's `--bg` #0a0e14 is near-black but brand-set; text tokens are
already blue-grays, not pure white. Sources: design.google (3-0 x2).
- Action: keep the palette; fix the a11y debt the frontend audit found instead:
  visible `:focus-visible` rings (WCAG 3:1 for UI components), consistent disabled
  states, no small pure-white text.

## Cross-cutting debt adopted alongside (from the frontend inventory)
- One shared modal component (help/library-browse/plates modals each reimplement
  overlay CSS); the new completion modal uses it.
- Notification cards built from innerHTML strings; keep, but route all new surfaces
  through the shared modal/notif helpers.
- No loading feedback during async fetches (ties into finding 9).

## Implementation plan (this phase)
1. `ui.js` + index.html: shared modal component (`svcsModal.show/hide`), focus-visible
   rings, empty-state + skeleton CSS.
2. Backend: persistent job history (app-data JSON log via a small service), recorded on
   pipeline finish and per auto-compress batch; `/api/jobs/recent` endpoint; autocompress
   status exposes batch `current_index`/`total`/`current_file`.
3. Frontend: "file N of M" in AUTO-COMPRESS, Recent-jobs panel on HOME, completion
   summary modal (manual runs + auto-compress batches), empty states for Library /
   segments / upload / AUTO-COMPRESS.
4. Tests for the new endpoint + runner status fields; suite green; browser-verified.

## Research caveats (verbatim concerns kept honest)
- No claims about Blue Iris, Ubiquiti Protect, Verkada, Rhombus, or Eagle Eye survived
  verification; the VMS pattern set is Frigate + Milestone only. Phase 3 revisits this.
- No comparative htmx/Alpine/Web-Components tradeoffs survived; irrelevant since we
  stay vanilla.
- No numeric-WCAG claims survived; the 4.5:1 / 3:1 thresholds cited above are the
  standard's own values, applied during implementation, not research conclusions.
- NN/g thresholds derive from 2014 articles rooted in older perception research
  (stable but old). Impact/effort ranks are the synthesizer's judgment.
