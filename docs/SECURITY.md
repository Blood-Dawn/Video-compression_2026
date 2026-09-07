# SVCS Security

Consolidated security documentation for SVCS (Surveillance Video Compression
System), a self-hosted, open-source (AGPL-3.0) surveillance video compression
tool. This file merges the red-team audit record, the audit brief, and the
owner-run manual verification checklist into one document.

Audit performed 2026-06-21 on branch `app`. Sources merged here:
`docs/SECURITY-AUDIT.md` and `docs/SECURITY-MANUAL-VERIFY.md`.

---

## Threat model

SVCS is a local desktop application with a Flask dashboard. What it holds is the
reason to care: **recorded video of real people**, a **bearer credential** (the
dashboard password and per-device API tokens), and a **dashboard that can be
reachable on the LAN**. Losing any of the three is a real-world privacy incident,
not an abstract one.

What the app actually does, and therefore what the attack surface is:

* Serves a Flask dashboard. `run_gui.py` defaults `--host` to `0.0.0.0` and the
  Dockerfile passes it explicitly, so a LAN-reachable bind is a shipping
  configuration, not a hypothetical. The frozen desktop launcher binds
  `127.0.0.1`.
* Takes many user-supplied filesystem paths (library, autocompress watch folders,
  encrypt/decrypt input and output, media serving, config import/export).
* Runs `ffmpeg` / `ffprobe` as subprocesses.
* Queries a SQLite metadata DB from query parameters.
* Serves files by path for in-browser playback.
* Performs AES-256-GCM encryption of stored footage.
* Ingests untrusted and possibly malicious video (upload, watch folder, library).
* Deletes original footage after compression when the operator opts in.
* Ships an `irm | iex` PowerShell installer.

Realistic attackers:

* A malicious file dropped into a watched or uploaded folder.
* Another user or device on the same LAN.
* A malicious web page the operator visits, driving state-changing routes with
  the browser's cached credentials (CSRF).
* A crafted request to a state-changing route.
* A lost or stolen phone holding a device token.

Highest-consequence failure modes, in order:

1. **Footage loss.** The delete-original feature removes user files. Deleting the
   only copy of real footage is the worst outcome this codebase can produce.
2. **Feed exposure.** An unauthenticated LAN or internet bind means anyone
   nearby can open a camera dashboard.
3. **Credential or PII leakage.** Passwords, derived keys, plaintext, and
   license-plate strings must never reach logs, SSE output, error responses, or
   crash reports.

---

## Hardening implemented

Phase 1 attacked the app across 8 checklist categories (Flask test client, code
review, the `/security-review` command, and an adversarial multi-agent recon pass
that produced 22 candidates, kept 14, refuted 8). Phase 2 fixed every
Critical/High plus the cheap Mediums and Lows. Each fix landed with a regression
test under `tests/security/`, suite green at every commit.

### Findings and fixes

