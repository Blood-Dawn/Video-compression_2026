# Design Note: Night Video Quality and Light Glare
**Status:** Observed Issue - Needs Investigation
**Date:** 2026-03-24
**Reported by:** Bloodawn (KheivenD)
**Assigned to:** Riley Roberts (algorithm tuning), Bloodawn (KheivenD) (pipeline integration)

---

## Observation

During the first demo run on `data/dataset/nightVideos/bridgeEntry/`, the output comparison
images showed that the foreground masks at night are noisy and unclear. The bright point
light sources on the bridge (streetlamps, vehicle headlights) create glare halos that
bleed into surrounding pixels. Both MOG2 and KNN are picking up this light variation as
foreground even when no objects are actually moving through the scene.

Additionally, MOG2 and KNN produced opposite results at night compared to daytime:

| Scene | MOG2 avg FG | KNN avg FG |
|---|---|---|
| highway (day) | 8.76% | 7.10% |
| bridgeEntry (night) | 2.10% | 4.42% |

At night, KNN reports MORE foreground than MOG2. This is the reverse of daytime behavior.
The likely explanation: MOG2's Gaussian model gradually absorbs flickering light sources
into the background model over time, suppressing them. KNN stores raw pixel samples and
remains sensitive to any pixel-level variation from flickering or glare, treating it as
foreground activity even when no real object is present.

---

## Why This Matters

For the sponsor use case (base entry surveillance), cameras will operate 24/7 including
overnight. If the night algorithm produces noisy masks, two bad things happen:

1. **False positives inflate storage** - the pipeline flags "foreground" pixels that are
   just light halos, encoding them at high CRF when they hold no intelligence value.
2. **Object detection is unreliable** - a vehicle's headlights may be detected as a
   large foreground blob while the vehicle body itself is lost in the dark background.

---

## Proposed Solutions (in order of feasibility for this project)

### 1. CLAHE Preprocessing (implement first - low effort, high impact)
Apply Contrast Limited Adaptive Histogram Equalization to each frame before background
subtraction. This normalizes local contrast and significantly reduces the bloom effect
from point light sources.

```python
# Add to BackgroundSubtractor.apply() as optional preprocessing step
clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
lab[:, :, 0] = clahe.apply(lab[:, :, 0])
frame_enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
```

### 2. Increase MOG2 varThreshold for Night Scenes
The default `varThreshold=16` is calibrated for daytime footage. At night, pixel noise
from sensor grain and compression artifacts is higher. Raising the threshold to 25-35
for night scenes reduces false positives from static noise without missing real objects.

```python
# Night-specific subtractor config
subtractor_night = BackgroundSubtractor(method="MOG2", var_threshold=30, history=700)
```

### 3. Use CDnet Thermal Dataset for Testing
CDnet 2014 includes a `thermal/` category with IR camera footage. Thermal cameras are
unaffected by visible light glare and produce clean foreground masks in any lighting.
The `corridor`, `lakeSide`, and `park` clips in our dataset are directly applicable.

Run:
```bash
python demo_detection.py --input data/dataset/thermal/corridor/ --all-methods --sample-rate 20
```

### 4. SuBSENSE / LOBSTER Algorithms (Milestone 2 stretch goal)
These are pixel-level background subtraction algorithms specifically designed for
challenging conditions including night video. They use local binary pattern features
instead of raw pixel values, making them robust to lighting variation and glare.

- SuBSENSE paper: St-Charles et al., TPAMI 2015
- OpenCV does not include these natively; they require the `pybgs` library
- Assign to Riley if the thermal approach is insufficient

### 5. Nighttime-Specific CDnet Evaluation (for the March 30 report)
When reporting night results, note the algorithm flip (MOG2 tighter than KNN at night)
and flag it as an open research question. Sponsor Cody should be made aware that
nighttime performance needs a different tuning profile than daytime.

---

## Immediate Action Items

| Task | Owner | Target |
|---|---|---|
| Add CLAHE preprocessing option to BackgroundSubtractor | Riley | Milestone 1 |
| Run demo on thermal/corridor and thermal/lakeSide clips | Bloodawn (KheivenD) | This week |
| Benchmark CLAHE vs. no-CLAHE on bridgeEntry | Riley | Milestone 1 |
| Add --night-mode flag to pipeline.py that sets higher varThreshold | Bloodawn (KheivenD) | Milestone 2 |

---

## Better Night Video Sources (for future testing)

If CDnet thermal clips are not sufficient, the following external sources have
higher-quality night surveillance footage:

- **CDnet nightVideos category** (already downloaded) - 6 clips: bridgeEntry,
  busyBoulvard, fluidHighway, streetCornerAtNight, tramStation, winterStreet
- **CDnet thermal category** (already downloaded) - IR footage, no glare issue
- **ATON dataset** (Abandoned Objects at Night) - specifically night surveillance
- **LASIESTA dataset** - includes indoor/outdoor night sequences with ground truth
- **Record your own** - phone camera pointed at a lit parking lot from a static
  position for 2+ minutes gives clean test data matching your actual use case
