import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.result_numbers import (MIB, clip_count, fmt_length, format_result, plan_segments,
                          summarize_result)


class ResultTests(unittest.TestCase):
    def test_basic_percent_and_mb(self):
        r = summarize_result([(184 * MIB, 70 * MIB)])
        self.assertEqual(r["saved_pct"], 62)  # 114/184 = 61.96
        self.assertEqual((r["before_mb"], r["after_mb"], r["saved_mb"]), (184.0, 70.0, 114.0))
        self.assertEqual(r["ratio"], 2.6)

    def test_sums_not_average_of_percentages(self):
        # 100 MB -> 10 MB (90%) and 10 MB -> 9 MB (10%): average of percents is 50, real is 82.7
        r = summarize_result([(100 * MIB, 10 * MIB), (10 * MIB, 9 * MIB)])
        self.assertEqual(r["saved_pct"], 83)

    def test_displayed_numbers_add_up(self):
        for src, out in [(1000003, 333333), (7 * MIB + 123456, 3 * MIB + 654321), (5555555, 12345)]:
            r = summarize_result([(src, out)])
            self.assertAlmostEqual(r["before_mb"] - r["after_mb"], r["saved_mb"], places=6)

    def test_never_100_percent_while_file_exists(self):
        r = summarize_result([(1_000_000_000, 1000)])
        self.assertEqual(r["saved_pct"], 99)

    def test_output_not_smaller(self):
        r = summarize_result([(10 * MIB, 12 * MIB)])
        self.assertEqual(r["verdict"], "no_saving")
        self.assertEqual(r["saved_pct"], 0)
        self.assertEqual(r["saved_bytes"], 0)
        self.assertIn("No space saved", format_result(r)["headline"])

    def test_equal_sizes(self):
        self.assertEqual(summarize_result([(MIB, MIB)])["verdict"], "no_saving")

    def test_unknown_source(self):
        self.assertEqual(summarize_result([(0, 5)])["verdict"], "unknown")

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            summarize_result([(-1, 5)])

    def test_unit_is_binary_like_explorer(self):
        # 1,048,576 bytes shows as 1 MB in Windows Explorer
        self.assertEqual(summarize_result([(2 * MIB, MIB)])["before_mb"], 2.0)

    def test_format_strings_use_the_same_numbers(self):
        f = format_result(summarize_result([(184 * MIB, 70 * MIB)]))
        self.assertEqual(f["headline"], "Saved 62%")
        self.assertEqual(f["detail"], "184.0 MB to 70.0 MB, 114.0 MB freed, 2.6 times smaller")


class SegmentTests(unittest.TestCase):
    def test_default_is_whole_video_in_one_clip(self):
        for dur in (12.4, 130.0, 600.0, 3725.5):
            p = plan_segments(dur)
            self.assertGreaterEqual(p["default_seconds"], dur)
            self.assertEqual(clip_count(dur, p["default_seconds"]), 1)

    def test_recommended_is_half_rounded_up_to_ten(self):
        self.assertEqual(plan_segments(130.0)["recommended_seconds"], 70)   # 65 -> 70
        self.assertEqual(plan_segments(600.0)["recommended_seconds"], 300)
        self.assertEqual(plan_segments(61.0)["recommended_seconds"], 40)    # 30.5 -> 40

    def test_recommended_gives_two_clips(self):
        for dur in (130.0, 600.0, 61.0, 900.0):
            self.assertEqual(plan_segments(dur)["clips_at_recommended"], 2)

    def test_short_videos_recommend_whole(self):
        p = plan_segments(15.0)
        self.assertEqual(p["recommended_seconds"], p["whole_seconds"])
        self.assertEqual(p["presets"], [])

    def test_presets_only_shorter_than_video(self):
        p = plan_segments(130.0)
        self.assertEqual([x["seconds"] for x in p["presets"]], [30, 60, 120])
        p = plan_segments(4000.0)
        self.assertEqual([x["seconds"] for x in p["presets"]][-1], 1800)

    def test_long_video_can_exceed_slider(self):
        p = plan_segments(7200.0)
        self.assertGreater(p["default_seconds"], 1800)
        self.assertFalse(p["fits_slider"])

    def test_live_source(self):
        p = plan_segments(None)
        self.assertEqual(p["kind"], "live")
        self.assertEqual(p["default_seconds"], 600)
        self.assertIn(300, [x["seconds"] for x in p["presets"]])

    def test_labels(self):
        self.assertEqual(fmt_length(30), "30 s")
        self.assertEqual(fmt_length(300), "5 min")
        self.assertEqual(fmt_length(3725), "1 h 2 min 5 s")


if __name__ == "__main__":
    unittest.main()