| ID | Category | Severity | Where it lives | Risk | Fix | Status |
|----|----------|----------|----------------|------|-----|--------|
| SEC-001 | CSRF | High | Every state-changing POST: `pipeline_bp /api/start`, `autocompress_bp /api/autocompress/start`, `encryption_bp /api/decrypt` and `/api/encrypt`, `setup_bp /api/setup/reset` and `/api/setup/choose`, `files_bp /api/segments/clear`, `hls_bp /api/hls/start`, `rtsp_bp /api/rtsp/*` | A page the operator visits could `fetch()` a state-changing route; the browser attaches cached Basic-Auth and no token or Origin check blocked it, giving cross-site footage deletion and pipeline control | CSRF mitigation applied across state-changing routes (same-origin / custom-header requirement), regression tested | fixed (`7f90460`) |
| SEC-002 | Path traversal, arbitrary read | High | `/api/media?path=` (`files_bp.py:315`) | Streamed ANY video-extension file anywhere on disk. Only checked is_absolute + exists + extension, never confined to a root. The "localhost only" comment in the code was false, since the app binds `0.0.0.0`. `/api/media_debug` acted as a confirmation oracle | Route funnels through the central `confine_to_allowed()` / `allowed_media_roots()` helpers in `src/gui/services/path_safety.py` | fixed (`aa949e8`) |
| SEC-003 | Path traversal, arbitrary read | Medium | `/api/library/file`, `/meta`, `/thumb` (`library_bp.py` `_safe_video`) | `_safe_video` resolved the path first, so its `'..' in p.parts` check was dead code. Any existing video-extension file on disk was served with no root confinement | Same central confinement helper; the dead `..` check replaced with a real root test | fixed (`aa949e8`) |
| SEC-004 | Info disclosure | Medium | `/media/<path:rel_path>` (`files_bp.py:280`) | Confined to the repo root but served ANY file under it with no extension restriction, so `/media/src/utils/encryption.py` and `/media/outputs/metadata.db` disclosed source and the metadata DB | Confined to `allowed_media_roots()`, which deliberately excludes the repo source tree | fixed (`aa949e8`) |
| SEC-005 | Path traversal, arbitrary read | Low | `/api/encrypt` `key_file` (`encryption_bp.py:350`) | Unlike `/api/decrypt`, encrypt read `key_file` with no trusted-root check, so `key_file: 'C:/Windows/win.ini'` read an arbitrary file as key material | Trusted-root check applied to `key_file` on the encrypt path | fixed (`e8590d6`) |
| SEC-006 | Path traversal, arbitrary write | Low | `/api/encrypt` output (`encryption_bp.py:362-374`) | The `.enc` output dir came from `config.encrypted_dir` with no confinement. `_safe_output_dir`'s `..`-after-resolve check is a no-op, and the encrypt/decrypt trusted roots included the whole project root | Output directory confined; trusted roots narrowed | fixed (`e8590d6`) |
| SEC-007 | DoS, missing timeout | Low | `roi_encoder.py:997` audio mux | The audio-mux `subprocess.run(...)` had no `timeout=`, so a crafted clip could hang the encode worker. Every other ffprobe/ffmpeg call already had one | `timeout=` added to the audio-mux subprocess call | fixed (`20c1b18`) |
| SEC-008 | Supply chain | Medium | `uv.lock` | `pip-audit` flagged runtime `cryptography 47.0.0` (GHSA-537c-gmf6-5ccf, fixed in 48.0.1) and `urllib3 2.6.3` (PYSEC-2026-141/142, fixed in 2.7.0) | Both runtime dependencies upgraded. The remaining flagged packages (jupyter-server, jupyterlab, mistune, notebook, tornado, bleach, basicsr, idna) are dev/notebook-only and are tracked separately (see Deferred below) | fixed (`0c7b8a7`) |
| SEC-009 | SSRF (formatter) | Informational | `/api/cameras/rtsp_url`, `/discover` | `rtsp_url` only FORMATS a URL and performs no fetch; discovery is an intentional LAN ONVIF broadcast with a timeout. No attacker-controlled fetch exists | No change. Risk reviewed and **accepted** | accepted |
| SEC-010 | Auth bypass, LAN exposure | High | `gui/app.py:305` `__main__`, and `python -m gui.app` | Running `python src/gui/app.py` did `create_app().run(host="0.0.0.0", ...)` with NO auth installed, because only `run_gui.py` installs the guard. The dashboard was exposed unauthenticated on the LAN | The direct-run entry point now goes through the same auth policy decision; auth is not bypassable by choosing a different entry point | fixed (`95f05dd`) |
| SEC-011 | Destructive file op, footage loss | High | `autocompress_runner._process_one` (`autocompress_runner.py:196-237`) | With delete-original ON, stopping the daemon mid-encode (or any interruption) could leave a partial but decodable output that passed `_verify_output`, which only checked "non-empty plus a decodable v:0 stream". The original was then recorded and DELETED, losing the only full copy | Output verification strengthened and the delete gated behind a genuinely complete, verified output | fixed (`20c1b18`) |
| SEC-012 | Destructive file op, mis-attribution | Medium | `autocompress_runner.scan_once` / `_process_one` | The before/after diff over the whole `compressed/` dir was not tied to THIS source's `camera_id`, so a concurrent or leftover file appearing in `compressed/` could be recorded as this source's output and gate its deletion | Output attribution tied to the specific source rather than a directory-wide diff | fixed (`20c1b18`) |
| SEC-013 | SSRF | Medium | `input_source` reaching `cv2.VideoCapture` (`utils/frame_source.py`, `gui/services/hls_runner.py`) from `/api/start` and `/api/hls/start` | An authenticated operator, or CSRF before SEC-001, could set `input_source` to `file:///...` or `http://169.254.169.254/...`. FrameSource allowlisted http/https and opened it. Blind, but the server connected to an attacker-chosen host and scheme | `is_safe_input_source()` in `src/gui/services/path_safety.py`: scheme allowlist (rtsp, rtsps, rtp, rtmp, rtmps, http, https, udp, tcp, mms, srt, plus local paths and webcam indices), explicit blocklist for `file`/`gopher`/`dict`/`ftp`/`sftp`/`smb`/`data`/`php`/`jar`/`netdoc`/`ldap`, and blocked cloud-metadata and link-local hosts. Private LAN hosts stay allowed so real RTSP cameras keep working | fixed (`0c7b8a7`) |
| SEC-014 | Stored XSS | Medium | `scanVideos()` (`static/js/pipeline.js:181-187`) | The inline `onclick` interpolated a filename into a SINGLE-quoted JS string via `escHtml`, which does not escape `'`. A file named `x';alert(1);'.mp4` broke out and executed when the operator clicked Scan | Filename escaped for the JS-string context (single quotes included) before interpolation | fixed (`e8590d6`) |
| SEC-015 | Info disclosure | Low | `/api/media_debug` (`files_bp.py:295`) | Reported `exists` / `resolved` / `would_serve` for ANY absolute path, making it a filesystem existence and path-disclosure oracle with no confinement | Confined to the same allowed roots as the media routes | fixed (`aa949e8`) |
| SEC-016 | Supply chain (installer) | Low | `installer/Install-SVCS.ps1` | The direct-download fallback fetched the Release `.exe` over HTTPS and ran it silently with no hash or signature check. The winget path pins a SHA256; this path did not | Hash verification added to the direct-download fallback path | fixed (`0c7b8a7`) |

