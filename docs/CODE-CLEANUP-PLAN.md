# SVCS code cleanup plan

Baseline: origin/main at ee3c53c, measured 2026-11-09 with vulture 2.16, radon 6.0.1 and ruff 0.17.0. Nothing below is deleted yet except where the status says "done".

## Why this plan exists

Two short videos prompted it. One argues that AI assisted code needs the full test ladder (CI first, then unit, integration, end to end, performance). The other lists 20 security holes that AI written web apps keep shipping. The request was to apply both to this codebase and to plan the removal of code we do not need. This file covers the removal plan, a checklist of what each video's points mean for SVCS, and the techniques gathered from the web.

## Baseline numbers

The app has 107 Python files and about 22,900 lines under src, 25 JavaScript files, and 139 test files. The last full run on main plus the library delete work was 2143 passed, 46 skipped and 3 failed (the 3 were route count guards, since fixed).

Complexity (radon, grade D or worse, 21 or higher): 18 functions. The worst are `run_pipeline` in src/pipeline/pipeline.py at 123, `benchmark_enhancement` at 43, `_hls_annotator_thread` at 31, `LayerSegmentEncoder.add_frame` at 30, `render_demo` at 30, `api_start` at 29, `purge_once` at 29, `estimate` in retention.py at 28, and `api_library_videos` at 27.

Ruff, extra rule families on src (223 findings): 42 complex structure, 37 suppressible exception, 32 silent try/except/pass, 26 subprocess calls, 22 too many branches, 20 too many statements, 10 urlopen scheme audits, 4 string built SQL, 3 hardcoded password name matches (all constant names, not secrets), 2 bind all interfaces, 2 tar extract calls.

Vulture at its default 60 percent confidence prints 183 lines. Most are Flask route handlers and context manager signatures, which vulture cannot see being called. Settings that stop this were added to pyproject.toml (status: done). At 80 percent confidence vulture now reports nothing.

## Phase 1: quality gates in CI (small, do first)

The test video's first point is that the pipeline comes before everything else. CI already runs the full suite on Linux and Windows. Add the following, each as its own small change so a failure points at one cause:

1. A vulture step at 80 percent confidence. It exits 3 when it finds dead code. Config is already in pyproject.toml. Status: done (Linux job of ci.yml, vulture pinned to 2.16 in the step, not a project dependency). Verified locally only: `vulture` with no arguments exits 0. Not verified: a real GitHub Actions run.
2. A pip audit step against the lockfile export. It reads the OSV database. Run it on every push.
3. A complexity ratchet: fail only when a new or changed function goes above 15 (radon grade C). Existing hotspots are listed in Phase 3 and are not blocked. Status: done as scripts/complexity_ratchet.py plus scripts/complexity_baseline.json (39 functions above 15 recorded; radon 6.0.1 pinned in the CI step). The ratchet compares against the baseline, not against git changes, so a function that is not in the baseline fails even if untouched. Not verified: a real CI run.
4. Pin GitHub Actions to commit SHAs and add a dependabot file for pip and github actions. Audit the workflows once with zizmor.
5. Optional later: widen ruff to the S family with the current findings recorded as a baseline, so only new ones fail.

## Phase 2: remove dead code

Rule for every item: grep the name in src and tests, read the one caller if there is one, delete the code together with tests that only exercise it, run the full suite, and commit one removal per commit so any can be reverted alone. After each batch rerun vulture, because deleting one thing often exposes the next.

Done in wave 1 (branch chore/code-quality-wave1): removed the unused `roi_green_tint_strength` parameter from the demo overlay function (nothing passed it). The three other vulture hits at 80 percent were required signatures (`__exit__` arguments, `redirect_request` arguments) and are now whitelisted by name in pyproject.toml instead of changed.

Wave 2 status (2026-11-09, same branch): removed `make_hold_frames` (demo.py) and `describe_mode` (pipeline/modes.py), each with zero references in src, tests, scripts, web and docs (commits 04f8ef8 and e8d4877). Vulture at 60 percent went from 80 to 78 lines. Radon grade D or worse is 19 functions, not 18 (`find_crf_for_target` at 22 was missed). Baseline suite on this tree: 2140 passed, 46 skipped, 0 failed.

Needs owner decision (not deleted, reason given):

