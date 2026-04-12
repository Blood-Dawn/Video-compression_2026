"""
tuning_experiment.py

Systematic parameter tuning for MOG2 and KNN background subtractors.
Tests both algorithms across daytime, night, and mixed-lighting conditions
using synthetic frames. Measures false positive and false negative rates
for each parameter combination and outputs a summary table.

Run with:
    python src/background_subtraction/tuning_experiment.py

Author: Jorge Sanchez (@sanchez-jorge)
Section: 2.7 — Detection Tuning and Calibration
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import numpy as np
import cv2
from dataclasses import dataclass
from typing import List, Dict, Tuple
from background_subtraction.background_subtraction import BackgroundSubtractor


def make_blank_frame(h=480, w=640, brightness=0):
    return np.full((h, w, 3), brightness, dtype=np.uint8)


def make_frame_with_object(h=480, w=640, obj_x=200, obj_y=150,
                            obj_w=100, obj_h=120, brightness=200, bg_brightness=0):
    frame = make_blank_frame(h, w, bg_brightness)
    frame[obj_y:obj_y + obj_h, obj_x:obj_x + obj_w] = brightness
    return frame


def make_noisy_frame(h=480, w=640, base_brightness=30, noise_std=8):
    base = np.full((h, w, 3), base_brightness, dtype=np.float32)
    noise = np.random.normal(0, noise_std, (h, w, 3))
    return np.clip(base + noise, 0, 255).astype(np.uint8)


def train_subtractor(bs, frame, n_frames=60):
    for _ in range(n_frames):
        bs.apply(frame)


def daytime_clips(n_bg=60, n_obj=10):
    bg = [make_blank_frame(brightness=120)] * n_bg
    obj = [make_frame_with_object(brightness=220, bg_brightness=120)] * n_obj
    return bg, obj


def night_clips(n_bg=60, n_obj=10):
    bg = [make_noisy_frame(base_brightness=25, noise_std=6) for _ in range(n_bg)]
    obj = [make_frame_with_object(brightness=90, bg_brightness=25, obj_w=100, obj_h=120)] * n_obj
    return bg, obj


def mixed_lighting_clips(n_bg=60, n_obj=10):
    bg = []
    for i in range(n_bg):
        brightness = max(20, 120 - int(i * (100 / n_bg)))
        bg.append(make_blank_frame(brightness=brightness))
    obj = [make_frame_with_object(brightness=150, bg_brightness=20)] * n_obj
    return bg, obj


def measure_fp_rate(bs, static_frames):
    fp_counts = []
    for frame in static_frames:
        mask = bs.apply(frame)
        fp_counts.append(np.count_nonzero(mask) / mask.size)
    return float(np.mean(fp_counts))


def measure_fn_rate(bs, obj_frames):
    obj_x, obj_y, obj_w, obj_h = 200, 150, 100, 120
    fn_counts = []
    for frame in obj_frames:
        mask = bs.apply(frame)
        roi = mask[obj_y:obj_y + obj_h, obj_x:obj_x + obj_w]
        detected = np.count_nonzero(roi)
        fn_counts.append(1.0 - detected / (obj_w * obj_h))
    return float(np.mean(fn_counts))


@dataclass
class ExperimentResult:
    condition: str
    method: str
    params: dict
    fp_rate: float
    fn_rate: float

    def passes_acceptance(self):
        return self.fp_rate < 0.02


def run_experiment(condition_name, bg_frames, obj_frames, method, params):
    bs = BackgroundSubtractor(method=method, **params)
    for frame in bg_frames:
        bs.apply(frame)
    static_test = bg_frames[-20:]
    fp = measure_fp_rate(bs, static_test)
    fn = measure_fn_rate(bs, obj_frames)
    return ExperimentResult(condition=condition_name, method=method, params=params, fp_rate=fp, fn_rate=fn)


MOG2_PARAM_SETS = [
    {"history": 500, "var_threshold": 16, "min_area": 500},
    {"history": 500, "var_threshold": 30, "min_area": 500},
    {"history": 200, "var_threshold": 16, "min_area": 500},
    {"history": 500, "var_threshold": 40, "min_area": 500},
    {"history": 500, "var_threshold": 16, "min_area": 500, "use_clahe": True},
    {"history": 500, "var_threshold": 30, "min_area": 500, "use_clahe": True},
]

KNN_PARAM_SETS = [
    {"history": 500, "min_area": 500},
    {"history": 200, "min_area": 500},
    {"history": 500, "min_area": 500, "use_clahe": True},
    {"history": 500, "min_area": 500, "night_mode": True},
]

CONDITIONS = {
    "daytime": daytime_clips,
    "night": night_clips,
    "mixed_lighting": mixed_lighting_clips,
}


def main():
    np.random.seed(42)
    results = []
    print("Running tuning experiments...\n")
    for condition_name, clip_fn in CONDITIONS.items():
        bg_frames, obj_frames = clip_fn()
        for params in MOG2_PARAM_SETS:
            results.append(run_experiment(condition_name, bg_frames, obj_frames, "MOG2", params))
        for params in KNN_PARAM_SETS:
            results.append(run_experiment(condition_name, bg_frames, obj_frames, "KNN", params))

    print(f"{'Condition':<18} {'Method':<6} {'varThr':>6} {'hist':>5} {'CLAHE':>6} {'FP%':>7} {'FN%':>7} {'Pass?':>6}")
    print("-" * 75)
    for r in results:
        vt = r.params.get("var_threshold", "-")
        hist = r.params.get("history", "-")
        clahe = "Y" if r.params.get("use_clahe") or r.params.get("night_mode") else "N"
        passed = "Y" if r.passes_acceptance() else "N"
        print(f"{r.condition:<18} {r.method:<6} {str(vt):>6} {str(hist):>5} {clahe:>6} {r.fp_rate*100:>6.2f}% {r.fn_rate*100:>6.2f}% {passed:>6}")

    print("\n--- Best MOG2 config per condition ---")
    for cond in CONDITIONS:
        cond_results = [r for r in results if r.condition == cond and r.method == "MOG2" and r.passes_acceptance()]
        if cond_results:
            best = min(cond_results, key=lambda r: r.fp_rate)
            print(f"  {cond}: varThreshold={best.params.get('var_threshold')}, history={best.params.get('history')}, CLAHE={'Y' if best.params.get('use_clahe') else 'N'} -> FP={best.fp_rate*100:.2f}%, FN={best.fn_rate*100:.2f}%")
        else:
            print(f"  {cond}: No passing config found")

    print("\n--- Best KNN config per condition ---")
    for cond in CONDITIONS:
        cond_results = [r for r in results if r.condition == cond and r.method == "KNN" and r.passes_acceptance()]
        if cond_results:
            best = min(cond_results, key=lambda r: r.fp_rate)
            print(f"  {cond}: history={best.params.get('history')}, CLAHE={'Y' if best.params.get('use_clahe') or best.params.get('night_mode') else 'N'} -> FP={best.fp_rate*100:.2f}%, FN={best.fn_rate*100:.2f}%")
        else:
            print(f"  {cond}: No passing config found")

    print("\nDone.")
    return results


if __name__ == "__main__":
    main()