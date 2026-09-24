package org.svcs.mobile.compress

import android.media.MediaCodec
import android.os.Build
import android.os.Bundle
import androidx.media3.common.Format
import androidx.media3.transformer.Codec
import org.svcs.mobile.detect.NormBox

/** What happened when a job asked for region-of-interest encoding. */
sealed interface RoiOutcome {
    /** QP-offset rects were handed to the encoder. */
    data class Applied(val encoderName: String, val regions: Int, val param: String) : RoiOutcome
    /** The encoder Media3 picked does not report FEATURE_Roi. */
    data class NotSupported(val encoderName: String) : RoiOutcome
    /** Supported on paper, but the parameters could not be set. */
    data class Failed(val reason: String) : RoiOutcome
}

/**
 * Wraps Media3's encoder factory to give the video encoder a region-of-interest
 * plan (RoiPlanner) right after it starts.
 *
 * Why a wrapper, and why reflection: Media3 1.5.1 builds and starts the
 * MediaCodec inside DefaultCodec, whose MediaCodec field is private, and has
 * no API for extra codec parameters. PARAMETER_KEY_QP_OFFSET_RECTS is a
 * MediaCodec.setParameters() key that "lasts throughout the encoding session",
 * so setting it once after start, before the first frame arrives, covers the
 * whole clip. The field is found by type rather than by name so R8 renaming
 * cannot break it. Anything unexpected (a Media3 update changes DefaultCodec,
 * the vendor rejects the string) ends in [RoiOutcome.Failed] and a normal
 * encode at the requested bitrate: this only ever redistributes bits, it is
 * never needed for the job to succeed.
 *
 * Not verified on a device with FEATURE_Roi yet: the development machines
 * have none (see STANDALONE-COMPRESSOR-ROADMAP.md, Phase 2 progress).
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (Phase 2: ROI encoding prototype).
 */
class RoiEncoderFactory(
    private val delegate: Codec.EncoderFactory,
    private val regions: List<NormBox>,
    /** Rotation from RoiPlanner.encoderRotation for this source and output. */
    private val rotationDegrees: Int,
) : Codec.EncoderFactory {

    @Volatile
    var outcome: RoiOutcome? = null
        private set

    override fun createForAudioEncoding(format: Format): Codec = delegate.createForAudioEncoding(format)

    override fun createForVideoEncoding(format: Format): Codec {
        val codec = delegate.createForVideoEncoding(format)
        outcome = try {
            apply(codec)
        } catch (t: Throwable) {
            RoiOutcome.Failed(t.javaClass.simpleName + ": " + (t.message ?: ""))
        }
        return codec
    }

    override fun audioNeedsEncoding(): Boolean = delegate.audioNeedsEncoding()

    override fun videoNeedsEncoding(): Boolean = delegate.videoNeedsEncoding()

    private fun apply(codec: Codec): RoiOutcome {
        val config = codec.configurationFormat
        val mime = config.sampleMimeType ?: return RoiOutcome.Failed("encoder has no MIME type")
        val info = EncoderCapabilities.byName(codec.name, mime)
        if (info == null || !info.roi || Build.VERSION.SDK_INT < 35) {
            return RoiOutcome.NotSupported(codec.name)
        }
        val rects = RoiPlanner.rects(regions, config.width, config.height, rotationDegrees)
        if (rects.isEmpty()) return RoiOutcome.Failed("no regions to encode")
        val param = RoiPlanner.qpOffsetRectsParam(rects)
        val mediaCodec = findMediaCodec(codec) ?: return RoiOutcome.Failed("MediaCodec not reachable")
        mediaCodec.setParameters(Bundle().apply { putString(MediaCodec.PARAMETER_KEY_QP_OFFSET_RECTS, param) })
        return RoiOutcome.Applied(codec.name, regions = rects.size - 1, param = param)
    }

    private fun findMediaCodec(codec: Codec): MediaCodec? {
        var cls: Class<*>? = codec.javaClass
        while (cls != null) {
            for (field in cls.declaredFields) {
                if (MediaCodec::class.java.isAssignableFrom(field.type)) {
                    field.isAccessible = true
                    return field.get(codec) as? MediaCodec
                }
            }
            cls = cls.superclass
        }
        return null
    }
}
