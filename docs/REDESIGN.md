# SVCS redesign checklist

Read this before touching any UI code on the `design/ui-redesign` branch. It collects what the skills on the Personal MCP skills server ask for, applied to the Windows dashboard (`src/gui/templates/index.html`, `src/gui/static/js/*.js`) and the Android app (`mobile/android/.../ui`). Tick an item only after checking it in a running build, not just in the source.

Source skills (ids on the server): `design/accessibility-review`, `everything-claude-code/accessibility`, `design/design-critique`, `design/design-handoff`, `design/design-system`, `everything-claude-code/design-system`, `everything-claude-code/frontend-design`, and the guides inside `modern-web-guidance/modern-web-guidance` (accessibility, platform-controls-dismiss-dialog, accessible-error-announcement, improve-text-layout-and-legibility).

Rules for working on this branch: never edit compression code, view models or navigation. No push or merge unless the user says so. Keep behavior and element ids unchanged so the script blocks and the tests keep working. Run the full test suite and the Android compile before each commit.

Status key: [x] done and checked, [ ] open, [~] partly done.

## 1. Design tokens (design-system, design-handoff)

- [x] Use tokens, never raw values: text-dim #95a9c0, control border #5d7da3, amber text #d99a00 (dashboard CSS variables, Android `Color.kt`).
- [~] Hunt hardcoded hex values and arbitrary px/rem sizes in templates and Compose files and move them to tokens. The dashboard still has hundreds of inline styles.
- [ ] Define a spacing scale (4, 8, 16, 24) and use it for new code. Define a type scale and name it.
- [ ] Keep the dashboard and Android token names in step. Note that `Color.kt` was hand edited after the original generation.
- [ ] Document each reusable component with variants, states (default, hover, active, disabled, loading, error, empty), sizes and accessibility notes. Start with button, input, tab, mode card, stat card, status pill, saved card.

## 2. Perceivable (accessibility-review, accessibility, modern-web-guidance)

- [x] Normal text contrast 4.5:1 or better. Large text and UI parts 3:1 or better. Measure, do not guess.
- [x] Input and button borders 3:1 or better against their background (non-text contrast).
- [ ] Never show status with color alone. Add text or an icon (Saved 0% is grey plus a sentence, keep that rule everywhere, including error and success states in the dashboard).
- [x] Minimum text 12px on screen. Prefer rem or em for font sizes. Do not use justified text. Keep paragraph width under 80 characters.
- [ ] Support 200% text zoom and 400% reflow without loss of content. Not tested yet.
- [ ] Support `prefers-reduced-motion` (stop spinners and transitions). Not checked.
- [ ] Dashboard is dark only. If light mode is ever added, honor `prefers-color-scheme` and set `color-scheme`. Optional: reinforce borders under `prefers-contrast: more`.
- [ ] Add `text-wrap: balance` to short headings and `text-wrap: pretty` to body paragraphs (progressive enhancement, no fallback needed).
- [x] Decorative icons hidden from assistive tech, meaningful icons labeled.

## 3. Operable (accessibility-review, accessibility)

- [x] Every control reachable by keyboard in a logical order. Checked first 12 tab stops on the dashboard.
- [x] Visible focus ring on every control: 3px amber, 2px offset, never `outline: none` without a replacement.
- [~] Touch targets: 44px minimum on the dashboard (WCAG 2.2 minimum is 24px), 48dp on Android. One inline link and the "Change..." button are still smaller.
- [~] Dialogs: done with `static/js/dialogs.js` (page behind goes inert, focus moves in, Escape clicks the close button, focus returns to the opener; setup dialog excluded from Escape). Still open: moving to the native `<dialog>` element opened with `showModal()` where possible. It makes the page behind inert, closes with Escape, and needs no focus trap. For overlays that stay as divs, set `inert` on the content behind and add Escape handling. Return focus to the trigger on close. Applies to help, decrypt, setup, browse, plate and the DONE modal.
- [x] Skip link target (`<main id="main" tabindex="-1">`) so focus lands there.
- [ ] No positive tabindex values. Do not hide focusable elements with `aria-hidden`.
- [ ] Custom keyboard widgets: Enter on keydown, Space on keyup, `aria-expanded` or `aria-pressed` for toggles.
- [ ] Mode picker and tab bar: if they use role tab or radio semantics, they must also behave that way with the keyboard (arrow keys). Today the tab bar has plain buttons, which is acceptable, but do not add role="tab" without the full pattern.

