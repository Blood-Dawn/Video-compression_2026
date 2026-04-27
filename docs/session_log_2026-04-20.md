# Session Log — 2026-04-20

**Author:** Kheiven D'Haiti (Bloodawn)
**Branch:** `dev`
**Milestone:** 3 — Live stream pipeline, GUI overhaul, logging hardening

---

## Summary

This session focused on three areas that came out of the first successful live-stream test: fixing the compression pipeline to draw ROI bounding boxes on output .mp4 files (they were missing), enabling real RTSP/HTTP URLs as pipeline input sources (crashing with a `RuntimeError` before this fix), and overhauling the dashboard layout and logging so the GUI is ready for sponsor demos. Also fixed a persistent bug where switching video sources after a server restart would play back the old stream. Confirmed the full pipeline works end-to-end against a VLC-served RTSP stream using `cameraJitter_traffic.mp4`.

---

## For Team Members — What to Expect After Pulling

Pull the `dev` branch and restart the server. No new dependencies were added so you do not need to re-run `uv sync` or `pip install`. The changes are all in existing Python source files and the HTML template.

### What changed and why

**`src/utils/frame_source.py` — RTSP/HTTP URLs now work as pipeline input**

Before this fix, if you typed an RTSP URL like `rtsp://localhost:8554/live` into the Pipeline Config input field, the server crashed immediately with:

```
RuntimeError: Input path does not exist: rtsp://localhost:8554/live
```

This happened because `FrameSource` passed the URL through Python's `Path()` constructor, which on Windows mangles `rtsp://` into a backslash-separated path that doesn't exist on disk. The fix detects any URL scheme (`rtsp://`, `http://`, `https://`, `rtmp://`, `rtsps://`) before `Path()` is ever called, and routes those directly to `cv2.VideoCapture`. The rest of the pipeline is unchanged — it doesn't know or care whether the source is a file or a stream.

**What this means for you:** Any IP camera, RTSP relay, or HTTP MJPEG stream can now be used as a pipeline input source. If you are testing with a local video, nothing changes.

---

**`src/compression/roi_encoder.py` — ROI boxes now appear in saved segments**

The output `.mp4` files in `outputs/` had no green bounding boxes even when vehicles or people were detected. The encoder was using the bounding box data to pick the compression quality (CRF 18 for foreground, CRF 40 for background) but never drawing the rectangles before encoding. This fix adds a `cv2.rectangle()` pass on each annotated frame before it gets piped to FFmpeg. Background-only segments are unaffected — no extra processing happens when there are no detections.

**What this means for you:** Open any new segment in the dashboard player that has `TARGET: YES` — you will see green boxes around detected objects. Old segments already in `outputs/` will not be retroactively annotated.

---

**`src/gui/app.py` — Logging writes to a file + HLS stale segment fix**

Two things changed here:

1. **Log file.** The server now writes a full debug log to `outputs/svcs.log` every time it runs. The browser SSE stream and terminal still show INFO-level messages. The file gets DEBUG-level output — pipeline internals, frame counts, FFmpeg stderr. A shutdown timestamp is written automatically when you stop the server. If something goes wrong and you need to show a log to Kheiven or paste it into a support channel, this is the file to grab.

2. **HLS stale video bug.** If you stopped the server, changed the input source, and restarted, the browser would play back the old video instead of the new one. This happened because old `.ts` segment files stayed on disk and FFmpeg continued the old playlist sequence. The fix clears all `.ts` and `.m3u8` files from the HLS output directory before each new stream starts. It also adds a timestamp to the playlist URL so the browser doesn't serve a cached copy. You should no longer need to hard-refresh the page when switching sources.

---

**`src/gui/templates/index.html` — Layout and tooltip changes**

The log panel is now hidden by default. When you open the dashboard you will see the Output Segments table taking up the full bottom area. To open the log terminal, click the **▶ LOG** button in the top-right corner of the segments panel. Click **✕ LOG** to close it again.

Hovering over any row in the Output Segments table now shows a tooltip with the estimated raw file size and the calculated compression ratio for that segment.

Column headers for Target, ROIs, and Size have `ⓘ` icons — hover them to see what each column means.

---

### Quick sanity check after pulling

1. `git pull origin dev`
2. `python src/gui/app.py` (or `python run_gui.py`)
3. Open `http://localhost:5000`
4. The bottom panel should show Output Segments full-width with no log panel visible
5. Click **▶ LOG** — the log panel should appear on the right
6. Run a short pipeline on any CDnet clip — the output segment should have green ROI boxes in the player

