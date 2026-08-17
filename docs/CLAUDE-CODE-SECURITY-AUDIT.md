# Claude Code - Security + Stress Hardening (red-team this app, find flaws, fix them all in one session)

For: Claude Code (auto mode, max effort). Same operating rules as `docs/CLAUDE-CODE-MASTER-PLAN.md`: run `pwsh scripts/run_tests.ps1` to green after every change (current baseline ~1025 passed, 0 failed), commit per fix (`<type>(<scope>): <subject>` + why-body + final line `Bloodawn(KheivenD)`, NO emojis), `git push origin app`. M0 gotchas apply (.venv, never `[plates]`, opencv-contrib, LF, ffprobe not cv2). NO em-dashes or en-dashes (guard test enforces `src/`). Branch `app`.

This is one job in two phases, in the SAME session: (1) attack the app and record every flaw you find, then keep looking until you stop finding new ones; (2) fix all of them, each with a regression test, suite green at every commit. Start by running the `/security-review` command on the current diff/branch as a first pass, then go far beyond it with the targeted checklist below.

**Deliverable:** a living `docs/SECURITY-AUDIT.md` (table: ID | Category | Severity Critical/High/Med/Low | Route or file | Repro | Status open/fixed | Fix commit) AND a new `tests/security/` suite that programmatically attacks the app and asserts it defends - these become permanent regression tests so the flaw cannot come back. Fix every Critical and High this session; fix Mediums where cheap; record any genuinely-deferred item in `docs/BLOCKERS.md` with a reason.

---

## Threat model (what we are actually defending)

SVCS is a local desktop app whose Flask dashboard **binds 0.0.0.0** (so it is reachable by anyone on the LAN, behind a basic-auth gate added in R1 FIX 4.4). It (a) takes many user-supplied filesystem PATHS, (b) runs ffmpeg as a subprocess, (c) queries a SQLite metadata DB from query params, (d) serves files by path for in-browser playback, (e) does AES-256-GCM encryption, (f) ingests untrusted/possibly-malicious video files (upload, watch-folder, library), and (g) ships an `irm | iex` PowerShell installer. The realistic attackers: a malicious file dropped into a watched folder or uploaded; another user/device on the same LAN; a malicious config file; a crafted request to a state-changing route.

Existing defenses to VERIFY (do not assume they hold everywhere): `src/gui/services/path_safety.py` (`_assert_within_output`, `_safe_output_dir`, `_safe_filename`); ffmpeg invoked with argument LISTS (no `shell=True`); config import uses `request.get_json` (not pickle/yaml.load); HLS segment route does `Path(ts_file).name` to strip traversal; non-localhost bind requires basic auth.

---

## PHASE 1 - Attack and record (find as many flaws as possible, then find more)

Go category by category. For each, build attack inputs, fire them at the routes via the Flask test client (and live where needed), and record what gets through. After you finish a category and fix its findings, RE-SCAN for siblings (e.g., once you find one unguarded path param, check every other route that takes a path).

### 1. Path traversal / arbitrary file read + write (highest risk - many path params)
Routes that take a path or folder: `/api/library/videos|meta|thumb|file|browse_folder|list_dirs` (folder, path), `/api/autocompress/start|scan_now` (folder), `/api/encrypt|/api/decrypt` (input + OUTPUT paths), `/api/config/import|export`, `/media/<path:rel_path>`, `/api/media`, `/api/hls/<camera_id>/<path:ts_file>`, `/api/setup/choose` (output + encrypted dirs), `/api/open_folder`/`/api/browse`.
Attack payloads: `..\..\..\Windows\System32\...`, absolute paths (`C:\Windows\win.ini`, `/etc/passwd`), UNC paths (`\\attacker\share`), drive-relative, symlinks, `%00`/null bytes, very long paths, mixed slashes, URL-encoded `..%2f`, and case tricks. The critical questions: can `/api/library/file` or `/media` read ANY file outside the configured folders? Can `/api/decrypt` WRITE its output anywhere on disk? Can `/api/config/import` cause a write outside app-data? Does EVERY path-taking route funnel through one confinement check, or do the newer ones (autocompress, library, the R3 delete-original) bypass `path_safety`? Record each unguarded route.

### 2. The delete-original-after-compress feature (R3) - destructive file ops
This deletes user files. Attack it: can the deleted path escape the watched source folder (traversal in the watched-folder config, a symlink inside it, a `..` in a discovered filename)? Is there a TOCTOU window (file swapped between the ffprobe-verify and the delete)? Can it ever delete the only copy before a valid output exists (kill the encode mid-run, feed a zero-byte/corrupt output)? Confirm it refuses to delete anything under `<output>/compressed/`. This is the highest-consequence bug class for a surveillance tool (losing the only footage), treat any escape as Critical.

### 3. Auth, LAN exposure, CSRF, SSRF
- Verify basic auth is enforced on EVERY route when bound non-localhost, not just a subset. Test a timing-safe credential compare (use `hmac.compare_digest`), reject empty/default creds, and confirm the flask secret is strong + per-install (not a constant).
- CSRF: the dashboard has no CSRF tokens, yet `/api/start`, `/api/autocompress/start`, `/api/decrypt`, `/api/setup/reset`, `/api/segments/clear`, etc. are state-changing POSTs. While bound to LAN with browser-stored basic-auth, a malicious page could drive them. Decide and implement a mitigation (same-origin / custom-header requirement, or a CSRF token), and test it.
- SSRF: the RTSP URL builder (`/api/cameras/rtsp_url`), ONVIF discovery, HLS input, and `/api/gdrive/detect` take URLs/hosts. Can they be coerced to hit internal addresses or file:// schemes? Restrict to expected schemes/hosts; test with `http://169.254.169.254/`, `file:///`, `localhost:<other-port>`.