**Count: 16 SEC findings. 15 fixed, 1 (SEC-009) reviewed and accepted as
informational with no attacker-controlled fetch.**

### Verified defenses (attacked, found holding)

These were attacked and held. They produced regression tests, not fixes, so they
cannot silently regress.

| ID | Category | Where | Result |
|----|----------|-------|--------|
| SEC-D1 | SQL injection | `utils/db/queries.py`, `files_bp /api/segments` | Every query parameterized (`?`), including the `IN (...)` count form and `LIMIT ?`. `' OR 1=1 --`, `'; DROP TABLE`, and `UNION SELECT` are inert |
| SEC-D2 | Crypto (AES-256-GCM) | `utils/encryption.py` | Random 12-byte nonce per call, random 16-byte salt per file, GCM tag verified (`InvalidTag` becomes `RuntimeError` with no plaintext written), PBKDF2-HMAC-SHA256 at 600k iterations. A wrong password fails cleanly |
| SEC-D3 | XSS (escaped renderers) | `files.js`, `library.js`, `autocompress.js` | Filenames, camera ids, and metadata go through `escHtml` / `_esc` / `jsAttr` before `innerHTML`. Camera ids are sanitized to `[A-Za-z0-9_-]` at ingestion. The one gap found was SEC-014 |
| SEC-D4 | Auth | `gui/auth.py` | `hmac.compare_digest` constant-time compare, refuses a non-localhost bind without credentials, both username and password compared |
| SEC-D5 | Secret / session key | `gui/app.py:51` | `SECRET_KEY` is `os.urandom(32)`, persisted at mode 0600, per install |
| SEC-D6 | delete-original symlink escape | `autocompress_runner._safe_delete_original` | `src.resolve()` defeats symlink escape. Only files under the resolved watched root, never under `compressed/`, and the verified non-empty output is re-checked immediately before `unlink` |
| SEC-D7 | Command / argument injection | `utils/ffmpeg.py`, pipeline, `files_bp` | Argument LISTS only, no `shell=True`. ffmpeg/ffprobe inputs must be existing files, so a `-`-prefixed filename resolves to a non-existent path and is rejected |
| SEC-D8 | Concurrency | `/api/start` (`pipeline_bp.py:64`) | Refuses a second encode while one is running (HTTP 409) |

