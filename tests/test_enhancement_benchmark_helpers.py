"""Pins the helpers taken out of enhancement_benchmark.benchmark_enhancement."""

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from enhancement import enhancement_benchmark as eb  # noqa: E402
from enhancement import plate_reader  # noqa: E402


def test_empty_result_describes_an_unreadable_clip():
    r = eb._empty_result(Path("x.mp4"), [1, 2, 3, 4], "Video file not found.", "Not found: x.mp4")
    assert r.frames_examined == 0 and r.frames_total == 0 and r.variants == {} and r.deltas == {}
    assert r.roi_box == (1, 2, 3, 4) and r.sr_backend == "unknown" and r.ocr_backend is None
    assert r.verdict == "Video file not found." and r.warnings == ["Not found: x.mp4"]


def test_a_given_enhancer_is_used_as_is():
    sentinel = object()
    warnings = []
    assert eb._resolve_enhancer(sentinel, 4, None, warnings) is sentinel and warnings == []


def test_failing_enhancer_construction_degrades_to_none_with_a_warning(monkeypatch):
    from enhancement import enhancer as enhancer_mod

    def boom(*a, **k):
        raise RuntimeError("no weights")

    monkeypatch.setattr(enhancer_mod, "Enhancer", boom)
    warnings = []
    assert eb._resolve_enhancer(None, 4, None, warnings) is None
    assert warnings == ["Enhancer construction failed: no weights; using bicubic only"]


class Backend:
    name = "fake"

    def __init__(self, available):
        self.available = available


def test_ocr_off_means_no_backend_and_no_warning():
    warnings = []
    assert eb._setup_ocr(False, "auto", None, warnings) == (None, None) and warnings == []


def test_unavailable_ocr_backend_warns_and_is_dropped(monkeypatch):
    monkeypatch.setattr(plate_reader, "_select_backend", lambda *a, **k: Backend(False))
    warnings = []
    assert eb._setup_ocr(True, "auto", None, warnings) == (None, "fake")
    assert len(warnings) == 1 and warnings[0].startswith("OCR requested but no backend installed")


def test_available_ocr_backend_is_returned(monkeypatch):
    be = Backend(True)
    monkeypatch.setattr(plate_reader, "_select_backend", lambda *a, **k: be)
    assert eb._setup_ocr(True, "auto", "cpu", []) == (be, "fake")


@pytest.mark.parametrize("device,gpu", [(None, False), ("cpu", False), ("CUDA", True), ("mps", True)])
def test_gpu_flag_follows_the_device(monkeypatch, device, gpu):
    seen = {}

    def select(name, use_gpu):
        seen["g"] = use_gpu
        return Backend(True)

    monkeypatch.setattr(plate_reader, "_select_backend", select)
    eb._setup_ocr(True, "auto", device, [])
    assert seen["g"] is gpu


def test_ocr_setup_error_becomes_a_warning(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no backends")

    monkeypatch.setattr(plate_reader, "_select_backend", boom)
    warnings = []
    assert eb._setup_ocr(True, "auto", None, warnings) == (None, None)
    assert warnings == ["OCR setup failed: no backends"]


def test_accumulators_start_empty_for_the_three_variants():
    variants, sums = eb._new_accumulators()
    assert list(variants) == ["no_enhancement", "full_frame_sr", "roi_only_sr"] == list(sums)
    assert all(s["psnr_n"] == 0 and s["sharp_roi"] == 0.0 for s in sums.values())


def _frame():
    rng = np.random.default_rng(1)
    return rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)


def test_one_frame_feeds_every_variant_without_an_enhancer():
    variants, sums = eb._new_accumulators()
    eb._accumulate_frame(_frame(), (20, 30, 50, 50), None, 2, None, variants, sums)
    assert all(sums[k]["sharp_roi"] > 0 for k in sums)
    # Without an enhancer all three variants are the bicubic baseline, so SR variants match it.
    assert sums["full_frame_sr"]["psnr_n"] == 1 and sums["roi_only_sr"]["ssim_n"] == 1
    assert sums["full_frame_sr"]["sharp_full"] == 0.0 and sums["no_enhancement"]["ocr_n"] == 0


def test_ocr_results_are_summed_and_sample_texts_capped_at_five():
    class Ocr:
        available = True

        def ocr(self, image):
            return [("AB12", 0.8, (0, 0, 1, 1)), ("x", 0.1, (0, 0, 1, 1))]

    variants, sums = eb._new_accumulators()
    for _ in range(7):
        eb._accumulate_frame(_frame(), (20, 30, 50, 50), None, 2, Ocr(), variants, sums)
    assert sums["roi_only_sr"]["ocr_n"] == 7 and sums["roi_only_sr"]["ocr_conf"] == pytest.approx(5.6)
    assert variants["roi_only_sr"].sample_texts == ["AB12"] * 5


def test_summary_averages_over_examined_frames_and_counts():
    variants, sums = eb._new_accumulators()
    sums["no_enhancement"].update(sharp_roi=10.0)
    sums["full_frame_sr"].update(sharp_roi=30.0, sharp_full=8.0, psnr=60.0, psnr_n=2, ssim=1.5, ssim_n=3,
                                 ocr_conf=1.2, ocr_n=4)
    eb._summarize_variants(variants, sums, 2)
    assert variants["no_enhancement"].avg_sharpness_roi == 5.0
    v = variants["full_frame_sr"]
    assert (v.avg_sharpness_roi, v.avg_sharpness_full, v.avg_psnr_vs_baseline) == (15.0, 4.0, 30.0)
    assert (v.avg_ssim_vs_baseline, v.avg_ocr_confidence, v.ocr_reads) == (0.5, 0.3, 4)


def test_summary_with_no_frames_leaves_everything_unset():
    variants, sums = eb._new_accumulators()
    eb._summarize_variants(variants, sums, 0)
    assert variants["no_enhancement"].avg_sharpness_roi in (0, 0.0, None)


def test_deltas_are_percent_gain_over_the_baseline_and_ocr_gain_when_known():
    variants, _ = eb._new_accumulators()
    variants["no_enhancement"].avg_sharpness_roi = 100.0
    variants["full_frame_sr"].avg_sharpness_roi = 150.0
    variants["roi_only_sr"].avg_sharpness_roi = 80.0
    d = eb._compute_deltas(variants)
    assert d == {"roi_sharpness_gain_full_sr_pct": 50.0, "roi_sharpness_gain_roi_sr_pct": -20.0}
    variants["no_enhancement"].avg_ocr_confidence = 0.5
    variants["roi_only_sr"].avg_ocr_confidence = 0.75
    d = eb._compute_deltas(variants)
    assert d["ocr_confidence_gain_roi_sr"] == 0.25 and "ocr_confidence_gain_full_sr" not in d
