# Live Stream and Compression - Architecture Notes
**EGN 4950C Group 16 - SVCS**
Last updated: Apr 20, 2026

---

## Option A - How the current system works (two independent features)

There are two completely separate systems in the dashboard right now. They do not share state, threads, or output. You can run both at the same time from the same source, but they operate independently.

---

### Feature 1 - HLS Live Stream (monitoring/preview)

This is the "Live Stream (HLS)" section in the sidebar. Its only job is to let you watch a camera feed in the browser with ROI overlays. Nothing gets recorded or saved to disk.

**Step by step - what happens when you click START STREAM:**

1. The browser POSTs to `/api/hls/start` with the input source, camera ID, and mode label.

2. Flask starts `_hls_annotator_thread` as a daemon thread. The route returns immediately - the thread does all the work.

3. The thread opens the source with `cv2.VideoCapture`. For RTSP, it uses a Python-level 10-second timeout (OpenCV's built-in timeout property is ignored on Windows pip builds). For local files, it opens instantly.

4. The thread reads `CAP_PROP_FRAME_WIDTH/HEIGHT`. RTSP streams return 0×0 before the first frame, so if dimensions are zero it reads frames until one arrives and gets the shape from that frame.

5. FFmpeg is launched as a subprocess receiving rawvideo from stdin:
   ```
   ffmpeg -f rawvideo -pix_fmt bgr24 -s {w}x{h} -r {fps} -i pipe:0
          -c:v libx264 -preset ultrafast -tune zerolatency -an
          -f hls -hls_time 2 -hls_list_size 5
          -hls_flags delete_segments+append_list
          outputs/hls/{camera_id}/playlist.m3u8
   ```

6. The frame loop begins. On every frame:
   - `BackgroundSubtractor.apply(frame)` updates the MOG2 model and returns the foreground mask.
   - After the first 30 warmup frames, `get_foreground_regions(mask)` returns a list of `ForegroundRegion` objects.
   - A green rectangle (`cv2.rectangle`) is drawn for each region.
   - A small corner overlay (`_draw_corner_overlay`) is drawn top-left showing the mode label and elapsed time (e.g. `MODE 0` / `00:01:23`).
   - The annotated frame is written to `proc.stdin` as raw bytes.

7. FFmpeg receives the rawvideo frames from stdin, encodes them to H.264, and writes 2-second `.ts` HLS segments to disk. The playlist file (`playlist.m3u8`) is updated after each segment.

8. The browser retries `GET /api/hls/{camera_id}/playlist.m3u8` every 2 seconds until it gets a 200. Once the playlist exists, `hls.js` attaches to the video element and starts playing.

9. A status poll runs every 1 second for the first 15 seconds (to catch fast connection failures), then drops to every 3 seconds. If `running=False` and `error` is set, the dashboard shows "Connection failed" or "Stream stopped" depending on the error text.

10. When you click STOP, Flask sets the stop event, terminates the FFmpeg subprocess directly, and sets `running=False`. The thread unblocks, closes stdin, waits for FFmpeg to flush, and exits.

**What the HLS stream does NOT do:**
- Does not write segments to the `outputs/` directory (HLS chunks go to `outputs/hls/` and are auto-deleted by FFmpeg after 5 segments)
- Does not write anything to `metadata.db`
- Does not apply Mode 1 frame-gating (every frame is always shown regardless of the mode label in the overlay)
- Does not apply dual-CRF encoding (FFmpeg uses `-preset ultrafast` for low latency, not the CRF 18/45 split)

---

### Feature 2 - Compression Pipeline

This is the "Pipeline Config" section at the top of the sidebar. It records, compresses, and archives footage to disk in real-time.

**Step by step - what happens when you click START:**

1. The browser POSTs to `/api/start` with the full config (input source, mode, segment duration, etc.).

2. Flask starts `_run_pipeline_thread` as a daemon thread. It patches `FrameSource.read()` and `ROIEncoder.encode_segment()` to increment the live frame/segment counters in the sidebar.

3. The thread calls `run_pipeline(...)` from `src/pipeline/pipeline.py`. The pipeline:
   - Opens the source with `FrameSource`
   - Runs `BackgroundSubtractor` on every frame to build the background model
   - Accumulates frames into a segment buffer (`segment_seconds` long, default 60s)

4. **Mode 0** - Every frame goes into the buffer. At the end of each 60-second window, `ROIEncoder.encode_segment()` fires regardless of whether any motion was detected.

5. **Mode 1** - Only frames where `get_foreground_regions()` returns at least one region are added to the buffer. Segments with zero motion frames are skipped entirely. This is where the storage savings come from on static cameras.

6. When a segment is ready, `ROIEncoder.encode_segment()` runs FFmpeg with the **dual-CRF** approach:
   - Foreground ROI regions: CRF 18 (high quality - these are the targets)
   - Background regions: CRF 45 (aggressive compression - these are just context)
   - This is what produces the 16.6× compression ratio at PSNR 41.2 dB

7. The encoded `.mp4` segment is written to `outputs/` and a row is inserted into `metadata.db` (timestamp, camera ID, ROI count, object type, file size, duration).

8. The dashboard polls `/api/status` every second and updates the frame counter, segment counter, FPS, and elapsed time in real-time.

9. When you click STOP, the stop event is set and the pipeline exits cleanly after finishing the current segment.

**Compression timing - it is neither "wait for space" nor "once per hour."** Compression happens continuously in real-time. One segment (60 seconds of footage by default) is compressed and written to disk every 60 seconds while the pipeline runs. There is no batch step.

---

### Running both at the same time

You can run the HLS stream and the pipeline simultaneously from the same source file or camera. They each open their own `VideoCapture` instance independently. The HLS stream gives you a live annotated preview in the browser while the pipeline records and compresses in the background. They do not interfere with each other.

---

---

## Option B - Integrated live-stream pipeline (future work)

> **For team members who want to build this out after the current milestone.**

Right now the HLS stream and the compression pipeline are two separate codebases that happen to use the same `BackgroundSubtractor`. Option B merges them so that a single frame loop drives both the live preview and the compression recording simultaneously.

### Why it matters

In a real deployed system, you would not run two separate OpenCV decode threads from the same camera. That wastes CPU and doubles the network load on the camera. Option B produces one decoded frame stream that fans out to both outputs.

Additionally, with Option B, Mode 1 would be **visually demonstrable in real-time**: when no motion is present, the HLS stream would show the static scene but no segment would be written to disk. A viewer watching the dashboard would see motion → green boxes appear → segment counter ticks up → exactly the mechanism the sponsor cares about, live.

### Architecture

The current architecture:

```
Camera/File → VideoCapture #1 → annotate → FFmpeg HLS
Camera/File → VideoCapture #2 → pipeline → ROIEncoder → disk
```

Option B architecture:

```
Camera/File → VideoCapture (single) → frame fan-out
                 ├─→ annotate + pipe to FFmpeg HLS
                 └─→ pipeline segment buffer → ROIEncoder → disk
```

### What would need to change

**New module: `src/pipeline/live_pipeline.py`**

A new `LivePipeline` class that replaces both `_hls_annotator_thread` and `_run_pipeline_thread` when running in live-integrated mode. It would:

- Own a single `FrameSource`
- On each frame: run `BackgroundSubtractor`, get ROI regions
- Write the annotated frame to the HLS FFmpeg stdin pipe
- Feed the frame into the segment buffer (gated by mode)
- On segment completion, hand off to `ROIEncoder` (can run in a second thread so it does not block the frame loop)

**Changes to `src/gui/app.py`**

- `api_hls_start` would accept an optional `compress=True` flag
- When `compress=True`, it starts `LivePipeline` instead of `_hls_annotator_thread`
- The status endpoint would return a unified state (stream running, segment count, etc.)

**Changes to `index.html`**

- A checkbox "Also compress to disk" in the HLS section
- When checked, the segment counter and output dir config appear inline
- The existing segments table in content-bottom would update in real-time as the live pipeline writes segments

### What does NOT need to change

- `ROIEncoder` - unchanged, still handles the dual-CRF FFmpeg call
- `BackgroundSubtractor` - unchanged
- `metadata.db` schema and queries - unchanged
- `hls.js` playback and retry logic in the browser - unchanged
- All existing tests - unchanged (the new module would get its own test file)

### Estimated scope

About 2-3 days of focused work for one person:

- `src/pipeline/live_pipeline.py` - ~150 lines
- Updates to `app.py` - ~80 lines
- Updates to `index.html` - ~40 lines
- `tests/test_live_pipeline.py` - ~20 tests following the same dummy-injection pattern as `test_pipeline.py`

The hardest part is making the `ROIEncoder` segment write happen in a non-blocking way so it does not cause dropped frames in the HLS stream. The recommended approach is a `queue.Queue` where the frame loop enqueues completed segments and a separate encoder thread dequeues and calls `encode_segment()`.

### Owner suggestion

Riley (ROIEncoder/pipeline) and Kheiven (HLS stream/GUI) are the two natural owners for this, since it merges their systems. Coordinate on the `LivePipeline` API before writing any code.