### Auth and credential hardening in the shipping code

Beyond the numbered audit findings, the following is what the current auth stack
actually does. Read this as the description of record.

* **Bind policy** (`src/gui/auth.py`, `decide_auth`). A loopback bind
  (`127.0.0.0/8`, `localhost`, `::1`) makes auth optional and enables it anyway
  if credentials are supplied. Any other bind makes HTTP Basic Auth REQUIRED:
  the server raises `AuthConfigError` and refuses to start unless credentials are
  configured via `--username`/`--password` or `SVCS_DASHBOARD_USER` /
  `SVCS_DASHBOARD_PASSWORD`, or the operator explicitly opts out with
  `--no-auth`. Auth is deliberately not installed inside `create_app()`; only the
  real server entry point installs it after deciding policy.
* **Two accepted credentials** (`install_basic_auth`). `Authorization: Basic`
  with the configured username and password (the browser path), or
  `Authorization: Bearer <token>` matching a live device token (the mobile path).
  Both comparisons are constant-time and compare UTF-8 BYTES, not `str`, because
  `hmac.compare_digest` raises `TypeError` on non-ASCII `str` operands. With
  `str`, any unauthenticated caller sending a non-ASCII password turned every
  request into a 500 with a logged traceback, and an operator whose password
  contained an accent could never log in.
* **Failed-auth throttle** (M0.2). 10 failures per IP in a 300s sliding window
  trips a 300s lockout returning HTTP 429 with `Retry-After`. The IP table is
  bounded at 1024 entries and evicts the oldest, so a spoofed-IP flood cannot buy
  immunity by filling the table. `X-Forwarded-For` is deliberately NOT trusted,
  since nothing in the app sets up `ProxyFix` and honoring the header would let
  one attacker spread attempts across unlimited fake identities. Requests
  carrying no credential at all are not counted, because browsers routinely fire
  one unauthenticated request before retrying. Hand-rolled rather than pulling in
  flask-limiter, to avoid widening the license and supply-chain surface of an
  AGPL project.
* **Per-device tokens** (`src/gui/device_tokens.py`, M0.10). Tokens are minted
  with 256 bits of entropy, carry an `svcs_` prefix so secret scanners and log
  filters have something to match, and are shown exactly ONCE. Only the SHA-256
  is persisted, so a leaked token file yields no working credential and there is
  no "show it again" path. Verification is constant-time over the hash and
  compares every candidate even after a match, so the loop does not leak which
  token matched or how many exist. Revocation is a tombstone rather than a
  delete, so the operator can still see the device existed and when it was last
  used. Minting and revoking require the PASSWORD (Basic), never a token, so a
  stolen token cannot mint successors or revoke the operator's other devices.
* **Token store durability.** Storage is `data_dir()/device_tokens.json`,
  registered in `STATE_FILE_NAMES` so a factory reset revokes every device. It
  deliberately does not live in the per-output-folder `metadata.db`, which
  travels with the videos and is cleared by `/api/segments/clear`. Reads that
  precede a write use `_read_all_strict()`, which refuses to rewrite the store if
  any record was unparseable. The lenient reader was silently destructive: one
  transient read error (an antivirus scanner or sync client holding the file on
  Windows) turned into a write containing only the new token, unpairing every
  other device with no error anywhere. Reproduced in
  `tests/test_device_tokens_durability.py`. Verification stays lenient so one
  corrupt record cannot lock out every other device, but it skips the
  `last_used_at` touch when records were dropped.
* **Bind-exposure warning** (`bind_exposure_warning`, M0.8). Any bind that is not
  loopback, RFC1918, RFC4193, link-local, or the Tailscale CGNAT block
  (100.64.0.0/10) prints a warning at startup. `0.0.0.0` and `::` are explicitly
  NOT treated as private: they bind every interface, which on a machine with a
  public IP puts the dashboard on the public internet. The warning names the real
  problem, that the dashboard serves recorded video of real people over plain
  HTTP with the password sent in cleartext, and points at a VPN or a reverse
  proxy with real TLS.
