package org.svcs.mobile.compress

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure-math coverage for the standalone compressor's presets (Fall roadmap
 * Phase 1). The numbers here are anchored to the first real-device run:
 * a 107.27 s clip through the Discord (10 MB) preset came out at ~594 kbps
 * video, which is what bitrateForTargetSize predicts to within ~1%.
 */
class CompressionPresetsTest {

    @Test
    fun targetSize_matchesTheFieldTestedDiscordRun() {
        val bps = bitrateForTargetSize(SizePresets.DISCORD_FREE, durationMs = 107_267)
        // (10e6 * 8 / 107.267 - 128k) * 0.95
        assertEquals(587_000.0, bps.toDouble(), 1_500.0)
    }

    @Test
    fun targetSize_noAudioBudgetGoesToThePicture() {
        val withAudio = bitrateForTargetSize(SizePresets.WHATSAPP, 60_000)
        val silent = bitrateForTargetSize(SizePresets.WHATSAPP, 60_000, audioBps = 0)
        assertEquals((128_000 * 0.95).toInt().toDouble(), (silent - withAudio).toDouble(), 2.0)
    }

    @Test
    fun targetSize_neverDropsBelowTheFloor() {
        // A 10 MB budget over an hour would be ~22 kbps; the floor keeps it
        // at something an encoder can produce watchable frames with.
        val bps = bitrateForTargetSize(SizePresets.DISCORD_FREE, durationMs = 3_600_000)
        assertEquals((300_000 * 0.95).toInt(), bps)
    }

    @Test
    fun targetSize_zeroDurationIsTreatedAsOneSecond() {
        val bps = bitrateForTargetSize(SizePresets.EMAIL, durationMs = 0)
        assertTrue(bps > 0)
    }

    @Test
    fun customPreset_labelsWholeAndFractionalMegabytes() {
        assertEquals("Custom (8 MB)", SizePresets.custom(8.0).label)
        assertEquals(8_000_000L, SizePresets.custom(8.0).maxBytes)
        assertEquals("Custom (7.5 MB)", SizePresets.custom(7.5).label)
    }

    @Test
    fun customPreset_clampsNonsenseToAPositiveSize() {
        assertTrue(SizePresets.custom(0.0).maxBytes > 0)
        assertTrue(SizePresets.custom(-5.0).maxBytes > 0)
    }

    // ── scaledFrameSize: the portrait fix ────────────────────────────────

    @Test
    fun portrait_capsTheWidthNotTheHeight() {
        // The Phase 1 bug: createForHeight(720) made this 405x720.
        assertEquals(720 to 1280, scaledFrameSize(1080, 1920, 0, 720))
    }

    @Test
    fun storedLandscapeWithRotation_isTreatedAsPortrait() {
        // Most phones store portrait video as landscape pixels + rotation 90.
        assertEquals(720 to 1280, scaledFrameSize(1920, 1080, 90, 720))
        assertEquals(720 to 1280, scaledFrameSize(1920, 1080, 270, 720))
    }

    @Test
    fun landscape_capsTheHeight() {
        assertEquals(1280 to 720, scaledFrameSize(1920, 1080, 0, 720))
        assertEquals(1280 to 720, scaledFrameSize(1920, 1080, 180, 720))
    }

    @Test
    fun neverUpscales() {
        assertNull(scaledFrameSize(640, 360, 0, 720))
        assertNull(scaledFrameSize(1280, 720, 0, 720))
        assertNull(scaledFrameSize(1080, 1920, 0, 1080))
    }

    @Test
    fun noCapOrBadInput_meansLeaveItAlone() {
        assertNull(scaledFrameSize(1920, 1080, 0, null))
        assertNull(scaledFrameSize(0, 1080, 0, 720))
        assertNull(scaledFrameSize(1920, 1080, 0, 0))
    }

