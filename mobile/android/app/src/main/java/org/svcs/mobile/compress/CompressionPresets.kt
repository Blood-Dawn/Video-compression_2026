package org.svcs.mobile.compress

/**
 * Compression presets for the standalone (server-free) compressor.
 *
 * Fall roadmap Phase 1. Deliberately built around bitrate/resolution targets
 * rather than a CRF/quality dial: STANDALONE-COMPRESSOR-ROADMAP.md section 2
 * documents that constant-quality encoding (BITRATE_MODE_CQ) is unreliable or
 * outright unsupported on major Android vendors (Exynos, Google's own AV1
 * encoder), so a preset here always resolves to a concrete bitrate + optional
 * resolution cap, never a quality number handed to the encoder.
 *
 * Author: Bloodawn (KheivenD), 2026-09-22 (Fall roadmap Phase 1).
 */

/** A quality preset: a bitrate ceiling plus an optional resolution cap. */
data class QualityPreset(
    val label: String,
    val targetBitrateBps: Int,
    val maxShortSidePx: Int? = null,
)

object QualityPresets {
    val HIGH = QualityPreset("High", targetBitrateBps = 10_000_000, maxShortSidePx = null)
    val MEDIUM = QualityPreset("Medium", targetBitrateBps = 6_000_000, maxShortSidePx = 1080)
    val LOW = QualityPreset("Low", targetBitrateBps = 3_000_000, maxShortSidePx = 720)
    val ALL = listOf(HIGH, MEDIUM, LOW)
}

/**
 * A "fit under this size" preset, matching the app-specific limits users
 * actually compress for (Compressor by JoshAtticus ships the same idea).
 * Resolved to a bitrate at enqueue time once the source's duration is known
 * (see CompressionWorker.bitrateForTargetSize).
 */
data class SizePreset(
    val label: String,
    val maxBytes: Long,
    val maxShortSidePx: Int? = 1080,
)

object SizePresets {
    val DISCORD_FREE = SizePreset("Discord (10 MB)", 10L * 1_000_000, maxShortSidePx = 720)
    val DISCORD_NITRO = SizePreset("Discord Nitro (25 MB)", 25L * 1_000_000)
    val WHATSAPP = SizePreset("WhatsApp (16 MB)", 16L * 1_000_000, maxShortSidePx = 720)
    val INSTAGRAM = SizePreset("Instagram (100 MB)", 100L * 1_000_000)
    val ALL = listOf(DISCORD_FREE, DISCORD_NITRO, WHATSAPP, INSTAGRAM)
}

/**
 * H.265 is the default per the roadmap (broadest reliable hardware-encode
 * support across vendors); H.264 is the universal compatibility fallback.
 * AV1 is deliberately not offered yet - the roadmap notes documented
 * "broken output" reports on Google's own Pixel AV1 hardware encoder path.
 */
enum class VideoCodecChoice(val label: String, val mimeType: String) {
    H265("H.265 (recommended)", "video/hevc"),
    H264("H.264 (most compatible)", "video/avc"),
}

/** What the UI actually asks the worker to do. */
sealed interface CompressionMode {
    data class Quality(val preset: QualityPreset) : CompressionMode
    data class TargetSize(val preset: SizePreset) : CompressionMode
}


/**
 * Resolve a [SizePreset] to a concrete video bitrate for a source of the
 * given duration. Reserves a flat 128 kbps for the audio track and leaves a
 * 5% safety margin under the raw target, since Android's hardware encoders
 * are single-pass (no true two-pass VBR - STANDALONE-COMPRESSOR-ROADMAP.md
 * section 2), so a bitrate*duration estimate is the best available control
 * over the final file size, not a guarantee.
 */
fun bitrateForTargetSize(preset: SizePreset, durationMs: Long): Int {
    val durationSec = (durationMs / 1000.0).coerceAtLeast(1.0)
    val audioBps = 128_000
    val totalBps = (preset.maxBytes * 8.0 / durationSec).toInt()
    val videoBps = (totalBps - audioBps).coerceAtLeast(300_000)
    return (videoBps * 0.95).toInt()
}
