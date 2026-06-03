# SVCS v2 - Product and Technical Plan

**Status:** Re-planned from scratch, 2026-05-31. Revised the same day to lock the project as **open-source-first, surveillance-focused**.
**Supersedes:** the strategic intent in `ROADMAP-V2.md` and `ARCHITECTURE.md` where this document contradicts them (each disagreement is called out explicitly in §6).
**Author of this re-plan:** planning session for Kheiven D'Haiti (Bloodawn).
**Companion:** `docs/EXECUTION-CLAUDE-CODE.md` (the sequenced engineering task list derived from this plan).

This plan is opinionated on purpose. Where the existing planning was sound, it is ratified by name. Where it was wrong or thin, it is replaced with reasoning in the form *current doc says X; I believe Y because Z; cost of being wrong is W*.

## What changed in this revision (read first)

The owner set the direction explicitly:

1. **Open source, full stop.** SVCS ships AGPL-3.0, free, full-featured. There is no paid edition in v2. The commercial license, the dual-license split, and the `premium` branch are **not part of the v2 plan**. A commercial fork may happen *later, only if the team is legally allowed to* (see §13 - the DoD/FAU IP question decides that), and it would branch off a finished open-source product, not run alongside it. The CLA is shelved; it is not needed to ship an open-source project. (It can be revived if and when a commercial fork is actually pursued.)
2. **Surveillance is the product.** Not "any video," not a generic transcoder. SVCS compresses surveillance and security-camera footage. Everything points there.
3. **Consumer and prosumer security cameras are in scope** - Ring, Nest, Wyze, Reolink, Arlo, Eufy, Amcrest, and the ONVIF/RTSP ecosystem. A homeowner with a couple of cameras should be able to shrink their footage with SVCS, the same way a small business with a 16-camera CCTV system can. This is a new positioning pillar and a new milestone (§7, M-CAM).
4. **No competitor name-dropping as positioning.** The product stands on what it does for surveillance footage, not on comparisons.

Everything below reflects those four decisions.

---

## 0. Questions outstanding

The handoff asked me to surface questions I cannot answer from the repo. With the commercial track shelved, the list is shorter and only one item is genuinely gating.

1. **Who owns the IP - and does it constrain even open-source release?** SVCS is an FAU EGN-4950C capstone sponsored by the Defense Innovation Unit / NIWC Pacific (DoD). Three parties may hold rights: FAU (university IP policy + course agreement), the U.S. Government (DoD-funded work often carries Government Purpose or Unlimited Rights in the deliverable), and the five students. For an **open-source AGPL release** this is usually fine - universities and the Government are generally happy to see sponsored work released openly, and AGPL grants no exclusive commercial advantage to anyone. But confirm it: a short written "yes, the team may release this under AGPL-3.0" from FAU's tech-transfer office and the sponsor closes the question. **This becomes hard-gating only if a commercial fork is ever pursued** - at that point ownership must be nailed down, because you cannot sell what you do not own. For now: get the open-source-release blessing in writing; defer the rest.
2. **Does the sponsor relationship continue?** Affects whether `dev` (the v1.x bugfix line) stays alive and whether any data-rights clause touches the surveillance footage handling. Worth a one-line answer from Cody.
3. **Is there a small budget for the things that cost money even for open source?** Code-signing certs (Windows EV ~\$300-600/yr, Apple Developer \$99/yr) and a download host. Open source doesn't remove these costs; it just removes the revenue that would offset them. The plan sequences free work first, but a signed installer eventually needs a cert. (Open-source projects sometimes get free signing via SignPath or similar - worth investigating; noted in §8.)

That's it. No pricing validation, no CLA lawyer review, no LLC - all shelved with the commercial track.

---

## 1. Executive summary

SVCS is a working AI-aware compression pipeline for surveillance footage: it keeps the parts of a frame that matter (people, vehicles, motion, faces, plates) at high quality and throws bits away on the static background a fixed camera stares at all day. It came out of a DoD-sponsored surveillance capstone and runs today on the `app` branch as a Python + Flask desktop app with a working (if oversized) PyInstaller bundle.

The thesis is simple and it's the original one: **a security camera pointed at a parking lot records 24 hours of mostly-nothing, and every dead pixel still costs storage. SVCS cuts that - 6× on typical footage, up to 16× on quiet scenes (the repo's own CDnet measurements) - with the moving, important parts kept sharp.** It runs on-prem, nothing leaves the machine, no cloud, no subscription.

