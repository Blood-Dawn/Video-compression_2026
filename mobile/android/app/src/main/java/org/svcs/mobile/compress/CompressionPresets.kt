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
    // Nitro's real upload ceiling is 500 MB, not the old 25 MB placeholder.
    val DISCORD_NITRO = SizePreset("Discord Nitro (500 MB)", 500L * 1_000_000)
    val WHATSAPP = SizePreset("WhatsApp (16 MB)", 16L * 1_000_000, maxShortSidePx = 720)
    val INSTAGRAM = SizePreset("Instagram (100 MB)", 100L * 1_000_000)
    val TWITTER_X = SizePreset("X / Twitter (512 MB)", 512L * 1_000_000)
    val EMAIL = SizePreset("Email (25 MB)", 25L * 1_000_000, maxShortSidePx = 720)
    val ALL = listOf(DISCORD_FREE, DISCORD_NITRO, WHATSAPP, INSTAGRAM, TWITTER_X, EMAIL)

    /**
     * A user-typed target size, for anything not covered by the presets
     * above. No hardcoded list can keep up with every app's limit (or a
     * limit someone was just told over text), so this is the actual fix
     * for "I need a size that isn't in the list" rather than adding
     * presets forever.
     */
    fun custom(megabytes: Double): SizePreset {
        val mb = megabytes.coerceAtLeast(0.1)
        val label = if (mb == mb.toLong().toDouble()) {
            "Custom (${mb.toLong()} MB)"
        } else {
            "Custom (%.1f MB)".format(mb)
        }
        return SizePreset(label, (mb * 1_000_000).toLong())
    }
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


/** What a target-size job budgets for the AAC track. Pass 0 to
 *  [bitrateForTargetSize] when the output will have no audio (source has
 *  none, or the user removed it) so those bits go to the picture instead. */
const val AUDIO_RESERVE_BPS = 128_000

/**
 * Resolve a [SizePreset] to a concrete video bitrate for a source of the
 * given duration. Reserves a flat 128 kbps for the audio track and leaves a
 * 5% safety margin under the raw target, since Android's hardware encoders
 * are single-pass (no true two-pass VBR - STANDALONE-COMPRESSOR-ROADMAP.md
 * section 2), so a bitrate*duration estimate is the best available control
 * over the final file size, not a guarantee.
 */
fun bitrateForTargetSize(preset: SizePreset, durationMs: Long, audioBps: Int = AUDIO_RESERVE_BPS): Int {
    val durationSec = (durationMs / 1000.0).coerceAtLeast(1.0)
    val totalBps = (preset.maxBytes * 8.0 / durationSec).toInt()
    val videoBps = (totalBps - audioBps).coerceAtLeast(300_000)
    return (videoBps * 0.95).toInt()
}

/**
 * The output frame size for a resolution cap, in display orientation, or
 * null when the source should be left at its own resolution.
 *
 * "1080p"/"720p" name the SHORT side, and phone video is mostly portrait,
 * so capping the literal height (what Phase 1 shipped) shrank a 1080x1920
 * portrait clip to 405x720 on the Low preset instead of 720x1280. It also
 * upscaled sources already smaller than the cap, spending bits on
 * interpolated pixels. This caps the true short side and never upscales.
 *
 * [rotationDegrees] is the container rotation (MediaMetadataRetriever's
 * METADATA_KEY_VIDEO_ROTATION): Media3 hands effects upright frames, so a
 * stored-landscape clip with 90/270 rotation is portrait by the time the
 * Presentation effect sees it. Dimensions are rounded to even numbers,
 * which hardware encoders require.
 */
fun scaledFrameSize(width: Int, height: Int, rotationDegrees: Int, maxShortSidePx: Int?): Pair<Int, Int>? {
    if (maxShortSidePx == null || maxShortSidePx <= 0 || width <= 0 || height <= 0) return null
    val sideways = Math.floorMod(rotationDegrees, 180) != 0
    val displayW = if (sideways) height else width
    val displayH = if (sideways) width else height
    val shortSide = minOf(displayW, displayH)
    if (shortSide <= maxShortSidePx) return null
    val scale = maxShortSidePx.toDouble() / shortSide
    fun even(v: Double): Int = (Math.round(v / 2.0) * 2).toInt().coerceAtLeast(2)
    return even(displayW * scale) to even(displayH * scale)
}
