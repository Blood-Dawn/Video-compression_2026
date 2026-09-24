package org.svcs.mobile.compress

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SizeCalibrationTest {

    @Test
    fun tooFewJobs_meansNoBoost() {
        assertEquals(1.0, SizeCalibration.factor(emptyList()), 0.0)
        assertEquals(1.0, SizeCalibration.factor(listOf(0.8, 0.8)), 0.0)
    }

    @Test
    fun boostIsSizedFromTheLeastUndershootingJob() {
        // The Sep 22 field test landed about 80% of the requested bitrate.
        val f = SizeCalibration.factor(listOf(0.80, 0.78, 0.84))
        assertEquals(0.97 / 0.84, f, 1e-9)
        // Every past job, boosted, stays at or under 97% of what was asked.
        listOf(0.80, 0.78, 0.84).forEach { assertTrue(it * f <= 0.97 + 1e-9) }
    }

    @Test
    fun boostIsCapped() {
        assertEquals(SizeCalibration.MAX_BOOST, SizeCalibration.factor(listOf(0.3, 0.4, 0.35)), 0.0)
    }

    @Test
    fun anEncoderThatAlreadyHitsItsTarget_isLeftAlone() {
        assertEquals(1.0, SizeCalibration.factor(listOf(0.80, 0.99, 0.82)), 0.0)
    }

    @Test
    fun onlyRecentJobsCount() {
        // Ten recent low ratios outweigh an old near-target one beyond HISTORY.
        val ratios = List(10) { 0.8 } + listOf(0.99)
        assertEquals(0.97 / 0.8, SizeCalibration.factor(ratios), 1e-9)
    }

    @Test
    fun ratios_useOnlyComparableJobs_newestFirst() {
        fun rec(ts: Long, mode: String = "TARGET_SIZE", codec: String = "video/hevc",
                fallback: Boolean = false, req: Int = 1_000_000, act: Int = 800_000) = CompressionRecord(
            outputUri = "u$ts", outputDisplayName = "n", originalName = null, originalSizeBytes = 1,
            outputSizeBytes = 1, durationMs = 1, timestampMs = ts, codecMime = codec, modeType = mode,
            presetLabel = "", usedFallback = fallback, requestedVideoBps = req, actualVideoBps = act,
        )
        val history = listOf(
            rec(1, act = 700_000),
            rec(3, act = 900_000),
            rec(2, mode = "QUALITY"),
            rec(4, codec = "video/avc"),
            rec(5, fallback = true),
            rec(6, req = 0),
        )
        assertEquals(listOf(0.9, 0.7), SizeCalibration.ratios(history, "video/hevc"))
    }

    @Test
    fun actualBitrate_prefersTheReportedValue_elseEstimatesFromTheFile() {
        assertEquals(750_000, SizeCalibration.actualVideoBps(750_000, 1, 1, 0))
        // 8 MB over 100 s with 128 kbps of audio: 640 kbps total minus 128 kbps.
        assertEquals(512_000, SizeCalibration.actualVideoBps(0, 8_000_000, 100_000, 128_000))
        assertEquals(0, SizeCalibration.actualVideoBps(-1, 0, 0, 0))
    }
}