Who it's for, now made explicit and widened: not just professional CCTV/NVR operators, but **anyone with a security camera** - including the consumer Ring/Nest/Wyze crowd. A homeowner with three cameras filling up a microSD card or a NAS has the same problem as a warehouse with thirty, just smaller. SVCS should serve both. (The honest constraint on the consumer side: cloud-locked cameras like Ring and Nest don't expose their footage locally, so for those we compress *exported* clips or ingest through a bridge like Home Assistant / Scrypted / Frigate - we do not scrape vendor clouds. RTSP/ONVIF cameras like Reolink and Amcrest we ingest directly. Details in §2 and §7 M-CAM.)

The plan keeps the strong engineering instincts from the existing planning and pushes back on the over-reach:

- **Ship the Python desktop app well before rewriting anything.** The biggest concrete problem - a 2.5-4.7 GB installer - is mostly PyTorch/CUDA, not Python. Swapping inference to ONNX Runtime gets it to ~400-600 MB **without** a Rust rewrite. The Rust core and Flutter UI from `ARCHITECTURE.md` become measured, gated spikes, not committed summer work (§6). Two simultaneous rewrites on a five-person part-time student team over one summer is the textbook second-system trap.
- **Fix the test suite first.** The most recent full-suite run on disk (`pytest_final.log`, 2026-05-14 20:23, *after* the last commit) shows **48 failed, 465 passed, 5 errors** - contradicting the "118 passing / all green" claim. The whole-file failure pattern (every test in `test_encryption`, `test_crash_reporting`, `test_gui_api`) points at missing optional dependencies rather than 48 real regressions, but until there's a reproducible green run *we don't know what works.* Everything starts there (§11).
- **Hide the four encode modes behind named presets.** The repo's own `mode_size_hierarchy.md` shows the intuitive "Mode 3 < Mode 2 < Mode 1 < Mode 0" size ordering is false (Mode 2 is the *largest*). A user picking "Mode 2" expecting smaller files and getting bigger ones is a bug report. Users pick "Continuous CCTV - max savings" or "Motion-event doorbell cam"; the engine maps that to a mode (§6, §16).

The roadmap is sequenced for ship-small-and-often at a part-time pace, with the rewrite-shaped risks at the back as explicit spikes.

---

## 2. Positioning and landscape

### What SVCS is, stated honestly

A pipeline that does background subtraction (MOG2) plus an optional YOLO object filter, separates regions of interest from background, and encodes them at different quality levels. Its edge is **content-aware bit allocation driven by object detection**: spend bits where the people, vehicles, faces, and plates are; starve the static background a fixed camera never stops watching.

That edge is largest exactly where surveillance lives - **static-camera footage** - because a fixed camera's frame is mostly unchanging. This is the home-field advantage and the whole reason to be surveillance-focused: it's the footage where AI-aware compression wins biggest. A parking-lot or doorbell camera is 90-95% dead pixels; the repo measured 6× typical and 16× on quiet scenes.

### Where SVCS sits

SVCS is not a VMS (video management system), not a camera, and not a cloud service. It is a **compression layer** that sits downstream of whatever records the footage:

| Footage source | How SVCS gets it | Notes |
|---|---|---|
| **Pro CCTV / IP cameras (ONVIF/RTSP)** - Hikvision, Dahua, Axis, Amcrest, Reolink | Direct RTSP ingestion (already supported) + ONVIF discovery (M-CAM) | The strongest fit. Live or pull-and-compress. |
| **NVR / NAS exports** - any recorder that writes files | Watch-folder on the export/recording directory | Compress clips as they land. The universal path. |
| **microSD / local-storage consumer cams** - Wyze, Reolink, Eufy (local) | Watch-folder on the card dump or NAS sync, or RTSP if the cam supports it | Many budget cams now do RTSP or ONVIF. |
| **Cloud-locked consumer cams** - Ring, Nest, Arlo | Compress *exported/downloaded* clips via watch-folder, OR ingest via a bridge (Home Assistant / Scrypted / Frigate) that re-exposes them as RTSP | We do **not** scrape vendor cloud APIs (ToS risk, constant breakage). Honest about this limit. |

The wedge, three things together that the recorders and cloud-cam subscriptions don't do:

