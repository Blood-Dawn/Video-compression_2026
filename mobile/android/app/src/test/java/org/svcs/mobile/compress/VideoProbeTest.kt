package org.svcs.mobile.compress

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The pure half of MediaProbe: turning stored size + container rotation into
 * what the user sees. Phone video is mostly stored landscape with a 90 or 270
 * degree rotation flag, which is exactly the case the Sep 23 portrait bug was
 * about.
 */
class VideoProbeTest {

    private fun probe(w: Int, h: Int, rot: Int) =
        VideoProbe(durationMs = 1_000, hasAudio = true, width = w, height = h, rotationDegrees = rot)

    @Test
    fun portraitPhoneClip_isDisplayedTall() {
        val p = probe(1920, 1080, 90)
        assertEquals(1080, p.displayWidth)
        assertEquals(1920, p.displayHeight)
    }

    @Test
    fun rotation270AndNegative90_areAlsoSideways() {
        assertEquals(1080, probe(1920, 1080, 270).displayWidth)
        assertEquals(1080, probe(1920, 1080, -90).displayWidth)
    }

    @Test
    fun upsideDown_keepsItsShape() {
        val p = probe(1920, 1080, 180)
        assertEquals(1920, p.displayWidth)
        assertEquals(1080, p.displayHeight)
    }

    @Test
    fun unknown_hasNoFrameSizeAndAssumesAudio() {
        assertFalse(VideoProbe.UNKNOWN.hasFrameSize)
        // Over-reserving audio is the safe miss for size-limited jobs.
        assertTrue(VideoProbe.UNKNOWN.hasAudio)
        assertEquals(0L, VideoProbe.UNKNOWN.durationMs)
    }

    @Test
    fun oneMissingDimension_meansNoFrameSize() {
        assertFalse(probe(1920, 0, 0).hasFrameSize)
        assertTrue(probe(1920, 1080, 0).hasFrameSize)
    }
}
