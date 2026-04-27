# Sponsor meeting notes — April 15, 2026
## EGN 4950C Group 16 · NIWC Pacific / DIU weekly sync

**Date:** April 15, 2026  
**Time:** 12:04 PM  
**Duration:** ~35 minutes  
**Attendees:**
- Kheiven D'Haiti (team lead)
- Riley Roberts
- Cody Hayashi — CIV, NIWC ACT PAC Hawaii (H56H0), primary sponsor
- Geena Wann-Kung — CIV, NIWC ACT PAC Hawaii (H56C0), project coordinator
- Sean — NIWC Pacific (new contact, introduced by Geena)

This was the final scheduled weekly sync before the May 6 capstone deadline.

---

## Demo walkthrough

Kheiven opened with a screen share of the current GUI. He walked through the file browser (so operators don't have to type file paths), Ashleyn's metadata search panel (which automatically populates after a clip finishes processing and lets you filter by object type), and Riley's side-by-side demo output.

Cody's feedback: "Love the website. Looks good, looks clean. Love dark mode. Easy on the eyes — and being able to retool settings on the fly is awesome."

He asked two questions during the demo:

**"Are you controlling the object detection, or is that coming from somewhere else?"**
The boxes are OpenCV background subtraction (MOG2). Kheiven confirmed this. Cody followed up: "So how do you implement the boxes — YOLO or OpenCV?" Riley answered that it's OpenCV, not a neural detector. (Note: the YOLO classification gate we added in PR #31 sits on top of MOG2 as a secondary filter, but the primary detection is still MOG2.)

**"Is it compressing right now?"**
Yes — Kheiven ran the pipeline live during the demo and showed the output clip once it finished. The in-browser preview wasn't working yet (still required opening the file locally), which Cody noted.

---

## Mode system discussion

Riley walked Cody through all four modes in detail. This exchange is worth capturing in full because Cody's questions will shape the roadmap.

Mode 0 encodes everything — foreground at CRF 18, background at CRF 45. Continuous stream, no data dropped.

Mode 1 skips frames that have no detected objects. Cody's reaction: "Oh, awesome." Riley's framing: good for night mode when there's not much activity — you don't save any of those dead pixels at all.

Mode 2 captures one background keyframe before objects appear, then composites just the bounding box crops over that frozen background on subsequent frames. Cody's question: "For the background, is there value in updating it? For example, once every half hour? Conditions change — rain, sun, lighting." Riley confirmed: yes, `bg_refresh_interval` handles this. He also flagged the hard constraint: if traffic is constant, the background never gets a clean frame to refresh from, and Mode 2 breaks down. The planned fix is a context switch that falls back to Mode 0 automatically when the activity rate exceeds a threshold.

Mode 3 only encodes what's inside the bounding boxes. Everything else is blacked out. Cody's paraphrase: "Focus streaming." That's accurate.

Cody asked if we can also change the streaming algorithm (not just compression/detection). Riley clarified that we hadn't done live streaming yet — only file output. That opened the streaming discussion below.

---

## Streaming recommendation (Cody Hayashi)

This is a direct technical recommendation from the sponsor and should be treated as a specification.

Recommended architecture:

```
Camera → RTSP → pipeline server → FFmpeg → HLS → browser (hls.js or video.js)
```

Camera to server: RTSP. Most cameras already speak it. RTSP is fast and secure. RTP (without the S) lacks security — don't use it.

Server to browser: HLS. Opens natively in most browsers via the `<video>` element. Two open source player options — hls.js (functional, slightly harder to style) and video.js (backed by Mux, whose infrastructure powers Netflix; prettier and more styleable). Cody recommends video.js. Both are 100% free.

HLS is bandwidth-heavy and not ideal for low-latency applications. Apple extended it with HLS-LL and adaptive bitrate variants, but for static cameras on a DoD network the overhead is fine.

Testing approach: use VLC to re-stream a local clip as HLS, then test your player against it before building your own server side. video.js also exposes public live test streams you can point at.

Free test source: gookami.org. Cody's colleague Mikey found that all Hawaii state traffic cameras stream live 24/7 there. Full HD, raw video (no bounding boxes), free. Pull the HLS stream URL from the page source and attach it to the pipeline directly.

Status: HLS streaming is implemented. `src/gui/app.py` has 5 HLS routes. Tested April 20 with VLC re-streaming `cameraJitter_traffic.mp4` via RTSP — two vehicle segments captured with ROI boxes.

---

## Color detection (Geena Wann-Kung / Cody Hayashi)

Geena's ask: "Do you think we could search by color? Like if we're looking for a blue vehicle."

Cody's approach, proposed live:

1. Take the existing bounding box (MOG2 + classifier — no new model needed)
2. Crop the center 50% of that box (reduces road and background contamination)
3. Build an HSV color histogram over those pixels
4. Find the peak hue bin, map it to a label (red, orange, yellow, green, blue, white, black, gray)
5. Store the label in the segments DB

His reasoning: "Most of the bounding box should be a certain color. If it's an orange car, that's the only time you'll see orange, primarily." White cars are the hard case — they blend with backgrounds and overcast skies. He figured it would still be low effort relative to the value.

Riley noted the detector centers reasonably well on most vehicles, though close vehicles sometimes merge into a single oversized box (both cars detected as one object — visible in the demo). That's a separate issue.

Status: not started. Tracked in ROADMAP.md section 4.3.

---

## Config export (Cody Hayashi)

A "save config" button that exports known-working stream parameters — codec, compression quality, resolution, mode — as a JSON file. Operators load it on new hardware and get the same setup without re-tuning.

The motivation Cody gave: on DoD networks, the network is usually the bug. If a configuration works end-to-end on a specific network segment, you want to reproduce it exactly. "If I tool it in and press save, and it tells me: use this resolution, this algorithm, this mode — that'd be killer."

Geena flagged the time constraint. Cody agreed it's a nice-to-have, not a blocker.

Status: not started. Tracked in ROADMAP.md section 4.1.

---

## Electron desktop packaging (Cody Hayashi)

Kheiven asked whether to build a desktop app from the GUI. Cody's answer: web app first, desktop as a backup.

Web app is the primary target — one server, one place to secure, works on anything. For DoD deployment, getting a web app on a standalone server approved is often easier than pushing software onto individual machines.

The desktop case Geena described: if there's no network available (field testing, certain DoD environments with bandwidth limits), a bundled app lets you plug a laptop directly into the camera and run everything locally without a server. She said this is a real scenario.

Technical constraint: no React. React is blocked on certain DoD networks. Flask + vanilla HTML/JS (our current stack) is already compliant. An Electron shell that launches the Flask backend as a subprocess would work.

Cody's guidance: "If it takes an hour, go for it. If it's going to be a day or more, skip it." He mentioned there's a process for getting desktop apps approved on DoD machines, and it's less painful than it used to be.

Status: not started. Tracked in ROADMAP.md section 4.7 as a stretch goal.

---

## uv package manager (Sean, NIWC Pacific)

Sean asked for a migration from pip to uv (https://astral.sh/uv). The NIWC security teams require it. uv sandboxes the Python version and all packages away from global system installs, gives deterministic environments through a lock file, and eliminates the version drift that causes "works on my machine" failures. Sean: "All the security people are kind of crazy about uv — it's their favorite."

What it means in practice: `pyproject.toml` replaces `requirements.txt`, `uv lock` generates `uv.lock`, and `uv sync` replaces `pip install -r requirements.txt`. FFmpeg still needs a separate system install.

Status: done. `pyproject.toml` and `uv.lock` are in the repo. README and DEV.md updated. Tracked in ROADMAP.md section 4.5.

---

## Per-mode compute benchmarks (Cody Hayashi / Geena Wann-Kung)

Geena's scenario: a laptop plugged into a camera, running for hours with no network. She needs to know how long the battery holds up and whether the hardware can keep up with the encode.

They asked for: average CPU% per mode (0, 1, 2, 3) on the same test clip, encode time per mode, and estimated battery life. Cody suggested using a 3-hour laptop battery as a baseline and working backward from CPU draw. Storage per hour per mode is partially covered by Jorge's stress test results, but CPU% and battery drain are not.

Status: not started. Tracked in ROADMAP.md section 4.6.

---

## Compression literature review (Cody Hayashi)

Cody raised a question about comparing our system to existing compression standards. Riley correctly pointed out the comparison isn't fair — we're not compressing everything, we're selectively dropping data that doesn't contain objects. A storage ratio comparison against naive H.264 isn't apples-to-apples.

Cody's response: "I wonder if there are research papers where people do something similar — intentional lossy compression where you actually get rid of data." He asked us to look. If prior work exists, citing it strengthens the final report. If it doesn't, the absence of prior work is its own finding.

Search terms to try: "selective video compression surveillance," "ROI-based video compression static camera," "event-driven video encoding," IEEE Xplore, arXiv.

Status: not started. Tracked in ROADMAP.md section 4.8.

---

## Summary of action items

| Item | Owner | Status | Notes |
|---|---|---|---|
| HLS streaming (RTSP → pipeline → HLS → browser) | KD | Done | Completed April 20 |
| uv migration | KD | Done | `pyproject.toml` + `uv.lock` in repo |
| Color detection via HSV histogram on bbox center | AM | Open | Section 4.3 |
| Config export (JSON of working stream params) | KD | Open | Section 4.1 |
| Electron desktop app | KD | Open | Stretch — only if fast |
| Per-mode CPU + battery life benchmarks | JS | Open | Section 4.6 |
| Literature review on selective compression | KD/RR | Open | Section 4.8 |

---

## Sponsor's overall assessment

Cody's closing: "That was all the comments I had on the GUI. It looks good. Looks solid." He specifically called out the bottom-right panel of the dashboard as a nice touch. Geena: "I know I'm giving you guys a lot of stuff to think about and work on." Riley's reply: "I look forward to next week when we can show off what we've done."

The tone of the meeting was collaborative. Cody was engaged and technical, not just checking boxes. He pushed back with good questions (the background refresh interval, the apples-to-apples comparison problem), suggested concrete implementation approaches (the histogram color idea, the HLS architecture), and was honest about what's a nice-to-have vs. what matters.