## 4. Understandable (accessibility-review, accessible-error-announcement)

- [~] Every input has an accessible name. Prefer a visible `<label for>`. Placeholder and title are not names. The current aria-labels derived from ids and placeholders are a stopgap: replace them with real labels.
- [ ] Hints go in `aria-describedby`, above the field. Do not pack errors into the label.
- [ ] Validation: style with `:user-invalid`, set `aria-invalid` and `aria-errormessage` when the user has interacted, never on first focus.
- [ ] Error messages say what went wrong and how to fix it.
- [ ] No context changes on focus alone. Consistent navigation order across tabs.
- [ ] Do not ask for the same data twice (redundant entry).
- [ ] Plain wording: one sentence reasons for odd states ("Encoder fallback" is explained on Saved).

## 5. Robust (accessibility, modern-web-guidance)

- [x] One h1 per page, headings in order, landmarks: header, nav, main, aside. Do not over label sections.
- [~] Live regions: one polite region for status and one assertive for critical failures. Status pill is polite, error banner is an alert. Do not announce "Loading" noise. Coordinate announcements with dialogs.
- [ ] Do not repeat state in the name (no "pressed" in a name that already has `aria-pressed`). Do not repeat the role in the label.
- [ ] Same accessible name only for links that share a destination. Disambiguate repeated "Edit", "Delete" buttons with hidden text.
- [ ] `lang` on html, unique `title`, iframe titles.
- [~] Android: done so far: roles and click labels on the Saved play thumbnail, the Compress Change button and the shared panel and action components, 48dp targets there. Still to audit: `contentDescription` on icon-only buttons, `Role.Button` on clickable surfaces, `stateDescription` or selected state on chips and toggles, live region for progress, touch targets 48dp, text in sp so it scales. Audit every screen: Compress, Configure, Progress, Done, Failed, Saved, More.

## 6. Layout and hierarchy (design-critique, frontend-design)

- [x] Three step layout with Start always visible (sticky bar).
- [x] Single column below 720px with no sideways overflow.
- [ ] One clear primary action per screen, in amber. Secondary actions outlined, destructive actions in red outline with a confirmation.
- [ ] First run: one thing at a time. The consent banner now waits for the setup dialog. Keep it that way.
- [ ] Reading order matches the visual order. Whitespace groups related controls.
- [ ] Keep the identity: dark terminal look, amber accent, Bebas Neue, Space Mono, Outfit. Add no gradients, glass effects or decoration that serve no purpose (design-system slop check).
- [ ] Motion only where it explains something. No scroll effects.
- [ ] Handle empty, loading, error and long text states (truncate with ellipsis, wrap tags) on every list and card.
- [ ] Responsive check at 1440, 1024, 768 and 390 widths, and Android at 360dp and 411dp wide plus large font scale.

## 7. Verification before every commit

- [ ] Automated scan (script of text under 12px, small targets, unlabeled inputs, h1 count, outline none count). Record before and after numbers. Last run: 2 small text, 2 small targets, 3 hidden inputs, 1 h1.
- [ ] Keyboard only pass: Tab, Shift+Tab, Enter, Space, Escape on every dialog. Focus never gets stuck.
- [ ] Screen reader pass (NVDA with Firefox or Chrome on Windows, TalkBack on Android). Not done yet.
- [ ] Zoom to 200% and check the layout.
- [ ] Full Python test suite passes. Android `compileDebugKotlin` passes. Run the debug build on the emulator (package `org.svcs.mobile.debug`, not `org.svcs.mobile`) and look at every changed screen.
- [ ] Commit message lists what changed and what is not verified. Report honestly.
