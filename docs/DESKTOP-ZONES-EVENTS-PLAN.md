# Desktop zones + events UI plan (R6 Track A3/A4, desktop half)

Written 2026-08-17. The server APIs already exist and are phone-proven:
GET/POST /api/zones (per-camera normalized exclude rects, crossing lines,
loiter zones) and GET /api/events/recent (events.jsonl in the output dir).
This plan puts the same powers in the desktop dashboard. Same operating rules
as every round: suite green per commit, browser-verify each UI task, no em or
en dashes, route-guard bumps travel in the same commit as any new route.

## D1 - EVENTS panel on the TOOLS tab (small)

A collapsible "BEHAVIOR EVENTS" card: newest-first table from
/api/events/recent (kind, camera, headline, wall time), 10s auto-refresh
while the tab is visible, empty state that says to draw zones first and run a
compress. Reuse the archive-results table styles. Files: index.html, a new
static/js/events.js, strings.js.

## D2 - zone editor with a REAL backdrop frame (medium)

Better than the phone v1: the desktop can show the scene. New route
GET /api/zones/frame?camera_id=X returns a JPEG still - the newest thumbnail
for that camera from the library cache, else a black 16:9 placeholder
(reuse the thumb pipeline; no new ffmpeg surface). Canvas overlay on top:
drag to draw exclude rects (red fill), crossing lines (amber), loiter zones
(blue outline); toolbar chips ZONE | LINE | LOITER | CLEAR | SAVE mirroring
the phone; camera id input with a datalist of camera ids seen in
/api/library/videos folder labels. POST /api/zones on save; banner echoes
"applies to the next run". Route guards +1. Files: index.html canvas +
static/js/zones.js, events_bp.py for the frame route.

## D3 - desktop event toasts (small)

The SSE log already streams "EVENT line_crossing at gate..." lines from the
pipeline. events.js listens on the existing SSE feed, filters lines starting
with EVENT, and shows the dashboard's toast component with the headline.
Zero new routes, zero polling.

## D4 - webhook emitter (small server, completes the R5 5.7 notifier tail)

utils/event_webhook.py: on append_events, if the operator configured a
webhook URL (setup state, off by default), POST the event JSON to it with a
2s timeout, fire-and-forget, never blocking the pipeline. The URL must pass
the existing SSRF input guard (SEC-013) - private-network URLs are exactly
the legitimate ones here, so reuse is_safe_input_source semantics inverted:
allow loopback/RFC1918, refuse cloud-metadata ranges. Tests with a local
socket server. UI: one field + enable toggle in Setup/TOOLS.

## D5 - acceptance

Draw a zone + line for a camera in the desktop editor over a real backdrop,
run the highway clip, watch the toast fire, see the rows in the EVENTS panel,
and confirm the phone shows the same events (shared server state). Suite
green; browser-verified screenshots in the round notes.

Order: D1 (visibility) then D2 (the editor) then D3 then D4.
