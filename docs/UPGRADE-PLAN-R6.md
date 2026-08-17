# R6 - the app upgrade plan (desktop + mobile together)

Written 2026-08-17 after the milestone audit below. Same operating rules as
every prior round: one task at a time, suite green before commit, no em or en
dashes anywhere, physical-device verification for anything mobile, publish
gates stay owner-only.

## Milestone audit (what "everything up to here" means)

Complete: M0-M5b desktop productization, fix rounds R1-R4, the security round
SEC-001..016, R5 tasks 5.1 (VMAF-targeted rate control), 5.2 (static-scene
measurement), 5.3 (scene-change keyframes), 5.4 (natural-language search,
API + desktop UI), 5.6 core (exclude zones in the pipeline), 5.7 core
(tracked-object behavior events), 5.8 (tamper-evident manifests); mobile
M0-M3, M4 (playback, library views, compress-from-phone with mode picker,
job registry + start TOCTOU fix), M5 first slice (job-completion
notifications, app-alive polling); R8 minification with verified keep rules.

Open, NOT gated (this plan): R5 5.5 semantic search; the zone and line
DRAWING interfaces (the APIs exist, nothing draws yet); event notifiers
beyond the phone slice (desktop toast, webhook); chunked resumable upload
(the M4 tail); closed-app push (the M5 tail).

Open, OWNER-GATED (money or an explicit go): macOS signed dmg (Apple cert),
the Rust core spike M6 (explicit go-ahead), optional TASK 3.3 adaptive
per-segment bitrate (deferred by decision), release re-tag to a public
non-beta (publish gate).

## Track A - zones and events become visible (highest user value)

A1. Phone EVENTS tab: newest-first list from /api/events/recent (kind, camera,
    time, direction), auto-refresh, empty-state honesty. Small.
A2. Phone zone editor: pick a camera, fetch a thumbnail as the backdrop, draw
    exclude rects and one crossing line by drag, POST /api/zones. Compose
    Canvas + pointerInput; normalized coords already match the API. Medium.
A3. Desktop zone editor: same on the TOOLS tab with an HTML canvas over a
    still frame. Medium.
A4. Event notifications reuse the M5 poller: notify on new behavior events,
    not only job completions. Small.

## Track B - ingest completion (the M4 tail)

B1. Server chunked upload: POST /api/upload/chunk (offset + sha256 per chunk,
    resume query), append-only temp file, ffprobe verify on finalize, then
    the standard start flow. Medium.
B2. Phone: pick a gallery video (Storage Access Framework), WorkManager
    upload with resume, progress notification. Medium-large.

## Track C - closed-app push (the M5 tail)

C1. Self-hosted ntfy (or UnifiedPush) publisher on the server: POST on job
    and behavior events to a user-configured topic URL. Opt-in, off by
    default, no third-party default server. Small server side.
C2. Phone: subscribe via the ntfy Android app (zero code, documented) first;
    native UnifiedPush later if wanted. Documentation slice first.

## Track D - R5 5.5 semantic search (the last R5 box)

D1. RESEARCH-SEMANTIC-SEARCH.md per the R5 spec (model choice, storage,
    offline story), then the opt-in skeleton with a stub embedder so CI
    never downloads a model. The real model install stays a helper-script
    extra like the plate reader. Medium.

## Track E - polish debts

E1. App icon (current launcher icon is the template robot). Small.
E2. Desktop toast for behavior events (the SSE log already streams; a toast
    on EVENT lines). Small.
E3. Winget manifest refresh for the 2.2 installer sha. Small, blocked on the
    owner publishing a non-beta tag.

Suggested order: A (visibility for everything built tonight), then B, then
C, then D, with E slotted between as breathers.
