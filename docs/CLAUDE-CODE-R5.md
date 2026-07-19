# Claude Code Round 5 - compression frontier, smart retrieval, behavior alerts

For: Claude Code (auto mode). This round follows R4. It keeps SVCS's main objective front and center, compressing surveillance video smaller at the same visual quality, and adds retrieval and alerting on top of the metadata the pipeline already produces. Work the tasks in order. Same operating rules as `docs/CLAUDE-CODE-MASTER-PLAN.md` and the earlier fix rounds apply.

Every idea here was scouted against current practice; the sources are listed at the bottom so you can read the technique before you build it. Two of the tasks (5.1 and 5.5) are heavier and start with a short research-and-spike doc, the same way `docs/RESEARCH-PLATES.md` preceded the plate reader.

## Operating rules (do not violate)

- Branch `app` only. One task at a time. Run `pwsh scripts/run_tests.ps1` to green before you commit (it must end with 0 failed; the webcam-hardware skips are expected). Never delete, weaken, or skip a test to fake green; if a test is genuinely obsolete, rewrite it with a comment saying why.
- Tick the task `[ ]` to `[x]` in this file as you finish it. Commit format `<type>(<scope>): <subject>`, a body explaining why, final line exactly `Bloodawn(KheivenD)`, no emojis. Then `git push origin app`. One reviewable commit per task.
- No em-dashes (U+2014) or en-dashes (U+2013) anywhere in code, comments, docs, or UI strings. Use an ASCII hyphen, or restructure with commas and periods. This doc is written that way; keep it that way.
- M0 gotchas still bind: use `.venv` (not `venv`); never install the `[plates]` extra into the working or CI env; keep `opencv-contrib-python`; LF line endings; validate produced mp4s with `ffprobe`, not OpenCV (AV1 is not always decodable by cv2).
- Browser-verify every UI change with the Preview MCP, the way TASK 1.7 was verified. Add the tests each task names in the same commit.
- Route-count guard: the blueprint-registration test asserts the current route total (17 blueprints, 73 routes as of v2.2.0.dev0). When a task adds a route, update that assertion in the same commit; do not silently drift it.

## Decisions already made (do not re-open)

- Compression is the product. Every feature below must either shrink files, or ride on data the compressor already produces. Do not turn SVCS into a general VMS.
- Open-source only, AGPL-3.0. Offline and self-hosted by default. No cloud calls, no SaaS, no telemetry beyond the existing opt-in path.
- Codec policy is unchanged: mode0/mode1 H.264 (libx264), mode2/mode3 AV1 (libsvtav1). Do NOT add H.265/HEVC even though the market leans on it, it is patent-encumbered and that was a deliberate call. AV1 stays the max-compression path.
- Heavy optional dependencies are never bundled into the slim exe. Anything large or torch-adjacent (for example a semantic-search model) ships as an opt-in extra installed into the same env with a helper, exactly like the ONNX plate reader, and the slim build degrades gracefully without it.
- Data-loss and PII rules from the security round hold: delete-original never runs before a verified compressed output exists; never log plaintext, passwords, keys, plate text, or face crops; anything that embeds images of people stays local and opt-in.

---

## Phase 1 - compression frontier (the main objective)

### TASK 5.1 - VMAF-targeted rate control (research doc first, then build)

- [x] **Research spike:** write `docs/RESEARCH-VMAF-TARGET.md` describing the approach before coding. The R4 work already measures VMAF; this task spends exactly enough bits to hit a perceptual-quality target instead of a fixed CRF, so each clip gets the smallest file at constant perceived quality. The established method is an interpolated binary search over CRF on short sample encodes, the same idea `ab-av1` uses with svt-av1 + vmaf (it searches CRF to satisfy a `--min-vmaf` and a `--max-encoded-percent`; the useful target range is roughly VMAF 85 to 97). Document the sampling scheme (encode a few short segments, not the whole clip, at candidate CRFs; interpolate), the clamp range, and the fallback when the VMAF tool is missing.
- [x] **What:** add a "Target quality (VMAF)" encode mode. When enabled for a preset, the encoder runs a short sample-based CRF search to hit a target VMAF (default about 93, clamp 85 to 97) instead of the preset's fixed CRF, then encodes the full clip at the found CRF. Keep it opt-in per preset so the existing fixed-CRF modes are untouched.
- **Files:** a new `src/compression/vmaf_target.py` (the search: sample-encode, measure with the existing VMAF harness, interpolate, clamp, cache the result per source), wire it into the encode path in `src/compression/` and the pipeline; a preset toggle + target field in the UI (`src/gui/templates/index.html`, the relevant `static/js/*.js`, `strings.js`).
- **Acceptance:** on a representative test clip, target mode produces a file whose measured VMAF is within about +/-1 of the target and whose size is less than or equal to the fixed-CRF output for that mode. Unit tests cover the search (monotonic CRF-to-VMAF assumption, interpolation, clamping, and graceful fallback to fixed CRF when the VMAF backend is absent). Do not block the UI thread during the search; run it in the existing worker.
- **Risk:** the search adds encode time. Keep samples short and cache the chosen CRF keyed by source hash + preset so a re-run is instant. If VMAF is unavailable, fall back to fixed CRF and surface that in the log, never hang.