- src/compression/layer_encoder.py (364 lines, only tests use it): a whole module over 200 lines, so removal needs approval. Its tests in tests/test_layer_encoder.py would go with it.
- src/background_subtraction/tuning_experiment.py (176 lines): documented as a standalone script (`python src/background_subtraction/tuning_experiment.py`). Not dead if anyone still runs it; candidate to move to scripts/ or delete. The `train_subtractor` hit is a separate helper of the same name in tests/test_background_subtraction.py.
- `encode_frame_sequence` in roi_encoder.py: no callers anywhere, but its docstring says it is kept for backward compatibility. This is compression code, so it needs a decision.
- `active_scale` (enhancer.py): public property, referenced in a docstring and documents the scale in effect. Kept.
- `_assert_within_output` (path_safety.py): re-exported by src/gui/app.py and named in docs/SECURITY.md. Kept.
- Functions that only tests call (about 35, for example `compute_psnr`, `compute_ssim`, `MultiFrameSource`, `is_video_ext`, `list_profiles`, `bind_exposure_warning`, `push_targets`): deleting them means deleting their tests, so each needs a call on whether it is public API or leftover.

Candidates, each needing the check above before deleting (the items above are already triaged):

- src/compression/layer_encoder.py: `LayerSegmentEncoder` is defined once in src and referenced only by tests. Its `add_frame` is complexity 30. Likely the whole file.
- src/background_subtraction/tuning_experiment.py: `train_subtractor` and a `main` of complexity 23, only referenced inside the file. Looks like a one off experiment script.
- src/enhancement/enhancement_benchmark.py: `_full_frame_sr_then_crop`, four result fields that are set and never read, and `benchmark_enhancement` at complexity 43.
- src/demo/demo.py and split_screen.py: `add_bottom_right_labels`, `make_skip_card`, `make_hold_frames`, `make_metrics_card`, `fit_frame`, `draw_label`.
- src/compression/roi_encoder.py (1256 lines): `build_kwargs_at`, `scene_is_static`, `background_motion_score`, `encode_frame_sequence`, `get_file_size`. `encode_segment` appears 73 times across src and tests, so confirm which class each hit belongs to first.
- src/gui: `any_tokens_configured` and `push_targets` in device_tokens.py, `is_server` in edition.py, `_require_basic_auth` and `_csrf_guard` (check whether they are registered through a decorator before calling them dead).
- src/enhancement/plate_reader.py: unused result fields and the `ocr_available` property. src/enhancement/enhancer.py: `active_scale`.
- 32 places that swallow an exception with `pass`. These are not dead code, but each should at least log at debug level so failures leave a trace.

## Phase 3: cut unnecessary complexity

Order by risk and payoff, one function per commit, tests green before and after:

1. `run_pipeline` (123). Split along its stages, keeping the same call order and the same outputs. This function is the core path, so first add or confirm characterization tests that pin its outputs for a short clip in every mode, then extract.
2. The route handlers over 25: `api_start`, `api_library_videos`, `api_encrypt`, `api_decrypt`. Move validation into small helpers and return early on bad input.
3. `purge_once`, `estimate`, `scan_once`, `_hls_annotator_thread`.
4. Replace long if/elif chains on a string with a dictionary of handlers.

Techniques that apply: guard clauses instead of nested ifs, extract method into named helpers, group repeated exit conditions into one named boolean helper, dictionary dispatch, and polymorphism only where behavior truly depends on type. Pitfalls named by the sources: moving complexity into more functions without reducing it, gaming the metric, and premature abstraction.

Compression refactors go on their own branch off main with the retention and size checks rerun, never on the redesign branch.

## Phase 4: test ladder (from the first video)

Mapping of the video's rungs to what SVCS has and lacks:

- CI/CD: present. Phase 1 adds gates.
- Unit: strong (about 2100 tests). Gap: property based tests with hypothesis for the path confinement helpers and for the rule that compression never grows a file.
- Integration: Flask test client tests exist for most blueprints. Gap: one test that chains upload, compress, library list and delete.
- End to end: none today in CI. The video's point is that an agent can now write and run these cheaply. Plan: a small Playwright suite (Library select and delete, Upload, Settings) driven against run_gui on 127.0.0.1, run on Linux in CI. The browser checks done by hand in this project already live in outputs/design_review and can seed it.
- Performance: some perf tests exist (names starting test_perf). Gap: a budget on library listing for 5,000 files and on thumbnail generation.
- Mutation testing (mutmut or similar) on src/gui/services/path_safety.py only, as a one time check that its tests fail when its logic is broken.

## Phase 5: the 20 security points from the second video

Status key: "checked" means I looked at the code or ran a search in this session. "Not checked" means open work.