* **Camera-credential redaction** (`redact_input_source`, M3). RTSP camera URLs
  routinely carry inline credentials, and `/api/cameras/rtsp_url` builds exactly
  that shape. Those URLs were echoed verbatim by `/api/hls/status` and by
  `/api/status` as `config.input_source`, so any caller holding a DEVICE TOKEN
  could read the camera's password. Device tokens are deliberately the weaker
  credential, and a camera password usually also unlocks the camera's own web
  admin. The password is now replaced with `***`; host, port, path, and username
  survive so the operator can still tell which camera a stream belongs to.

### Path confinement helpers

All of it lives in `src/gui/services/path_safety.py`, pure functions with no
shared state and no I/O beyond `Path.resolve()`:

* `is_within(path, root)` - resolved containment test.
* `confine_to_allowed(path, allowed_roots)` - resolves and requires the path to
  live under one of the roots, else raises `ValueError`. Every file-serving route
  funnels through this.
* `is_path_allowed(path, allowed_roots)` - non-raising variant.
* `allowed_media_roots()` - the only folders a media or library path may be read
  from: the configured output / library / encrypted folders, the last demo output
  root, the default cloud output dir and detected cloud SVCS root, the per-user
  Videos/SVCS and app-data dirs, and the repo's `data/` and `outputs/`. NOT the
  whole drive and NOT the repo source tree.
* `_assert_within_output`, `_safe_output_dir`, `_safe_filename` - the older
  per-route guards, retained for existing call sites. Note that
  `_safe_output_dir`'s `".." in p.parts` check is a no-op after `resolve()`; it is
  kept as a belt-and-braces guard and is not the real confinement. Rely on
  `confine_to_allowed`.
* `is_safe_input_source`, `redact_input_source` - the SSRF guard and the
  credential redactor described above.

### Test suite

`tests/security/` programmatically attacks the app and asserts it defends. Every
fixed finding has a regression test that reproduces the original attack and now
asserts the block, so the flaw cannot silently return.

### Deferred and not claimed as covered

These are honest gaps. They were not run and are not claimed as covered.

* External network penetration test against a live LAN bind.
* A fuzzing campaign (AFL, boofuzz) on the video-ingest and ffmpeg path with
  dedicated tools.
* Live RTSP/ONVIF camera-path testing with real hardware or MediaMTX.
* Upgrading the dev/notebook dependency stack (jupyter-server, jupyterlab,
  mistune, notebook, tornado, bleach, basicsr). Not runtime dependencies, but
  still outstanding. Tracked in `docs/BLOCKERS.md`.
* The installer is unsigned, so SmartScreen fires. Expected until it is signed.

---

## Manual verification checklist

Run this yourself on the real, frozen build after any security round and after
rebuilding the installer. Automated tests prove the code rejects attack inputs.
This checklist proves the two highest-consequence failure modes are actually safe
on the shipped app, where only a human can confirm them:

* **A. Network exposure** - "anyone on the same wifi can open my camera dashboard."
* **B. Delete-original** - "the app deleted the only copy of my footage."

Use THROWAWAY copies of videos for everything in section B.

**Ship rule: do not hand the build to a teammate or a sponsor unless A1 (or A2 if
you expose it) and B2 both pass.** Those two are the difference between "a rough
beta" and "it leaked a camera feed or ate someone's footage."

### A. Network exposure and auth

Background: the installed desktop app should bind `127.0.0.1`. The launcher was
fixed to do this when frozen. LAN exposure (`0.0.0.0`) is only for the
server/Docker scenario, and that path must require a password. Verify both.