### 4. Injection
- SQL: `/api/segments`, `/api/query_segments`, `/api/daily_summary`, `/api/busiest` take filter params that reach the metadata DB. Verify every query is parameterized (no f-string/`%`/`.format` into SQL). Fire `' OR 1=1 --`, `'; DROP TABLE segments; --`, `UNION SELECT`. (There is a `test_sql_injection_protection` already - extend it to every query route.)
- Command/arg injection: filenames and camera IDs flow into ffmpeg arg lists and into `explorer/open/xdg-open` calls. Confirm no `shell=True` path exists and that a filename like `; rm -rf` or `$(...)` or `--evil-ffmpeg-flag` (argument injection - a filename starting with `-` consumed as an ffmpeg option) cannot inject. Prepend `./` or use `--` separators where a user value could be read as a flag.
- XSS: filenames, camera IDs, scene/object metadata, and log lines are rendered in the dashboard and streamed over SSE. Inject `<script>`, `<img onerror>`, and SSE-breaking sequences into a filename / camera id / log and confirm they are escaped in the rendered HTML and the log panel.

### 5. Crypto + secrets handling
- AES-256-GCM: verify the nonce/IV is unique per encryption (never reused under the same key), the GCM tag actually rejects tampered ciphertext, PBKDF2 iteration count is the intended 600k, and a wrong password/key fails cleanly. (There are encryption tests - extend with a nonce-uniqueness test and a bit-flip-tamper test if missing.)
- Secret leakage: confirm passwords, derived keys, raw key bytes, and decrypted plaintext NEVER appear in logs, SSE output, error messages/responses, or crash reports (verify the Sentry scrubbing covers them). Same for license-plate strings (PII). Grep the code for places that log or jsonify request bodies / kwargs.

### 6. DoS / resource exhaustion / malformed input
- Malformed/adversarial video: feed truncated, zero-byte, wrong-extension, and deliberately-malformed mp4s (and a known "zip bomb"-style highly-compressible or huge-dimension file) into upload, the watch folder, and library thumbnailing. Assert the app rejects/contains them, does not hang forever (ffmpeg/ffprobe must run with a timeout), and does not crash the server.
- Concurrency: does `/api/start` allow unbounded concurrent encodes? Hammer it; ensure one-at-a-time or a bounded worker. Flood the watch folder with many files at once. Open many SSE log clients. List a folder with tens of thousands of files (library) - is it paginated/bounded? Is the autocompress queue bounded?
- Stability/leaks: run repeated compresses + a long watch session and look for file-handle / sqlite-connection / memory leaks (we already fixed one `get_connection` leak; look for more, especially in the new autocompress/library code).

### 7. Info disclosure + debug surface
- Do error responses leak absolute paths or stack traces? Should be generic in production. Is `/api/media_debug` (and any debug route) safe to expose? Do `/api/system_metrics|gpu_info|network_info` leak more host detail than needed to an unauthenticated-on-localhost or LAN client?

### 8. Supply chain + the installer
- Run `pip-audit` (or `uv pip audit`) against the locked deps; record any known-vuln dependency.
- The `Install-SVCS.ps1` `irm | iex` pattern executes remote code - confirm it is only ever served over HTTPS from the repo, document the trust assumption, and prefer pinning/checksums. Confirm the winget manifest SHA256 matches the actual built installer.

---

## PHASE 2 - Fix everything (same session), test-guarded

- Fix every Critical and High you recorded, each in its own commit with a regression test under `tests/security/` that reproduces the attack and now asserts the app defends. Suite green at every commit.
- Prefer CENTRAL fixes over per-route patches: if path params are inconsistently guarded, add one `confine_to_allowed(path, allowed_roots)` helper in `path_safety.py` and route EVERY path-taking endpoint through it (then a single test can assert each route rejects traversal). Same for a single auth decorator applied to all state-changing routes, and a single subprocess wrapper that forbids `shell=True` and `--`-separates user values.
- Add the missing hardening: ffmpeg/ffprobe timeouts; a bounded compress concurrency; CSRF mitigation; `hmac.compare_digest` for auth; generic production error messages; output-path confinement on encrypt/decrypt; the delete-original confinement + no-TOCTOU.
- Re-run the Phase-1 attack suite after the fixes and confirm everything that was open is now blocked. Update `docs/SECURITY-AUDIT.md` statuses to fixed with the commit hash.

---

## Honesty / scope notes (do not fake coverage)

- The pytest-coverable core is the input/route/path/SQLi/XSS attack suite and the regression tests - build that and keep it green. A real external network penetration test, a fuzzing campaign with dedicated tools, and testing the live RTSP/camera path are MANUAL / owner-side; note them in `docs/SECURITY-AUDIT.md` as recommended follow-ups rather than claiming they were run.
- Do not weaken or delete an existing test to make something pass. If a security fix changes behavior a test asserted, update that test with a comment.
- If a fix is genuinely too large/risky to land safely this session, record it in `docs/BLOCKERS.md` with severity and a proposed approach rather than half-fixing it.

When done: report the count of findings by severity, what was fixed vs deferred, the new `tests/security/` count, the new total test count, the `pip-audit` result, and the final `docs/SECURITY-AUDIT.md` summary.
