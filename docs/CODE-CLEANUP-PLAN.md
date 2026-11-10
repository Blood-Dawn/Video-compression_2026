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
2. A pip audit step against the lockfile export. It reads the OSV database. Run it on every push. Status: done and BLOCKING. It was first added report only; after the lockfile upgrade below it is a hard gate. Run locally on 2026-11-09 against requirements.txt, pip-audit 2.10.1 found 168 advisories across 15 of 131 locked packages: pillow (64, fix 13.0.0), mistune (30), jupyterlab (17), tornado (16), jupyter-server (13), notebook (4), bleach (3), setuptools (3), urllib3 (3), anyio (2), certifi (2), cryptography (2, fix 50.0.0), idna (2), soupsieve (6), werkzeug (1, fix 3.1.9). A hard gate would fail CI today. Lockfile upgraded on 2026-11-09 (14 packages, uv lock --upgrade-package each, see the commit message): pip-audit now reports 0 of 131. setuptools could not be upgraded because another package pins it lower, and it is not flagged in the exported requirements. Not verified: which of these packages ship in the installer versus dev only, and a real CI run.
3. A complexity ratchet: fail only when a new or changed function goes above 15 (radon grade C). Existing hotspots are listed in Phase 3 and are not blocked. Status: done as scripts/complexity_ratchet.py plus scripts/complexity_baseline.json (39 functions above 15 recorded; radon 6.0.1 pinned in the CI step). The ratchet compares against the baseline, not against git changes, so a function that is not in the baseline fails even if untouched. Not verified: a real CI run.
4. Pin GitHub Actions to commit SHAs and add a dependabot file for pip and github actions. Audit the workflows once with zizmor. Status: done. Every `uses:` line is pinned to the commit SHA the GitHub API returned for its major tag (version kept in a trailing comment); .github/dependabot.yml updates github-actions and uv weekly with a 7 day cooldown; zizmor 1.32.0 offline found 17 issues (no permissions blocks, checkout persisting credentials, dependabot cooldown, a cache poisoning error in appimage.yml) and now reports none after adding `permissions: contents: read` to each workflow, `persist-credentials: false` on every checkout, and turning the setup-uv cache off in the release tag AppImage build. Checked first that no workflow pushes, releases or uses secrets. Not verified: a real GitHub Actions run of any workflow, and zizmor's online audits (it ran with --offline).
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
- Functions that only tests call (about 35, for example `compute_psnr`, `compute_ssim`, `MultiFrameSource`, `is_video_ext`, `list_profiles`, `bind_exposure_warning`, `push_targets`): DECIDED by the owner to keep them and their tests. Nothing to delete.

Candidates, each needing the check above before deleting (the items above are already triaged):

- src/compression/layer_encoder.py: `LayerSegmentEncoder` is defined once in src and referenced only by tests. Its `add_frame` is complexity 30. Likely the whole file.
- src/background_subtraction/tuning_experiment.py: `train_subtractor` and a `main` of complexity 23, only referenced inside the file. Looks like a one off experiment script.
- src/enhancement/enhancement_benchmark.py: `_full_frame_sr_then_crop`, four result fields that are set and never read, and `benchmark_enhancement` at complexity 43.
- src/demo/demo.py and split_screen.py: `add_bottom_right_labels`, `make_skip_card`, `make_hold_frames`, `make_metrics_card`, `fit_frame`, `draw_label`.
- src/compression/roi_encoder.py (1256 lines): `build_kwargs_at`, `scene_is_static`, `background_motion_score`, `encode_frame_sequence`, `get_file_size`. `encode_segment` appears 73 times across src and tests, so confirm which class each hit belongs to first.
- src/gui: `any_tokens_configured` and `push_targets` in device_tokens.py, `is_server` in edition.py, `_require_basic_auth` and `_csrf_guard` (check whether they are registered through a decorator before calling them dead).
- src/enhancement/plate_reader.py: unused result fields and the `ocr_available` property. src/enhancement/enhancer.py: `active_scale`.
- 32 places that swallow an exception with `pass`. Reviewed 2026-11-09 and deferred: all but one are in GUI services and utilities, each is a deliberate best effort guard (history, telemetry, persistence, cleanup) and most already carry a comment saying so. The one in compression is a cache read in vmaf_target.py. A blanket debug log would add noise at 32 sites for little gain; if wanted, start with the ones with no comment (cpu_sampler.py:75, cloud_detection.py:309, gui_state_persist.py:78 and 106, path_safety.py:138 to 179, hls_runner.py:438, retention.py:108 and 135).

