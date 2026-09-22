# SVCS Project Plan

This is the canonical planning document for SVCS. It combines the GUI refactor
plan, the R6 desktop and mobile upgrade plan, the desktop zones and events plan,
and the owner-gated delivery work. Dated source plans remain in this folder as
historical records; this file is the place to update the current order and
status.

## 1. Planning rules

- Work one reviewable task at a time and keep the test suite green after each task.
- Keep route-guard and blueprint-count changes in the same change as new routes.
- Browser-verify desktop UI work and physically verify mobile work.
- Do not weaken security, delete tests, or treat owner gates as implementation work.
- Avoid em dashes and en dashes in code, UI text, and documentation.
- Keep release publishing, signing certificates, credentials, and hardware checks owner-only.

## 2. Current milestone audit

The R6 audit records the following as complete: desktop productization through
M5b, security findings SEC-001 through SEC-016, R5 tasks 5.1 through 5.4,
5.6 core, 5.7 core, and 5.8, plus mobile M0 through M5 first slice and R8
minification. The source audit also lists the following as open or requiring
follow-up:

- R5 5.5 semantic search.
- Zone and line drawing interfaces for phone and desktop.
- Desktop behavior-event toasts and outbound event notifications.
- Chunked resumable upload for server and phone.
- Closed-app push completion and native UnifiedPush evaluation.
- macOS signed DMG, the Rust core spike, and a public non-beta release.
- Optional adaptive per-segment bitrate.

These statuses originate from the August 2026 plan and must be checked against
code and tests before a release is declared complete.

## 3. Active work tracks

### Track A: zones and events

The server APIs already provide per-camera zones, crossing lines, loiter zones,
and recent events. The intended delivery order is:

1. **Events visibility.** Add an EVENTS panel to the desktop TOOLS tab and an
   EVENTS view on the phone using `/api/events/recent`, with newest-first rows,
   refresh while visible, and an honest empty state.
2. **Desktop zone editor.** Add a real thumbnail backdrop, an HTML canvas, and
   drawing tools for exclude rectangles, crossing lines, and loiter zones. Save
   normalized coordinates through `/api/zones`; add the guarded frame route only
   if the existing thumbnail path cannot supply the backdrop.
3. **Desktop event toasts.** Consume existing SSE lines beginning with `EVENT`
   and route them through the shared notification component. This needs no new
   route.
4. **Outbound event delivery.** Add an opt-in webhook only after the SSRF rules,
   timeout, redirect, credential, and private-network cases have dedicated
   tests. Delivery must run off the pipeline thread.

Acceptance: draw a zone and line over a real camera thumbnail, run a known
highway clip, observe the event toast and event rows, and confirm shared state
is visible to the phone. Keep browser screenshots with the round notes.

### Track B: resumable ingest

Add a server chunk endpoint carrying an offset and per-chunk SHA-256, append to
a temporary file, resume an interrupted upload, and require ffprobe validation
before handing the file to the normal start flow. Then add Android Storage
Access Framework selection and a WorkManager foreground upload with progress.

Acceptance: interrupt and resume a transfer, reject a mismatched chunk or
malformed final file, and prove the resulting video follows the existing upload
and compression path.

### Track C: closed-app notifications

The documented first slice uses a self-hosted ntfy topic, disabled by default,
with no third-party default server. Keep plate text, paths, credentials, and
media out of notifications. Native UnifiedPush is a later evaluation, not a
prerequisite for the self-hosted path.

Acceptance: test delivery while the app is closed, verify the topic guard blocks
metadata and redirect abuse, and confirm a slow notification server never stalls
encoding.

### Track D: semantic search

Write the research decision record before choosing an embedding model. Keep the
first implementation opt-in and offline-capable, with a stub embedder for CI so
model downloads never occur during ordinary tests. Store only the metadata needed
for the search contract and document rebuild behavior when the model changes.

### Track E: release and polish

Track the app icon, desktop event toast, winget manifest refresh, macOS signing,
installer rebuild, and the public non-beta release here. Each release still
requires the quality gate, clean installer smoke test, checksums, code-signing
verification where applicable, and owner publication.

## 4. GUI refactor constraints

The original `plans/REFACTOR-PLAN-gui-app.md` is the architectural plan for the
completed `app.py` split. Its constraints remain useful for maintenance:

- `from gui.app import app` must continue to work.
- Compatibility re-exports for state and worker symbols must remain available
  to existing tests and callers.
- The shutdown handler must flush the file logger.
- New GUI submodules must be included in frozen-build hidden imports.
- Imports flow one way: state and services, then blueprints, then the app
  assembly. Services must not import the app module.
- SSE state, mutable worker globals, and hardware sampler startup need explicit
  ownership rather than import-time side effects.

The route inventory, proposed file tree, migration order, and refactor-specific
test list remain in the dated source plan for historical detail.

## 5. Owner gates and deferred work

These items are not silently considered complete merely because implementation
scaffolding exists:

| Gate | Evidence ready | Owner action |
|---|---|---|
| Windows code signing | `installer/build.ps1 -Sign` and release checklist | Obtain certificate, build, and verify both binaries |
| Public release and winget | manifests, validation script, release notes | Publish exact installer asset, recompute SHA-256, submit |
| AppImage publication | CI build and smoke path | Attach and publish the verified artifact |
| macOS DMG | no owner certificate or Mac build environment | Build and notarize on macOS |
| Live camera validation | manual checklist and MediaMTX recipe | Test real RTSP/ONVIF hardware or a live relay |
| External penetration test | security regression suite | Test a real LAN deployment before production |
| Video-ingest fuzzing | deterministic malformed-input tests | Run a dedicated fuzzing campaign |
| Plate model bundling | ONNX backend and coexistence recipe | Check individual model licenses and bundle only approved weights |

The detailed owner register remains in `plans/BLOCKERS.md`; security-specific gates
are also indexed in `SECURITY.md`.

## 6. Source plans

- `plans/REFACTOR-PLAN-gui-app.md`: historical GUI extraction constraints and route inventory.
- `plans/UPGRADE-PLAN-R6.md`: August 2026 desktop and mobile roadmap audit.
- `plans/DESKTOP-ZONES-EVENTS-PLAN.md`: detailed D1 through D5 desktop implementation plan.
- `plans/BLOCKERS.md`: owner actions, credentials, build tools, and manual gates.
- `releases/RELEASE-CHECKLIST.md`: release execution checklist.

When one of these source records changes a current decision, update this file
and preserve the dated source record.
