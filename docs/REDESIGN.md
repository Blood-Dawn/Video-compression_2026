# SVCS redesign checklist

Read this before touching any UI code on the `design/ui-redesign` branch. It collects what the skills on the Personal MCP skills server ask for, applied to the Windows dashboard (`src/gui/templates/index.html`, `src/gui/static/js/*.js`) and the Android app (`mobile/android/.../ui`). Tick an item only after checking it in a running build, not just in the source.

Source skills (ids on the server): `design/accessibility-review`, `everything-claude-code/accessibility`, `design/design-critique`, `design/design-handoff`, `design/design-system`, `everything-claude-code/design-system`, `everything-claude-code/frontend-design`, and the guides inside `modern-web-guidance/modern-web-guidance` (accessibility, platform-controls-dismiss-dialog, accessible-error-announcement, improve-text-layout-and-legibility).

Rules for working on this branch: never edit compression code, view models or navigation. No push or merge unless the user says so. Keep behavior and element ids unchanged so the script blocks and the tests keep working. Run the full test suite and the Android compile before each commit.

Status key: [x] done and checked, [ ] open, [~] partly done.

## 1. Design tokens (design-system, design-handoff)

- [x] Use tokens, never raw values: text-dim #95a9c0, control border #5d7da3, amber text #d99a00 (dashboard CSS variables, Android `Color.kt`).
- [~] Hunt hardcoded hex values and arbitrary px/rem sizes in templates and Compose files and move them to tokens. The dashboard still has hundreds of inline styles.
- [x] (documented in docs/DESIGN_SYSTEM.md, applied to new code only) Define a spacing scale (4, 8, 16, 24) and use it for new code. Define a type scale and name it.
- [x] (table in docs/DESIGN_SYSTEM.md) Keep the dashboard and Android token names in step. Note that `Color.kt` was hand edited after the original generation.
- [x] (docs/DESIGN_SYSTEM.md) Document each reusable component with variants, states (default, hover, active, disabled, loading, error, empty), sizes and accessibility notes. Start with button, input, tab, mode card, stat card, status pill, saved card.

## 2. Perceivable (accessibility-review, accessibility, modern-web-guidance)

- [x] Normal text contrast 4.5:1 or better. Large text and UI parts 3:1 or better. Measure, do not guess.
- [x] Input and button borders 3:1 or better against their background (non-text contrast).
- [~] (dashboard messages carry their meaning in words and are announced as live regions; Saved and Done follow the rule; not every inline style audited) Never show status with color alone. Add text or an icon (Saved 0% is grey plus a sentence, keep that rule everywhere, including error and success states in the dashboard).
- [x] Minimum text 12px on screen. Prefer rem or em for font sizes. Do not use justified text. Keep paragraph width under 80 characters.
- [x] Support 200% text zoom and 400% reflow without loss of content. Checked in the browser rig.
- [x] Support `prefers-reduced-motion` (stop spinners and transitions).
- [ ] Dashboard is dark only. If light mode is ever added, honor `prefers-color-scheme` and set `color-scheme`. Optional: reinforce borders under `prefers-contrast: more`.
- [x] Add `text-wrap: balance` to short headings and `text-wrap: pretty` to body paragraphs (progressive enhancement, no fallback needed).
- [x] Decorative icons hidden from assistive tech, meaningful icons labeled.

## 3. Operable (accessibility-review, accessibility)

- [x] Every control reachable by keyboard in a logical order. Checked first 12 tab stops on the dashboard.
- [x] Visible focus ring on every control: 3px amber, 2px offset, never `outline: none` without a replacement.
- [~] Touch targets: 44px minimum on the dashboard (WCAG 2.2 minimum is 24px), 48dp on Android. One inline link and the "Change..." button are still smaller.
- [~] Dialogs (done with inert, Escape and focus return in dialogs.js; native `<dialog>` not adopted, the overlays stay divs): use the native `<dialog>` element opened with `showModal()` where possible. It makes the page behind inert, closes with Escape, and needs no focus trap. For overlays that stay as divs, set `inert` on the content behind and add Escape handling. Return focus to the trigger on close. Applies to help, decrypt, setup, browse, plate and the DONE modal.
- [x] Skip link target (`<main id="main">`) needs `tabindex="-1"` so focus lands there.
- [x] No positive tabindex values. Do not hide focusable elements with `aria-hidden`.
- [x] Custom keyboard widgets: Enter on keydown, Space on keyup, `aria-expanded` or `aria-pressed` for toggles.
- [x] Mode picker (now a full radio group with arrow keys) and tab bar: if they use role tab or radio semantics, they must also behave that way with the keyboard (arrow keys). Today the tab bar has plain buttons, which is acceptable, but do not add role="tab" without the full pattern.