1. **AI-aware compression** - keep what matters sharp, starve the rest. Biggest win on static-camera footage.
2. **Self-hosted, private** - nothing leaves the machine. For a tool with DoD origins and security-camera footage (often sensitive: faces, plates, the inside of someone's home), this is not a feature, it's the entire posture. A surveillance tool that phones home is dead on arrival.
3. **Open and free** - AGPL-3.0, runs on a regular computer, no GPU required, no subscription, no per-camera fee.

### Positioning line

> **Self-hosted, AI-aware compression for security-camera footage. Keep the people, cars, faces, and plates sharp; shrink everything else. 6-16× smaller archives, on your own hardware, nothing sent to the cloud. Free and open source.**

Works for a 30-camera CCTV install and for a homeowner with three Reolinks or an exported folder of Ring clips.

---

## 3. User profiles

No "paying" tiers - it's open source. These are *who uses it*, which still drives features and priorities.

| Profile | Who | Their problem | What SVCS gives them | Priority |
|---|---|---|---|---|
| **Pro CCTV operator / installer** | Shop, clinic, warehouse, school with 8-64 fixed cameras | NVR storage fills up; long retention is expensive in drives | On-prem 6-16× reduction across the fleet; footage stays local; no cloud subscription | **Primary** |
| **Prosumer self-hoster** | Home-lab / Plex-adjacent person running cameras + a NAS, often via Frigate/Home Assistant | TBs of motion clips and continuous recordings eating the NAS | Watch-folder automation; runs on their existing box; integrates downstream of their NVR/bridge | **Primary** |
| **Consumer camera owner** | Homeowner with Ring/Nest/Wyze/Reolink, a microSD card or a cloud plan | Card fills up; cloud retention costs a monthly fee; exported clips are huge | Compress local recordings or exported clips; for RTSP cams, ingest directly; shrink before archiving | **New focus (M-CAM)** |
| **Researcher / student** | Academic working with surveillance datasets (CDnet-style) | Storing/sharing large video corpora | Free, scriptable, reproducible compression with rich metadata | Secondary |
| **Security-conscious / air-gapped** | Anyone who can't or won't use a cloud encoder | Needs compression that never touches a network | Fully local, no telemetry by default | Secondary |

The two primary profiles share one need: **point it at where the footage lands and let it compress in the background.** That makes watch-folder automation (M4) and camera ingestion (M-CAM) the load-bearing features.

---

## 4. Feature inventory (one edition, open source)

There is one edition. Everything is free and AGPL-3.0. Optional `pyproject.toml` extras exist only to keep the default install small, not to gate features behind payment.

Core (always present):

- The four encode modes, exposed **as named presets**, not "Mode 0-3" (§6 Pushback 2).
- Background subtraction (MOG2) + optional YOLO object filter.
- Ingestion: file, RTSP, live camera, **ONVIF discovery (M-CAM)**, **watch-folder automation**.
- SQLite metadata index + browser dashboard (search, file browser, four-quadrant demo, HLS player).
- AES-256-GCM encryption at rest (PBKDF2 600k).
- Surveillance preset family + content auto-detection.
- Consumer-camera preset family + bridge-ingestion guide (M-CAM).

Optional extras (free, split out only for install size):

- **`[enhance]`** - Real-ESRGAN super-resolution (basicsr + realesrgan).
- **`[plates]`** - AI license-plate reader (EasyOCR + Real-ESRGAN + multi-frame consensus). **Now a free optional feature**, not a paid one - the reason it was "premium" was monetization, which is gone. It stays an *extra* purely because EasyOCR is a heavy dependency; the dashboard hides the plate-reader controls when the backend isn't installed (existing behavior - keep it).
- **`[crash-reporting]`** - Sentry, opt-in, off by default, not shipped unless explicitly installed.

The `premium` branch's reason to exist (paid feature gating) is gone. **Recommendation:** fold the plate reader from `premium` back into `app` as a free `[plates]` extra, and let `premium` go dormant (don't delete it - it's the natural seam if a commercial fork ever happens, per §13). This removes the dual-branch mirror dance from the daily workflow.

---

## 5. Sustainability (replaces "pricing")

Open source still has costs (hosting, signing certs, time). How the project stays alive without a paid tier:

- **Keep costs near zero.** GitHub (repo, Releases, Pages, Actions) is free for public projects. CI runs on free runners. Downloads ship from GitHub Releases. No CDN bill.
- **Optional donations, no feature gating.** A GitHub Sponsors / "buy us a coffee" link funds the signing cert and nothing else. Never a paywall.
- **Free code-signing for OSS.** Investigate SignPath.io's open-source program and Sigstore for signing without buying an EV cert outright (§8).
- **The commercial fork is the *only* monetization path, and it's deferred and conditional** (§13): if the team is legally cleared (§0 item 1) and *wants* to, after the open-source product is mature, fork a commercial edition then. Not now, not in v2, and not a precondition for any of the work below.

This section is deliberately short because the project's job in v2 is to be a good open-source surveillance tool, not a business.

---

## 6. Architecture - extending and correcting `ARCHITECTURE.md`

`ARCHITECTURE.md`'s destination (one core, many platforms, AI-aware modes) is coherent. My disagreements are about sequencing and risk, stated in X/Y/Z/cost form. Decisions I ratify, I name.

### Ratified without change

- **AGPL-3.0 open source.** Correct and now the whole story. Keep `LICENSE` as AGPL-3.0.
- **platformdirs for state files.** Correct; was the biggest installer blocker; done. Keep.
- **Opt-in, double-guarded crash reporting.** Correct privacy posture. Keep (caveat: its tests are currently red - §11; design right, test health not).
- **Ultralytics (YOLOv8) in core.** Fine - AGPL YOLO in an AGPL project is no conflict. The permissive-detector swap (RT-DETR/ONNX) is now only relevant *if* a commercial fork ever happens (§13), so it's deferred, but the ONNX work in M2 makes the seam exist for free.
- **Python-first, ship before rewriting.** The best instinct in the existing plan. Keep it and lean harder.

### Pushback 1 - Defer the Rust rewrite; solve installer size in Python with ONNX

**Current docs say:** v2 is a Rust `svcs-core` crate with Flutter on top; Rust port starts July; motivation is the 2.5-4.7 GB bundle ("real solution comes with the Rust port - ~50 MB binary").

**I believe:** defer Rust indefinitely; fix installer size inside the Python app by replacing PyTorch/CUDA with ONNX Runtime, CPU-first.

**Because:** the bulk of 2.5-4.7 GB is PyTorch + CUDA + weights, not Python. YOLOv8-nano and Real-ESRGAN both export to ONNX and run on ONNX Runtime at a fraction of PyTorch's footprint - plausibly ~400-600 MB with no algorithm rewritten in a new language. Rust buys maybe another ~250 MB and a cleaner binary at the cost of porting the whole pipeline and learning `ffmpeg-next`/`opencv-rust`/`ort` plus FFI maintenance - ~3 engineer-years for a part-time team. Verified: neither `svcs-core` nor `svcs-flutter` exists; `kdev` is just a repo copy with no Rust scaffold. Nothing is sunk.

**Cost of being wrong:** if Rust really is needed later, nothing's lost - the ONNX swap is useful regardless, and the port can run as a measured spike (M6). If we commit to Rust *now* and it's wrong, we burn the summer on FFI plumbing instead of shipping. The asymmetry is enormous. **Defer Rust to a gated spike.**

### Pushback 2 - Defer Flutter and mobile; the Flask app is the v2 desktop UI

**Current docs say:** Flutter UI replacing Flask; Android app in August; one codebase everywhere.

**I believe:** keep and harden the Flask dashboard through GA (the refactor is already planned); defer Flutter + Android until the desktop product has users.

**Because:** a second simultaneous rewrite compounds Pushback 1. The Flask app works and is mid-refactor (`docs/REFACTOR-PLAN-gui-app.md`). Mobile background compression is unproven (the handoff flags Adreno/Mali quirks) and there's no evidence yet of mobile demand for a *surveillance compression* tool - the footage lives on NVRs and NASes, not phones. Build mobile after the desktop tool proves the workflow.

**Cost of being wrong:** deferring Flutter costs a plainer desktop UI for a while (fine - it's a local tool). Committing now and being wrong costs the summer.

### Pushback 3 - Hide the four modes behind presets

**Current product:** Modes 0-3 are user-visible and named by number.

**I believe:** users never see "Mode 0-3"; presets pick modes internally.

**Because:** `docs/mode_size_hierarchy.md` measured that the intuitive size ordering is false and Mode 2 is the *largest*. A user choosing a mode by number to save space and getting a bigger file files a bug. Presets ("Continuous CCTV - max savings," "Motion-event cam," "Doorbell," "Archive - visually lossless") map to a (mode, foreground-CRF, background-CRF, codec) tuple. Raw mode control lives behind an "Advanced" toggle.

**Cost of being wrong:** near zero; advanced users get the toggle.

### Pushback 4 - Consumer cameras are a first-class ingestion problem, not an afterthought

**Current docs:** ingestion is file / RTSP / camera, framed around pro/IP cameras.

**I believe:** consumer/prosumer cameras (Ring, Nest, Wyze, Reolink, Arlo) need their own ingestion design because half of them are cloud-locked.

**Because:** the owner wants homeowners served, and the naive assumption "just point RTSP at it" fails for Ring/Nest (no local stream). The honest design (M-CAM): ONVIF/RTSP direct for cameras that support it; watch-folder on exported clips for cloud-locked ones; documented bridge integration (Home Assistant / Scrypted / Frigate) for users who want cloud-cam footage as a local RTSP stream. Explicitly **not** vendor-cloud scraping.

**Cost of being wrong:** promising "works with Ring" and then trying to scrape Ring's cloud → broken on their next app update and a likely ToS violation. The bridge/export framing is durable.

### Corrected near-term architecture (what actually ships in v2)

**Python pipeline + Flask UI + ONNX Runtime inference + bundled LGPL FFmpeg + ONVIF/RTSP + watch-folder + Inno Setup installer.** One language, one process, no FFI, no rewrite, slimmed to a few hundred MB. The Rust/Flutter/mobile destination in `ARCHITECTURE.md` stays as the long-term aspiration, pursued as measured spikes (M6), promoted to committed work only on evidence.

---

## 7. Roadmap with monthly granularity through Q1 2027

Sequenced for a part-time student team, ship-small-and-often, rewrite risk at the back. Each milestone maps to a heading in `EXECUTION-CLAUDE-CODE.md`. Ordering is load-bearing; dates will slip.

**June 2026 - M0 Foundation + M1 Refactor (`app`)**
- M0 (gating): reproducible green test baseline (triage the 48 failures / 5 errors), GitHub Actions CI (build + test, no auto-deploy), version bump off `0.1.0`, repo hygiene (drop stray `db_query.py`, reconcile `requires-python`), and **fold the plate reader from `premium` into `app` as a free `[plates]` extra; retire the premium mirror workflow** (§4).
- M1: split `src/gui/app.py` (3,880 lines, 48 routes) per `docs/REFACTOR-PLAN-gui-app.md`; split `index.html` (7,026 lines) into JS modules. Suite stays green throughout.

**July 2026 - M2 Slim installer + M3 Surveillance presets (`app`)**
- M2: PyTorch → ONNX Runtime (YOLOv8n + Real-ESRGAN to ONNX), CPU-first; trim exclude list; bundle LGPL FFmpeg; weights as an optional installer component; Inno Setup → `SVCS-Setup-x.y.z.exe`. Target ≤ ~600 MB download.
- M3: preset system v1 centered on **surveillance** preset families (continuous CCTV, motion-event, doorbell, multi-camera, archive) + content auto-detection (rule-based, §16). Modes hidden behind presets.

**August 2026 - M-CAM Camera ingestion + M4 Self-host (`app`)**
- M-CAM (new): ONVIF discovery + RTSP auto-config for IP/consumer cameras that support it; export-folder watch presets tuned to common camera clip formats; documented bridge integration (Home Assistant / Scrypted / Frigate) for cloud-locked Ring/Nest/Arlo; a consumer-camera preset family.
- M4: harden watch-folder automation; Docker image for the server scenario; dashboard auth for non-localhost binds (security gap today - §10).

**September 2026 - M5 Public beta (`app`)**
- Public download page (GitHub Pages); first **unsigned** public beta `v2.0.0-beta` (Windows); opt-in anonymous usage stats wired (§9); user-facing getting-started + camera-setup docs.

**Q4 2026 - M5b Signing + M6 Rust spike (gated)**
- M5b: code signing (Windows EV, or SignPath OSS program) → first signed build; macOS `.dmg` notarization *if* cert/budget exist (else defer); Linux AppImage.
- M6 (gated spike, `kdev`): port the encoder module only to Rust, validate byte/quality parity on CDnet clips, measure the real size/perf win, produce a written go/no-go. Promote further Rust work only if it justifies itself.

**Q1 2027 - Decision point**
- With the Python surveillance tool in the field and the M6 spike measured, make the explicit go/no-go on the Rust core and on Flutter/Android. Begin i18n scaffolding if there's pull. Revisit (only if the team chooses and is legally cleared) whether a commercial fork is worth pursuing - from a position of a mature product and real users, not as a v2 precondition.

---

## 8. Build, release, and distribution pipeline

### End-to-end, `git push` → installed `.exe`, with every missing step marked

1. Commit on `app`, message ends `Bloodawn(KheivenD)`, push. **(exists)**
2. ~~Mirror to `premium` after every commit.~~ **Retired** - with no paid edition, the `premium` mirror dance is dropped (M0). `premium` goes dormant.
3. CI on push: install deps, `pytest tests/`, build the PyInstaller bundle on Windows, smoke-test. **(MISSING - M0 adds GitHub Actions)**
4. On a release tag, CI builds the bundle and publishes artifacts. **(MISSING - M0/M5)**
5. Bundle ONNX models + LGPL FFmpeg, or fetch as an optional first-run component. **(MISSING - FFmpeg on PATH today, torch still bundled; M2)**
6. Wrap in Inno Setup → `SVCS-Setup-x.y.z.exe` with an optional "AI model weights" component. **(MISSING - M2)**
7. Code-sign the installer. **(MISSING - needs cert or SignPath OSS; M5b)**
8. Publish to GitHub Pages + GitHub Releases with SHA-256 checksums. **(MISSING - M5)**
9. macOS `.dmg` (signed + notarized) and Linux AppImage. **(MISSING - M5b; macOS gated on Apple cert)**
10. Update channel: a simple "check latest GitHub Release" version ping with a manual-download link. No silent auto-update for v2 (§16). **(MISSING - post-GA)**

### Bundle-size budget

| Component | Today | After M2 (ONNX) |
|---|---|---|
| PyTorch + CUDA | ~1.5-2.5 GB | removed |
| ONNX Runtime (CPU) | - | ~50-150 MB |
| Model weights (YOLOv8n + Real-ESRGAN x4) | ~70 MB | ~70 MB, optional component |
| FFmpeg (LGPL) | on PATH | ~80-120 MB bundled |
| Python + app + OpenCV etc. | ~0.5-1 GB | ~0.4-0.7 GB |
| **Installer download (target)** | **2.5-4.7 GB** | **~400-600 MB** |

The strongest argument for Pushback 1: most of the Rust rewrite's promised win is available without it.

---

## 9. Telemetry / privacy posture

**Ratified:** crash reporting is opt-in, off by default, and not shipped unless the user installs the `[crash-reporting]` extra and sets both env vars. For a surveillance tool handling sensitive footage, default-off is non-negotiable - it's the whole §2 posture.

**Extension:** add a **separate, explicitly opt-in, anonymous usage-stats channel** (preset popularity, codec choice, encode success/failure, anonymized error categories - no footage, no file contents, no paths, no PII, no reinstall-surviving IDs). Default off, with a clear first-run consent screen. This lets the team choose which presets and which camera integrations to invest in without compromising privacy. The current "no telemetry at all" leaves product decisions blind; a small consented anonymous signal is strictly better while keeping the privacy posture intact.

---

## 10. Security model

- **Encryption at rest:** AES-256-GCM, PBKDF2 600k. Sound, implemented. (Its tests are currently red in the full run - §11; design fine, test health not.)
- **Key management:** document the threat model - password-derived vs raw-key modes, keys never written plaintext, and that losing the password loses the data (say so loudly in the UI).
- **Plate-reader PII:** the highest-sensitivity path. License plates are PII in many jurisdictions. Keep recognized plate strings out of logs and crash reports (verify Sentry scrubbing covers them), store encrypted if persisted, and ship a "know your local ALPR/recording laws" notice. This applies doubly now that the plate reader is a *free* feature anyone can enable.
- **Camera-footage sensitivity:** surveillance footage often shows faces, plates, and the inside of homes (consumer cams). The default posture - fully local, nothing uploaded - is the protection. Document it as a feature.
- **Dashboard has no auth.** On localhost that's correct. The moment it binds `0.0.0.0` (the Docker/server scenario, which is also how a prosumer might run it on a NAS), anyone on the network reaches it. **M4 must add basic auth for non-localhost binds or refuse to start without an explicit override.** This is R-AUTH below and is the one real security gap in the current code.
- **Supply chain:** `uv.lock` pins deps (good); add a CI vulnerability scan (M0). The ONNX swap *reduces* attack surface by dropping torch/paddle.
- **Installer integrity:** publish SHA-256 checksums (M5); signing (M5b) is the real fix for tamper/SmartScreen.

---

## 11. Quality bar

### The test suite is not currently green - fix this first

Verified against the repo:

- `pytest_final.log` (2026-05-14 20:23, **after** the last commit at 16:20): **48 failed, 465 passed, 3 skipped, 5 errors**.
- Counts are quoted inconsistently across docs - 118 (handoff), 102 (commit + REFACTOR-PLAN), 274+ (`CONTRIBUTING.md`), 93 / 465 (logs). Test counts are hand-written into prose and drifting.
- Failures cluster by whole file (all of `test_encryption`, `test_crash_reporting`, `test_gui_api`) - the signature of a missing optional dependency or import error in that environment, not 48 independent regressions. A hypothesis until a controlled run confirms it.

**Mandate (M0, gating):**
1. One reproducible command yielding a known result on a clean checkout with documented extras; commit its output.
2. Triage every failure/error: real regression vs environment/optional-dep; fix or explicitly skip-with-reason.
3. Stop hand-writing test counts in prose; CI prints the number, docs link to CI.

Until this exists, *we don't know what works.*

### Discipline (ratified)

- Every behavior change ships a test; every refactor proves regression-free by a green CI run, not a subset.
- Real-video integration tests against CDnet clips stay (they caught issues unit tests couldn't).
- A CI coverage floor that ratchets up, never down.

### Accessibility & i18n

- Flask dashboard: pragmatic accessibility subset (keyboard nav, focus order, contrast, alt text) in M5b hardening. Full WCAG 2.1 AA is a target *if* Flutter happens; don't gate GA on it for a local tool.
- i18n: not a v2 feature. Extract user-facing strings into a catalog during the M1 frontend split so later translation is mechanical; translate nothing until usage stats (§9) show where users are.

---

## 12. Support and community

- **GitHub Issues + Discussions** as the free baseline (ratified).
- **Discord** once there's a beta (M5) - the self-hoster / Frigate / Home Assistant crowd lives in Discord and is exactly the M-CAM audience. One channel, light moderation.
- **Docs** under `docs/` (ratified). A user-facing getting-started + **camera-setup guide** (which cameras work directly, which need a bridge or export) ships before the public beta (M5). This guide is high-leverage for the consumer audience.
- No SLAs - it's a volunteer open-source project; set expectations as best-effort.

---

## 13. Legal and licensing

### Open-source release (the live question)

For an AGPL-3.0 release, the IP picture (FAU + DoD + students) is almost certainly permissive - sponsors generally welcome open release. Get a short written blessing from FAU tech-transfer + the sponsor (§0 item 1) and proceed. This is *not* gating for the open-source work below; it's a confirmation to obtain in parallel.

### FFmpeg LGPL vs GPL (ratified with detail)

Default to an **LGPL** FFmpeg build for the bundle. Note: x264/x265 are GPL; an FFmpeg built with them becomes GPL. For an **AGPL open-source project this is harmless** (AGPL is GPL-compatible) - so v2 can freely bundle GPL FFmpeg with x265. Document the matrix in `docs/ffmpeg-licensing.md` anyway, because it's the thing a future commercial fork would have to untangle (AV1/OpenH264 default, HEVC patent-pool royalties per deal). For v2 itself: no constraint.

### Dependency audit

Turn `ARCHITECTURE.md`'s dependency table into a CI-generated `docs/licenses.md`. For an AGPL project nothing copyleft is a problem; the audit's value is hygiene and readiness for a possible future fork. `OpenALPR` stays excluded (AGPL) - though for an AGPL project that's no longer a hard block, EasyOCR (Apache) remains the better backend on size/quality grounds.

### The commercial fork (deferred and conditional)

If - and only if - the team is legally cleared to commercialize (IP ownership confirmed with FAU + DoD), *and* chooses to, *after* the open-source product is mature, a commercial fork can branch from a frozen open-source release. At that point: revive the CLA (lawyer-reviewed), form an entity before the first dollar, cap any indemnity, swap Ultralytics→RT-DETR/ONNX and GPL-FFmpeg→AV1/OpenH264 for closed distribution. **None of this is v2 work.** The `premium` branch stays dormant in the repo as the natural seam. The `CLA.md` and `LICENSE-COMMERCIAL.md` files can stay in the repo as drafts marked "not in force" or be removed for clarity - owner's call (see EXECUTION TASK 0.6).

### Contact hygiene

The commercial-contact email in `LICENSE-COMMERCIAL.md`/`CLA.md` is an FAU student address (`kdhaiti2024@fau.edu`). For an open-source project, a project issue tracker + a stable project email/alias is better than a student address that expires at graduation. Low priority while open-source-only, but worth a project-owned alias before the public beta.

---

## 14. Risk register

| # | Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|---|
| R2 | **Test suite not green** - building on unverified correctness | High | Confirmed (present) | M0 gating: reproducible baseline, triage 48 failures/5 errors, CI-enforced green. |
| R3 | **Scope/rewrite over-reach** - Rust + Flutter + mobile on a part-time team | High | High | §6: defer Rust/Flutter/mobile to gated spikes; ship Python desktop first. |
| R-AUTH | **Dashboard has no auth on non-localhost binds** | High | Medium | §10/M4: basic auth for server/NAS profile or refuse to start without override. |
| R4 | **Installer too big to download** | Medium | Confirmed (present) | M2: ONNX swap → ~400-600 MB without a rewrite. |
| R5 | **No CI** | High | Confirmed (present) | M0: GitHub Actions build+test (no auto-deploy). |
| R-CAM | **"Works with Ring/Nest" over-promise** - cloud-locked cams can't be tapped locally | Medium | Medium | §6 Pushback 4 / M-CAM: support export-folder + bridge ingestion; never scrape vendor clouds; document the limit clearly. |
| R6 | **Code-signing absent** - SmartScreen/Gatekeeper scares users; costs money | Medium | High | Unsigned beta (M5), signed GA (M5b); investigate SignPath OSS program. |
| R-IP | **IP not cleared even for open release** | Low-Medium | Low | §0/§13: get written AGPL-release blessing from FAU + sponsor; likely a formality. |
| R13 | **Plate-reader PII / ALPR-law exposure** (now a free feature) | Medium | Medium | §10: plates out of logs/crash data, encrypt if stored, lawful-use disclaimer. |
| R12 | **Mobile GPU paths unproven** | Medium | Low | Deferred (§6 Pushback 2); only a risk if/when mobile is committed. |
| R14 | **Part-time students; schedules slip** | Medium | High | §7 sequenced for slip; ordering matters, dates don't; checkpoint small. |
| R17 | **Rust spike hits a crate bug** (`ffmpeg-next`, `flutter_rust_bridge`) | Medium | Low | M6 is a measured spike with a go/no-go - that's the mitigation. |

(The commercial-track risks from the prior revision - indemnity, equal-split friction, LLC, pricing - are removed; they don't apply to an open-source-only v2.)

---

## 15. Open questions remaining

1. **macOS vs Linux priority** for installers - macOS needs a paid Apple cert; Linux AppImage is cheap. Linux-first may be right if budget is tight; decide when the cert situation is known.
2. **Which consumer cameras to prioritize in M-CAM** - Reolink/Amcrest (RTSP, easy) vs the Ring/Nest (bridge-only) crowd. The RTSP cams are the cheaper, higher-success first target; instrument usage (§9) to see what people actually have.
3. **Auto-detect classifier sophistication** - §16 specs rule-based v1; whether it ever needs a learned model depends on field misclassification rates. Instrument and decide.
4. **Update channel** - manual version-ping for v2 (§16); revisit auto-update after GA once signing exists.
5. **How long `dev` (v1.x) stays alive** - depends on §0 item 2 (sponsor follow-on).
6. **Keep or remove `CLA.md` / `LICENSE-COMMERCIAL.md`** from the repo - owner's call (TASK 0.6); they're harmless as marked-dormant drafts but can confuse contributors into thinking there's a paid edition.

---

## 16. Resolutions to the handoff's §6 open questions

- **Pricing tiers:** N/A - open source, no paid tier (§5). A future commercial fork would price then, if ever (§13).
- **Hosted SaaS?** No, and now doubly so - self-hosted/local is the entire privacy posture for surveillance footage. Out of scope indefinitely.
- **Preset auto-detection - the classifier:** rule-based, hand-engineered, reusing signals the pipeline already computes. Analyze the first ~30 seconds: foreground-area ratio (free from MOG2), scene-change rate, motion variance, resolution, frame rate, luma/color distribution, audio presence. A small decision tree maps these to a **surveillance** preset (e.g., *very low foreground ratio + static histogram → "Continuous CCTV - max savings"; sparse motion events → "Motion-event / doorbell"; busy multi-object scene → "Active scene"*). **Not a CNN** - the MOG2 foreground ratio is already a strong free signal. Swap in a learned model later behind the same interface if field data demands it.
- **Plex/Jellyfin / self-host integration:** pulled in via M4 + M-CAM. For surveillance specifically, the bigger integrations are **Frigate, Home Assistant, and Scrypted** (the self-hosted-NVR ecosystem) - these are where the prosumer camera crowd already is, and they expose RTSP we can consume. Watch-folder + RTSP downstream of these, minimally scoped.
- **Update channel:** simple "check latest GitHub Release" ping + manual download; no silent auto-update for v2.
- **Telemetry:** §9 - crash reporting stays opt-in/off; add a separate opt-in anonymous usage-stats channel so investment decisions (which presets, which cameras) aren't blind.
- **i18n / accessibility:** §11 - string extraction now, translation later; pragmatic accessibility subset on Flask in M5b.
- **Mobile-specific features:** deferred (§6 Pushback 2); when it lands: battery-aware throttling, storage-aware refusal, network-aware (Wi-Fi-only, never cellular upload). For surveillance the mobile use case is "view/manage compressed footage," not "capture," which simplifies it.
- **Rust-port risk:** §6 Pushback 1 + R17 - deferral-to-spike (M6) is the mitigation; encoder-only port, measured parity, go/no-go before any further commitment.

---

*End of `PLAN-V2.md`. The sequenced engineering tasks are in `docs/EXECUTION-CLAUDE-CODE.md`.*
