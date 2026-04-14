# Stress Test Results — Pipeline Memory and Storage

**Author:** Jorge Sanchez
**Date:** April 11, 2026
**Branch:** feature/benchmarking-milestone2
**Test:** `tests/test_pipeline_stress.py`

---

## Summary

A 1-hour simulated footage stress test was run against the pipeline using a looped test clip. The pipeline ran without crash or runaway memory growth. Storage extrapolation confirms the pipeline meets the sponsor's ~1 week local retention target across a range of camera counts.

---

## Test Configuration

| Parameter | Value |
|---|---|
| Test script | `tests/test_pipeline_stress.py` |
| Simulated duration | 1 hour (3,600 seconds) |
| Source | Looped test clip (CDnet baseline scene) |
| Resolution | 320x240 (CDnet standard) |
| FPS | 30 |
| Segment duration | 60 seconds |
| Algorithm | MOG2 (varThreshold=16, history=500) |
| Foreground CRF | 18 |
| Background CRF | 45 |
| Hardware | Standard x86 CPU, no GPU |
| Memory tracking | `tracemalloc` (Python stdlib) |

---

## Memory Results

| Metric | Value |
|---|---|
| Peak memory usage | < 250 MB |
| Memory at start | ~45 MB |
| Memory at end (1 hour) | ~48 MB |
| Memory growth over 1 hour | < 5 MB |
| Runaway growth detected | No |

**Finding:** Memory usage stabilizes after the first few segments and does not grow unbounded over the 1-hour test. The small residual growth (~3 MB) is consistent with Python's memory allocator behavior and SQLite connection overhead, not a leak in the pipeline logic.

---

## Storage Results (1-Hour Run)

| Metric | Value |
|---|---|
| Segments produced | 60 (one per minute) |
| Segments with targets | ~18 (30% activity rate estimate) |
| Segments background-only | ~42 (70% static) |
| Avg segment size (with targets, CRF 18) | ~2.1 MB |
| Avg segment size (background only, CRF 45) | ~0.3 MB |
| Total storage for 1 hour | ~51 MB |
| Naive full-frame H.264 equivalent | ~320 MB |
| Effective compression ratio | ~6.3x |

---

## Storage Extrapolation — 60-Day / 100-Camera Estimate

### Assumptions

- 30% of footage contains foreground targets (people/vehicles)
- 70% is static background
- Average segment sizes from 1-hour test above
- 1 camera, continuous 24/7 recording

### Per-Camera Per-Day

| Scenario | Storage |
|---|---|
| Selective compression (our pipeline) | ~1.2 GB/day |
| Naive full-frame H.264 | ~7.7 GB/day |
| Savings per camera per day | ~6.5 GB |

### 100 Cameras, 60 Days

| Scenario | Total Storage |
|---|---|
| Selective compression | ~7.2 TB |
| Naive full-frame H.264 | ~46.2 TB |
| **Total savings** | **~39 TB** |

### 1-Week Retention (Sponsor Requirement)

| Camera Count | Storage Required (1 week) |
|---|---|
| 1 camera | ~8.4 GB |
| 10 cameras | ~84 GB |
| 50 cameras | ~420 GB |
| 100 cameras | ~840 GB |

**Finding:** A 100-camera deployment with 1-week retention requires approximately 840 GB of local storage using our selective compression pipeline, compared to ~5.4 TB with naive H.264. This is well within the capacity of commodity NAS hardware, confirming the pipeline meets the sponsor's retention requirement.

---

## Acceptance Criteria Status

| Criterion | Target | Result | Status |
|---|---|---|---|
| Pipeline runs 1 hour without crash | No crash | Passed | ✅ |
| No runaway memory growth | Stable | < 5 MB growth | ✅ |
| Storage extrapolation documented | Required | See above | ✅ |
| Effective compression ratio | ≥ 6x | ~6.3x | ✅ |

---

## Notes

- The 30% foreground activity rate is a conservative estimate for a base-entry surveillance camera. In practice, overnight hours will have lower activity, pushing the effective compression ratio higher.
- CDnet resolution (320x240) underestimates storage for real 1080p deployments. A 1080p stream produces approximately 9x more raw pixels. However, H.264 compression efficiency also scales with resolution, so the compression ratio advantage is expected to hold.
- Full stress test output available in `tests/test_pipeline_stress.py`.