## 4. Understandable (accessibility-review, accessible-error-announcement)

- [~] Every input has an accessible name. Prefer a visible `<label for>`. Placeholder and title are not names. The current aria-labels derived from ids and placeholders are a stopgap: replace them with real labels.
- [ ] Hints go in `aria-describedby`, above the field. Do not pack errors into the label.
- [x] Validation (validation.js): style with `:user-invalid`, set `aria-invalid` and `aria-errormessage` when the user has interacted, never on first focus.
- [ ] Error messages say what went wrong and how to fix it.
- [ ] No context changes on focus alone. Consistent navigation order across tabs.
- [ ] Do not ask for the same data twice (redundant entry).
- [ ] Plain wording: one sentence reasons for odd states ("Encoder fallback" is explained on Saved).

## 5. Robust (accessibility, modern-web-guidance)

- [x] One h1 per page, headings in order, landmarks: header, nav, main, aside. Do not over label sections.
- [~] Live regions: one polite region for status and one assertive for critical failures. Status pill is polite, error banner is an alert. Do not announce "Loading" noise. Coordinate announcements with dialogs.
- [x] Do not repeat state in the name (no "pressed" in a name that already has `aria-pressed`). Do not repeat the role in the label.
- [ ] Same accessible name only for links that share a destination. Disambiguate repeated "Edit", "Delete" buttons with hidden text.
- [x] `lang` on html, unique `title`, iframe titles.
- [~] Android (all screens now have headings, selected states, 48dp targets and spoken progress and result values; Pick, Configure, Progress, Done, Failed, Saved and More checked on the emulator with a real on-device compression, and Done and More at 1.6x font scale; server Library and Events screens changed but not seen on a device; nothing checked with TalkBack): `contentDescription` on icon-only buttons, `Role.Button` on clickable surfaces, `stateDescription` or selected state on chips and toggles, live region for progress, touch targets 48dp, text in sp so it scales. Audit every screen: Compress, Configure, Progress, Done, Failed, Saved, More.

## 6. Layout and hierarchy (design-critique, frontend-design)

- [x] Three step layout with Start always visible (sticky bar).
- [x] Single column below 720px with no sideways overflow.
- [ ] One clear primary action per screen, in amber. Secondary actions outlined, destructive actions in red outline with a confirmation.
- [x] First run: one thing at a time. The consent banner now waits for the setup dialog. Keep it that way.
- [ ] Reading order matches the visual order. Whitespace groups related controls.
- [ ] Keep the identity: dark terminal look, amber accent, Bebas Neue, Space Mono, Outfit. Add no gradients, glass effects or decoration that serve no purpose (design-system slop check).
- [ ] Motion only where it explains something. No scroll effects.
- [ ] Handle empty, loading, error and long text states (truncate with ellipsis, wrap tags) on every list and card.
- [~] Responsive check (dashboard done at 1440, 1024, 768 and 390; Android checked on the emulator at about 393dp wide and at 1.6x font, 360dp and 411dp not done). Original item: 1440, 1024, 768 and 390 widths, and Android at 360dp and 411dp wide plus large font scale.

## 7. Verification before every commit

- [x] Automated scan (axe-core 4.10.2 on the rendered page: only the disabled Start contrast flag remains) (script of text under 12px, small targets, unlabeled inputs, h1 count, outline none count). Record before and after numbers. Last run: 2 small text, 2 small targets, 3 hidden inputs, 1 h1.
- [ ] Keyboard only pass: Tab, Shift+Tab, Enter, Space, Escape on every dialog. Focus never gets stuck.
- [ ] Screen reader pass (NVDA with Firefox or Chrome on Windows, TalkBack on Android). Not done yet.
- [x] Zoom to 200% and check the layout.
- [~] Full Python test suite passes (2138 passed, 45 skipped on the last run). Android `compileDebugKotlin` passes. Run the debug build on the emulator (package `org.svcs.mobile.debug`, not `org.svcs.mobile`) and look at every changed screen.
- [ ] Commit message lists what changed and what is not verified. Report honestly.

## Open items and known issues

- Fixed: Start button now stays locked until Setup is complete and while running (ui.js and setup.js).
- Not done: real NVDA and TalkBack pass, token parity document, component docs, color-only status audit on error states, 360dp width check on Android, server Library and Events on a device.

