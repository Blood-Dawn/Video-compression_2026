# Sponsor meeting notes - April 22, 2026
## EGN 4950C Group 16 · NIWC Pacific weekly sync

**Date:** April 22, 2026
**Time:** ~12:02 PM
**Duration:** ~35 minutes
**Attendees:**
- Riley Roberts (presenter - Kheiven was not present)
- Cody Hayashi - CIV, NIWC ACT PAC Hawaii (H56H0), primary sponsor
- Geena Wann-Kung - CIV, NIWC ACT PAC Hawaii (H56C0), project coordinator

---

## Demo walkthrough

Riley shared his screen and ran the demo live. Mode 2 and Mode 3 were new since the April 15 meeting. Cody's first reaction: "That's good to see - mode two and three are new."

File sizes shown on the same test clip across all four modes:

| Mode | Size | Description |
|------|------|-------------|
| Mode 0 | ~76 MB | Full continuous, dual CRF |
| Mode 1 | ~67 MB | Event clips only |
| Mode 2 | ~30 MB | Background keyframe + object patches |
| Mode 3 | ~17 MB | Objects only, all else blacked out |

Riley also showed the HLS live streaming panel and the local RTSP server, both added since April 15. Cody's overall read: the product is starting to look real.

---

## Background update strategy (Mode 2)

Cody's question: how does the background reference frame update over a long session? Riley explained the current approach - capture the last clean frame during warmup, freeze it as the keyframe, composite new object patches over it per frame.

Cody's suggestion: rather than trying to update the background on the edge device, keep the last known clean state and reconstruct context at playback time on a more powerful machine. The edge device is constrained. The playback environment isn't. His framing: "Show something representative of the scene, even if it's from way before."

This separates the compression problem (edge device) from the display problem (operator workstation). Worth tracking as a design option for Mode 2 playback.

Geena's addition: operators want to be able to pick a time window and stitch segments back together themselves. If the device has storage headroom, give them that flexibility. If it doesn't, the static background approach is the right call. The trade-off is losing context of background changes (lighting, weather).

---

## Mode 3 forensic use case

Cody confirmed Mode 3's value: if you know something happened and you're looking for what was in frame, Mode 3 gives you that at the smallest possible file. If you need to understand the full scene context, Mode 0 or 1 is better. His language for Mode 3: "focus streaming" - same as the April 15 framing.

Current bug Riley flagged: the background isn't updating when it should in some Mode 2 scenarios. Needs a fix before the final demo.

---

## Metrics - the main gap

Cody raised metrics as the single biggest open item. The project has compression ratio numbers but no CPU, latency, or encode-time data broken out by mode.

What he wants specifically:

- Compression ratio per mode (we have this for Mode 0, need 1-3)
- Average CPU% per mode on the same test clip
- Encode time per mode
- Latency from ingest to HLS output in the browser
- All of the above run on low-power hardware (Raspberry Pi or equivalent)

His exact framing on why: "Good metrics could lead to publishing after the class ends." He sees this as potential academic work - open source project with real benchmark data is publishable. The metrics also matter operationally: operators making hardware decisions need CPU% and battery draw, not just file sizes.

This is assigned to Jorge (CPU/encode benchmarks) and Kheiven (latency, notebook).

---

## Detection accuracy characterization

Cody's framing: the question isn't just false positive rate - it's whether the false negatives matter. If the system misses a pedestrian who is too small and blurry to identify anyway, that's not a meaningful miss. The goal is to describe what we catch and what we miss at a level operators can act on.

His specific suggestion: filter by confidence score AND bounding box size together. A high-confidence detection on a tiny bounding box is usually a false positive. A large box with moderate confidence is usually real. Combining both thresholds should improve accuracy without losing important detections.

Example use case Geena raised: a person walking near the road who might get hit by a car. Even if the person is far from the camera and detection confidence is lower, you want to capture that segment because the context matters. The system should be tunable by operators who understand their scene.

Current state: everything is classified as "vehicle." The team needs to separate people, vehicles, and unknown in the database and the query interface before the final demo.

---

## Super-resolution

Cody said he wants an honest test of where the super-resolution tech actually is. Not a demo optimized for the best case - a real test on footage where a person is small in the background. The question is whether the enhancer recovers enough detail to be useful. Riley confirmed the enhancer is in the pipeline with bicubic fallback.

No specific action item beyond running the test on realistic footage before May 6.

---

## Test footage (Geena Wann-Kung)

Geena's request: use a camera with oncoming traffic rather than a side view. Her reasoning: oncoming vehicles show varied sizes, colors, and approach speeds, which exercises the detector more than a side angle where everything is roughly the same shape.

Specific camera she suggested: intersection near a Pearl City shopping center. Oncoming traffic view.

What both Geena and Cody want to see in the test data:

- High-traffic and low-traffic footage from the same camera (rush hour vs. 2am)
- Nighttime footage (algorithms should auto-adjust contrast)
- Multiple vehicle colors and sizes
- Footage showing Mode 1's storage advantage on a real scene, not a synthetic benchmark

Cody mentioned gookami.org again (from April 15) as a source of live Hawaii traffic cameras - the team should pull representative clips from there for the final demo.

---

## Class presentation

Cody offered to attend the May 6 capstone presentation remotely if the team sends an invite. He asked for representative camera data to be ready before then so he can share context with his colleagues.

---

## Summary of action items

| Item | Owner | Status | Notes |
|---|---|---|---|
| Per-mode CPU%, encode time, battery benchmarks | JS | Open | Section 4.6 |
| Latency measurement (ingest to HLS output) | KD | Open | New from this meeting |
| Run all benchmarks on low-power hardware (Raspberry Pi) | KD/JS | Open | New from this meeting |
| Separate people / vehicle / unknown in DB and query UI | AM | Open | Currently all classified as vehicle |
| Fix Mode 2 background update bug | RR | Open | Background not updating in some scenarios |
| Make demo viewable in GUI (not just file output) | RR | Open | Currently requires opening file locally |
| Test super-resolution on real low-res footage | KD | Open | Honest test, not optimized demo |
| Pull diverse test footage from gookami.org | KD/RR | Open | Rush hour + nighttime, same camera |
| Send Cody invite for May 6 presentation | KD | Open | He confirmed he can attend remotely |
| Add metrics display to demo end screen | RR | Open | CPU%, compression ratio, storage savings per mode |

---

## Sponsor's overall read

Cody's closing: the product is coming together. The demo looks real. The gap is metrics - without per-mode CPU and latency numbers, operators can't make hardware decisions, and the project doesn't have publishable data. His interest in potential academic publishing after the class ends is genuine and worth taking seriously. The compression numbers we have are strong; the question is whether we can characterize them fully before May 6.