### TASK 5.2 - background-reference compression for static cameras

- [x] **What:** exploit long-term redundancy that fixed cameras produce. SVCS already computes a MOG2 background model; use the stable background as an explicit low-bitrate reference so bits are spent only on changed regions. Concretely, extend the R4 encoder-level ROI: raise the quantizer hard on background-only regions, force a periodic clean background keyframe to act as a long-term reference, and let subsequent frames delta against it (conditional-replenishment style, where only the macroblocks that changed, including the area revealed behind a moving object, are refreshed).
- **Files:** the encoder ROI/qp-map path from R4 Phase 2, the `src/background_subtraction` consumer that already produces the foreground mask, and the pipeline glue.
- **Acceptance:** on a static-camera clip with intermittent motion, this mode yields a smaller output than the R4 ROI mode at equal measured VMAF, and the moving-object regions retain their quality (no visible smearing of the subject). Tests assert the size reduction versus the R4 baseline and that foreground regions keep a quality floor.
- **Risk:** overly aggressive background QP produces blocky static areas that look worse even if VMAF is fine; keep a configurable background-quality floor and default it conservatively. Camera shake or auto-exposure defeats the "static" assumption, so gate this mode on a low measured background-motion score and fall back to plain ROI when the scene is not actually static.
- **OUTCOME (2026-07-16): the QP half of this task was built, measured, and dropped; only the static-scene signal shipped.** The acceptance ("smaller than the R4 ROI mode at equal measured VMAF") is not reachable by quantizing background harder. Measured on libx264 against both a clean and a sensor-noise static clip: file size is flat above qoffset ~0.30 while VMAF falls steeply (noisy clip, qoffset 0.30 -> 759,847 B @ VMAF 95.65 vs 0.80 -> 780,159 B @ 67.23, i.e. bigger AND 28 VMAF points worse), and R4's default ROI already sits at 0.43, past the knee. The "clean background keyframe as long-term reference" idea measured a wash or a regression against every lever tried, because x264's mb-tree already does it. Structurally, the proposed mode differed from R4 ROI only by widening the qoffset clamp, so below the clamp the two emit byte-identical output. What actually shrinks static-camera footage is keyframe frequency (`-g 15` -> 37,578 B @ VMAF 96.80 vs `-g 150` -> 11,000 B @ 96.83: **70% smaller at equal VMAF**), which is TASK 5.3's stated scope. **Shipped:** `background_motion_score` / `scene_is_static()` on ROIEncoder, derived from the existing foreground signal. **CORRECTION (2026-07-19):** this note predicted 5.3 would gate GOP extension on that signal. 5.3 measured it and it does not work - the signal is blind to the axis that actually moves the optimal GOP. The 70% figure quoted above is real but is a property of GOP length generally, not something the motion signal can steer. See the 5.3 outcome below. **Not shipped:** any user-facing "background reference" toggle, since a control that trades 28 VMAF points for 0 bytes would mislead users. Full measurements: `docs/BLOCKERS.md`.

### TASK 5.3 - content-adaptive GOP and scene-change keyframes