- Exposed .git folder and source maps: checked. No .map, .env or key files are tracked (only a test temp file turned up on disk). Still to confirm: the packaged app and the static route never serve repo files.
- Open redirect: checked. No redirect calls exist in src.
- Clickjacking: checked. X-Frame-Options DENY and a frame-ancestors CSP are set in src/gui/security_headers.py.
- SSRF: mostly checked. event_webhook.py calls the same `validate_push_url` as push_notify.py, pins the connection to the validated addresses and refuses redirects. update_manager.py (GitHub releases URL), usage_stats.py and rtsp_server.py (mediamtx release URL) use hardcoded https URLs, not user input. The asset download URL at update_manager.py line 315 comes from the GitHub release JSON and is not checked for scheme or host, and the saved file name is the last part of that URL. The installer is only run after a SHA256 check, which limits the damage, but the checksum URL also comes from the same release data. Small hardening, not yet done: require https and the github.com host family, and take the file name from the asset record. Not checked: the ruff scheme audits on the other urlopen calls.
- Path traversal: partly checked. Library routes confine paths. rtsp_server.py extracts tar files with the data filter on current Python but falls back to unfiltered extraction on older Python, and extracts zip files with no filter. Plan: require Python 3.11.4 or newer, or validate member names before extraction.
- SQL injection: partly checked. Four f-string built queries (files_bp.py twice, nl_query.py, db/queries.py). The pieces I read use fixed fragments and question mark parameters. Not checked: every fragment source.
- Weak secret: partly checked. SECRET_KEY is persisted from a file or generated. Not checked: key length and file permissions.
- Credential stuffing and user enumeration: not checked. A login throttle exists in auth.py. Confirm it is per client address and that failure messages are identical.
- Race conditions: not checked. One concurrency test (two devices writing tokens) failed intermittently earlier and is still unexplained. Treat it as a real signal until proven otherwise.
- Request size limits: checked, REAL FINDING, FIXED. Both upload routes now enforce one configurable per-file cap, default 8 GB (matching the old chunked cap), stored by src/utils/upload_limits.py and changed from Settings, UPLOAD SIZE LIMIT, through GET/POST /api/upload/limit (password only, a device token gets 403; allowed range 0.1 to 1024 GB). `/api/upload` refuses by Content-Length and also bounds bodies sent without one; the chunked route also caps each chunk body at 16 MB so it cannot be read whole into memory (the phone app uses at most 4 MB). Not done: an app wide MAX_CONTENT_LENGTH for the JSON routes. Not verified: a real multi gigabyte upload through a browser.
- Third party scripts (the polyfill.io case): checked, REAL FINDING, not fixed. src/gui/templates/index.html line 11 loads `https://cdn.jsdelivr.net/npm/hls.js@latest` with no version pin and no integrity hash, so a compromised or changed upstream release runs in the dashboard. Fonts from Google are also loaded (CSS only). Status: FIXED by vendoring hls.js 1.7.4 (Apache-2.0, npm tarball checked against the registry integrity value) under src/gui/static/js/vendor, same pattern as uPlot. tests/test_no_external_scripts.py fails if any template loads an external script. Not verified: live HLS playback in a browser (the file loads, serves with 200 and defines the Hls global).
- Debug mode: checked. app.run uses debug=False.
- Hardcoded secrets: checked by tool. The three ruff hits are constant names, not secret values.
- Not applicable to this app: Next.js headers, Supabase storage, price from the browser, SMS pumping, prompt injection (the natural language search is a rule parser, not a model), subdomain takeover, account pre-hijacking, reset poisoning.
- Small fix done in wave 1: the thumbnail cache key hash now declares it is not for security, which silences the scanner and states the intent.

## Techniques gathered

From pages fetched during this session: vulture prefers whitelist files over ignore flags, can ignore functions by decorator (Flask routes are its own example), and sets a confidence ladder (100 for unreachable code, 90 for imports, 60 for everything else). The Flask hardening reference lists debug off, a strong secret from the environment, secure cookie flags, CSRF protection for state changing routes, security headers, upload size and type limits with server made filenames, redirect validation, SSRF allow lists, and request size limits. A Python supply chain guide recommends layered controls: hash pinned requirements, a pip audit run in CI, ruff S rules, dependabot, SBOM generation, trusted publishing instead of long lived tokens, and pinned workflow actions. A refactoring guide gives radon grades (A 1 to 5, B 6 to 10, C 11 to 20, D 21 to 30, E 31 to 40, F 41 and up), suggests a gate between 10 and 15 for new code, and a ratchet for legacy code.

Not verified: these are summaries of what each page said, read through a fetch helper. I ran vulture, radon and ruff on this repo and did not try the other tools.

## Order of work

1. Merge wave 1 (config, tiny removals).
2. Phase 1 gates, one pull request.
3. Phase 2 batches, smallest first.
4. Characterization tests for `run_pipeline`, then Phase 3.
5. Phase 5 open items, since a few could be real bugs.
6. Phase 4 end to end suite last, once the code under it stops moving.
