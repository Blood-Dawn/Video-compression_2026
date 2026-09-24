# RESEARCH: desktop deep-dive - compression upgrades + per-section UI data views (2026-09)

Date: 2026-09-24. Method: web research (11 searches, 4 pages fetched) cross-checked
against the current codebase (`src/compression`, `src/pipeline`, `src/gui`) and the
two prior deep-research passes this project already ran: `RESEARCH-COMPRESSION.md`
(R4 Phase 2, 109 agents, adversarial verification) and `RESEARCH-UIUX.md` (R4 Phase 1,
24 sources, adversarial verification). This pass is lighter-weight than those two -
no adversarial vote count - so findings below are marked by confidence, not by a
vote tally. Where this document repeats something those two already decided, it says
so and does not re-litigate it.

**Baseline, so this plan does not propose things already shipped:** the pipeline
already has long-GOP defaults, capped-CRF budgeting, NVENC (H.264/HEVC/AV1) with probe
+ fallback, opt-in pre-encode denoise, opt-in activity-grid ROI (`addroi`,
x264/x265-only), VMAF-targeted CRF search (`vmaf_target.py`), and a working codec
matrix of libx264/libx265/libsvtav1/libaom-av1. On the UI side, job history, a
completion-summary modal, empty states, and push/webhook notification config all
already exist. R4 Phase 4 (the Server/Field two-exe split) has also already shipped
(`docs/build/BUILDS.md`). Two things `RESEARCH-UIUX.md` explicitly deferred *until
after* that split - the goal-oriented tab reorg and the timeline review UI - are
therefore ripe to revisit now, and both show up below.

---

## Part A: compression algorithm upgrades

