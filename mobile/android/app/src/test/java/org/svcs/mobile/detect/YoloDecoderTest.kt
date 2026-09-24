package org.svcs.mobile.detect

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Synthetic [84, anchors] outputs, laid out the way the exported model emits them. */
class YoloDecoderTest {

    private val classes = intArrayOf(0, 2) // person, car

    private fun output(anchors: Int) = Array(84) { FloatArray(anchors) }

    private fun put(out: Array<FloatArray>, a: Int, cx: Float, cy: Float, w: Float, h: Float, cls: Int, score: Float) {
        out[0][a] = cx; out[1][a] = cy; out[2][a] = w; out[3][a] = h
        out[4 + cls][a] = score
    }

    @Test
    fun normalizedBox_decodesToCornerCoordinates() {
        val out = output(3)
        put(out, 1, cx = 0.5f, cy = 0.5f, w = 0.2f, h = 0.4f, cls = 0, score = 0.9f)
        val d = YoloDecoder.decode(out, classes, threshold = 0.25f, inputSize = 320).single()
        assertEquals(0, d.classId)
        assertEquals(0.4f, d.box.left, 1e-4f)
        assertEquals(0.3f, d.box.top, 1e-4f)
        assertEquals(0.6f, d.box.right, 1e-4f)
        assertEquals(0.7f, d.box.bottom, 1e-4f)
    }

    @Test
    fun pixelBoxes_areNormalizedByInputSize() {
        val out = output(2)
        put(out, 0, cx = 160f, cy = 80f, w = 64f, h = 32f, cls = 2, score = 0.8f)
        val d = YoloDecoder.decode(out, classes, 0.25f, inputSize = 320).single()
        assertEquals(0.4f, d.box.left, 1e-4f)
        assertEquals(0.2f, d.box.top, 1e-4f)
    }

    @Test
    fun belowThresholdAndNonTargetClasses_areIgnored() {
        val out = output(3)
        put(out, 0, 0.5f, 0.5f, 0.2f, 0.2f, cls = 0, score = 0.2f)  // too weak
        put(out, 1, 0.5f, 0.5f, 0.2f, 0.2f, cls = 57, score = 0.99f) // couch: scenery
        assertTrue(YoloDecoder.decode(out, classes, 0.25f, 320).isEmpty())
    }

    @Test
    fun overlappingBoxes_collapseToTheStrongest() {
        val out = output(3)
        put(out, 0, 0.50f, 0.50f, 0.2f, 0.2f, cls = 0, score = 0.6f)
        put(out, 1, 0.51f, 0.50f, 0.2f, 0.2f, cls = 0, score = 0.9f)
        put(out, 2, 0.10f, 0.10f, 0.1f, 0.1f, cls = 2, score = 0.5f)
        val dets = YoloDecoder.decode(out, classes, 0.25f, 320)
        assertEquals(2, dets.size)
        assertEquals(0.9f, dets[0].score, 1e-6f)
    }

    @Test
    fun boxesAreClampedToTheFrame() {
        val out = output(1)
        put(out, 0, 0.02f, 0.98f, 0.2f, 0.2f, cls = 0, score = 0.9f)
        val b = YoloDecoder.decode(out, classes, 0.25f, 320).single().box
        assertEquals(0f, b.left, 0f)
        assertEquals(1f, b.bottom, 0f)
    }
}