- [x] **What:** make the GOP adapt to content. R4 added a long GOP; here, detect motion onsets and scene changes and place a keyframe there, while extending the GOP through genuinely static stretches. This complements 5.2 (the forced background keyframe) and prevents the long GOP from smearing across a real cut.
- **Files:** the encode-config path; reuse the existing motion/foreground signal rather than adding a second detector.
- **Acceptance:** on a clip with a hard scene change, a keyframe lands at the change (verify with `ffprobe` frame types), and average file size on mostly-static clips drops versus a fixed GOP at equal VMAF. Tests assert keyframe placement at a synthetic cut and no quality regression.
- **Risk:** do not double-count motion; drive this from the same foreground signal 5.2 uses.
- **OUTCOME (2026-07-19): the scene-change half already worked and is now guarded; the adaptive-GOP half is refuted.** (a) Scene-change keyframes needed NO new code: x264's built-in detection already places an IDR at a hard cut, verified with ffprobe at the production argv shape (`-g 500`) putting an I-frame at exactly the 4.0s cut. What was missing was a guard, since `-sc_threshold 0` silently disables it and that flag already exists in `hls_runner.py` where it is correct for even HLS segments; copying that argv into the recording encoder would degrade every recording with no error. `tests/test_scene_change_keyframes.py` pins it, with a negative control proving the test can fail. (b) Adaptive GOP from the 5.2 motion signal is refuted on 7 real CDnet clips. The headline Pearson r was +0.556, but leave-one-out collapses it to **+0.009** without a single clip, motion=0.0000 occurs three times with saturation GOPs of 60/300/30 (**a 10x spread on identical predictor input**), and a permutation test gives **p=0.165**. The mechanism: the clips punishing a long GOP are a fountain and snowfall, where pixels churn but there is no coherent object motion, so the subtractor scores them 0.0394 and 0.0016. The axis that matters is temporal entropy, and seeing it needs a second detector - which this task's own risk note forbids. **The task's constraint forecloses the only signal that would work.** Also measured: the current `gop_seconds=20` default sits in the saturated region (GOP 300 and 600 were byte-identical on 5 of 6 clips), so it could be halved at ~zero size cost and would double seek granularity for an operator scrubbing footage. Left as an **owner decision**, since it changes output for every existing user and the gain is usability, not compression. Full statistics: `docs/BLOCKERS.md`.

---

## Phase 2 - smart retrieval (rides on the metadata the pipeline already writes)

### TASK 5.4 - structured natural-language search over the metadata DB

- [ ] **What:** the SQLite metadata DB already records object class, color, scene, camera, and time per event. Add a light query layer that turns a phrase like "red car after 9pm on cam2" into structured filters (class=car, color=red, hour>=21, camera=cam2) and returns matching events, plus a SEARCH-tab UI to type the phrase and see results with thumbnails. This is the self-hosted, no-cloud answer to the "natural-language search" that current NVR products advertise, and it uses data you already have.
- **Files:** a new `src/gui/services/nl_query.py` (a deterministic parser: tokenize, map known class/color words, parse relative and absolute times, map camera aliases, emit a parameterized SQL WHERE, never string-concatenate user input into SQL), the queries blueprint, and the SEARCH tab (`index.html`, `static/js/`, `strings.js`).
- **Acceptance:** the parser maps a table of example phrases to the correct filters (include at least ten phrases covering class, color, time-of-day, absolute date, and camera), unknown terms degrade to a free-text match on the caption field rather than erroring, and all queries are parameterized (a phrase containing SQL metacharacters cannot alter the query). Tests cover the parser and the SQL safety.
- **Risk:** keep it deterministic and offline. Do not reach for an LLM here; a rules parser over your own controlled vocabulary is accurate, fast, and needs no model. Leave semantic free-text to 5.5.

### TASK 5.5 - local semantic search (optional extra, research doc first)

- [ ] **Research spike:** write `docs/RESEARCH-SEMANTIC-SEARCH.md`. For queries that go beyond the structured fields ("person in a hi-vis vest near the loading door"), embed event thumbnails with a local CLIP/SigLIP-class model and match a free-text query by cosine similarity over a small local vector index. Current CLIP/SigLIP models reach roughly 85 to 90 percent retrieval accuracy on general content; open self-hosted references include SentrySearch (local model + ChromaDB) and CLIPSE. Document the model choice, where embeddings are stored, and the offline story.
- [ ] **What:** an OPT-IN semantic index. It must ship as an optional extra installed into the same env with a helper (the ONNX/`--no-deps` pattern used for the plate reader), NOT bundled into the slim exe, and the app must run and pass tests without it. Embed only event thumbnails the pipeline already crops; store vectors in a local index (ChromaDB or a plain numpy cosine store, whichever keeps the dependency light). Add a toggle in SEARCH that falls back to the 5.4 structured search when the extra is absent.
- **Files:** a new optional module under `src/enhancement/` or `src/gui/services/`, an install helper mirroring `scripts/install_plates.ps1`, a `pyproject` optional-extra comment documenting the `--no-deps` recipe, and the SEARCH UI toggle.
- **Acceptance:** with the extra installed, a free-text query returns semantically relevant events; with it absent, the feature hides itself and the suite is green. Tests use a tiny stub embedder so CI never downloads a model or pulls a heavy dep.
- **Risk (PII):** embeddings of people are sensitive. Keep the index local, never transmit it, gate it behind an explicit opt-in, and never write raw crops or vectors to the shared log. Honor the same no-cloud rule as the rest of the app.

---

## Phase 3 - behavior alerts and zones (operational value, and it helps compression)

### TASK 5.6 - zone masks (include/exclude regions per camera)

