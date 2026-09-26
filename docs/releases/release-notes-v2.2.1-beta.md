# SVCS v2.2.1-beta - draft release notes

Desktop-only rebuild. The v2.2.0-beta installer was cut 2026-08-17 and had
gone stale: the chunked resumable upload, zone/behavior events, job
registry, mobile push, the webhook emitter, and the SEC-017 SSRF fix all
landed after that build. This release exists to get a current installer
attached so those features are actually reachable, not just merged.

## Desktop (SVCS-Setup-2.2.1.dev0.exe)

Everything since the 2.2.0 beta:

- Event webhook: `src/utils/event_webhook.py` posts job and detection
  events to a configured HTTPS endpoint, HMAC-SHA256 signed
  (`X-SVCS-Signature`), with retry, an in-app Test button
  (Settings, Webhook), and the shared SSRF guard also used by push
  notifications.
- SEC-017 fix: the SSRF guard's hostname validation and the outbound
  request now share one DNS resolution instead of two, closing a
  DNS-rebinding TOCTOU window where a validated hostname could
  re-resolve to a private or loopback address by the time the real
  connection was made. Regression coverage in
  `tests/security/test_dns_rebinding.py`.
- EVENTS panel, zone editor, and Setup folder-browse from Week 3.
- Chunked resumable upload and its filename-sanitization fix, so a
  browser-side upload cannot write outside the intended folder.
- Job registry, zone/behavior events, and mobile push wiring that mobile
  0.6 through 1.1 already depend on server-side.

## Companion: SVCS Web (new, separate project)

A browser dashboard (Supabase-backed, deployed on Netlify) that a desktop
install can push job and detection events to over the webhook above, so a
household or small team can see camera activity without opening the
desktop app. Multi-user with admin, operator, and guest roles enforced by
Postgres row-level security. Tracked in
`docs/plans/WEB-DASHBOARD-PLAN.md`; the Supabase Edge Function that
ingests the webhook still needs a CLI deploy with service-role access
before the webhook URL in Settings will do anything on the receiving end.

## Verification

- `uv run pytest`: 1787 passed, 9 skipped (webcam/Docker/optional-model
  tests that need hardware or opt-in flags not present on the build
  machine), 0 failed.
- `tests/security/`: 134 passed, including the new DNS-rebinding
  regression test for SEC-017.
- Built with `installer\build.ps1 -Installer` from `mobile` at commit
  `7f3ac24`, Python 3.11.9, PyInstaller 6.22.3.
- Smoke test: launched `dist\SVCS\SVCS.exe --no-browser --no-sync --port
  5000 --host 127.0.0.1`, got HTTP 200 from `http://127.0.0.1:5000/`.
- `SHA256SUMS.txt` generated against the built installer.

## Known gaps

- Unsigned installer, so Windows SmartScreen will warn on first run. No
  code-signing cert is configured yet (see `docs/BLOCKERS.md`).
- The SVCS Web Edge Function is not deployed yet, so the webhook has
  nowhere to actually deliver events until that CLI step runs.
- This build was not run through the mobile Android instrumented suite;
  no mobile-side changes are included in this release.