# Session handoff - continue SVCS from here (written 2026-08-17, post 0.8.0)

For: the next Claude session (Cowork, full tool access) working with the owner
(Bloodawn / Kheiven D'Haiti). Read this whole file, then docs/UPGRADE-PLAN-R6.md
and docs/DESKTOP-ZONES-EVENTS-PLAN.md, then start with Track C below. Verify
against the repo, not memory; the git log on branch `mobile` is the truth.

## What this project is

SVCS: free, open-source (AGPL-3.0), self-hosted, AI-aware surveillance video
compression. Python pipeline (MOG2 + YOLO ONNX + ROI-aware FFmpeg encoding,
SQLite metadata) + Flask dashboard (21 blueprints, 85 routes) + Windows
installer + a native Android companion app (Kotlin/Compose, mobile/android).
Codec law: mode0/1 = H.264, mode2/3 = AV1, NEVER H.265. Offline and
self-hosted by default; no cloud, no telemetry beyond the existing opt-in.

## Where everything stands (all verified on real hardware)

Complete: desktop M0-M5b, fix rounds R1-R4, security round SEC-001..016,
R5 5.1-5.4 + 5.6 core + 5.7 core + 5.8, mobile M0-M5 (M4 fully: playback,
library views, compress with mode picker, job registry + start TOCTOU fix,
chunked RESUMABLE upload; M5 first slice: job + behavior-event notifications
while the app process lives). R8 minification is ON with completed keep rules
(the 0.3.0 black screen was stripped kotlinx-serialization $$serializer
classes + Signature attribute; rules file explains). R6 Track A shipped: the
phone's EVENTS tab, event notifications, drag-to-draw zone/line editor.
0.8.0 added the auto-compress-on-upload toggle (MORE) and per-clip INFO
metrics. Desktop exe and SVCS-Mobile-0.8.0-beta.apk are on the v2.2.0-beta
GitHub release with SHA256SUMS.

Open work, in the owner's priority order:
1. TRACK C (start here): closed-app push. Self-hosted ntfy publisher on the
   server for job + behavior events (opt-in, off by default, URL must pass an
   SSRF-aware validator that ALLOWS loopback/RFC1918 but refuses cloud
   metadata ranges); document the ntfy Android app subscription first, native
   UnifiedPush later. This finishes the M5 tail.
2. Desktop zones/events UI: docs/DESKTOP-ZONES-EVENTS-PLAN.md (D1 EVENTS
   panel, D2 editor over a real still frame, D3 SSE toasts, D4 webhook).
3. Track D: R5 5.5 semantic search (research doc first, opt-in extra
   installed like the plate reader, stub-tested skeleton, no model in CI).
4. Polish: WorkManager wrapper so uploads survive app death (the protocol
   already supports it), app icon, maybe remove the general METRICS tab (the
   owner called it useless; INFO per clip exists now - ASK before deleting),
   release-notes Mobile heading may lag the newest APK version.
Owner-gated (do not do without an explicit go): macOS signing, Rust spike M6,
publishing a non-beta tag.

## Environment facts you will need

- Repo: C:\Users\kheiven\Documents\GitHub\Video-compression_2026. Branch
  `mobile` is where commits land; `app` fast-forwards from it via
  `git fetch . mobile:app` then push BOTH. Commit style: <type>(<scope>):
  subject, why-body, final line exactly Bloodawn(KheivenD), no emojis, and
  NO em-dashes or en-dashes anywhere (docs, code, commits, UI strings).
- Python: .venv (never venv). Tests: `pwsh scripts/run_tests.ps1` or targeted
  `.venv\Scripts\python.exe -m pytest ... --basetemp=.pytest_tmp_r5 -p
  no:cacheprovider` (a UNIQUE basetemp per parallel run; two runs sharing
  .pytest_tmp corrupt each other and fake failures).
- THREE route guards must move together when adding routes:
  test_gui_blueprint_registration.py (rule strings, now 85, plus EXPECTED map
  and EXPECTED_BLUEPRINTS set), test_gui_routes_resolve.py (url_map rules,
  now 86, plus a SAMPLES entry per route, plain paths only, no query
  strings), and register the blueprint in gui/app.py register_blueprints.
- Android: mobile/android, JDK 17 at C:\Program Files\Microsoft\
  jdk-17.0.19.10-hotspot, SDK at %LOCALAPPDATA%\Android\Sdk. BUILD VIA THE
  DETACHED SCRIPT $env:TEMP\svcs_050.ps1 (writes .apk_050_build.log in the
  repo root) because MCP tool timeouts and PowerShell pipeline
  early-termination (Select-Object -First N KILLS gradle mid-build) have
  both produced stale APKs; ALWAYS check the APK LastWriteTime is fresh
  before installing. Release signing: keystore %USERPROFILE%\.svcs\
  svcs-release.jks, credentials in keystore-credentials.txt next to it, env
  vars SVCS_ANDROID_KEYSTORE / SVCS_ANDROID_KS_PASS (the script sets them).
  versionCode 11 / versionName 0.8.0-beta as of this handoff; bump both per
  release and keep the comment ledger in app/build.gradle.kts.
- Phone: Samsung SM-S948U1 over wireless adb (adb at %LOCALAPPDATA%\Android\
  Sdk\platform-tools\adb.exe; it reconnects via mdns). The app sets
  FLAG_SECURE so SCREENSHOTS ARE BLACK BY DESIGN; verify UI via
  `adb shell uiautomator dump /sdcard/ui.xml` + parsing text=/content-desc=
  bounds, tap with `adb shell input tap`, drag with `input swipe`. The phone
  sleeps into a Daydream screensaver; if dumps come back empty or the focus
  is DreamActivity/Bouncer, ask the owner to unlock (send_user_message) and
  poll dumpsys window mCurrentFocus.
- LAN test server: started via $env:TEMP\svcs_e2e_server.ps1 (binds
  0.0.0.0:5000 with basic auth user bloodawn; the password is embedded in
  that script and mirrored in repo-root .e2e_test_pass.txt; the phone's
  bearer token is minted via POST /api/auth/tokens and the current one is in
  .e2e_token.txt). RESTART THE SERVER after server-code changes (kill
  python.exe with run_gui.py in the command line, rerun the script), and
  remember restarts briefly 401 the phone's pollers; the auth throttle
  locks an IP for 300s after 10 failures. A desktop factory reset deletes
  device_tokens.json and permanently unpairs every phone (by design; it
  happened once tonight - re-mint and re-pair via MORE).
- The phone pins its library folder (folder context param on videos/thumb/
  file/meta) so the desktop moving the server-global library folder cannot
  break it mid-session; keep that param on any new media route.
- Browser verification of desktop UI: run a second instance
  `run_gui.py --host 127.0.0.1 --port 5001 --no-browser --no-sync --no-auth`
  and drive it with the Chrome MCP (basic auth dialogs are not automatable).
- Release updates: gh CLI is authed as Blood-Dawn. Swap pattern: copy APK to
  dist\SVCS-Mobile-X.Y.Z-beta.apk, regenerate SHA256SUMS.txt with BOTH
  assets, gh release delete-asset the old APK, upload new + sums with
  --clobber, and keep docs/release-notes-v2.2.0-beta.md's Mobile heading in
  step. The v2.1.0-beta artifacts and RELEASE-CHECKLIST are pinned by tests;
  leave them.
- Safety rules that never bend: delete-original only after a verified
  output; never log secrets/plate text; no [plates] extra in the working
  env; ffprobe (not cv2) validates outputs; never weaken a test to go green.

## How to work (the owner's expectations)

One task at a time; tests ship with the change; every mobile change gets a
physical-device verification pass before it goes on the release; be honest
in commit bodies about what remains; surface what you shipped in short,
concrete summaries. The owner is hands-on: they will unlock the phone, tap
things when asked, and give quick feedback - use send_user_message for
mid-task asks and AskUserQuestion for direction choices.
