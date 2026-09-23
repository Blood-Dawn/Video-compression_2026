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
}
