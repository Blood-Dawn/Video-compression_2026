package org.svcs.mobile.detect

/**
 * A box in normalized frame coordinates (0..1, origin top-left), in the
 * orientation the frame was analyzed in, which for Smart Compress is upright
 * (display) orientation.
 */
data class NormBox(val left: Float, val top: Float, val right: Float, val bottom: Float) {
    val width: Float get() = (right - left).coerceAtLeast(0f)
    val height: Float get() = (bottom - top).coerceAtLeast(0f)
    val area: Float get() = width * height

    fun iou(other: NormBox): Float {
        val ix = (minOf(right, other.right) - maxOf(left, other.left)).coerceAtLeast(0f)
        val iy = (minOf(bottom, other.bottom) - maxOf(top, other.top)).coerceAtLeast(0f)
        val inter = ix * iy
        val union = area + other.area - inter
        return if (union <= 0f) 0f else inter / union
    }

    fun clamped(): NormBox = NormBox(
        left.coerceIn(0f, 1f), top.coerceIn(0f, 1f), right.coerceIn(0f, 1f), bottom.coerceIn(0f, 1f),
    )
}

/** One detected object: where, which COCO class, how confident. */
data class Detection(val box: NormBox, val classId: Int, val score: Float)

/**
 * Turns YOLOv8's raw output into boxes. Pure, so it is unit-tested without
 * LiteRT or a device.
 *
 * The exported model's single output is [1, 4 + classes, anchors]: rows 0..3
 * are the box centre x, centre y, width and height, and the remaining rows are
 * per-class scores (already sigmoid-activated). Ultralytics' TFLite export
 * emits the box normalized to 0..1; some exports use input pixels instead, so
 * coordinates clearly above 1 are divided by the input size.
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (Phase 2: boxes for ROI encoding).
 */
object YoloDecoder {

    fun decode(
        output: Array<FloatArray>,
        targetClasses: IntArray,
        threshold: Float,
        inputSize: Int,
        iouThreshold: Float = 0.5f,
        maxDetections: Int = 20,
    ): List<Detection> {
        if (output.size < 5) return emptyList()
        val anchors = output[0].size
        var maxCoord = 0f
        for (row in 0 until 4) for (a in 0 until anchors) maxCoord = maxOf(maxCoord, output[row][a])
        val scale = if (maxCoord > 2f) 1f / inputSize else 1f

        val candidates = ArrayList<Detection>()
        for (a in 0 until anchors) {
            var best = -1
            var bestScore = threshold
            for (cls in targetClasses) {
                val row = 4 + cls
                if (row >= output.size) continue
                val s = output[row][a]
                if (s > bestScore) {
                    bestScore = s
                    best = cls
                }
            }
            if (best < 0) continue
            val cx = output[0][a] * scale
            val cy = output[1][a] * scale
            val w = output[2][a] * scale
            val h = output[3][a] * scale
            val box = NormBox(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2).clamped()
            if (box.area > 0f) candidates += Detection(box, best, bestScore)
        }
        return nonMaxSuppression(candidates, iouThreshold, maxDetections)
    }

    /** Greedy NMS across classes: a person box and a backpack box that mostly
     *  overlap are one region worth protecting, not two. */
    fun nonMaxSuppression(dets: List<Detection>, iouThreshold: Float, maxDetections: Int): List<Detection> {
        val kept = ArrayList<Detection>()
        for (d in dets.sortedByDescending { it.score }) {
            if (kept.none { it.box.iou(d.box) > iouThreshold }) kept += d
            if (kept.size >= maxDetections) break
        }
        return kept
    }
}