    @Test
    fun outputDimensionsAreAlwaysEven() {
        // 3840x1644 (a 2.33:1 cinema crop) capped at 720 -> 1681.x wide.
        val (w, h) = scaledFrameSize(3840, 1644, 0, 720)!!
        assertEquals(0, w % 2)
        assertEquals(0, h % 2)
        assertEquals(720, h)
    }

    // ── estimateOutputBytes: the COMPRESS screen's "up to" figure ────────

    @Test
    fun estimate_isBitrateTimesDuration() {
        // 6 Mbps video + 128 kbps audio for 10 s = 7.66 MB.
        assertEquals(7_660_000L, estimateOutputBytes(6_000_000, 128_000, 10_000))
    }

    @Test
    fun estimate_ofASizeTargetStaysUnderTheTarget() {
        val video = bitrateForTargetSize(SizePresets.DISCORD_FREE, durationMs = 107_267)
        val est = estimateOutputBytes(video, AUDIO_RESERVE_BPS, 107_267)
        assertTrue("estimate $est should be under 10 MB", est < SizePresets.DISCORD_FREE.maxBytes)
    }

    @Test
    fun estimate_negativeDurationIsZero() {
        assertEquals(0L, estimateOutputBytes(6_000_000, 128_000, -5))
    }

    // ── capToSourceBitrate: the "3.5 MB became 32 MB" bug ────────────────

    @Test
    fun capToSource_shrinksAFlatPresetDownToTheSourcesOwnRate() {
        // The reported bug, reproduced: a 3.5 MB, 30 s clip (~933 kbps total,
        // ~805 kbps of video after the audio reserve) asked to compress with
        // the Medium preset's flat 6 Mbps. Uncapped that inflates the file;
        // capped it should land at (approximately) what the source already used.
        val capped = capToSourceBitrate(
            requestedBps = QualityPresets.MEDIUM.targetBitrateBps,
            inputBytes = 3_500_000,
            durationMs = 30_000,
            hasAudio = true,
        )
        assertEquals(805_333, capped)
        assertTrue("capped bitrate must be well under Medium's flat 6 Mbps", capped < QualityPresets.MEDIUM.targetBitrateBps)
    }

    @Test
    fun capToSource_leavesARequestAloneWhenAlreadyBelowSourceRate() {
        // A high-bitrate 4K source being compressed down with the Low preset
        // (3 Mbps): the request is already well under the source's own rate,
        // so the cap must not touch it.
        val capped = capToSourceBitrate(
            requestedBps = QualityPresets.LOW.targetBitrateBps,
            inputBytes = 200_000_000,
            durationMs = 30_000,
            hasAudio = true,
        )
        assertEquals(QualityPresets.LOW.targetBitrateBps, capped)
    }

    @Test
    fun capToSource_ignoresAudioReserveWhenSourceIsSilent() {
        val withAudio = capToSourceBitrate(10_000_000, 3_500_000, 30_000, hasAudio = true)
        val silent = capToSourceBitrate(10_000_000, 3_500_000, 30_000, hasAudio = false)
        assertTrue(silent > withAudio)
    }

    @Test
    fun capToSource_neverDropsBelowTheFloor() {
        // A tiny, long source (100 KB over 10 minutes) computes to a near-zero
        // rate; the floor keeps the cap at something an encoder can use.
        val capped = capToSourceBitrate(6_000_000, 100_000, 600_000, hasAudio = true)
        assertEquals(MIN_VIDEO_BITRATE_BPS, capped)
    }

    @Test
    fun capToSource_skipsWhenSizeOrDurationIsUnknown() {
        assertEquals(6_000_000, capToSourceBitrate(6_000_000, inputBytes = 0, durationMs = 30_000, hasAudio = true))
        assertEquals(6_000_000, capToSourceBitrate(6_000_000, inputBytes = 3_500_000, durationMs = 0, hasAudio = true))
        assertEquals(6_000_000, capToSourceBitrate(6_000_000, inputBytes = -1, durationMs = -1, hasAudio = true))
    }
}