## 8. Redesign of the other dashboard tabs

Design boards: the "SVCS App Redesign" artifact, group "Other dashboard tabs" (Upload, Library, Library one video, Auto compress, Metrics, Search, Tools, Encrypt, Other tabs phone width, Other tabs handoff). Home is already implemented (section 6). Everything here follows the same rules as before: keep every element id, keep the script blocks working, do not touch compression code, view models or navigation, run the full tests and screenshot before each commit.

Research behind the boards (checked 2026-11): Primer and accessible-data-interfaces for table rules, Cieden, Shopify and Eleken for settings pages and toggle rows, Tella, Sanity and UI/UX Atlas for video library behavior, plus the design-critique, accessibility-review, design-system and dataviz skills. Rules that came out of it are in 8.9.

### 8.1 Page frame (all tabs)

- Each tab opens with an h2 title in Bebas Neue and one sentence of purpose in dim text, then content at a maximum width of 1280px. The Home tab already uses `.side-title`; reuse it.
- Cards use `--surface`, 1px `--border`, 4px radius, 20px padding. Do not add gradients, glass or decoration.
- Primary action is one amber button per card. Secondary actions are outlined, destructive actions are outlined in red.

### 8.2 Upload

Change: three states in one place (waiting, uploading with a real progress bar, finished with "Compress this video" and "Open in Library"). Keep ids: `upload-zone`, `upload-input`, `upload-status`, `video-list`. Needs new code: a visible Cancel upload button and the finished card; the percent and byte counts come from the existing status text, so wire them only if the status already exposes them.

### 8.3 Library (grid and one video)

Change: Folder field with Browse and Load; an All, Originals, Compressed segmented control; a sort menu; a grid and list toggle; active filter chips with Clear filters; cards at one uniform 16:9 size with middle truncated names, a Compressed or Original badge and "Saved n%" in words (never color alone). The detail view becomes a two column page: player on the left, a plain facts table and four actions on the right. Keep ids: `library-folder`, `library-browse-btn`, `library-search`, `library-sort`, `library-view-grid`, `library-view-list`, `library-kind-*`, `library-grid`, `library-empty`, `library-detail`, `library-player`, `library-detail-name`, `library-detail-meta`, `library-count`, `library-status`, `library-stats-strip`.
Needs new code: multi select with a selection bar (Encrypt, Compress again, Delete), the "Last 7 days" style filter chips, a third sort direction, remembering sort and view in `localStorage`. Empty states per cause: no videos yet, filter matches nothing, load error with retry. Selection bar replaces the filter row instead of pushing content down, Escape clears it.

### 8.4 Auto compress

Change: one status card ("Auto compress is off" with a single Turn on button), a "What to watch" card, a "Keep disk space under control" card with a disk bar and plain numbers, destructive purge in red outline. Keep ids: `ac-state-badge`, `ac-folder`, `ac-browse-btn`, `ac-mode`, `ac-profile`, `ac-delete-original`, `ac-delete-warn`, `ac-toggle-btn`, `ac-scan-btn`, `ac-status-line`, `ac-recent`, `retention-panel`, `ret-enabled`, `ret-max-age`, `ret-max-gb`, `ret-estimate`, `ret-purge-btn`, `ac-log`. Keep the existing `confirm()` before the purge and make its text say how many files and how much space. The disk bar and "6 clips would be removed" line should come from `ret-estimate`; only show numbers that API really returns. The delete original switch keeps its red warning.

### 8.5 Metrics

Change: four stat tiles, two single series charts (space saved per day in amber, average size reduction by mode in teal) each with a View as table link, and a segment table. The table shows Time, Camera, Mode, Object, Length, Size, Smaller, Quality and three named icon actions (Play, Encrypt, Delete); Color, Scene, Light, Motion, Cars and People move behind a Columns menu. Keep ids: `metrics-table`, `segments-tbody`, `met-filter-cam`, `met-filter-type`, `met-filter-enc`, `metrics-detail`, `metrics-video`, `metrics-meta-grid`, `metrics-enc-btn`, `metrics-timelapse-btn`, `metrics-history-chart`, `mlib-segments`, `mlib-size`, `mlib-saved`, `mlib-avg-dur`, `mlib-enc`, `mode-cpu-card` and its children.
Notes: the existing split view (table plus a detail pane with the video) stays; on desktop open the detail as a slide over panel from the right. The mode CPU card is not drawn on the board, keep it under the charts. The saved per day chart needs a data source: reuse `metrics-history-chart` data if it is per day, otherwise group `segments` by date in `metrics.js`. Chart colors: amber and teal only, one series per chart, labels on the bars, `role="img"` with a text summary, and a table version behind the link. The dataviz validator flags the lightness band for these bright accents on the dark surface; this is accepted because every mark is directly labeled and each chart has only one series.