- [ ] **A1 (Critical) - the desktop app is NOT reachable from another device.**
  - [ ] Launch SVCS normally. The dashboard URL bar should read
    `http://127.0.0.1:5000` (or a similar localhost address), not your LAN IP.
  - [ ] Find the PC's LAN IP: run `ipconfig` in PowerShell and note the IPv4
    address (for example `192.168.1.50`).
  - [ ] From a DIFFERENT device on the same wifi (phone, second laptop), browse
    to `http://<that-IP>:5000`.
  - [ ] PASS: it does NOT load (connection refused or times out). FAIL: the
    dashboard opens with no password. Stop and fix before sharing the build.
- [ ] **A2 (Critical, only if you use server/LAN mode) - auth is enforced when
  bound to the network.**
  - [ ] From another device, browse to `http://<PC-IP>:5000`.
  - [ ] PASS: you are prompted for a username and password (HTTP Basic), a WRONG
    password is rejected, and only the correct credential gets in. FAIL: the
    dashboard opens with no prompt, or any password works. Do not expose it.
  - [ ] Confirm the credential is not blank or a default. You set it, and it is
    not `admin/admin`.
- [ ] **A3 - if you do not need LAN access, keep it localhost.** The safest
  default for a single-PC install is localhost-only (A1). Only turn on `0.0.0.0`
  deliberately, behind A2.

### B. Delete-original-after-compress (use throwaway copies)

The dangerous failure is deleting an original when the compress did NOT actually
succeed. Test the failure path on purpose.

- [ ] **B0 - default is keep.** With a fresh setup, the "Delete original after
  compress" toggle in the AUTO-COMPRESS tab is OFF by default.
- [ ] **B1 - keep mode leaves originals alone.**
  - [ ] Make a throwaway folder and copy 2 or 3 clips into it.
  - [ ] Leave delete OFF, run auto-compress (or "Compress existing now") on it.
  - [ ] PASS: compressed copies appear under the `compressed/` output and ALL
    originals are still in the source folder.
- [ ] **B2 (Critical) - failure must NOT delete the original.** The single most
  important check.
  - [ ] Throwaway folder again. Put in it one good clip plus a deliberately
    BROKEN file: copy a .txt and rename it `fake.mp4`, and/or truncate a real
    clip to its first few KB.
  - [ ] Turn the delete-after-compress toggle ON and read the warning it shows.
  - [ ] Run it.
  - [ ] PASS: the good clip compresses and, per your choice, its original may be
    removed AFTER a valid compressed file exists. The BROKEN file is NOT deleted
    and is still sitting in the folder. FAIL: the broken or unconvertible file
    got deleted even though no valid compressed output was produced. That is data
    loss. Stop and fix.
  - [ ] Bonus: start compressing a large clip and kill the app (close the window
    or end task) mid-encode. Relaunch. The original of the interrupted file must
    still be there, since no output existed and nothing should have been deleted.
- [ ] **B3 - it only deletes inside the watched folder.**
  - [ ] Confirm nothing under the `compressed/` output folder ever gets deleted.
    Those are your results.
  - [ ] If you can, point auto-compress at a folder containing a shortcut or
    symlink to a file OUTSIDE it, and confirm only real files inside the watched
    folder are ever touched.

### C. Quick high-value spot-checks (about 5 minutes)

