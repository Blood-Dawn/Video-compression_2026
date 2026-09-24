package org.svcs.mobile.compress

import android.media.MediaCodecInfo
import android.media.MediaCodecList
import android.os.Build

/** What one video encoder on this phone can do, as far as SVCS cares. */
data class EncoderInfo(
    val name: String,
    val mime: String,
    val hardware: Boolean,
    /** Android 15 FEATURE_Roi: honors MediaCodec QP-offset rects/maps. */
    val roi: Boolean,
    /** BITRATE_MODE_CQ (constant quality). Unreliable across vendors, which
     *  is why presets drive bitrate; recorded so a quality mode can be
     *  offered where it exists (roadmap section 2). */
    val constantQuality: Boolean,
)

/**
 * Queries MediaCodecList for the H.265 and H.264 encoders on this phone.
 *
 * FEATURE_Roi is OEM-optional and new in Android 15, so the honest default
 * answer is "not supported"; this is how the app finds out per device instead
 * of assuming. Smart Compress uses it to decide between region-of-interest
 * encoding and the whole-clip bitrate fallback, and MORE shows it.
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (Phase 2: ROI capability probe).
 */
object EncoderCapabilities {

    val MIMES = listOf(VideoCodecChoice.H265.mimeType, VideoCodecChoice.H264.mimeType)

    /** Every encoder for [mime], in MediaCodecList's order (hardware first on
     *  most devices, which is also Media3's default preference). */
    fun encodersFor(mime: String): List<EncoderInfo> = runCatching {
        MediaCodecList(MediaCodecList.REGULAR_CODECS).codecInfos
            .filter { it.isEncoder && it.supportedTypes.any { t -> t.equals(mime, ignoreCase = true) } }
            .map { info(it, mime) }
    }.getOrDefault(emptyList())

    /** The encoder with this exact name, as Media3 reports it after creating one. */
    fun byName(name: String, mime: String): EncoderInfo? = encodersFor(mime).firstOrNull { it.name == name }

    fun all(): List<EncoderInfo> = MIMES.flatMap(::encodersFor)

    private fun info(codec: MediaCodecInfo, mime: String): EncoderInfo {
        val caps = codec.getCapabilitiesForType(mime)
        val roi = Build.VERSION.SDK_INT >= 35 &&
            caps.isFeatureSupported(MediaCodecInfo.CodecCapabilities.FEATURE_Roi)
        val cq = runCatching {
            caps.encoderCapabilities.isBitrateModeSupported(
                MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CQ,
            )
        }.getOrDefault(false)
        return EncoderInfo(
            name = codec.name,
            mime = mime,
            hardware = codec.isHardwareAccelerated,
            roi = roi,
            constantQuality = cq,
        )
    }

    /**
     * One plain-language line per format for the MORE screen, e.g.
     * "H.265: region-of-interest encoding supported (c2.qti.hevc.encoder)".
     * Pure, so it is unit-tested.
     */
    fun summary(encoders: List<EncoderInfo>): List<String> = MIMES.map { mime ->
        val label = if (mime == VideoCodecChoice.H265.mimeType) "H.265" else "H.264"
        val forMime = encoders.filter { it.mime == mime }
        val roi = forMime.firstOrNull { it.roi }
        when {
            forMime.isEmpty() -> "$label: no encoder found"
            roi != null -> "$label: region-of-interest encoding supported (${roi.name})"
            else -> {
                val hw = forMime.firstOrNull { it.hardware } ?: forMime.first()
                "$label: no region-of-interest support (${hw.name}); Smart Compress uses the whole-clip mode"
            }
        }
    }
}
