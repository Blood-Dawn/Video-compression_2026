# Session Log - 2026-04-12 — jorgesanchez

**Author:** Jorge Sanchez (@sanchez-jorge)
**Branch:** `feature/detection-tuning`
**Milestone:** 2 — Section 2.7 Detection Tuning and Calibration (Jorge's tasks)

---

## Summary

Completed Jorge's half of Section 2.7: researched MOG2 and KNN tuning parameters, generated synthetic test footage for three lighting conditions, ran both algorithms and measured false positive/false negative rates, and documented optimal parameter sets.

---

## Work Completed

### `src/background_subtraction/tuning_experiment.py`

- Written from scratch to systematically test MOG2 and KNN across daytime, night, and mixed-lighting conditions using synthetic numpy frames (same approach as existing test suite)
- Generates three clip types: daytime (brightness=120, clean object entry), night (noisy background brightness=25, noise_std=6), mixed lighting (background gradually shifts from bright to dim simulating dusk)
- Tests 6 MOG2 parameter combinations (varThreshold 16/30/40, history 200/500, CLAHE on/off) and 4 KNN combinations (history 200/500, CLAHE/night_mode on/off)
- Measures false positive rate on static scenes (accepta