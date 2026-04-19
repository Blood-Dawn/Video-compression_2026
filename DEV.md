# Developer Guide
## Open Source Selective Video Compression for Static Surveillance Cameras

This document is for **team members setting up the project for the first time** and for anyone who wants to understand how the codebase is structured and how all the moving parts fit together. Read this before you touch any code.

---

## Table of Contents

1. [What This Project Does](#1-what-this-project-does)
2. [System Requirements](#2-system-requirements)
3. [First-Time Setup](#3-first-time-setup)
4. [Verifying Your Setup](#4-verifying-your-setup)
5. [How the Code Is Organized](#5-how-the-code-is-organized)
6. [How Each Module Works](#6-how-each-module-works)
7. [Running the Pipeline](#7-running-the-pipeline)
8. [Running the Tests](#8-running-the-tests)
9. [Git Workflow](#9-git-workflow)
10. [Common Problems and Fixes](#10-common-problems-and-fixes)
11. [Adding New Features](#11-adding-new-features)
12. [Enhancement Module Setup (Milestone 2)](#12-enhancement-module-setup-milestone-2)
13. [Getting Test Videos](#13-getting-test-videos)

---

## 1. What This Project Does

Static surveillance cameras produce massive amounts of redundant video because most of the image never changes between frames  -  the wall, the pavement, the fence are always there. The only thing that matters intelligence-wise is moving objects: people walking, vehicles passing.

This pipeline:
1. **Reads** a video stream frame by frame
2. **Separates** the moving foreground (people, cars) from the static background using OpenCV background subtraction
3. **Encodes** the foreground at high quality and the background at heavy compression using FFmpeg
4. **Indexes** every saved segment in a SQLite database for fast retrieval
5. **Stores** compressed video locally for approximately one week
6. **(Optional, post-offload)** Applies CPU-based super-resolution to enhance compressed footage

The result is approximately 6x smaller video files compared to standard H.264 compression, with no GPU required.

---

## 2. System Requirements

### Operating System
- Linux (Ubuntu 20.04+ recommended), macOS 12+, or Windows 10/11 with WSL2
- Windows native is **not tested**  -  use WSL2 if you are on Windows

### Python
- Python **3.9 or higher** (3.11 recommended)
- Check your version: `python3 --version`

### FFmpeg (Required  -  must be installed as a system binary)
FFmpeg is not a Python package. It must be installed on your system separately.

**Ubuntu/Debian / WSL2:**
```bash
sudo apt update && sudo apt install ffmpeg -y
```

**macOS (Homebrew):**
```bash
brew install ffmpeg
```

**Windows (native  -  no WSL):**

Option A - Windows Package Manager (fastest):
```powershell
winget install ffmpeg
```

Option B - Manual install:
1. Download the latest build from https://www.gyan.dev/ffmpeg/builds/ (grab `ffmpeg-release-essentials.zip`)
2. Extract the zip to a folder like `C:\ffmpeg`
3. Add `C:\ffmpeg\bin` to your Windows PATH:
   - Open Start, search "Environment Variables"
   - Under System Variables, find "Path", click Edit
   - Click New and add `C:\ffmpeg\bin`
   - Click OK and restart your terminal

After installing with either option, close and reopen your terminal, then verify:
```bash
ffmpeg -version
```
You should see output starting with `ffmpeg version 4.x` or higher. If you get `command not found`, FFmpeg is not on your PATH yet.

### Git
- Git 2.x or higher
- Check: `git --version`

### (Optional) VS Code
- Recommended extensions: Python, Pylance, Jupyter, GitLens
- Open the repo folder directly in VS Code: `code .` from inside the project directory

---

## 3. First-Time Setup

Follow these steps **in order**. Do not skip any step.

### Option A — uv (recommended, requested by NIWC/Sean)

uv manages the virtual environment, Python version, and dependency lock file for you. No manual venv creation needed.

**Step 1 — Install uv**

```bash
# Linux / macOS / WSL2
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
winget install astral-sh.uv
```

Restart your terminal after installing so the `uv` command is on your PATH.

**Step 2 — Clone the repo**
```bash
git clone https://github.com/Blood-Dawn/capstone-compression.git
cd capstone-compression
```

**Step 3 — Install dependencies**
```bash
uv sync
```

This creates a `.venv/` directory, pins the exact Python version, and installs all dependencies from `pyproject.toml`. If `uv.lock` is present in the repo, it uses that to ensure every developer gets identical package versions.

To also install the optional super-resolution enhancer (needed for `--enhance` flag):
```bash
uv sync --extra enhance
```

Note: `basicsr` and `realesrgan` pull in large CUDA packages. Skip `--extra enhance` if you are on a CPU-only machine and do not plan to use `--enhance`.

**Step 4 — Run anything**

Prefix commands with `uv run` — it automatically activates the managed virtualenv:
```bash
uv run python src/pipeline/pipeline.py --help
uv run python run_gui.py
uv run pytest
```

Or activate the venv directly if you prefer:
```bash
source .venv/bin/activate      # Linux / macOS
.venv\Scripts\activate         # Windows PowerShell
```

---

### Option B — pip (fallback)

Use this if uv is unavailable on your machine.

**Step 1 — Clone the repo**
```bash
git clone https://github.com/Blood-Dawn/capstone-compression.git
cd capstone-compression
```

**Step 2 — Create a Python virtual environment**

Linux / macOS:
```bash
python3 -m venv venv
source venv/bin/activate
```

Windows (PowerShell or Git Bash):
```bash
python -m venv venv
.\venv\Scripts\Activate.ps1    # PowerShell
source venv/Scripts/activate   # Git Bash
```

Your terminal prompt should show `(venv)` when active.

**Step 3 — Install Python dependencies**
```bash
pip install -r requirements.txt
```

This installs OpenCV, NumPy, FFmpeg-Python, scikit-image, pytest, and all other required packages. It may take a few minutes.

### Step 5  -  Verify FFmpeg Is on PATH
```bash
ffmpeg -version
```
If this fails, see [FFmpeg installation](#ffmpeg-required--must-be-installed-as-a-system-binary) above.

### Step 6  -  Create Required Directories
Some output directories are gitignored and need to be created locally:
```bash
mkdir -p outputs logs data/samples
```

### Step 7  -  Get a Test Video Clip
Video files are gitignored (they are too large for git). Ask a teammate for the shared test clips, or use any short `.mp4` file. Place it in `data/samples/`. A clip of a parking lot, hallway, or street corner works best.

### Step 8  -  Run the Dependency Check Script
```bash
bash check_deps.sh
```
This will tell you if anything is missing. See [Verifying Your Setup](#4-verifying-your-setup) for details.

---

## 4. Verifying Your Setup

Run the dependency check script from the project root:
```bash
bash check_deps.sh
```

It checks:
- Python version (must be 3.9+)
- FFmpeg installed and on PATH
- All pip packages from requirements.txt are installed
- `data/samples/` and `outputs/` directories exist

If everything passes, you will see:
```
✅  All checks passed. You are ready to run the pipeline.
```

If something fails, the script will tell you exactly what is missing and how to fix it.

You can also run the test suite as a quick sanity check:
```bash
pytest tests/ -v
```
All tests should pass with no errors on a clean setup.

---

## 5. How the Code Is Organized

```
capstone-compression/
│
├── src/                              ← All application source code lives here
│   ├── background_subtraction/
│   │   ├── __init__.py
│   │   └── background_subtraction.py ← BackgroundSubtractor class
│   │
│   ├── compression/
│   │   ├── __init__.py
│   │   └── roi_encoder.py            ← ROIEncoder class (FFmpeg wrapper)
│   │
│   ├── enhancement/
│   │   ├── __init__.py
│   │   └── enhancer.py               ← Enhancer class (Milestone 2, not yet complete)
│   │
│   ├── pipeline/
│   │   ├── __init__.py
│   │   └── pipeline.py               ← Main entry point, orchestrates everything
│   │
│   └── utils/
│       ├── __init__.py
│       ├── metrics.py                ← PSNR, SSIM, compression ratio calculations
│       └── db.py                     ← SQLite metadata database (Milestone 1)
│
├── data/
│   └── samples/                      ← Put your test .mp4 clips here (gitignored)
│
├── notebooks/                        ← Jupyter notebooks for analysis and benchmarking
│   ├── milestone1_benchmark.ipynb
│   └── algorithm_comparison.ipynb
│
├── tests/                            ← Unit and integration tests
│   ├── __init__.py
│   └── test_background_subtraction.py
│
├── docs/                             ← Design documents, meeting notes, results
│
├── outputs/                          ← Compressed video outputs go here (gitignored)
├── logs/                             ← Log files (gitignored)
│
├── check_deps.sh                     ← Dependency verification script
├── requirements.txt                  ← Python dependencies
├── .gitignore
├── README.md                         ← Project overview
├── ROADMAP.md                        ← Milestone plan with team task assignments
└── DEV.md                            ← This file
```

---

## 6. How Each Module Works

### `src/background_subtraction/background_subtraction.py`

**What it does:** Takes individual video frames and returns a binary mask where white pixels are "foreground" (moving objects) and black pixels are "background" (static scene). It also returns a list of bounding boxes around detected foreground regions.

**Key class:** `BackgroundSubtractor`

**Key methods:**
- `__init__(method='MOG2', ...)`  -  Creates the subtractor. `method` can be `'MOG2'`, `'KNN'`, or `'GMG'`. MOG2 is the default and works best for most cases.
- `apply(frame)`  -  Pass a single BGR frame (NumPy array). Returns `(mask, bounding_boxes)` where `mask` is a grayscale image and `bounding_boxes` is a list of `(x, y, w, h)` tuples.
- `reset()`  -  Resets the background model. Call this when switching to a new video source.

**How it works internally:**
OpenCV's background subtraction algorithms maintain a statistical model of what the "background" looks like based on the last N frames. When a new frame comes in, each pixel is compared to its expected background value. Pixels that deviate significantly are classified as foreground. MOG2 uses a Gaussian mixture model; KNN uses k-nearest neighbors in pixel color space. Both are adaptive  -  they update the background model over time to account for slow lighting changes.

**Example usage:**
```python
from src.background_subtraction.background_subtraction import BackgroundSubtractor

subtractor = BackgroundSubtractor(method='MOG2')
mask, bboxes = subtractor.apply(frame)
# mask: H x W grayscale image, white = foreground
# bboxes: [(x, y, w, h), ...]
```

---

### `src/compression/roi_encoder.py`

**What it does:** Takes a video frame, the foreground bounding boxes, and encodes the video segment to disk using FFmpeg. Foreground regions are encoded at high quality (low CRF); the background is encoded at low quality (high CRF).

**Key class:** `ROIEncoder`

**Key methods:**
- `__init__(output_dir, fg_crf=18, bg_crf=45, fps=30)`  -  Configure the encoder. `fg_crf` controls foreground quality (lower = better quality, larger file). `bg_crf` controls background quality (higher = worse quality, smaller file).
- `encode_segment(frames, bboxes_per_frame, camera_id, timestamp)`  -  Encode a list of frames into a compressed video segment. Returns the output file path and file size.
- `get_file_size(path)`  -  Returns the size of an output file in bytes.

**How it works internally:**
FFmpeg is called as a subprocess via `ffmpeg-python`. The pipeline passes raw frames to FFmpeg through a pipe (stdin). FFmpeg encodes them using libx264 with the specified CRF values. ROI-specific quality is controlled using FFmpeg's `filter_complex` to apply different quantization levels to different spatial regions.

**CRF reference:**
- CRF 0 = lossless (huge file)
- CRF 18-23 = visually near-lossless (used for foreground)
- CRF 28 = default H.264 quality
- CRF 40-51 = very aggressive compression (used for background)

---

### `src/pipeline/pipeline.py`

**What it does:** Ties everything together. It reads frames from a camera or video file, runs background subtraction, passes results to the encoder, and writes metadata to the database.

**How to run it:**
```bash
# On a pre-recorded test clip
python src/pipeline/pipeline.py --input data/samples/test_clip.mp4 --camera-id cam_test --output outputs/

# On a live USB camera (index 0)
python src/pipeline/pipeline.py --input 0 --camera-id cam_live --preview

# With all options
python src/pipeline/pipeline.py \
  --input data/samples/test_clip.mp4 \
  --camera-id cam_01 \
  --output outputs/ \
  --method MOG2 \
  --fg-crf 20 \
  --bg-crf 45 \
  --segment-duration 30 \
  --preview
```

**CLI flags:**
| Flag | Default | Description |
|---|---|---|
| `--input` | (required) | Path to video file or camera index (0, 1, ...) |
| `--camera-id` | `cam_default` | Identifier stored in the metadata database |
| `--output` | `outputs/` | Directory where compressed segments are saved |
| `--method` | `MOG2` | Background subtraction algorithm (MOG2, KNN, GMG) |
| `--fg-crf` | `20` | CRF for foreground regions (lower = better quality) |
| `--bg-crf` | `45` | CRF for background (higher = more compressed) |
| `--segment-duration` | `60` | Seconds per output video segment |
| `--preview` | off | Show live preview window with foreground mask |

**What the pipeline loop does per frame:**
1. Read frame from camera/file
2. Call `BackgroundSubtractor.apply(frame)` → get mask + bounding boxes
3. If bounding boxes exist, flag segment as containing a detected target
4. Accumulate frames until `segment_duration` seconds of footage is buffered
5. Call `ROIEncoder.encode_segment(frames, bboxes)` → write compressed file to disk
6. Write one row to the metadata SQLite database
7. Print storage stats (original size vs. compressed size)

---

### `src/utils/metrics.py`

**What it does:** Calculates quality and efficiency metrics for evaluating the pipeline.

**Key functions:**
- `compute_psnr(original, compressed)`  -  Peak Signal-to-Noise Ratio in dB. Higher is better. Above 30 dB is generally acceptable; above 40 dB is excellent.
- `compute_ssim(original, compressed)`  -  Structural Similarity Index. Ranges 0 to 1. Above 0.85 is the target.
- `compute_compression_ratio(original_bytes, compressed_bytes)`  -  Returns a float. `6.0` means the compressed file is 6x smaller. Target is ≥ 6x.

---

### `src/utils/db.py` (Milestone 1  -  create this file)

**What it will do:** Maintains a SQLite database that indexes every compressed video segment.

**Schema (to be implemented):**
```sql
CREATE TABLE segments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,        -- ISO 8601 format
    camera_id     TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    file_size     INTEGER,              -- bytes
    duration      REAL,                 -- seconds
    target_detected INTEGER DEFAULT 0, -- 1 if foreground detected, else 0
    roi_count     INTEGER DEFAULT 0     -- number of bounding boxes in segment
);
```

**Why SQLite?** It's built into Python (no installation required), requires no server, and is perfectly adequate for indexing a week's worth of segments from a handful of cameras.

---

### `src/enhancement/enhancer.py` (Milestone 2  -  create this file)

**What it will do:** Take a compressed frame or ROI and upscale it using Real-ESRGAN running in CPU mode.

**Why we need this:** The background is stored at very low quality. After offload, analysts may want to enhance the footage for review. Super-resolution can recover some of the detail lost during aggressive compression.

**Model to use:** Real-ESRGAN (`RealESRGAN_x4plus.pth`)  -  download from the official repo at [https://github.com/xinntao/Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN). Place model weights in `models/` (gitignored). Do not commit model weights to git.

---

## 7. Running the Pipeline

### Quick Start (after setup)
```bash
# Activate your venv first
source venv/bin/activate

# Run on a test clip
python src/pipeline/pipeline.py \
  --input data/samples/your_clip.mp4 \
  --camera-id cam_test \
  --output outputs/ \
  --preview
```

### Checking the Output
After the pipeline runs:
```
outputs/
├── cam_test_20260115_143022.mp4    ← compressed video segment
├── cam_test_20260115_143122.mp4
└── metadata.db                     ← SQLite database with segment index
```

Query the database directly:
```bash
sqlite3 outputs/metadata.db "SELECT * FROM segments;"
```

---

## 8. Running the Tests

Always run tests before submitting a pull request.

```bash
# Run all tests (uv)
uv run pytest tests/ -v

# Run all tests (pip / activated venv)
pytest tests/ -v

# Run a specific test file
uv run pytest tests/test_background_subtraction.py -v

# Run with coverage report
uv run pytest tests/ -v --cov=src --cov-report=term-missing
```

A passing test run looks like:
```
tests/test_background_subtraction.py::test_mask_shape PASSED
tests/test_background_subtraction.py::test_empty_frame PASSED
...
5 passed in 1.23s
```

If any test fails, **do not open a PR** until it is fixed.

---

## 9. Git Workflow

### Daily Workflow
```bash
# Start of day  -  sync your branch with the latest dev
git checkout dev
git pull origin dev
git checkout feature/your-branch-name
git rebase dev

# Make your changes, then...
git add src/your_file.py tests/your_test.py
git commit -m "feat: describe what you did"
git push origin feature/your-branch-name
```

### Opening a Pull Request
1. Push your feature branch to GitHub
2. Open a PR from `feature/your-branch-name` → `dev` on GitHub
3. Assign one other team member as reviewer
4. Do not merge your own PR  -  wait for approval
5. Once approved, the reviewer or you can merge

### Commit Message Format
Use a short prefix to make the git history readable:
```
feat:  new feature or behavior
fix:   bug fix
test:  adding or fixing tests
docs:  documentation changes
chore: dependency updates, cleanup
bench: benchmarking or analysis changes
```

Examples:
```
feat: add minimum contour area filter to background subtractor
fix: FFmpeg process not terminated when pipeline stops
test: add integration test for ROI encoder output
docs: update DEV.md with enhancement setup steps
bench: milestone1 compression ratio notebook
```

### Branch Names
- Feature work: `feature/short-description`
- Bug fixes: `fix/short-description`
- Documentation: `docs/short-description`

---

## 10. Common Problems and Fixes

### `ModuleNotFoundError: No module named 'cv2'`
OpenCV is not installed or the venv is not active.
```bash
source venv/bin/activate
pip install opencv-python
```

### `FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'`
FFmpeg is not on your PATH.
```bash
# Ubuntu
sudo apt install ffmpeg -y
# macOS
brew install ffmpeg
# Check it works
ffmpeg -version
```

### `No such file or directory: 'data/samples/...'`
You need to create the directory and put a test clip in it.
```bash
mkdir -p data/samples
# Then copy a .mp4 file into data/samples/
```

### `sqlite3.OperationalError: no such table: segments`
The database hasn't been initialized yet. The pipeline creates the database on first run. Make sure the pipeline has been run at least once before querying.

### Foreground mask is all white (everything detected as foreground)
The background model needs time to learn the background. The first 30-100 frames are the "learning phase"  -  the mask will be noisy. This is normal. The mask quality improves after the model stabilizes. You can also increase the `history` parameter in `BackgroundSubtractor.__init__`.

### Foreground mask detects nothing (all black)
The `varThreshold` is too high (too strict). Lower it:
```python
subtractor = BackgroundSubtractor(method='MOG2', var_threshold=10)
```

### `PermissionError` when writing to `outputs/`
Create the output directory manually:
```bash
mkdir -p outputs
```

### Tests fail with `ImportError`
Make sure you're running pytest from the project root directory, not from inside `src/` or `tests/`:
```bash
cd capstone-compression   # project root
pytest tests/ -v
```

---

## 11. Adding New Features

### Adding a New Background Subtraction Method
1. Open `src/background_subtraction/background_subtraction.py`
2. Add your method name to the `SUPPORTED_METHODS` list
3. In `__init__`, add an `elif` branch that instantiates the new OpenCV object
4. Add a test case in `tests/test_background_subtraction.py`

### Adding a New Metric
1. Open `src/utils/metrics.py`
2. Add a new function following the existing pattern
3. Add a test in `tests/` to verify the function returns sane values
4. Use the metric in the relevant benchmark notebook

### Adding the Enhancement Module (Milestone 2)
1. Create `src/enhancement/enhancer.py`
2. Implement the `Enhancer` class with `upscale_frame(frame, scale)` and `upscale_roi(frame, bbox)` methods
3. Download model weights and place them in `models/` (do not commit to git)
4. Integrate the enhancer into `src/pipeline/pipeline.py` as an optional `--enhance` flag
5. Write tests in `tests/test_enhancer.py`
6. Document setup steps (model download, etc.) in this DEV.md file

---

## 12. Enhancement Module Setup (Milestone 2)

The enhancement module applies CPU-compatible super-resolution to sharpen foreground ROI regions before they are encoded. This uses [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN).

### Step 1 — Install the enhancement dependencies

These are optional extras — only needed if you plan to use the `--enhance` flag.

```bash
# uv (recommended)
uv sync --extra enhance

# pip fallback
pip install basicsr realesrgan
```

On macOS you may need Xcode command-line tools first:
```bash
xcode-select --install
```

### Step 2 — Download model weights

The model weights are **not** committed to git (they are ~67 MB and covered by the `*.pth` gitignore rule). Download them manually:

```bash
mkdir -p models
curl -L -o models/RealESRGAN_x4plus.pth \
  https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth
```

Or download from the browser: go to the [Real-ESRGAN releases page](https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.1.0) and save `RealESRGAN_x4plus.pth` into `models/`.

After downloading:
```
models/
└── RealESRGAN_x4plus.pth   ← 67 MB, gitignored
```

### Step 3 — Verify the module loads

```python
from src.enhancement.enhancer import Enhancer
e = Enhancer()
print(e.backend)   # should print "realesrgan" if weights + packages are present
```

If it prints `"bicubic"`, either the packages are not installed or the weights file is missing. The pipeline will still run — just without AI sharpening.

### Step 4 — Run the pipeline with enhancement

```bash
python src/pipeline/pipeline.py \
  --input data/samples/test_clip.mp4 \
  --camera-id cam_test \
  --output outputs/ \
  --enhance
```

**Enhancement CLI flags:**

| Flag | Default | Description |
|---|---|---|
| `--enhance` | off | Enable ROI super-resolution sharpening |
| `--enhance-scale` | `4` | Intermediate upscale factor (must match model, default 4) |

**Performance note:** Each foreground ROI is upscaled then downscaled back to original resolution on every frame. On a modern laptop CPU this adds ~50–200ms per frame depending on ROI size. Do **not** use `--enhance` on live camera feeds unless your hardware can sustain the load. It is intended for offline processing of stored footage.

### How it works

`upscale_roi(frame, bbox)` extracts the bounding box region, runs it through Real-ESRGAN at 4× (or bicubic fallback), then downsamples the result back to the original bbox dimensions and composites it into the frame. The frame size stays the same — this is a sharpening pass, not a resize. The sharpened frame is then handed to the segment writer and encoded at the foreground CRF setting.

### Troubleshooting

**`ImportError: No module named 'basicsr'`**
Run `uv sync --extra enhance` (or `pip install basicsr realesrgan` in an activated venv).

**`Model weights not found`**
The `.pth` file is missing from `models/`. Re-run the curl command in Step 2.

**`CUDA not available` warning**
Normal — the Enhancer always runs in CPU mode (`half=False`). This warning comes from PyTorch and can be ignored.

**Enhancement is slow**
Use `--enhance-scale 2` to run a lighter intermediate pass, or skip `--enhance` entirely and process footage offline after offload.

---

*Last updated: April 2026 by Victor Teixeira (Milestone 2 — Enhancement Module). If you find anything in this guide that is wrong or out of date, update it and open a PR.*

---

## 13. Getting Test Videos

The test videos are not committed to the repo — they are too large for GitHub and are gitignored. Every team member needs to build their own local copy. This section explains exactly how.

There are two datasets used across the project. **CDnet 2014** is used for background subtraction testing (pipeline modes, algorithm comparison, stress tests). **VIRAT** is used for person/vehicle detection testing. Build both.

---

### CDnet 2014 — Background subtraction benchmark

CDnet distributes footage as sequences of PNG image frames, not as video files. You download the frames and then use FFmpeg to stitch them into `.mp4` files. This is how the project's `data/samples/cdnet_mp4/` folder was originally built.

**Step 1 — Download the image frames**

Go to [changedetection.net](http://www.changedetection.net) and download the dataset. The site gives you a zip per category. Download whichever categories you need — baseline and nightVideos are the most useful for this project.

Extract everything to `data/dataset/`. After extraction the structure looks like this:

```
data/dataset/
├── baseline/
│   ├── highway/
│   │   └── input/
│   │       ├── in000001.png
│   │       ├── in000002.png
│   │       └── ...
│   ├── office/
│   ├── pedestrians/
│   └── PETS2006/
├── nightVideos/
│   ├── bridgeEntry/
│   └── ...
└── (other categories)
```

`data/dataset/` is gitignored. The raw frames never get committed.

**Step 2 — Convert a clip to MP4 with FFmpeg**

For each clip, run this command. Replace `{category}` and `{clipname}` with the folder names from the dataset:

```bash
ffmpeg -framerate 25 \
  -i data/dataset/{category}/{clipname}/input/in%06d.png \
  -c:v libx264 \
  -pix_fmt yuv420p \
  -crf 18 \
  data/samples/cdnet_mp4/{category}/{clipname}.mp4
```

Example — converting the highway clip from the baseline category:

```bash
ffmpeg -framerate 25 \
  -i data/dataset/baseline/highway/input/in%06d.png \
  -c:v libx264 \
  -pix_fmt yuv420p \
  -crf 18 \
  data/samples/cdnet_mp4/baseline/baseline_highway.mp4
```

The output file goes into the matching category subfolder under `data/samples/cdnet_mp4/`. The naming convention is `{category}_{clipname}.mp4`.

**Step 3 — Make sure the output folder exists first**

```bash
mkdir -p data/samples/cdnet_mp4/baseline
mkdir -p data/samples/cdnet_mp4/nightVideos
# (repeat for each category you downloaded)
```

**To convert an entire category at once**, run this loop in Git Bash or a terminal:

```bash
CATEGORY=baseline   # change this to the category you want

for clip_dir in data/dataset/$CATEGORY/*/; do
    clip=$(basename "$clip_dir")
    mkdir -p "data/samples/cdnet_mp4/$CATEGORY"
    ffmpeg -framerate 25 \
      -i "$clip_dir/input/in%06d.png" \
      -c:v libx264 \
      -pix_fmt yuv420p \
      -crf 18 \
      "data/samples/cdnet_mp4/$CATEGORY/${CATEGORY}_${clip}.mp4"
done
```

**Expected output folder structure when done:**

```
data/samples/cdnet_mp4/
├── baseline/
│   ├── baseline_highway.mp4
│   ├── baseline_office.mp4
│   ├── baseline_pedestrians.mp4
│   └── baseline_PETS2006.mp4
├── nightVideos/
│   ├── nightVideos_bridgeEntry.mp4
│   └── ...
└── (other categories)
```

See `data/samples/cdnet_mp4/README.md` for which clip to use for each type of test.

---

### VIRAT — Person and vehicle activity dataset

Riley uses VIRAT for person/vehicle detection testing. It ships as actual video files, so there is no conversion step.

**Step 1 — Download the videos**

Go to [viratdata.org](https://viratdata.org) and download the VIRAT Video Dataset. The site requires a short registration form. Download the ground camera videos (not aerial) — those are the ones that match surveillance camera scenarios.

Save the `.mp4` files to `data/samples/virat/`. That folder is gitignored.

```
data/samples/virat/
├── VIRAT_S_000000.mp4
├── VIRAT_S_000001.mp4
└── ...
```

**Step 2 — (Optional) Download annotations**

If you need the activity annotations (person bounding boxes, vehicle labels), get them from the [Kitware DIVA annotations repo](https://github.com/kitware/viratannotations). Clone it to `data/viratannotations-master/` — that folder is also gitignored.

```bash
git clone https://github.com/kitware/viratannotations.git data/viratannotations-master
```

Annotations are in KPF format (YAML). You do not need them to run the pipeline — only if you are doing annotation-based evaluation.

---

### Quick reference — which dataset for which tests

| Test file | Dataset to use |
|---|---|
| `tests/test_pipeline_stress.py` | CDnet — `baseline/baseline_pedestrians.mp4` is a good default |
| `tests/test_background_subtraction.py` | CDnet — any baseline or nightVideos clip |
| `tests/test_roi_encoder.py` | CDnet — any short clip |
| `tests/test_database.py` | No video needed (uses synthetic data) |
| `tests/test_enhancer.py` | No video needed (uses synthetic frames) |
| Riley's detection tests | VIRAT ground camera clips |

If a test is hardcoded to a specific path that does not exist on your machine, check the test file for a `CDNET` or `VIRAT` path variable at the top and update it to match your local setup — or open a PR to make it use the standard paths from `data/samples/cdnet_mp4/` and `data/samples/virat/`.

---

*Section 13 added April 2026 — Kheiven D'Haiti.*
