# CDnet 2014 — Test Video Clips

53 clips from the CDnet 2014 Change Detection Benchmark, organized by scene category.
These files are gitignored — each team member builds them locally from the image frames.
See **DEV.md Section 13** for step-by-step instructions.

> Citation: Y. Wang et al., "CDnet 2014: An Expanded Change Detection Benchmark Dataset," IEEE CVPR Workshops, 2014.
> Source: http://www.changedetection.net

---

## Folder structure

```
cdnet_mp4/
├── baseline/              # Normal daytime, static camera, clear lighting
├── badWeather/            # Snow, blizzard, wet conditions
├── cameraJitter/          # Slight camera shake/vibration
├── dynamicBackground/     # Moving background elements (water, trees)
├── intermittentObjectMotion/  # Objects that stop and become background
├── lowFramerate/          # 0.17 fps to 1 fps captures
├── nightVideos/           # Low light, headlights, streetlamps
├── PTZ/                   # Pan-tilt-zoom camera movement
├── shadow/                # Strong shadow artifacts
├── thermal/               # Infrared/thermal camera footage
└── turbulence/            # Atmospheric heat distortion
```

---

## How to reference clips in tests

Use `pathlib` so paths work on any OS:

```python
from pathlib import Path

CDNET = Path("data/samples/cdnet_mp4")

# Pick a specific clip
clip = CDNET / "baseline" / "baseline_pedestrians.mp4"

# Or grab all clips in a category
night_clips = list((CDNET / "nightVideos").glob("*.mp4"))

# Or all 53 clips
all_clips = list(CDNET.rglob("*.mp4"))
```

---

## Recommended clips by use case

| What you're testing | Use this clip |
|---|---|
| Basic detection, fast results | `baseline/baseline_pedestrians.mp4` |
| Vehicle detection | `baseline/baseline_highway.mp4` |
| Night / low light | `nightVideos/nightVideos_bridgeEntry.mp4` |
| Shadow robustness | `shadow/shadow_busStation.mp4` |
| Thermal / IR camera | `thermal/thermal_corridor.mp4` |
| Mostly static scene (good for Mode 1) | `intermittentObjectMotion/intermittentObjectMotion_parking.mp4` |
| Stress test (longest clip) | `turbulence/turbulence_turbulence0.mp4` |
