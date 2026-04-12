# Session Log - 2026-04-11

**Author:** Jorge Sanchez (@sanchez-jorge)
**Branch:** `feature/benchmarking-milestone2`
**Milestone:** 2 — Section 2.5 Algorithm Comparison and Pipeline Stress Test

---

## Summary

Completed all Section 2.5 deliverables: algorithm comparison documentation, stress test script, storage extrapolation, and the algorithm comparison notebook.

---

## Work Completed

### `docs/algorithm_comparison.md`

- Side-by-side comparison of MOG2 and KNN on CDnet 2014 benchmark data (46 scenes, 10 categories)
- Both algorithms produce identical average FG% across all categories (3.81% overall avg)
- MOG2 selected as production recommendation based on superior CPU performance (~64 fps vs ~40-50 fps), lower memory footprint, built-in shadow detection, and lower false positive rate on edge cases
- Included recommended default parameters for daytime (varThreshold=16) and night (varThreshold=30)
- Documented when to prefer KNN (thermal/IR footage, non-Gaussian noise, sharper boundary needs)

### `docs/stress_test_results.md`

- Documented 1-hour simulated footage stress test results
- Memory usage: peak < 250 MB, growth over 1 hour < 5 MB — no runaway growth detected
- Storage results: ~51 MB per hour vs ~320 MB naive H.264 (~6.3x compression ratio)
- Storage extrapolation for 60-day / 100-camera deployment:
  - Our pipeline: ~7.2 TB
  - Naive H.264: ~46.2 TB
  - Savings: ~39 TB
- 1-week retention per camera: ~8.4 GB (well within commodity NAS capacity)
- All acceptance criteria met

### `tests/test_pipeline_stress.py`

- Written from scratch with two test functions marked `@pytest.mark.slow`
- `test_pipeline_stress_one_hour`: simulates 60 one-minute segments through ROIEncoder, tracks memory via `tracemalloc`, asserts no errors and memory growth < 50 MB, verifies all 60 rows written to SQLite
- `test_storage_extrapolation`: encodes sample foreground and background segments, projects per-camera weekly and 100-camera 60-day storage, asserts compression ratio ≥ 3x vs naive H.264

### `notebooks/algorithm_comparison.ipynb`

- 6-cell Jupyter notebook with full MOG2 vs KNN visualization
- Cell 1: Setup and imports
- Cell 2: CDnet 2014 benchmark data (all 10 categories, MOG2 and KNN FG%)
- Cell 3: Side-by-side bar chart of FG% by category — saved to `docs/algorithm_comparison_bar.png`
- Cell 4: Performance profile bar chart (speed, memory, shadow detection, FP rate, legacy HW) — saved to `docs/algorithm_comparison_profile.png`
- Cell 5: Compression results summary (compression ratio, PSNR, SSIM for fg and bg scenarios) — saved to `docs/compression_results.png`
- Cell 6: Production recommendation printout with recommended parameters

---

## PR

- Branch: `feature/benchmarking-milestone2` → `main`
- PR #9: feat: Section 2.5 - algorithm comparison, stress test, storage extrapolation
- Reviewers: Blood-Dawn, ashleyn07, sRileyRoberts, victort29
- Status: Open, awaiting review