- [ ] **C1 Path confinement.** In Library or Setup, try to browse or enter
  `C:\Windows\System32` or a path containing `..\..\`. Confirm you cannot read
  system files through the app; it should reject or stay confined to allowed
  folders.
- [ ] **C2 XSS in filenames.** Rename a throwaway clip to something like
  `test<script>alert(1)</script>.mp4`, then view the Library. PASS: the name
  shows as literal text, with no popup and no broken page.
- [ ] **C3 No secrets in logs.** Encrypt a file with a password, then open the
  SVCS log (`svcs.log`, path shown in the Help overlay or your app-data SVCS
  folder) and the console. PASS: your password and the file contents are NOT
  anywhere in the log.
- [ ] **C4 Malformed input does not crash it.** Drop a 0-byte file named `x.mp4`
  and a random non-video renamed to `.mp4` into the upload or watch path. PASS:
  the app shows an error for them and keeps running, with no hang and no server
  crash.
- [ ] **C5 Installer trust.** The unsigned installer triggers SmartScreen
  ("More info -> Run anyway"), which is expected until it is signed. Only run the
  `irm ... | iex` terminal installer from your own official repo URL over HTTPS,
  never a copy someone pasted you.

### Result log

| Check | Result (PASS/FAIL) | Notes |
|---|---|---|
| A1 desktop not reachable from another device | | CRITICAL |
| A2 auth enforced in server/LAN mode | | n/a if you never use 0.0.0.0 |
| B0 delete toggle defaults OFF | | |
| B1 keep-mode leaves originals | | |
| B2 failure does NOT delete original | | CRITICAL |
| B3 only deletes inside watched folder | | |
| C1 path confinement | | |
| C2 no XSS via filename | | |
| C3 no secrets in logs | | |
| C4 malformed input handled | | |
| C5 installer trust | | |

---

## Reporting a vulnerability

SVCS is maintained by **Bloodawn / Kheiven D'Haiti**.

Please report security issues through the GitHub repository:
<https://github.com/Blood-Dawn/Video-compression_2026/issues>

Responsible disclosure, briefly:

* If the issue could expose someone's footage, credentials, or personal data, do
  not post a working exploit in a public issue. Open an issue saying only that
  you have a security report and how to reach you, and the details can be
  exchanged privately.
* For lower-risk issues, a normal public issue is fine and is usually faster.
* Please include: affected version or commit, the route or file, a minimal
  reproduction, and what an attacker gains.
* This is a small volunteer-maintained project. Expect an acknowledgement within
  a few days and a fix timeline that depends on severity. Critical and High
  issues that risk footage loss or feed exposure are treated as drop-everything
  work.
* There is no bug bounty. Credit in the changelog is offered to anyone who wants
  it.
* SVCS is AGPL-3.0. If you run a modified network-facing copy, the license
  obligations apply to your changes too, including security fixes.

---

## Operational rules that never bend

These are not preferences. A change that violates one of them does not ship.

1. **Delete the original only after a verified output exists.** A compressed file
   is not "verified" because it is non-empty and decodable; that exact assumption
   was SEC-011 and it lost footage. The output must be complete and attributable
   to the specific source that produced it (SEC-012), and the verified output is
   re-checked immediately before the `unlink`. Delete-original defaults to OFF.
   Never delete anything outside the resolved watched root, and never delete
   anything under `compressed/`. When in doubt, keep the file.
2. **Never log secrets, plate text, or credentials.** Passwords, derived keys,
   raw key bytes, decrypted plaintext, device tokens, and RTSP inline credentials
   never reach logs, SSE output, error messages, HTTP responses, or crash
   reports. License-plate strings are PII and are treated the same way. The auth
   failure log deliberately records the source address and nothing else: an
   operator gets to see they are being probed without the log becoming a place
   passwords are written down.
3. **Localhost by default; auth required on any non-localhost bind.** The frozen
   desktop app binds `127.0.0.1`. Any bind beyond loopback requires a credential,
   and the server refuses to start rather than silently expose an
   unauthenticated dashboard. `--no-auth` exists only as an explicit, deliberate
   operator opt-out. A bind that reaches beyond the local network prints a
   warning saying so.
4. **Auth is enforced at the server entry point, not per route.** There is one
   guard, it covers every route including static assets, media, and HLS
   segments, and no alternate entry point may bypass it. That was SEC-010.
5. **Every user-supplied path funnels through one confinement helper.** New
   path-taking routes use `confine_to_allowed()`. Do not hand-roll a per-route
   check, and do not trust a `".."`-in-parts test after `resolve()`; it is dead
   code.
6. **Subprocesses take argument LISTS and a timeout.** No `shell=True`, ever.
   Every ffmpeg and ffprobe invocation has a `timeout=`.
7. **No cloud, no telemetry beyond opt-in.** SVCS is self-hosted. Video, metadata,
   and plate text stay on the operator's machine and in folders the operator
   chose. Nothing phones home by default. Any crash reporting or analytics is
   off unless the operator turns it on, and its scrubbing must cover everything
   in rule 2.
8. **Do not weaken or delete a test to make something pass.** If a security fix
   legitimately changes behavior a test asserted, update the test and say why in
   a comment.