If you have VLC installed and want to test the RTSP path:
```powershell
& "C:\Program Files\VideoLAN\VLC\vlc.exe" `
  "data\samples\cdnet_mp4\cameraJitter\cameraJitter_traffic.mp4" `
  --sout "#rtp{sdp=rtsp://:8554/live}" --sout-keep --loop
```
Then set the Pipeline Config input to `rtsp://localhost:8554/live` and start the pipeline.

---

## Bugs Fixed

### 1. ROI bounding boxes missing from pipeline output segments

**File:** `src/compression/roi_encoder.py`

`encode_segment()` received `bboxes_per_frame` (list of `(x, y, w, h)` tuples) but only used it to choose the CRF value — it never drew the rectangles. The frames piped to FFmpeg were raw, unannotated.

**Fix:** Added a `cv2.rectangle()` loop that annotates frame copies before they are piped to FFmpeg stdin. Only runs when `has_targets` is True to avoid unnecessary copies on background-only segments. Clamps coordinates to frame bounds before drawing.

```python
if has_targets:
    annotated_frames = []
    for frame, boxes in zip(frames, bboxes_per_frame):
        if boxes:
            f = frame.copy()
            for bx, by, bw, bh in boxes:
                x1 = max(0, bx); y1 = max(0, by)
                x2 = min(w, bx + bw); y2 = min(h, by + bh)
                if x2 > x1 and y2 > y1:
                    cv2.rectangle(f, (x1, y1), (x2, y2), (0, 255, 0), 2)
            annotated_frames.append(f)
        else:
            annotated_frames.append(frame)
    raw = b"".join(f.tobytes() for f in annotated_frames)
else:
    raw = b"".join(f.tobytes() for f in frames)
process.communicate(input=raw)
```

Also added `import cv2` at the top of `roi_encoder.py`.

---

### 2. RTSP/HTTP URLs crash with "Input path does not exist"

**File:** `src/utils/frame_source.py`

`FrameSource.__init__()` wrapped `input_path` in `Path()` and called `.is_file()` / `.is_dir()`. On Windows, `Path("rtsp://localhost:8554/live")` mangles the URL into a backslash-separated path that resolves to nothing, so `.is_file()` returns False and the code fell through to `raise RuntimeError(f"Input path does not exist: {input_path}")`.

**Fix:** Added URL scheme detection before any `Path()` construction. Any input starting with `rtsp://`, `rtsps://`, `rtmp://`, `http://`, or `https://` is routed directly to the new `_init_video_url()` method, bypassing all filesystem checks.

```python
_URL_SCHEMES = ("rtsp://", "rtsps://", "rtmp://", "http://", "https://")
if any(input_path.lower().startswith(s) for s in _URL_SCHEMES):
    self._init_video_url(input_path)
    return
```

`_init_video_url()` calls `cv2.VideoCapture(url)` directly. Width/height may read as 0×0 on initial connection for live RTSP streams — the pipeline probes the first real frame for dimensions.

---

### 3. HLS stream plays old video after switching sources / server restart

**File:** `src/gui/app.py`

Two causes:
- Old `.ts` segment files remained on disk from the previous session. FFmpeg picked up where the old playlist left off, serving stale content.
- The `append_list` flag in the FFmpeg HLS command made FFmpeg continue the old playlist's segment sequence numbers rather than starting fresh.

**Fix:**
1. Delete all `*.ts` and `*.m3u8` files in the HLS output directory before launching FFmpeg.
2. Remove `append_list` from the `hls_flags` string.
3. Add a `?t=<unix_timestamp>` cache-buster to the playlist URL returned to the client so hls.js treats it as a new stream.

---

### 4. Corrupt RTSP log message

**File:** `src/gui/app.py`

Log line was producing `"Local RTSP server started — rtsp://localhost:rtsp://localhost:8554/live"` because the f-string substituted the full URL string into a prefix that already contained `rtsp://localhost:`.

**Fix:** Hardcoded the correct string: `"Local RTSP server started — listening on rtsp://localhost:8554/"`.

---

## Features Added

### Robust multi-handler logging with file output

**File:** `src/gui/app.py`

The previous setup had a single `_QueueLogHandler` attached at `INFO` level with no file output. Replaced with a three-handler setup:

