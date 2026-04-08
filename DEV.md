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

### Step 1  -  Clone the Repository
```bash
git clone https://github.com/Blood-Dawn/capstone-compression.git
cd capstone-compression
```

### Step 2  -  Create a Python Virtual Environment
This keeps project dependencies isolated from your system Python. Always do this.

**Linux / macOS:**
```bash
python3 -m venv venv
```

**Windows (PowerShell or Git Bash):**
```bash
python -m venv venv
```

Note: On Windows, `python3` is not recognized. Use `python` instead.

### Step 3  -  Activate the Virtual Environment

**Linux / macOS:**
```bash
source venv/bin/activate
```

**Windows Git Bash (MINGW64):**
```bash
source venv/Scripts/activate
```

**Windows PowerShell:**
```powershell
.\venv\Scripts\Activate.ps1
```

Your terminal prompt should now show `(venv)` at the beginning. If it does not, the venv is not active.

### Step 4  -  Install Python Dependencies
```bash
pip install -r requirements.txt
```

This will install OpenCV, NumPy, FFmpeg-Python, scikit-image, pytest, and all other required packages. It may take a few minutes.

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
# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_background_subtraction.py -v

# Run with coverage report
pytest tests/ -v --cov=src --cov-report=term-missing
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

## Enhancement Module Setup

The `Enhancer` class (`src/enhancement/enhancer.py`) supports two backends. Choose the one that fits your use case.

### Backend 1 — OpenCV dnn_superres (Recommended for CPU batch processing)

Fast, lightweight, and easy to set up. Best for bulk post-offload processing.

**Step 1 — Install opencv-contrib-python**
```bash
pip install opencv-contrib-python
```
If you already have `opencv-python` installed, uninstall it first to avoid conflicts:
```bash
pip uninstall opencv-python
pip install opencv-contrib-python
```

**Step 2 — Download model weights**

Create the `models/` directory in the project root (already gitignored):
```bash
mkdir -p models
```

Download your chosen model. ESPCN x4 is the fastest on CPU:
```bash
# ESPCN x2 and x4 (fastest — ~1-5 ms/frame)
curl -L "https://github.com/opencv/opencv_contrib/raw/master/modules/dnn_superres/models/ESPCN_x2.pb" -o models/ESPCN_x2.pb
curl -L "https://github.com/opencv/opencv_contrib/raw/master/modules/dnn_superres/models/ESPCN_x4.pb" -o models/ESPCN_x4.pb

# FSRCNN x2 and x4 (slightly better quality, ~5-15 ms/frame)
curl -L "https://github.com/opencv/opencv_contrib/raw/master/modules/dnn_superres/models/FSRCNN_x2.pb" -o models/FSRCNN_x2.pb
curl -L "https://github.com/opencv/opencv_contrib/raw/master/modules/dnn_superres/models/FSRCNN_x4.pb" -o models/FSRCNN_x4.pb
```

**Step 3 — Verify**
```python
from src.enhancement.enhancer import Enhancer
e = Enhancer(scale=4, model="espcn")
print(e.is_available())  # True if model file found and cv2.dnn_superres present
print(repr(e))
```

**Expected output:**
```
True
Enhancer(model='espcn', scale=4, device='cpu', backend='dnnsuperres', available=True)
```

---

### Backend 2 — Real-ESRGAN (Best quality, slower — for high-value forensic targets)

Produces the best visual quality. Use for specific frames of interest (faces, license plates).
CPU inference only — no CUDA required. Accepts `--fp32` mode automatically.

**Hallucination warning:** Real-ESRGAN (GAN-trained) may fabricate plausible details that are not in the original footage. For forensic applications, use `RealESRNet_x4plus` instead — it uses MSE loss and blurs rather than hallucinating.

**Step 1 — Install Real-ESRGAN**
```bash
pip install realesrgan basicsr facexlib gfpgan
```

**Step 2 — Download model weights**
```bash
mkdir -p models

# General purpose (best quality, GAN-trained — slight hallucination risk)
curl -L "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth" \
     -o models/RealESRGAN_x4plus.pth

# MSE-trained variant (fewer hallucinations — preferred for forensic use)
curl -L "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRNet_x4plus.pth" \
     -o models/RealESRNet_x4plus.pth

# Lighter general model (faster than x4plus, good quality)
curl -L "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth" \
     -o models/realesr-general-x4v3.pth
```

**Step 3 — Verify**
```python
from src.enhancement.enhancer import Enhancer
e = Enhancer(scale=4, model="realesrgan")
print(e.is_available())  # True if .pth file found and realesrgan package installed
```

**CPU performance reference (approximate, varies by hardware):**

| Model | 480p frame | 1080p frame |
|---|---|---|
| ESPCN x4 | ~3 ms | ~15 ms |
| FSRCNN x4 | ~10 ms | ~45 ms |
| Real-ESRGAN x4 (CPU fp32) | ~300 ms | ~1200 ms |
| RealESRNet x4 (CPU fp32) | ~280 ms | ~1100 ms |

For bulk post-offload processing of an hour of footage: ESPCN is practical; Real-ESRGAN is only practical for targeted, high-value clips.

---

### Running enhancement in the pipeline

Pass `--enhance` to the pipeline to enable frame-level enhancement before encoding:

```bash
python src/pipeline/pipeline.py \
  --input data/samples/test_clip.mp4 \
  --camera-id cam_01 \
  --output outputs/ \
  --enhance \
  --enhance-model espcn \
  --enhance-scale 4
```

If the model is not available, `--enhance` logs a warning and the pipeline continues without enhancement. It never hard-fails on a missing model.

---

## Encryption Setup

The pipeline supports AES-256-CBC encryption of all output video segments via `--encrypt`.

**Step 1 — Install the cryptography library**
```bash
pip install cryptography
```

This is a pure-Python FIPS 140-2 validated implementation. No system dependencies.

**Step 2 — Run the pipeline with encryption**

Using a password (PBKDF2-HMAC-SHA256 key derivation, 600,000 iterations):
```bash
python src/pipeline/pipeline.py \
  --input data/samples/test_clip.mp4 \
  --camera-id cam_01 \
  --output outputs/ \
  --encrypt \
  --password "your-secure-passphrase"
```

Using a raw key file (32 bytes = 256-bit key):
```bash
# Generate a key file once and store it securely
python -c "import os; open('secret.key', 'wb').write(os.urandom(32))"

python src/pipeline/pipeline.py \
  --input data/samples/test_clip.mp4 \
  --camera-id cam_01 \
  --output outputs/ \
  --encrypt \
  --key-file secret.key
```

**Step 3 — Decrypt a segment**
```python
from src.utils.encryption import decrypt_file
decrypt_file("outputs/cam_01_20260406_120000.mp4.enc", password="your-secure-passphrase")
# Writes: outputs/cam_01_20260406_120000.mp4
```

**Security notes:**
- A unique random IV is generated per segment. Two encrypted files with the same password are not identical.
- The IV is stored in the first 16 bytes of the `.enc` file. The salt (for password-based derivation) is in bytes 16–32.
- Never commit key files or passwords to git. Add `*.key` to `.gitignore`.
- The original `.mp4` is deleted after encryption; only the `.mp4.enc` remains.

---

*Last updated: April 2026 — Bloodawn (KheivenD). If you find anything wrong or out of date, update it and open a PR.*