- [ ] **What:** let the user draw include and exclude regions on a still frame per source (watch the door, ignore the road and the tree line). Both detection and compression honor the mask: excluded regions are treated as background (high QP, no events), included regions get the normal foreground budget. This cuts false events AND shrinks files, so it belongs to the compression story as much as the alerting one.
- **Files:** a canvas zone editor in the UI (`index.html`, a new `static/js/zones.js`, `strings.js`), persisted per source in the existing state/DB, and the pipeline + encoder honoring the mask (reuse the ROI path from 5.2).
- **Acceptance:** a masked-out region produces no events and encodes at the background quantizer (verify smaller output when a large area is masked), and the mask persists across runs. Tests cover mask persistence and that a masked region yields no events.
- **Risk:** coordinate spaces (display vs source resolution) are the usual bug; store masks in normalized source coordinates and test the round-trip.

### TASK 5.7 - class and behavior events on tracked objects

- [ ] **What:** raise events from classified, tracked objects rather than raw pixel motion, which is what makes analytics fire far less often on wind, rain, and headlights. Support line-crossing (object track crosses a user-drawn line), loitering (a track dwells in a zone past a time threshold), and simple direction. Record events to the existing `job_history` and optionally emit a local desktop notification or a user-configured webhook (no third-party service).
- **Files:** a tracking/event module (reuse the existing detector output; add lightweight IOU tracking if none exists), the events store, and an optional notifier + webhook config in the UI.
- **Acceptance:** given a synthetic track that crosses a defined line, exactly one line-crossing event is recorded; loitering fires only after the dwell threshold and not before; direction is correct for a known track. Tests drive synthetic tracks so no real inference is needed in CI.
- **Risk:** line-crossing with a class filter is the reliable workhorse; loitering is a timer that is sensitive to its threshold, so expose the threshold and default it sanely, and debounce so a single object cannot emit a burst of duplicate events.

---

## Phase 4 - evidence integrity (leans into the DoD origin)

### TASK 5.8 - tamper-evident hashing and chain-of-custody

- [ ] **What:** on finalize, write a SHA-256 of each compressed output plus a signed-style manifest (a hash chain linking outputs in order), and add a `verify` action that re-checks a folder against its manifest. Optionally burn a timestamp into a corner of the output. This makes a clip defensible as evidence, which is unusual for a free tool and fits SVCS's origin.
- **Files:** a new `src/utils/integrity.py`, a manifest writer in the finalize path, and a verify entry point (CLI subcommand and a small UI action).
- **Acceptance:** the manifest verifies on an untouched output set; flipping a single byte of any output makes verification fail and names the offending file; the manifest itself is tamper-evident (a changed entry breaks the chain). Tests cover verify-pass, single-byte-tamper-fail, and manifest-tamper-fail.
- **Risk:** keep it honest, this is integrity (detects tampering), not authenticity (proving who produced it), which needs signing keys; state that limitation in the code comment and any UI copy so no one over-claims it.

---

## Suggested order and gating

Phase 1 first, it is the mission and 5.2/5.3 build on the R4 encoder-ROI seam. Phase 2 next (5.4 is cheap and high-value; 5.5 is the optional heavy one, do the research doc and stub-tested skeleton, leave the model install as an opt-in). Phase 3 after (5.6 pays off in both compression and alerts, do it before 5.7). Phase 4 last. None of these are 🚦 gates; if you hit a genuine blocker, record it in `docs/BLOCKERS.md` and keep going with the next task.

## Sources scouted for this round

- ab-av1, CRF search to a VMAF target with svt-av1 + vmaf: https://github.com/alexheretic/ab-av1 and https://alexheretic.github.io/posts/ab-av1/
- SVT-AV1 preset/CRF trade-off analysis: https://ottverse.com/analysis-of-svt-av1-presets-and-crf-values/
- LiteVPNet, lightweight learned encoder-control for a quality target: https://arxiv.org/pdf/2510.12379
- Background modeling and referencing for surveillance video coding (long-term redundancy, background reference frames): https://dl.acm.org/doi/abs/10.1109/TMM.2018.2829163
- Conditional replenishment (refresh only changed macroblocks, including the area revealed behind a moving object): https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/6160848
- Self-hosted semantic video search with CLIP + a local vector DB (SentrySearch): https://aibit.im/en/article/sentrysearch-semantic-video-search-with-ai ; CLIPSE: https://arxiv.org/pdf/2504.17643 ; CLIP frame search walkthrough: https://docs.vultr.com/semantic-video-frame-search-using-openai-clip-and-vector-database
- Behavior analytics fire on classified/tracked objects to cut false alarms; line-crossing/loitering/intrusion patterns: https://www.forasoft.com/learn/video-surveillance/articles-vms/behavioral-analytics-loitering-intrusion-zones and reference implementation https://github.com/yas-sim/object-tracking-line-crossing-area-intrusion