| Handler | Destination | Level |
|---|---|---|
| `_queue_handler` | Browser SSE stream | INFO |
| `_file_handler` | `outputs/svcs.log` | DEBUG |
| `_console_handler` | `stderr` | INFO |

Root logger set to `DEBUG` so the file captures everything (pipeline internals, frame counts, FFmpeg stderr) while the browser only gets INFO and above.

Registered `_write_shutdown_log()` via `atexit` — writes a timestamped shutdown marker and flushes the file handler on clean exit. The log file can be fed directly to Claude or any reviewer for post-mortem debugging.

---

### HLS annotator thread: ROI boxes + mode overlay on live stream

**File:** `src/gui/app.py`

Rewrote the HLS pipeline from a direct FFmpeg subprocess (no annotations) to a Python thread that:
1. Opens the input source with `cv2.VideoCapture`
2. Runs background subtraction on each frame
3. Draws green ROI bounding boxes on detected regions
4. Burns a semi-transparent info box in the top-left corner showing the current mode label and elapsed time (`_draw_corner_overlay()`)
5. Pipes annotated frames to FFmpeg stdin as rawvideo

This makes the live HLS stream match the demo output visually — the sponsor sees the same annotations in the browser player as in the saved segments.

---

### Dashboard layout overhaul

**File:** `src/gui/templates/index.html`

Previous layout split the bottom panel 50/50 between output segments and the log terminal, making the segments panel cramped by default.

Changes:
- `#content-bottom` defaults to `grid-template-columns: 1fr` (segments full-width)
- `#log-panel-container` is `display: none` by default
- Added `▶ LOG` button in the output segments header; clicking it toggles `.log-open` class on `#content-bottom`, which switches to `1fr 1fr` and makes the log panel visible
- Button text updates to `✕ LOG` when open, `▶ LOG` when closed

---

### Segment hover tooltip with compression ratio

**File:** `src/gui/templates/index.html`

Added a fixed-position `#seg-tooltip` div that appears when hovering a row in the output segments table. Shows:
- Estimated raw file size (computed as `duration_s × width × height × 3 bytes × fps / 1e6`)
- Actual compressed size
- Estimated compression ratio

Column headers for Target, ROIs, and Size now show `ⓘ` icons with `title` tooltips explaining what each column means.

---

## Live Stream Testing

Confirmed the full pipeline works against a real RTSP stream:

- Source: VLC re-streaming `cameraJitter_traffic.mp4` via `--sout "#rtp{sdp=rtsp://:8554/live}" --sout-keep --loop`
- Pipeline input: `rtsp://localhost:8554/live`
- Output: Two segments visible in the dashboard, both tagged `vehicle`, 1.6–1.8 MB, green ROI boxes visible in the inline player

VLC command used (for future reference):
```powershell
& "C:\Program Files\VideoLAN\VLC\vlc.exe" `
  "C:\Users\kheiven\Documents\GitHub\Video-compression_2026\data\samples\cdnet_mp4\cameraJitter\cameraJitter_traffic.mp4" `
  --sout "#rtp{sdp=rtsp://:8554/live}" --sout-keep --loop
```

---

## Known Remaining Issue

Mode label and timelapse timer are not yet burned into regular pipeline output `.mp4` segments — only into the HLS live stream. The `DemoMetadataWriter` handles demo mode overlays, but `encode_segment()` in the main pipeline does not call it. This is a pending fix for the next session.

---

## Files Changed

| File | Type | Description |
|---|---|---|
| `src/utils/frame_source.py` | Bug fix | Added URL scheme bypass; new `_init_video_url()` method |
| `src/compression/roi_encoder.py` | Bug fix | Added cv2 ROI box drawing before FFmpeg pipe |
| `src/gui/app.py` | Feature + bug fix | Multi-handler logging, file output, atexit shutdown marker, HLS annotator thread, HLS stale segment cleanup, cache-busting playlist URL |
| `src/gui/templates/index.html` | Feature | Log toggle layout, segment hover tooltip, column header tooltips, MB display for large files |
| `src/utils/rtsp_server.py` | New file | MediaMTX manager for local RTSP relay (added previous session, untracked until now) |
| `docs/live_stream_and_compression.md` | New file | Notes on live stream architecture and HLS pipeline design |

---

*2026-04-20 — Kheiven D'Haiti (Bloodawn)*
