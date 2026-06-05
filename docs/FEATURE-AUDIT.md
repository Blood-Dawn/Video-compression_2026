# SVCS feature audit (R2.1)

Date: 2026-06-05. Branch `app`, version 2.1.0.dev0. Method: live server on
127.0.0.1, exercised through the Preview MCP (browser) and direct API calls
against the running app, plus the automated `tests/test_end_to_end_smoke.py`
(every read-only route returns non-5xx JSON). A real compression was run on a
generated 4 s clip and its output validated with ffprobe.

Legend: PASS = works as expected. FIXED = was broken, fixed in this round.
FOLLOW-UP = tracked below / in another task.

| Feature | How tested | Result | Notes |
|---------|-----------|--------|-------|
| Topbar tabs (HOME, UPLOAD, LIBRARY, METRICS, SEARCH, TOOLS, ENCRYPT) | Browser: switchTab each, assert page+button active | PASS | All 7 switch and activate. |
| Setup overlay (first run) | Browser: overlay shows, destinations list, save persists | PASS | Disables START until a destination is chosen; choice persists; encrypted defaults to `<output>/Encrypted`. |
| Sticky header | Browser: scroll at short viewport | PASS | Pinned, opaque, no bleed (FIX 3). |
| UPLOAD dropzone | Browser: element present, route exists | PASS | `#upload-input` present; `/api/upload` unchanged. |
| Presets | Browser: `#preset-select` populated from `/api/presets` | PASS | 11 presets load; applying sets mode/CRF/codec. |
| CRF / codec / verbose controls | Browser: inputs present; sent to `/api/start` | PASS | `crf-input`, `codec-select`, `verbose-toggle` all present and wired. |
| START a real compress (mode0) | API: POST `/api/start` on a 4 s clip, poll `/api/status` | PASS | Finished; status returned to not-running. |
| Output segment appears | API: `/api/segments` + on disk + ffprobe | PASS | `outputs/audit/audit_*.mp4` written; ffprobe reports `h264 320x240` (mode0 = H.264 per TASK 1.6). |
| Per-mode codec | ffprobe on output | PASS | mode0 produced H.264. Full per-mode matrix proven by `tests/test_real_videos.py` (R2.2). |
| Verbose logging | API: compress with `verbose:true`; unit test | PASS | Adds per-frame/per-segment detail (FIX 7); `test_verbose_logging.py` asserts more records. |
| METRICS: system metrics + per-mode CPU | API: `/api/system_metrics` | PASS | `cpu_pct` live; `mode_avgs` present (historical flagged, FIX 2). |
| METRICS: segments table | API: `/api/segments` | PASS | Populates after a run. |
| SEARCH: daily summary / busiest | API: `/api/daily_summary`, `/api/busiest` | PASS | Return real DB rows. |
| SEARCH: query segments | API: `/api/query_segments` | PASS | Requires an `object_type` filter (returns a clear 400 message without one); the SEARCH UI supplies it. By design, not a bug. |
| TOOLS: HLS + RTSP relocated | Browser: controls inside `#tab-tools-body` | PASS | Moved out of the sidebar (FIX 4). |
| TOOLS: RTSP MediaMTX detection | API: `/api/rtsp/status` | PASS | `binary_present: true` resolved via the robust resolver (FIX 5). |
| ENCRYPT: keygen | API: POST `/api/keygen` | PASS | Writes a 32-byte `camera.key`. |
| ENCRYPT: encrypt | API: POST `/api/encrypt` (password) | PASS | Wrote `Encrypted/<seg>.mp4.enc`, original kept. |
| ENCRYPT: decrypt round-trip | API: POST `/api/decrypt` (password) | PASS | Returned the decrypted MP4 (valid `ftyp`/x264 header). |
| Help overlay | Browser: open, sections render, deps check, reset | PASS | New sections present; "Check dependencies" lists ffmpeg/mediamtx/onnx; Reset wired (FIX 8/2). |
| Dependency status | API: `/api/setup/dependencies` | PASS | ffmpeg, ffprobe, mediamtx, onnx_model all resolve. |
| Factory reset | API: POST `/api/setup/reset` | PASS | Clears state, returns to first-run (FIX 2). |
| LIBRARY: tab + grid + detail + compress | Browser + API | FIXED in R2.3 | The tab, thumbnails, detail player, and compress-this all work when pointed at a folder with videos; the default folder is the (empty) output dir, so it showed "No videos" and looked broken. R2.3 adds a Browse folder picker, search, filters, a clear empty state, and persists the last folder. |
| Read-only API surface (28 routes) | `tests/test_end_to_end_smoke.py` | PASS | No route 5xxs on a clean install. |

## Findings and fixes

1. **Library "not working" (root cause).** The Library defaults to the chosen
   output folder, which is empty on a fresh install, so it correctly showed "No
   videos in this folder" with no obvious next step and no way to pick a folder
   except typing a path. Backend (`/api/library/*`) and the grid/detail/compress
   flow are sound. Addressed in **TASK R2.3** (Browse picker, search, filters,
   sort, clear empty state, persisted folder, thumbnail placeholder fallback).

2. **`/api/browse` is a native file dialog, not a folder navigator, and blocks.**
   It shells out to a tkinter `askopenfilename` dialog (a *file* picker) that
   blocks the request thread for the duration of the dialog (~28 s observed when
   no display interaction happens). It is excluded from the smoke test for that
   reason. R2.3 adds a dedicated *folder* picker rather than reusing this.

## Follow-ups (deferred)

- None blocking. The browse-dialog approach is desktop-only by nature (no remote
  folder picker); the Library in R2.3 offers both a native folder dialog and a
  typed path so remote/Docker users can still point at a folder.
- Real per-mode/per-codec proof on real footage is the job of
  `tests/test_real_videos.py` (R2.2); it runs the CDnet corpus through every mode
  and asserts valid + smaller + correct codec.

## Real-video integration test (R2.2)

`tests/test_real_videos.py` runs the real pipeline on the CDnet clips in
`data/samples/cdnet_mp4` (or set `SVCS_TEST_VIDEO_DIR` to point at any folder of
clips). It picks one clip per scene-type subfolder, trims a short window from
each to keep runtime bounded, and runs every clip through every mode, asserting
each output is a valid non-empty container (ffprobe), is far smaller than the raw
uncompressed size, and uses the correct per-mode codec (mode0/1 = H.264,
mode2/3 = AV1). It SKIPS cleanly when no clips are present (the corpus is
git-LFS, absent on CI).

Run `uv run --no-sync pytest tests/test_real_videos.py -s` to see real
compression ratios per clip and mode, and confirm each mode + codec works on
real footage. A sample run (8 scene types, 3 s window) validated 29 segments in
~21 s, with ratios versus raw ranging from ~65x (busy PTZ pan, mode1) to
~32000x (low-framerate port, mode3 object-only). No new media is committed.
Tune breadth with `SVCS_TEST_VIDEO_MAX` and the window with
`SVCS_TEST_VIDEO_TRIM`.
