# SVCS Security Audit (red-team + hardening)

Living record of the security audit run per `docs/CLAUDE-CODE-SECURITY-AUDIT.md`.
Phase 1 attacked the app across the 8 checklist categories (Flask test client +
code review + the `/security-review` command + an adversarial multi-agent recon
pass that produced 22 candidates, kept 14, refuted 8). Phase 2 fixes every
Critical/High and the cheap Mediums/Lows, each with a regression test under
`tests/security/`, suite green at every commit.

Threat model: a local Flask dashboard that binds `0.0.0.0` by default (LAN,
behind Basic-Auth that is REQUIRED for non-localhost binds via `run_gui.py`),
takes user-supplied filesystem paths, runs ffmpeg/ffprobe subprocesses, queries
SQLite, serves files by path, does AES-256-GCM, ingests untrusted video, and
ships an `irm|iex` installer. Realistic attackers: a malicious file dropped into
a watched/uploaded folder; another device on the LAN; a malicious web page the
operator visits (CSRF); a crafted request to a state-changing route.

Date: 2026-06-21. Branch: `app`.

## Findings

| ID | Category | Severity | Route / file | Repro | Status | Fix commit |
|----|----------|----------|--------------|-------|--------|------------|
| SEC-001 | CSRF | High | every state-changing POST (`pipeline_bp /api/start`, `autocompress_bp /api/autocompress/start`, `encryption_bp /api/decrypt|encrypt`, `setup_bp /api/setup/reset|choose`, `files_bp /api/segments/clear`, `hls_bp /api/hls/start`, `rtsp_bp /api/rtsp/*`) | A page the operator visits runs `fetch('http://127.0.0.1:5000/api/autocompress/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({folder:'C:/Users/v/Videos',delete_original:true})})`; the browser sends it with any cached Basic-Auth; no token/Origin check blocks it -> cross-site footage deletion / pipeline control | open | |
| SEC-002 | Path traversal / arbitrary read | High | `/api/media?path=` (`files_bp.py:315`) | `GET /api/media?path=C:%5CUsers%5Cvictim%5CVideos%5Cprivate.mp4` streams ANY video-extension file anywhere on disk; only checks is_absolute+exists+ext, never confines to a root. The "localhost only" comment is false (binds 0.0.0.0). `/api/media_debug` is a confirmation oracle | open | |
| SEC-010 | Auth bypass / LAN exposure | High | `gui/app.py:305` `__main__` (and `python -m gui.app`) | Running `python src/gui/app.py` (or `python -m gui.app`) does `create_app().run(host="0.0.0.0", ...)` with NO auth installed (only `run_gui.py` installs it) -> the dashboard is exposed unauthenticated on the LAN | open | |
| SEC-011 | Destructive file op (footage loss) | High | `autocompress_runner._process_one` (`autocompress_runner.py:196-237`) | With delete-original ON, stopping the daemon mid-encode (or any interruption) can leave a partial-but-decodable output that passes `_verify_output` (only checks "non-empty + a decodable v:0 stream"); the original is then recorded + DELETED, losing the only full copy | open | |
| SEC-003 | Path traversal / arbitrary read | Medium | `/api/library/file|meta|thumb` (`library_bp.py` `_safe_video`) | `_safe_video` resolves the path (so its `'..' in p.parts` check is dead code) and serves any existing video-ext file with NO root confinement; `GET /api/library/file?path=<any .mp4 on disk>` reads it | open | |
| SEC-012 | Destructive file op (mis-attribution) | Medium | `autocompress_runner.scan_once/_process_one` | The before/after diff over the whole `compressed/` dir is not tied to THIS source's camera_id; a concurrent/leftover file appearing in `compressed/` could be recorded as this source's output and gate its deletion | open | |
| SEC-013 | SSRF | Medium | `input_source` -> `cv2.VideoCapture` (`utils/frame_source.py`, `gui/services/hls_runner.py`) reached from `/api/start`, `/api/hls/start` | An authenticated operator (or CSRF, pre-SEC-001) can set `input_source` to `file:///...` or `http://169.254.169.254/...`; FrameSource allowlists http/https and opens it. Blind (frames go to the operator's output), but the server connects to attacker-chosen host/scheme | open | |
| SEC-014 | Stored XSS | Medium | `scanVideos()` (`static/js/pipeline.js:181-187`) | The inline `onclick` interpolates a filename into a SINGLE-quoted JS string via `escHtml`, which does not escape `'`. A file in `data/` named `x';alert(1);'.mp4` breaks out and executes when the operator clicks Scan | open | |
| SEC-004 | Info disclosure | Medium | `/media/<path:rel_path>` (`files_bp.py:280`) | Confined to the repo root but serves ANY file under it (no extension restriction): `GET /media/src/utils/encryption.py`, `/media/outputs/metadata.db` disclose source / the metadata DB | open | |
| SEC-008 | Supply chain | Medium | `uv.lock` | `pip-audit`: runtime `cryptography 47.0.0` (GHSA-537c-gmf6-5ccf, fix 48.0.1) and `urllib3 2.6.3` (PYSEC-2026-141/142, fix 2.7.0). The rest (jupyter-server, jupyterlab, mistune, notebook, tornado, bleach, basicsr, idna) are dev/notebook-only | open | |
| SEC-005 | Path traversal / arbitrary read | Low | `/api/encrypt` `key_file` (`encryption_bp.py:350`) | Unlike `/api/decrypt`, encrypt reads `key_file` with NO trusted-root check: `{file_path:<trusted>, key_file:'C:/Windows/win.ini'}` reads an arbitrary file as key material | open | |
| SEC-006 | Path traversal / arbitrary write | Low | `/api/encrypt` output (`encryption_bp.py:362-374`) | The `.enc` output dir comes from `config.encrypted_dir` with no confinement (`_safe_output_dir`'s `..`-after-resolve check is a no-op); the encrypt/decrypt trusted roots also include the whole project root | open | |
| SEC-007 | DoS (missing timeout) | Low | `roi_encoder.py:997` audio mux | The audio-mux `subprocess.run(...)` has no `timeout=`; a crafted clip could hang the encode worker (every other ffprobe/ffmpeg call has a timeout) | open | |
| SEC-015 | Info disclosure | Low | `/api/media_debug` (`files_bp.py:295`) | Reports `exists`/`resolved`/`would_serve` for ANY absolute path -> a filesystem existence + path-disclosure oracle, no confinement | open | |
| SEC-016 | Supply chain (installer) | Low | `installer/Install-SVCS.ps1` | The direct-download fallback fetches the Release `.exe` over HTTPS and runs it silently with no hash/signature check (the winget path pins a SHA, this path does not) | open | |
| SEC-009 | SSRF (formatter) | Informational | `/api/cameras/rtsp_url`, `/discover` | `rtsp_url` only FORMATS a URL (no fetch); discovery is an intentional LAN ONVIF broadcast with a timeout. No attacker-controlled fetch. Accepted | accepted | n/a |

## Verified defenses (attacked, found holding -> regression tests, not fixes)

| ID | Category | Route / file | Result |
|----|----------|--------------|--------|
| SEC-D1 | SQL injection | `utils/db/queries.py`, `files_bp /api/segments` | Every query parameterized (`?`, incl. the `IN (...)` count form and `LIMIT ?`); `' OR 1=1 --`, `'; DROP TABLE`, `UNION SELECT` are inert |
| SEC-D2 | Crypto (AES-256-GCM) | `utils/encryption.py` | Random 12-byte nonce per call, random 16-byte salt per file, GCM tag verified (`InvalidTag`->`RuntimeError`, no plaintext written), PBKDF2-HMAC-SHA256 at 600k; wrong password fails cleanly |
| SEC-D3 | XSS (escaped renderers) | `files.js`, `library.js`, `autocompress.js` | Filenames/camera ids/metadata go through `escHtml`/`_esc`/`jsAttr` before `innerHTML`; camera ids sanitized to `[A-Za-z0-9_-]` at ingestion (the one gap is SEC-014's single-quote-in-onclick) |
| SEC-D4 | Auth | `gui/auth.py` | `hmac.compare_digest` constant-time; refuses non-localhost bind without creds; user+pass both compared |
| SEC-D5 | Secret / session key | `gui/app.py:51` | `SECRET_KEY` = `os.urandom(32)` persisted at 0600 per-install |
| SEC-D6 | delete-original symlink escape | `autocompress_runner._safe_delete_original` | `src.resolve()` defeats symlink escape; only files under the resolved watched root, never under `compressed/`; re-checks the verified non-empty output before `unlink` |
| SEC-D7 | Command / argument injection | `utils/ffmpeg.py`, pipeline, `files_bp` | Argument LISTS only (no `shell=True`); ffmpeg/ffprobe inputs must be existing files, so a `-`-prefixed name resolves to a non-existent path and is rejected |
| SEC-D8 | Concurrency | `/api/start` (`pipeline_bp.py:64`) | Refuses a second encode while one runs (409) |

## Manual / owner-side follow-ups (NOT run here; not claimed as covered)

- External network penetration test against a live LAN bind.
- A fuzzing campaign (AFL/boofuzz) on the video-ingest + ffmpeg path with dedicated tools.
- Live RTSP/ONVIF camera-path testing with real hardware / MediaMTX.
- Upgrading the dev/notebook dependency stack (jupyter-server, jupyterlab, mistune, notebook, tornado, bleach, basicsr); tracked in `docs/BLOCKERS.md`.

## Test suite

`tests/security/` programmatically attacks the app and asserts it defends. Each
fixed finding has a regression test that reproduces the attack and now asserts
the block, so the flaw cannot silently return.
