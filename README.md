# Selective Video Compression for Surveillance Cameras
**EGN 4950C Capstone | Florida Atlantic University | Spring 2026**
Sponsored by the Defense Innovation Unit (DIU) / NIWC Pacific

---

## Download

**[⬇ Download the latest Windows installer](https://github.com/Blood-Dawn/Video-compression_2026/releases/latest)** - grab `SVCS-Setup-*.exe` from the Releases page, then verify it against the published `SHA256SUMS.txt` (the [download page](docs/site/index.html) has the steps).

Free and open source (AGPL-3.0). No account, no cloud, no telemetry by default. Runs offline on a regular PC - no GPU required. Also available as a [Docker image](docs/deployment_packaging.md) or from source (below).

---

## What this is

Security cameras waste a lot of storage. A camera pointed at a parking lot records 24 hours of footage a day, but 23 of those hours are just an empty parking lot - nothing moving, nothing happening. Every pixel of that dead footage still gets saved.

This project fixes that. Instead of recording everything equally, the pipeline watches the video in real time and figures out what's actually moving. The moving parts - a person walking, a car pulling in - get saved at high quality. The static background gets compressed aggressively, or in some modes, skipped entirely. The result is the same useful footage at a fraction of the file size.

**We tested this on the CDnet 2014 benchmark dataset (52 real surveillance clips).** On typical footage, we hit 6x smaller files compared to standard video compression. On scenes with little activity, that number climbs to 16x.

The whole thing runs on a regular computer. No GPU required.

---

## What you can do with it

There are four recording modes. You pick whichever fits how your cameras are used:

**Mode 0 - Keep everything, compress smarter.** The camera records continuously. Active frames (something moving) get saved at near-perfect quality. Quiet frames get compressed hard. You never have a gap in coverage, but quiet periods take up almost no space.

**Mode 1 - Only save what matters.** The camera only writes a clip when something is actually moving. Way smaller files. The trade-off: if you need to prove nothing happened at 2am, you can't - there's no recording for that window.

**Mode 2 - Motion + a reference frame.** Saves the moments something moved along with a single clean background frame for context. Even smaller than Mode 1.

**Mode 3 - Just the moving object.** Strips everything except the foreground object itself. The smallest possible output. Designed for pipelines that do facial recognition or license plate reading downstream.

On top of compression, the system also:
- Tags every saved clip with what was detected (person, vehicle) and stores it in a searchable database. If something happened at a specific camera at 3am, you query it - you don't scrub through footage.
- Encrypts every clip before it touches disk. Nobody reads it without the key.
- Can sharpen low-quality footage after the fact using a neural network upscaler. Useful when a clip from an old camera comes in blurry and you need to read a face or a plate.
- Streams live status to a browser-based dashboard. No terminal needed to operate it.

---

## How to run it

You'll need Python 3.10+ and FFmpeg installed on your machine.

### Quick setup with uv (recommended)

[uv](https://astral.sh/uv) handles the virtual environment and dependency locking automatically.

```bash
# 1. Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh   # Linux / macOS
# Windows: winget install astral-sh.uv

# 2. Clone the repo
git clone https://github.com/Blood-Dawn/capstone-compression.git
cd capstone-compression

# 3. Install dependencies and create virtualenv in one step
uv sync

# 4. Install FFmpeg (still required as a system binary)
sudo apt install ffmpeg -y    # Ubuntu/Debian/WSL2
brew install ffmpeg            # macOS

# 5. Run it on a clip
uv run python src/pipeline/pipeline.py \
  --input data/samples/your_clip.mp4 \
  --camera-id cam_01 \
  --output outputs/ \
  --mode mode0
```

To use the super-resolution enhancer (`--enhance` flag), install the optional extras:

```bash
uv sync --extra enhance
```

To open the dashboard:

```bash
uv run python run_gui.py
# Then open http://localhost:5000 in your browser
```

### Alternative setup with pip

```bash
git clone https://github.com/Blood-Dawn/capstone-compression.git
cd capstone-compression
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## Standalone executable

The primary deployment target is a server-hosted web app - one machine runs Flask, everyone connects from a browser. For field use without a network (laptop directly connected to a camera), we're evaluating an Electron shell that wraps Flask as a subprocess.

See `docs/deployment_packaging.md` for the full analysis of Docker, Electron, PyInstaller, and tarball options with DoD compliance notes.

---

## The team

| Name | GitHub | What they built |
|---|---|---|
| Kheiven D'Haiti | [@Blood-Dawn](https://github.com/Blood-Dawn) | Pipeline orchestration, background subtraction tuning, dashboard, encryption, night-mode CLAHE, project lead |
| Jorge Sanchez | [@sanchez-jorge](https://github.com/sanchez-jorge) | Video encoding (ROI encoder / FFmpeg integration), algorithm benchmarking, stress testing, storage extrapolation |
| Ashleyn Montano | [@ashleyn07](https://github.com/ashleyn07) | SQLite metadata database - schema, pipeline integration, query system |
| Riley Roberts | [@sRileyRoberts](https://github.com/sRileyRoberts) | Motion detection pipeline (Modes 2 and 3), object isolation |
| Victor De Souza Teixeira | [@victort29](https://github.com/victort29) | Image enhancement module - Real-ESRGAN upscaler, CPU benchmark |

---

## Credits and open resources used

**CDnet 2014 - Change Detection Benchmark**
52 real surveillance clips across 10 scene categories (normal lighting, night, bad weather, shadow, low frame rate, and more). This is the standard academic benchmark for background subtraction algorithms, and it's what we used to tune the detection and measure compression. Comes with pixel-level ground truth masks so you can measure accuracy, not just eyeball it.

> Y. Wang, P.-M. Jodoin, F. Porikli, J. Konrad, Y. Benezeth, and P. Ishwar, "CDnet 2014: An Expanded Change Detection Benchmark Dataset," IEEE CVPR Workshops, 2014.
> [changedetection.net](http://www.changedetection.net)

> N. Goyette, P.-M. Jodoin, F. Porikli, J. Konrad, and P. Ishwar, "changedetection.net: A New Change Detection Benchmark Dataset," IEEE CVPR Workshops, 2012.

**VIRAT Video Dataset**
Outdoor surveillance footage of people and vehicles in real-world scenarios. Used for testing detection on more varied activity. Annotations provided by the IARPA DIVA program via Kitware.

> S. Oh et al., "A Large-scale Benchmark Dataset for Event Recognition in Surveillance Video," IEEE CVPR, 2011.
> [viratdata.org](https://viratdata.org)

**Libraries and tools**

| What | License |
|---|---|
| OpenCV (MOG2 / KNN background subtraction) | Apache 2.0 |
| FFmpeg + libx264 | LGPL / GPL |
| Real-ESRGAN (super-resolution) | BSD 3-Clause |
| SQLite | Public Domain |
| Python 3 | PSF |
| pytest | MIT |

## License

SVCS is **free and open source under the GNU AGPL-3.0** (see `LICENSE`).
There is no paid or commercial edition. You can use, modify, self-host, and
redistribute it under the AGPL's terms. (`CLA.md` and `LICENSE-COMMERCIAL.md`
are dormant drafts retained only for a possible future commercial fork - they
are not in force; see their headers.)

---

*EGN 4950C Capstone | Florida Atlantic University | Spring 2026 | Final deadline: May 6, 2026*
