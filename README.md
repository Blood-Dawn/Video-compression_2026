# Selective Video Compression for Surveillance Cameras
**EGN 4950C Senior Design Capstone | Florida Atlantic University | Group 16**
Sponsored by the Defense Innovation Unit (DIU) / NIWC Pacific

---

## Download the desktop app

**Install from the terminal** (Windows PowerShell):

```powershell
irm https://raw.githubusercontent.com/Blood-Dawn/Video-compression_2026/app/installer/Install-SVCS.ps1 | iex
```

This opens a small menu where you pick what to install: the core app, an
optional license-plate reader, a local test camera server, and some sample
clips to try it on. Full options are in [docs/INSTALL.md](docs/INSTALL.md).

**Or [download the latest Windows installer](https://github.com/Blood-Dawn/Video-compression_2026/releases/latest) directly** -
grab `SVCS-Setup-*.exe` from the Releases page. The
[download page](docs/site/index.html) walks through checking it against the
published checksum file, which is good practice for anything you download and
run.

Free and open source (AGPL-3.0). No account, no cloud, and no telemetry unless
you turn it on yourself. Runs on a normal PC, no GPU needed. Also available as
a [Docker image](docs/BUILD-AND-RELEASE.md), or you can build it from source
(see below).

---

## What this is

Security cameras waste a lot of storage. A camera watching a parking lot
records 24 hours a day, but 23 of those hours are usually just an empty lot:
nothing moving, nothing happening. Every pixel of that dead footage still gets
saved to disk.

This project fixes that. Instead of recording everything at the same quality,
it watches the video as it comes in and figures out what is actually moving.
The moving parts, a person walking, a car pulling in, get saved at high
quality. The static background gets compressed hard, or in some modes,
skipped entirely. The result is the same useful footage at a fraction of the
file size.

We tested this against the CDnet 2014 benchmark, 52 real surveillance clips
used across the research field for exactly this kind of comparison. On
typical footage we saw files 6 times smaller than standard video compression.
On quiet scenes, that climbs to 16 times smaller.

It all runs on a regular computer. No GPU required.

---

## What you can do with it

There are four recording modes. Pick whichever fits how your cameras are
used:

**Mode 0, keep everything, compress smarter.** The camera records
continuously. Frames with movement stay near full quality; quiet frames get
compressed hard. You never lose coverage, but the quiet stretches take up
almost no space.

**Mode 1, only save what matters.** The camera only writes a clip when
something actually moves. Much smaller files, but if you ever need to prove
nothing happened at 2am, there is no recording to show for it.

**Mode 2, motion plus a reference frame.** Saves the moments something moved,
along with one clean background frame for context. Smaller than Mode 1.

**Mode 3, just the moving object.** Strips out everything except the object
itself. The smallest possible output, meant for a pipeline that runs facial
recognition or license-plate reading afterward.

On top of compression, SVCS also:

- Tags every saved clip with what it detected, a person or a vehicle, and
  stores that in a searchable database. If something happened at a specific
  camera at 3am, you can look it up instead of scrubbing through hours of
  footage by hand.
- Encrypts every clip before it ever touches disk.
- Can sharpen low-quality footage after the fact with a neural-network
  upscaler, useful when an old camera's clip is too blurry to make out a face
  or a plate.
- Streams live status to a browser dashboard, so day-to-day use needs no
  terminal at all.

---

## Beta: the mobile companion app

SVCS also has an Android app, currently in beta. Think of it as a phone-based
remote control and viewer for a desktop SVCS install you already have running,
not a separate product on its own: it does not record or compress anything
by itself, and it needs the desktop app (above) running somewhere on your
network to connect to.

**What it can do today:** watch a live camera feed, browse the library and
play clips back, trigger a compression job from your phone, upload a video
from your phone's own gallery, draw a zone on a camera and get an alert when
something crosses a line or lingers too long in it, and receive a push
notification even while the app itself is closed.

**What it is deliberately not:** it does not ask for a cloud account, and it
does not send your footage or alerts through any third-party company. Alerts
route through a notification server you run yourself.

**The honest risks, since this really is a beta:** two known issues are the
top priority for the next round of work. Reopening the app after closing it
does not reliably keep your last connection, so it can reconnect using an
old server address or an old login. And an upload from your phone does not
survive the app being closed mid-transfer, so a large upload needs the app
left open until it finishes. The app also has almost no automated test
coverage of its own yet, so most changes are still checked by hand on a
physical phone rather than caught by a test suite, and it has not yet been
through an outside security test (one is planned for the coming weeks; see
`docs/project-records/PLANNER-FALL-2026.md`).

**How to try it:** there is no public download yet, no Play Store listing and
no signed installer. If you are comfortable building an Android app from
source, the full build steps live in
[mobile/android/README.md](https://github.com/Blood-Dawn/Video-compression_2026/blob/mobile/mobile/android/README.md)
on the `mobile` branch. Everyone else should treat the desktop app above as
the finished, ready-to-use way to run SVCS today, and the phone app as a
preview of where the project is headed next.

---

## Running it from source

You'll need Python 3.10+ and FFmpeg installed on your machine.

### Quick setup with uv (recommended)

[uv](https://astral.sh/uv) handles the virtual environment and dependency
locking automatically.

```bash
# 1. Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh   # Linux / macOS
# Windows: winget install astral-sh.uv

# 2. Clone the repo
git clone https://github.com/Blood-Dawn/Video-compression_2026.git
cd Video-compression_2026

# 3. Install dependencies and create the virtual environment in one step
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

To use the optional super-resolution enhancer (`--enhance` flag), install the
extra dependencies it needs:

```bash
uv sync --extra enhance
```

To open the dashboard instead of running from the command line:

```bash
uv run python run_gui.py
# Then open http://localhost:5000 in your browser
```

### Alternative setup with pip

```bash
git clone https://github.com/Blood-Dawn/Video-compression_2026.git
cd Video-compression_2026
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## How it's built and shipped

SVCS ships two ways today. A Windows installer freezes the whole app,
including FFmpeg, into one `.exe` so a new machine needs nothing preinstalled;
that is the download at the top of this page. A Docker image is the other
supported path, for anyone who would rather run it on a server or a NAS.

An Electron desktop wrapper and a plain PyInstaller executable were both
looked at early on and set aside, mainly over first-run antivirus friction and
brittle build times; the installer and Docker paths turned out to cover the
real use cases better. See `docs/BUILD-AND-RELEASE.md` for the full build
process, the FFmpeg license reasoning, and the release checklist, and
`docs/SYSTEM-ARCHITECTURE.md` for how the pieces of the system fit together.

---

## The team

| Name | GitHub | What they built |
|---|---|---|
| Kheiven D'Haiti | [@Blood-Dawn](https://github.com/Blood-Dawn) | Pipeline orchestration, background subtraction tuning, dashboard, encryption, night-mode CLAHE, project lead |
| Jorge Sanchez | [@sanchez-jorge](https://github.com/sanchez-jorge) | Video encoding (ROI encoder / FFmpeg integration), algorithm benchmarking, stress testing, storage extrapolation |
| Ashleyn Montano | [@ashleyn07](https://github.com/ashleyn07) | SQLite metadata database, schema, pipeline integration, query system |
| Riley Roberts | [@sRileyRoberts](https://github.com/sRileyRoberts) | Motion detection pipeline (Modes 2 and 3), object isolation |
| Victor De Souza Teixeira | [@victort29](https://github.com/victort29) | Image enhancement module, Real-ESRGAN upscaler, CPU benchmark, security testing |

---

## Credits and open resources used

**CDnet 2014, Change Detection Benchmark**
52 real surveillance clips across 10 scene categories (normal lighting,
night, bad weather, shadow, low frame rate, and more). This is the standard
academic benchmark for background subtraction algorithms, and it is what we
used to tune detection and measure compression. It comes with pixel-level
ground truth masks, so accuracy can be measured directly rather than eyeballed.

> Y. Wang, P.-M. Jodoin, F. Porikli, J. Konrad, Y. Benezeth, and P. Ishwar, "CDnet 2014: An Expanded Change Detection Benchmark Dataset," IEEE CVPR Workshops, 2014.
> [changedetection.net](http://www.changedetection.net)

> N. Goyette, P.-M. Jodoin, F. Porikli, J. Konrad, and P. Ishwar, "changedetection.net: A New Change Detection Benchmark Dataset," IEEE CVPR Workshops, 2012.

**VIRAT Video Dataset**
Outdoor surveillance footage of people and vehicles in real-world scenarios,
used to test detection on more varied activity. Annotations provided by the
IARPA DIVA program via Kitware.

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
There is no paid or commercial edition, and no plan to add one to this
repository; a commercial variant, if one is ever built, would live in its
own separate fork. You can use, modify, self-host, and redistribute SVCS
under the AGPL's terms.

---

*EGN 4950C Senior Design Capstone | Florida Atlantic University | Group 16 | Fall 2026 semester runs through December 6, 2026*
