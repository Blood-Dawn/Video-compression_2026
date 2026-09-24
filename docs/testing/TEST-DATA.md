# Getting test videos

The test videos are not committed to the repo - they are too large for GitHub and are gitignored. Every team member needs to build their own local copy. This section explains exactly how.

There are two datasets used across the project. **CDnet 2014** is used for background subtraction testing (pipeline modes, algorithm comparison, stress tests). **VIRAT** is used for person/vehicle detection testing. Build both.

---

## CDnet 2014 - Background subtraction benchmark

CDnet distributes footage as sequences of PNG image frames, not as video files. You download the frames and then use FFmpeg to stitch them into `.mp4` files. This is how the project's `data/samples/cdnet_mp4/` folder was originally built.

**Step 1 - Download the image frames**

Go to [changedetection.net](http://www.changedetection.net) and download the dataset. The site gives you a zip per category. Download whichever categories you need - baseline and nightVideos are the most useful for this project.

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

**Step 2 - Convert a clip to MP4 with FFmpeg**

For each clip, run this command. Replace `{category}` and `{clipname}` with the folder names from the dataset:

```bash
ffmpeg -framerate 25 \
  -i data/dataset/{category}/{clipname}/input/in%06d.png \
  -c:v libx264 \
  -pix_fmt yuv420p \
  -crf 18 \
  data/samples/cdnet_mp4/{category}/{clipname}.mp4
```

Example - converting the highway clip from the baseline category:

```bash
ffmpeg -framerate 25 \
  -i data/dataset/baseline/highway/input/in%06d.png \
  -c:v libx264 \
  -pix_fmt yuv420p \
  -crf 18 \
  data/samples/cdnet_mp4/baseline/baseline_highway.mp4
```

The output file goes into the matching category subfolder under `data/samples/cdnet_mp4/`. The naming convention is `{category}_{clipname}.mp4`.

**Step 3 - Make sure the output folder exists first**

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

## VIRAT - Person and vehicle activity dataset

Riley uses VIRAT for person/vehicle detection testing. It ships as actual video files, so there is no conversion step.

**Step 1 - Download the videos**

Go to [viratdata.org](https://viratdata.org) and download the VIRAT Video Dataset. The site requires a short registration form. Download the ground camera videos (not aerial) - those are the ones that match surveillance camera scenarios.

Save the `.mp4` files to `data/samples/virat/`. That folder is gitignored.

```
data/samples/virat/
├── VIRAT_S_000000.mp4
├── VIRAT_S_000001.mp4
└── ...
```

**Step 2 - (Optional) Download annotations**

If you need the activity annotations (person bounding boxes, vehicle labels), get them from the [Kitware DIVA annotations repo](https://github.com/kitware/viratannotations). Clone it to `data/viratannotations-master/` - that folder is also gitignored.

```bash
git clone https://github.com/kitware/viratannotations.git data/viratannotations-master
```

Annotations are in KPF format (YAML). You do not need them to run the pipeline - only if you are doing annotation-based evaluation.

---

## Quick reference - which dataset for which tests

| Test file | Dataset to use |
|---|---|
| `tests/test_pipeline_stress.py` | CDnet - `baseline/baseline_pedestrians.mp4` is a good default |
| `tests/test_background_subtraction.py` | CDnet - any baseline or nightVideos clip |
| `tests/test_roi_encoder.py` | CDnet - any short clip |
| `tests/test_database.py` | No video needed (uses synthetic data) |
| `tests/test_enhancer.py` | No video needed (uses synthetic frames) |
| Riley's detection tests | VIRAT ground camera clips |

If a test is hardcoded to a specific path that does not exist on your machine, check the test file for a `CDNET` or `VIRAT` path variable at the top and update it to match your local setup - or open a PR to make it use the standard paths from `data/samples/cdnet_mp4/` and `data/samples/virat/`.

---

*Written April 2026 by Kheiven D'Haiti as DEV.md section 13; moved here 2026-09-24.*