## Phase 3: cut unnecessary complexity

Order by risk and payoff, one function per commit, tests green before and after:

1. `run_pipeline` (123, now 117 after the first extraction; progress below). Split along its stages, keeping the same call order and the same outputs. This function is the core path, so first add or confirm characterization tests that pin its outputs for a short clip in every mode, then extract.
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
- SSRF: mostly checked. event_webhook.py calls the same `validate_push_url` as push_notify.py, pins the connection to the validated addresses and refuses redirects. update_manager.py (GitHub releases URL), usage_stats.py and rtsp_server.py (mediamtx release URL) use hardcoded https URLs, not user input. The asset download URL at update_manager.py line 315 comes from the GitHub release JSON and is not checked for scheme or host, and the saved file name is the last part of that URL. The installer is only run after a SHA256 check, which limits the damage, but the checksum URL also comes from the same release data. Status: FIXED. `_is_trusted_asset_url` in update_manager.py now accepts only https on github.com under this repo's release download path with a plain file name (no userinfo, port, percent escapes, backslashes or extra segments). check_for_update ignores other links and _download_and_verify refuses them before any network call. The existing tests moved from example.invalid links to a github.com release path. Not checked: the ruff scheme audits on the other urlopen calls.
- Path traversal: checked, FIXED. Library routes confine paths. The MediaMTX download now goes through `_safe_extract` in rtsp_server.py for both zip and tar: every member name is checked before anything is written (no absolute paths, drive letters, `..` or resolution outside the folder), tar links and special files are refused, and the stdlib data filter is still applied where Python has it. tests/test_rtsp_safe_extract.py covers good and hostile archives. Not verified: a real MediaMTX download and extract.
- SQL injection: checked, clean. The four f-string queries (files_bp.py twice, nl_query.py, db/queries.py) join only literal fragments, module constants and a column and operator chosen from fixed choices; every user value goes through a `?` placeholder.
- Weak secret: checked, small gap, FIXED (see Findings). SECRET_KEY is 32 random bytes from os.urandom and device tokens use token_urlsafe, which is fine. Two gaps in src/gui/app.py: the key file is written and only then chmod 600, so on POSIX it is briefly readable by others, and an empty or short key file is accepted as is. Proposed fix: create it with mode 0600 from the start and regenerate if shorter than 32 bytes.
- Credential stuffing and user enumeration: checked, fine. auth.py throttles per socket address (10 failures in 5 minutes locks that address out for 5 minutes, X-Forwarded-For is not trusted), compares in constant time, and returns the same 401 for a wrong user and a wrong password. The bearer path is throttled the same way. The first unauthenticated request is not counted so browsers are not locked out on load.
- Race conditions: checked, not reproduced. Every read-modify-write in device_tokens.py holds one RLock and writes by temp file plus os.replace. I ran the two device concurrency test and the durability tests 40 times alone with no failure. The earlier intermittent failure is unexplained; the only gap I can see is that os.replace can raise PermissionError on Windows when antivirus or a sync client holds the file, which is not retried. Not changed. Note for anyone running tests: do not run two pytest processes at once, they share .pytest_tmp and produce spurious failures (I caused five that way and a clean rerun passed).
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

## Findings during the cleanup (all three FIXED with owner approval on 2026-11-09)

