# Open Source Selective Video Compression for Static Surveillance Cameras
**EGN 4950C Capstone Project | Florida Atlantic University | Spring 2026**
**Sponsor:** Defense Innovation Unit (DIU) | **Category:** AI / Video

---

## Project Overview

This project develops an open-source, hardware-lightweight software pipeline for
selective video compression of static surveillance camera footage, primarily targeting
Navy and DoD land surveillance use cases.

The core insight: static surveillance cameras produce enormous amounts of redundant
data because most pixels in any given frame are identical to the previous frame.
By applying background subtraction to isolate only the foreground objects of
intelligence value (people walking, vehicles moving), and compressing only those
regions at high quality while discarding or heavily compressing static background
pixels, we demonstrated storage savings of approximately 6x compared to standard
full-frame codec compression.

The system is designed to run on commodity, low-cost hardware with no GPU requirement,
making it deployable on existing DoD infrastructure without procurement of modern
accelerators.

---

## Problem Statement

Navy and DoD surveillance installations generate continuous video streams from static
cameras that must be stored locally for approximately one week before being offloaded
to longer-term storage. Current full-frame compression approaches (H.264/H.265) do not
account for the fact that the overwhelming majority of pixels in static camera footage
never change. The result is enormous storage overhead for data that contains no
actionable intelligence value.

The population of interest within these streams is small: people on foot and
occupants of vehicles passing through the camera frame. Everything else is background.

---

## Solution Architecture

```
[Static Camera Feed]
        |
        v
[Background Subtraction]  <-- OpenCV MOG2 / KNN
        |
        v
[Foreground Mask + Bounding Regions]
        |
   _____|______
  |            |
  v            v
[Foreground   [Background]
 ROI Encode]   Heavy compression or keyframe-only
  H.264 HQ    H.264 low bitrate / static JPEG
  |            |
  v            v
[Multiplexed Compressed Stream]
        |
        v
[Local Storage -- ~1 week retention]
        |
        v
[Offload + Optional Enhancement]
     Super-resolution / decompression
```

---

## Key Design Constraints

- Must run on **legacy / low-spec hardware** (no modern GPU, minimal RAM)
- All components must be **open source and royalty-free**
- Target storage reduction: **6x or greater** vs. naive full-frame compression
- Retention window: approximately **one week** of continuous footage
- Primary targets: **people walking** and **people in vehicles**
- Output must be **decompressable and enhanceable** after offload

---

## Tech Stack

| Layer | Technology | License |
|---|---|---|
| Background Subtraction | OpenCV MOG2 / KNN / GMG | Apache 2.0 |
| Video I/O and Codec | FFmpeg + libx264 / libx265 | LGPL / GPL |
| Pipeline Orchestration | Python 3.x | PSF |
| ROI Encoding | FFmpeg with filter_complex ROI | LGPL |
| Enhancement (post-offload) | Real-ESRGAN / BSRGAN (CPU mode) | BSD |
| Metadata / Index | SQLite | Public Domain |
| Testing | pytest | MIT |

---

## Repository Structure

```
capstone-compression/
├── src/
│   ├── background_subtraction/   # MOG2, KNN, GMG wrappers
│   ├── compression/              # FFmpeg ROI encoding pipeline
│   ├── enhancement/              # Post-offload super-resolution
│   ├── pipeline/                 # End-to-end orchestration
│   └── utils/                    # Metrics, logging, file I/O
├── data/
│   └── samples/                  # Sample clips for testing (gitignored if large)
├── notebooks/                    # Benchmarking and analysis notebooks
├── tests/                        # Unit and integration tests
├── docs/                         # Design documents and notes
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/Blood-Dawn/capstone-compression.git
cd capstone-compression

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\Activate.ps1

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install FFmpeg (system binary  -  required)
# Ubuntu/Debian:
sudo apt update && sudo apt install ffmpeg -y
# macOS:
brew install ffmpeg

# 5. Check that everything is ready
bash check_deps.sh

# 6. Run the pipeline on a test clip
python src/pipeline/pipeline.py \
  --input data/samples/your_clip.mp4 \
  --camera-id cam_test \
  --output outputs/ \
  --preview
```

---

## Documentation

| Document | Description |
|---|---|
| [ROADMAP.md](ROADMAP.md) | Full milestone plan with team task assignments |
| [DEV.md](DEV.md) | Developer setup guide, module explanations, Git workflow |
| `check_deps.sh` | Run in terminal to verify your environment is ready |

---

## Group Members

| Name | GitHub |
|---|---|
| Kheiven D'Haiti | [@Blood-Dawn](https://github.com/Blood-Dawn) |
| Jorge Sanchez |  -  |
| Ashleyn Montano |  -  |
| Riley Roberts |  -  |
| Victor De Souza Teixeira |  -  |

**Course:** EGN 4950C Capstone | Florida Atlantic University | Spring 2026
**Final Deadline:** May 6, 2026