### 8.6 Search

Change: a plain English box first ("Describe what you are looking for", example chips), filters in a disclosure with an "n active" count, the same table style as Metrics, result chips that remove one filter each, and a Results, Busiest clips, Daily summary segmented control. Keep ids: `nl-search-q`, `nl-search-explain`, `arc-object-type`, `arc-color`, `arc-scene`, `arc-tod`, `arc-camera-id`, `arc-date-from`, `arc-date-to`, `arc-min-rois`, `arc-enc-only`, `arc-pose-only`, `arc-searching`, `archive-result-count`, `archive-results-table`, `archive-tbody`, `archive-status`, `search-preview-*`. The count text keeps `aria-live="polite"`. Needs new code: removable chips built from the active filters, the example chips.

### 8.7 Tools

Change: a sticky section list on the left and one card per tool with a heading and one sentence: App updates, Phone alerts, Webhook, Recent events, Zone editor, Paired devices; a Danger zone card last. Toggles show On or Off as text, secrets are masked with a Show button and the saved value is never printed back, Send test shows its result inline as an icon plus text and is announced with `role="status"`. Keep every id in `update-panel`, `push-panel`, `webhook-panel`, `events-panel`, `zone-editor-panel`, `devices-panel` (see the ids listed in the template). Revoke buttons get a name that includes the device and a red outline (done in the redesign branch for the buttons that exist). Needs new code: the Show button on `push-token` and `webhook-secret`, and moving Revoke all into the Danger zone card. On phone width the sections become collapsible cards (see the phone board).

### 8.8 Encrypt

Change: Encrypt and Decrypt side by side, method as a segmented choice (Password or Key file), a password strength note on the encrypt side, a "Need a key file?" card, and a red "no password recovery" notice. Keep ids: `enc-src-path`, `enc-password-group`, `enc-password`, `enc-keyfile-group`, `enc-keyfile-path`, `enc-encrypt-status`, `dec-src-path`, `dec-password-group`, `dec-password`, `dec-keyfile-group`, `dec-keyfile-path`, `enc-decrypt-status`, `enc-keygen-name`, `enc-keygen-result`. Needs new code: Show button on both password fields and the strength note (length based only, do not claim cryptographic strength).

### 8.9 Rules that apply to every tab

- Tables: header cells use `scope="col"`; sort buttons sit inside the header and set `aria-sort`; each row action says which row it acts on ("Delete gate clip at 08:14", not "Delete"); an action column header exists but is visually hidden; wide tables scroll inside a focusable region with an accessible name; do not collapse rows into cards on phones.
- Toggles: static action first label, visible On or Off, `role="switch"`, 44px target. Use a checkbox and a Save button when a change needs review.
- Autosave only for instant toggles. Text fields and secrets use an explicit Save.
- Destructive actions: red outline, in their own group at the bottom, a confirmation that states the consequence, never color alone.
- Charts: one series each, a title that names it, a table view link, direct value labels, a text alternative.
- Empty, loading and error states are written for every list and card, one message per cause.
- Phone width: the section tabs become a bottom bar (Home, Library, Search, Tools, More); Upload, Auto compress, Metrics and Encrypt sit under More. Targets 44px.

### 8.10 Implementation order and status

Status key as above. Nothing in this section is implemented yet.

- [ ] 1. Page frame and shared classes (title, card, segmented control, switch, chips, table) added once to the template CSS.
- [ ] 2. Tools (largest and most self contained).
- [ ] 3. Library and detail.
- [ ] 4. Metrics (needs the per day data decision).
- [ ] 5. Search.
- [ ] 6. Auto compress.
- [ ] 7. Encrypt.
- [ ] 8. Upload.
- [ ] 9. Phone width pass for all of the above.
- [ ] 10. Per tab: axe scan in light and dark, keyboard pass, full tests, screenshots.

### 8.11 Open questions for the team

- Library multi select and bulk delete: confirm the delete path deletes files on disk or only list entries.
- Upload progress: does the server expose bytes and percent while uploading?
- Disk bar numbers: confirm `ret-estimate` returns used, cap and count.
- Searching: confirm "Last 7 days" style chips are wanted or if the date fields are enough.
- Not verified: none of this has been seen by a screen reader user, and the boards use sample data.
