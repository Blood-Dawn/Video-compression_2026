package org.svcs.mobile.compress

import kotlin.math.ceil
import kotlin.math.floor
import org.svcs.mobile.detect.NormBox

/** A rectangle in encoder-frame pixels with its suggested QP offset. */
data class RoiRect(val top: Int, val left: Int, val bottom: Int, val right: Int, val qpOffset: Int)

/**
 * Plans region-of-interest encoding from Smart Compress detections. Pure, so
 * every step is unit-tested without a device.
 *
 * The idea is the mobile version of the desktop's roi_encoder.py: spend more
 * of the same bitrate where people, vehicles and animals were seen, less on
 * the static rest. It uses Android 15's MediaCodec PARAMETER_KEY_QP_OFFSET_RECTS
 * ("top,left-bottom,right=offset;..." in encoder pixels, offsets -128..127,
 * earlier rects win where they overlap, and the setting lasts for the whole
 * session), which only encoders reporting FEATURE_Roi honor.
 *
 * It is one plan for the whole clip, built from every sampled frame. That
 * suits what this app is for (a fixed camera: the doorway, the driveway), and
 * it is also all a Surface-input encoder can be given reliably, because Media3
 * feeds frames through a Surface and there is no per-frame hook to change the
 * rects in step with the picture.
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (Phase 2: ROI encoding prototype).
 */
object RoiPlanner {
    /** Lower QP (better quality) where activity was seen. Modest on purpose:
     *  the rate control still has to hit the requested bitrate, so this moves
     *  bits around rather than adding them. */
    const val ROI_QP_OFFSET = -6

    /** Slightly higher QP for everything else, listed last so ROI rects win. */
    const val BACKGROUND_QP_OFFSET = 3

    /** Encoders drop rects past their own limit, so keep the list short and
     *  most important first. */
    const val MAX_REGIONS = 6

    /** Padding around each detection, as a fraction of the box size: motion
     *  between samples and the detector's loose fit both cost less than a
     *  sharp face with a blurry shoulder. */
    const val MARGIN = 0.15f

    /** If the regions cover more of the frame than this there is no
     *  "background" worth starving, and ROI encoding would just be noise. */
    const val MAX_COVERAGE = 0.6f

    /**
     * Merge detections from all sampled frames into a few padded regions,
     * largest first. Empty when there was nothing, or so much that a plan
     * would not help (see [MAX_COVERAGE]).
     */
    fun regions(detections: List<NormBox>): List<NormBox> {
        if (detections.isEmpty()) return emptyList()
        var merged = detections.map { pad(it) }.toMutableList()
        var changed = true
        while (changed) {
            changed = false
            outer@ for (i in merged.indices) {
                for (j in i + 1 until merged.size) {
                    if (overlaps(merged[i], merged[j])) {
                        merged[i] = union(merged[i], merged[j])
                        merged.removeAt(j)
                        changed = true
                        break@outer
                    }
                }
            }
        }
        merged = merged.sortedByDescending { it.area }.take(MAX_REGIONS).toMutableList()
        val coverage = merged.sumOf { it.area.toDouble() }
        return if (coverage > MAX_COVERAGE) emptyList() else merged
    }

    /**
     * The rotation Media3 1.5.1 applies before the encoder, so upright boxes
     * can be mapped into the encoder's frame. Mirrors
     * VideoSampleExporter.getSurfaceInfo(): portrait output is encoded as
     * landscape turned 90 degrees, and when the source's own rotation has the
     * same parity it is kept instead. The encoder frame is the upright frame
     * rotated counter-clockwise by this many degrees.
     */
    fun encoderRotation(displayWidth: Int, displayHeight: Int, sourceRotation: Int): Int {
        val base = if (displayWidth < displayHeight) 90 else 0
        val src = Math.floorMod(sourceRotation, 360)
        return if (src % 180 == base % 180) src else base
    }

    /** Map an upright normalized box into the encoder frame (see [encoderRotation]). */
    fun toEncoderFrame(box: NormBox, rotation: Int): NormBox = when (Math.floorMod(rotation, 360)) {
        90 -> NormBox(box.top, 1f - box.right, box.bottom, 1f - box.left)
        180 -> NormBox(1f - box.right, 1f - box.bottom, 1f - box.left, 1f - box.top)
        270 -> NormBox(1f - box.bottom, box.left, 1f - box.top, box.right)
        else -> box
    }

    /**
     * Encoder-pixel rects: each region at [ROI_QP_OFFSET], then the whole
     * frame at [BACKGROUND_QP_OFFSET]. Empty when there are no regions.
     */
    fun rects(regions: List<NormBox>, encoderWidth: Int, encoderHeight: Int, rotation: Int): List<RoiRect> {
        if (regions.isEmpty() || encoderWidth <= 0 || encoderHeight <= 0) return emptyList()
        val out = regions.map { r ->
            val b = toEncoderFrame(r, rotation).clamped()
            RoiRect(
                top = floor(b.top * encoderHeight).toInt(),
                left = floor(b.left * encoderWidth).toInt(),
                bottom = (ceil(b.bottom * encoderHeight).toInt() - 1).coerceAtLeast(0),
                right = (ceil(b.right * encoderWidth).toInt() - 1).coerceAtLeast(0),
                qpOffset = ROI_QP_OFFSET,
            )
        }
        return out + RoiRect(0, 0, encoderHeight - 1, encoderWidth - 1, BACKGROUND_QP_OFFSET)
    }

    /** The PARAMETER_KEY_QP_OFFSET_RECTS value for [rects]. */
    fun qpOffsetRectsParam(rects: List<RoiRect>): String =
        rects.joinToString(";") { "${it.top},${it.left}-${it.bottom},${it.right}=${it.qpOffset}" }

    private fun pad(b: NormBox): NormBox {
        val dx = b.width * MARGIN
        val dy = b.height * MARGIN
        return NormBox(b.left - dx, b.top - dy, b.right + dx, b.bottom + dy).clamped()
    }

    private fun overlaps(a: NormBox, b: NormBox) =
        a.left <= b.right && b.left <= a.right && a.top <= b.bottom && b.top <= a.bottom

    private fun union(a: NormBox, b: NormBox) =
        NormBox(minOf(a.left, b.left), minOf(a.top, b.top), maxOf(a.right, b.right), maxOf(a.bottom, b.bottom))
}