- Segment files overwrite each other. The output name is `<camera>_<UTC timestamp to the second>.mp4` (roi_encoder.py, three places). When a file is processed faster than real time and several segments finish inside one second, the later ones silently replace the earlier ones, while the index database still lists every segment. Reproduced on 2026-11-09 with parking_input.mp4 (100 s), segment_seconds 5: 20 segments logged and indexed, 7 files on disk. With the default 60 s segments on that clip the two segments land seconds apart, so normal use is mostly safe, but any short segment length on a file import can lose footage. FIXED: `_unique_segment_path` gives later segments of the same second a `_1`, `_2` suffix; the database timestamp is unchanged. Same clip and settings now give 20 files and 20 distinct indexed paths. Standard output is unchanged (modes 0, 1 and 3 byte identical).
- Spurious 500 on a device endpoint write. `os.replace` in device_tokens.py `_write_all` raised `PermissionError` (WinError 5) once in a full suite run (tests/test_push_endpoint_isolation.py::test_concurrent_writes_from_two_devices_never_cross, 2026-11-09), which is the unexplained intermittent failure noted under race conditions. All writers share one lock, so the target was held by something outside the process lock, most likely antivirus or an indexer scanning the freshly written file. The result is one failed PUT (500), not a corrupted store. It did not reproduce in 40 isolated runs. FIXED: `_replace_with_retry` tries up to 6 times with a short growing pause on PermissionError only. The real sharing violation could not be reproduced on demand, so the retry is tested with an injected error.
- SECRET_KEY file creation: FIXED. gui/secret_key.py creates the file with mode 0600 in the open call and replaces any key shorter than 32 bytes. POSIX permissions are only asserted at the creation call here (Windows machine).

## Phase 3 progress

- `run_pipeline` extraction 1: `_resolve_foreground_crf`, `_resolve_codec` and `_resolve_background_crf` pulled out as pure functions with the same rules (tests/test_pipeline_resolvers.py pins every mode and override). Complexity 123 to 117. Real clip check with scripts/pipeline_characterize.py on parking_input.mp4 (100 s, 320x240): modes 0, 1 and 3 byte identical to the unmodified code with identical detection counts (mode0 2 files 1,157,739 bytes, mode1 126,690, mode3 35,337, 182 detections in each); mode2 is not deterministic run to run (91,306 to 91,357 bytes across runs of the same code) and stayed inside that range with the same detection count.

