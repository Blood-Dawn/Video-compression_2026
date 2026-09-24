package org.svcs.mobile.compress

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.svcs.mobile.detect.NormBox

class RoiPlannerTest {

    private fun assertBox(expected: NormBox, actual: NormBox) {
        assertEquals(expected.left, actual.left, 1e-4f)
        assertEquals(expected.top, actual.top, 1e-4f)
        assertEquals(expected.right, actual.right, 1e-4f)
        assertEquals(expected.bottom, actual.bottom, 1e-4f)
    }

    @Test
    fun noDetections_meansNoPlan() {
        assertTrue(RoiPlanner.regions(emptyList()).isEmpty())
        assertTrue(RoiPlanner.rects(emptyList(), 1280, 720, 0).isEmpty())
    }

    @Test
    fun overlappingDetectionsAcrossFrames_mergeIntoOneRegion() {
        // The same person drifting a little between samples.
        val r = RoiPlanner.regions(listOf(
            NormBox(0.40f, 0.30f, 0.50f, 0.70f),
            NormBox(0.45f, 0.30f, 0.55f, 0.70f),
        ))
        assertEquals(1, r.size)
        assertTrue(r[0].left < 0.40f && r[0].right > 0.55f) // padded union
    }

    @Test
    fun separateDetections_staySeparate_largestFirst() {
        val r = RoiPlanner.regions(listOf(
            NormBox(0.05f, 0.05f, 0.10f, 0.10f),
            NormBox(0.60f, 0.40f, 0.80f, 0.90f),
        ))
        assertEquals(2, r.size)
        assertTrue(r[0].area > r[1].area)
    }

    @Test
    fun regionsCoveringMostOfTheFrame_areDropped() {
        // A close-up face filling the shot: nothing to call background.
        assertTrue(RoiPlanner.regions(listOf(NormBox(0.05f, 0.05f, 0.95f, 0.95f))).isEmpty())
    }

    @Test
    fun encoderRotation_matchesMedia3() {
        assertEquals(0, RoiPlanner.encoderRotation(1920, 1080, 0))    // landscape stays
        assertEquals(90, RoiPlanner.encoderRotation(1080, 1920, 0))   // portrait turned landscape
        assertEquals(90, RoiPlanner.encoderRotation(1080, 1920, 90))  // phone clip keeps its 90
        assertEquals(270, RoiPlanner.encoderRotation(1080, 1920, 270))
        assertEquals(180, RoiPlanner.encoderRotation(1920, 1080, 180))
        assertEquals(0, RoiPlanner.encoderRotation(1920, 1080, 90))   // parity differs: ignore source
    }

    @Test
    fun rotation90_mapsUprightTopLeftToEncoderBottomLeft() {
        // Encoder frame = upright frame turned 90 degrees counter-clockwise, so
        // the upright top-left corner ends up at the encoder's bottom-left.
        val corner = NormBox(0f, 0f, 0.1f, 0.2f)
        assertBox(NormBox(0f, 0.9f, 0.2f, 1f), RoiPlanner.toEncoderFrame(corner, 90))
        // 270 is the mirror case: upright top-left goes to the encoder's top-right.
        assertBox(NormBox(0.8f, 0f, 1f, 0.1f), RoiPlanner.toEncoderFrame(corner, 270))
        assertBox(NormBox(0.9f, 0.8f, 1f, 1f), RoiPlanner.toEncoderFrame(corner, 180))
        assertBox(corner, RoiPlanner.toEncoderFrame(corner, 0))
    }

    @Test
    fun rects_areEncoderPixels_roiFirst_backgroundLast() {
        val rects = RoiPlanner.rects(listOf(NormBox(0.25f, 0.5f, 0.5f, 1f)), 1280, 720, 0)
        assertEquals(2, rects.size)
        assertEquals(RoiRect(top = 360, left = 320, bottom = 719, right = 639, qpOffset = RoiPlanner.ROI_QP_OFFSET), rects[0])
        assertEquals(RoiRect(0, 0, 719, 1279, RoiPlanner.BACKGROUND_QP_OFFSET), rects[1])
    }

    @Test
    fun paramString_usesTheMediaCodecFormat() {
        val s = RoiPlanner.qpOffsetRectsParam(listOf(RoiRect(10, 20, 30, 40, -6), RoiRect(0, 0, 719, 1279, 3)))
        assertEquals("10,20-30,40=-6;0,0-719,1279=3", s)
    }
}