### A1. AV1 film grain synthesis (`film-grain=N`, SVT-AV1) - ADOPT, opt-in, narrow scope
SVT-AV1 can denoise the source before encoding and re-synthesize matching grain/noise
at decode time from a small model instead of spending bits coding real noise pixel by
pixel ([DEV Community write-up](https://dev.to/masonwritescode/turn-on-av1-film-grain-synthesis-and-measure-what-it-saves-on-your-own-footage-37bb),
[SVT-AV1 guide](https://gist.github.com/dvaupel/716598fc9e7c2d436b54ae00f7a34b95)).
Flags: `-svtav1-params tune=0:film-grain=8:film-grain-denoise=1` (8 for real-world
noise, lower for digital/animated sources).
- **Where it fits SVCS specifically:** night/IR footage is exactly the noisy-sensor
  case this technique targets, and `RESEARCH-COMPRESSION.md` finding 5 already
  flagged night footage as costing up to 3x daytime bitrate from sensor noise. Film
  grain synthesis is a second lever on the *same* problem the existing opt-in
  denoise filter (`hqdn3d`/`atadenoise`) addresses, and the two combine naturally:
  denoise removes the real noise, film-grain-denoise removes what denoise missed
  and models it, so detail isn't just thrown away.
- **Caveats found (and worth taking seriously):** the source I checked deliberately
  refused to cite a savings percentage because it depends entirely on how much of
  the bitrate was noise; clean daytime footage or screen-recorded demo clips see
  almost nothing. It also warns full-reference quality metrics (VMAF, PSNR) are
  "structurally unreliable" on film-grain output, because the grain is synthesized
  per-decode, not the same pixels as the reference - so this pass's honest VMAF
  gate (`vmaf_target.py`) would need to measure on a *decoded* sample, not compare
  against source directly, or it will misjudge quality.
- **Risk for a surveillance use case specifically:** synthesized grain is
  statistical, not the original signal, so a compliance/evidentiary use case (which
  `docs/BLOCKERS.md` already treats carefully via `TokenStore` and `FLAG_SECURE`
  discussions) should probably keep this off for anything that might need to survive
  forensic zoom on real sensor noise. Recommend it as an opt-in "space saver" knob
  next to the existing denoise option, off by default, documented with that caveat.
- **Action:** add `film_grain` (0-50, default 0/off) alongside the existing
  `denoise` option in the SVT-AV1/libaom-av1 encode path only (x264/x265/NVENC
  don't have it); surface it in ADVANCED, not the main preset picker.

### A2. AV1 hardware encoders are now genuinely competitive - confirms/extends existing NVENC support
A vendor-agnostic comparison ([Fora Soft](https://www.forasoft.com/learn/video-quality/articles-vqm/encoder-comparison-x264-x265-svt-av1))
put concrete numbers on what `RESEARCH-COMPRESSION.md` finding 4 adopted more
cautiously: NVENC AV1 at ~480 fps 1080p with roughly 40% smaller files than NVENC
H.264, versus SVT-AV1 software presets that only reach useful speed (30-60 fps) at
preset 8-10, well below their best efficiency. This doesn't change the existing
decision (NVENC already wired with fallback), but it strengthens the case for making
`av1_nvenc` the *default* real-time/live-ingest choice on machines that have it,
reserving SVT-AV1 slow presets for archive re-encodes where time doesn't matter.
Confidence: medium - one source, and it doesn't cover AMD AMF or Intel QSV AV1,
which `RESEARCH-COMPRESSION.md` already flagged as an untested gap.
- **Action:** in the codec auto-selection logic, prefer `av1_nvenc` over
  `hevc_nvenc`/`h264_nvenc` when the capability probe reports it usable, ahead of
  software AV1, for live/RTSP paths specifically (archival/offline paths keep
  quality-first software AV1 as today).

### A3. H.266/VVC - confirmed NOT ready, do not adopt yet
Checked because the user asked about "new algorithms." VVC's open-source encoder
ecosystem is still thin and FFmpeg's own VVC encoder support was still landing as
patches rather than a stable mainline feature as of the sources found
([FFmpeg-devel patch series](https://patchwork.ffmpeg.org/project/ffmpeg/cover/20231103095720.32426-1-thomas.ff@spin-digital.com/),
[HandBrake VVC issue, open](https://github.com/HandBrake/HandBrake/issues/5007)), and
hardware VVC encoders are enterprise silicon IP announcements, not consumer GPUs
([Allegro DVT press release](https://www.businesswire.com/news/home/20240716657668/en/Allegro-DVT-Launches-The-Industrys-First-Real-Time-VVCH.266-Encoder-IP)).
- **Decision: SKIP for now.** No CPU-friendly, FFmpeg-stable VVC encoder exists that
  SVCS's Windows-first, CPU-first audience could actually run. Revisit when FFmpeg
  ships a VVC encoder in a release build, not a devel patch series.

### A4. Neural/learned codecs - status unchanged from R4 Phase 2, still SKIP
`RESEARCH-COMPRESSION.md` finding 8 already checked DCVC-RT and found no CPU or
FFmpeg path. Nothing found in this pass changes that; still A100/RTX-only, no
consumer deployment story. No action.

### A5. Per-scene / shot-adaptive encoding - DEFER, not a good fit yet
Chunked, per-scene CRF/preset tuning (PySceneDetect-driven) is a real technique for
VOD pipelines that can re-encode a whole file scene-by-scene ahead of delivery. SVCS's
pipeline is different: mode0-3 process a live or near-live stream in fixed-length
segments for the reasons `pipeline.py` already documents (frame gating, ROI
compositing, seekable archives). Splicing a full pre-scan scene-detection pass in
would conflict with that segment-boundary model and is a bigger architecture change
than the ROI/GOP work already adopted.
- **Decision: DEFER.** The existing "activity-grid ROI refreshed at segment
  boundaries" (Compression finding 1) already gets most of the same benefit
  (spend bits where something is happening) without a full re-architecture.
  Worth a dedicated research pass of its own if segment-length flexibility becomes
  a priority later, not bundled into this one.

---

## Part B: per-section UI and data-view upgrades

The app has no charting library anywhere (a search found exactly one `<canvas>`, used
for the ROI zone editor, not for data). Every numeric surface - CPU/RAM, savings,
job history - is rendered as plain text or a static number. That is the single
biggest, lowest-risk upgrade available across every section, and it does not require
adopting a frontend framework: the codebase is intentionally vanilla JS
(`RESEARCH-UIUX.md` finding 8, "stay vanilla" - SKIP on Pico CSS reaffirmed the same
preference), so the right tool is a small dependency-free charting library, not React
plus a chart wrapper.

**Charting library recommendation:** [uPlot](https://github.com/leeoniya/uPlot) for
time-series (CPU/RAM over time, encode fps, per-job duration) - it is ~45 KB
unminified, canvas-based, and specifically built for dense real-time line charts,
which matches "live system metrics that update every ~2s" exactly. For the
occasional bar/pie/donut (savings breakdown by mode, codec mix in the library), a
tiny hand-rolled canvas or SVG bar chart is enough and avoids a second dependency;
Chart.js is the fallback if more chart types are wanted later, at the cost of being
roughly 10x the payload. Either drops in as a single `<script src=...>` the same way
the existing per-feature JS files are loaded, with no build-step change.

### B1. METRICS section - biggest gap
Today `/api/system_metrics` already computes `mode_avgs` (per-mode CPU averages) and
a rolling power/battery snapshot, but the frontend (`metrics.js`) only displays the
*current* numbers - none of that history is plotted.
- **Add:** a live line chart (uPlot) of CPU% and RAM% over the last N minutes,
  fed by the same polling loop that already exists (no new endpoint needed for the
  chart itself, just don't throw away each sample - buffer the last ~300 points
  client-side, or add a tiny ring-buffer server endpoint if the tab can be closed
  and reopened and should keep history).
- **Add:** a per-mode CPU comparison as a small bar chart instead of the current
  text list - the data (`mode_avgs`) already exists server-side.
- **Add:** an encode-throughput chart (fps or MB/min over time) using the job
  history data that already gets recorded (`job_history` service) - this turns
  "was that job fast" from a memory question into a glance.
- **Effort:** low. All the source data already exists; this is a rendering change
  plus a small client-side ring buffer, in `metrics.js` and `index.html`'s METRICS
  panel only.

### B2. LIBRARY section
Library already has grid/list views, kind filtering (all/original/compressed), lazy
thumbnails, and search - it's the most mature of the vanilla-JS modules. The gap is
in *aggregate* views once a folder has hundreds of clips:
- **Add:** a small stats strip above the grid - total clips, total size, average
  compression ratio for the currently filtered set (`_svcsLibrary.all` already holds
  everything needed client-side; this is a `.reduce()` and a few DOM nodes).
- **Add:** a size-over-time or size-distribution mini-chart (uPlot bar or a simple
  histogram) so an operator can see at a glance whether recent recordings are
  trending larger (codec regression, scene got busier) without opening each file.
- **Consider (medium effort):** duplicate/near-duplicate detection surfaced as a
  filter chip - `compressed_index` already tracks `<path>|<size>|<mtime>` signatures
  per `savings_bp.py`'s own comments, so an "originals with no compressed copy yet"
  or "orphaned compressed files" view may be close to free given data already on
  disk.
- **Revisit now that Phase 4 shipped:** `RESEARCH-UIUX.md` finding 5/7 deferred the
  Frigate/Milestone-style timeline-and-hover-preview review UI specifically until
  after the two-exe split, and `docs/BLOCKERS.md` lists it as "revisit post-split."
  That split is done (`docs/build/BUILDS.md`). This is a genuinely bigger feature
  (a synced timeline scrubber across clips) - it belongs in its own phase, not
  bundled with the chart additions above, but it's now unblocked and worth
  scheduling.

### B3. SAVINGS section
`savings_bp.py` already carefully separates "measured" (real before/after bytes)
from "recorded" (total bytes written, no honest ratio) - genuinely good, keep that
distinction. The gap is purely presentational:
- **Add:** a savings-over-time line chart (bytes saved per day/week) using
  `measured` data only, respecting the same honesty rule the backend already
  enforces - never blend in "recorded" bytes to inflate the line.
- **Add:** a per-mode / per-codec breakdown bar so "which setting is actually
  saving space" is visible instead of one aggregate number.

### B4. AUTO-COMPRESS section
`RESEARCH-UIUX.md` finding 1 already got "file N of M" batch progress adopted and,
per a code search, it appears implemented via the job-history/completion-summary
work. The next increment, now that the data exists:
- **Add:** a small queue-depth-over-time chart so a technician watching a big
  overnight batch can see throughput (files/hour) rather than just a single
  progress bar.

### B5. Cross-cutting: revisit the goal-oriented tab reorg (now unblocked)
`RESEARCH-UIUX.md` finding 4 explicitly deferred reorganizing tabs around operator
questions (HOME = "what's happening now," AUTO-COMPRESS = "what happened overnight,"
LIBRARY = "find a clip") because "Phase 4 will change the shell anyway." Phase 4 has
shipped. This is a navigation/IA change, not a data-view change, so it's listed here
as unblocked rather than folded into Part B's chart work - it should get its own
short design pass (mockup the reorganized tab bar, confirm with the owner) before
touching `index.html`'s tab markup, since it affects muscle memory for anyone already
using the app.

---

## Part C: code-level optimization notes found along the way

- `src/gui/templates/index.html` is a single 4,174-line, ~208 KB template. The JS
  and CSS have already been split out into per-feature files (the blueprint split
  and the `gui/static/js/*.js` split are both documented as deliberate past
  refactors), but the HTML itself is still one file. Given the app has no build
  step, splitting it further would mean either Jinja `{% include %}` partials (easy,
  zero risk, purely organizational) or a template-fragment endpoint approach (more
  invasive). Recommend the low-risk `{% include %}` split as a housekeeping item
  alongside the UI work in Part B, not a prerequisite for it.
- No dead code or obviously redundant modules turned up in this pass beyond what
  `docs/CLEANUP-2026-09.md` already addressed; the compression and routes layers
  are already organized by feature.

---

## Proposed phased plan

1. **Phase D1 - Metrics charts** (Part B1). Lowest risk, all data already exists,
   single-file-scoped change (`metrics.js` plus the METRICS panel markup). Add
   uPlot, wire live CPU/RAM history and the per-mode bar chart.
2. **Phase D2 - Savings and Library stats strips and charts** (Parts B2, B3). Same
   pattern, reuses uPlot from D1, no backend changes needed for the stats-strip
   items; the size-distribution chart and any duplicate-detection filter need a
   small look at what `compressed_index` already stores before deciding if new
   backend work is required.
3. **Phase D3 - Film grain synthesis opt-in** (Part A1). Backend-only: one new
   config field, plumbed through the SVT-AV1/libaom-av1 branch of the encoder the
   same way `denoise` already is, with the VMAF-on-decoded-sample caveat handled
   before the option ships, not just documented.
4. **Phase D4 - AV1 NVENC as default live-ingest choice** (Part A2). Small change
   to codec auto-selection order; verify against the existing capability probe so
   the fallback chain (`av1_nvenc` to `hevc_nvenc` to `h264_nvenc` to `libx264`)
   stays intact.
5. **Phase D5 - Tab reorg and timeline review UI design pass** (Part B5, B2's
   timeline note). Larger, IA-level change; scope this as its own design doc before
   any code, since it changes navigation for the whole app.

Each phase should keep the project's existing bar: tests for new arg-construction
and endpoints, no live-camera or hardware-dependent behavior claimed as verified
without an owner check on real hardware, and no changes to `TokenStore`,
`FLAG_SECURE`-adjacent code, or auth/CSRF paths as a side effect of UI work.

## Honest caveats

- This pass used general web sources, not the adversarial multi-agent verification
  the two prior research docs used - treat confidence as "spot-checked," not
  "verified 6-0."
- The film grain synthesis savings figure is explicitly not quantified by the
  source that discussed it; do not promise a percentage to the owner or in release
  notes without measuring on SVCS's own footage first.
- The AV1 hardware-encoder speed/efficiency numbers come from one comparison site
  and were not cross-checked against a second independent source the way
  `RESEARCH-COMPRESSION.md`'s NVENC numbers were; treat as directional.
- No charting-library benchmark was run against SVCS's actual data volumes; uPlot's
  reputation for high point-count time series is well documented, but pick it after
  a five-minute spike against real `/api/system_metrics` polling data, not on
  reputation alone.

Author: Claude (Sonnet 5), 2026-09-24, at the owner's request following up on
`RESEARCH-COMPRESSION.md` and `RESEARCH-UIUX.md`.