- `run_pipeline` extractions 2 and 3: `_load_zone_event_setup` (117 to 112), then `_apply_vmaf_target` and `_resolve_max_bitrate_kbps` (112 to 103). Each checked with scripts/pipeline_characterize.py on parking_input.mp4 against the recorded run of the original code: modes 0, 1 and 3 byte identical with 182 detections, mode2 inside its normal 91,306 to 91,357 byte range. Not covered by that clip: a saved zone or line config, `target_vmaf` set (needs libvmaf), encryption, enhancement and live sources. The rest of run_pipeline is the main loop, which closes over a lot of shared state; splitting it is the risky part and needs its own characterization first, so it stops here for now.
- `api_start` (29 to 11): `_parse_input_source`, `_validate_encrypt_inputs`, `_build_start_config`. Verified by loading the previous file from git and posting 31 payloads to both versions: identical status, error text and config for all 31.
- `api_library_videos` (27, now under 15): `_parse_ext_filter`, `_filter_library_items`, `_sort_library_items`. Same method with 401 random query combinations: identical. One pre-existing quirk is pinned by a test: spaces around a comma separated extension stay inside the extension.
- Skipped on purpose: `api_encrypt` and `api_decrypt` (encryption code). Handed to Victor with a full plan in docs/ENCRYPTION-CLEANUP-PLAN.md.
- `/api/start` bad numbers: DONE with owner approval. A non numeric `crf`, `background_crf`, `enhance_every_n`, `enhance_max_roi_px` or `filter_confidence` now returns 400 with `{"error": "<field> must be a number"}` instead of a 500. Reason: RFC 9110 uses 400 for a client error and 500 for a server fault, and every other bad field in this handler already returned 400. Checked against the old file: only those cases changed.
- `retention.estimate` (28, now under 15): `_folder_usage`, `_estimate_bytes_per_day`, `_headroom_days`. Checked against the old file on 225 scenarios (file layouts, policies, history values, disk states): identical.
- `autocompress_runner.scan_once` (25, now under 15): `_scan_settings`, `_find_candidates`. The batch ownership and locking code was not touched. Checked on 216 scenarios (all six profiles, overrides, stability outcomes): identical.
- `hls_runner._hls_annotator_thread` (31 to 18): `_open_capture`, `_probe_frame_size`, `_build_hls_ffmpeg_cmd`, and the three nested watchers lifted to module level. Checked by running old and new on a real 3 s clip with a fake ffmpeg: identical command, 77 identical frames, identical state in all five cases. Not covered: a real RTSP stream and its 10 s timeout.
- `retention.purge_once` (29 to 13): `_purge_candidates`, `_purge_by_age`, `_purge_by_size`. `_delete` (the confinement and in-flight guard before each unlink) and the order of operations were not touched. Checked on real temp folders against the old file: 120 scenarios (layouts, eight policies, an in-flight file, an undeletable read only file), identical summaries and identical surviving files. The index prune and notification were stubbed in the comparison so real data could not be touched.
- `nl_query.parse` (22 to 4): one function per stage (`_parse_time_windows`, `_parse_dates`, `_parse_camera`, `_parse_counts`, `_parse_word_filters`), same order. Checked against the old file on 4005 random phrases: identical, 739 distinct combinations of understood filters. Pinned quirk: `cam-a1` is read as camera `-a1`.
- `api_segments` (22 to 5): `_segment_filters`, `_query_segment_rows`, `_cpu_stats_for_dir`, `_segment_to_json`. SQL and response fields moved verbatim; every filter fragment is still a literal with bound parameters. Checked on 501 requests against two real metadata databases (plus a corrupt one): identical.
- Second branch (chore/code-quality-wave2, stacked on the first): `benchmark_enhancement` (43 to 13: `_empty_result`, `_resolve_enhancer`, `_setup_ocr`, `_new_accumulators`, `_accumulate_frame`, `_summarize_variants`, `_compute_deltas`), checked on 648 scenarios with a generated mp4 and fake enhancers and OCR backends, every result field identical; `render_demo` (30 to 14: `_group_records_by_segment`, `_probe_output_geometry`, `_open_segment_source`, `_fill_gap`, `_next_source_frame`), checked on 91 scenarios with a recording writer that hashes every frame, identical frames and error messages; `_detect_gdrive_root` (23 to 4: one helper per lookup source), checked on 48 registry and home folder layouts, identical. Harness lesson: two loaded copies of a dataclass are different classes and never compare equal, so compare with `dataclasses.asdict`.
- Encryption routes handed to Victor: docs/ENCRYPTION-CLEANUP-PLAN.md and GitHub issue 53.
- Still open from the Phase 3 list: `LayerSegmentEncoder.add_frame` (30, tests only), `analyze_video` (23), `main` in tuning_experiment (23), `find_crf_for_target` (22, compression code so it needs the real clip check), `read_plates_from_video` (21), `api_encrypt` and `api_decrypt` (Victor), and the main loop of `run_pipeline`.

## Numbers, 2026-11-09 (baseline at the start of the cleanup in brackets)

- Tests: 2503 passed, 47 skipped, 0 failed [2140 passed, 46 skipped, 0 failed]. The 363 more passing tests cover the new features and the pinned helpers.
- run_pipeline complexity 103 [123]. Grade D or worse functions: 8 [19]. Functions above 15 in the ratchet baseline: 29 [39].
- vulture at 80 percent: 0 findings [0]. At 60 percent: 80 lines [80]; two of those are `request.max_content_length = ...` assignments, which are false positives.
- pip-audit: 0 of 131 packages with advisories [15 packages, 168 advisories]. zizmor offline: 0 findings [17].
- Not verified anywhere in this cleanup: a real GitHub Actions run, the new Settings panel in a browser, large real uploads, and super-resolution on real images with pillow 13.
