package org.svcs.mobile.compress

/**
 * Spots when the encoder quietly delivered less than was asked for.
 *
 * Media3 falls back on its own when an encoder cannot do the requested format
 * or size: it may switch H.265 to H.264, or encode at a lower resolution (the
 * emulator's software HEVC encoder tops out around 512 px, and some phones
 * cap lower than their cameras record). The job still "succeeds", so before
 * this the user got a smaller, softer video with no idea why. Pure, so it is
 * unit-tested; the worker feeds it what Media3's ExportResult reports.
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (roadmap: tell the user about
 * encoder fallbacks).
 */
object EncoderFallback {

    /** Below this fraction of the requested long side counts as "lowered".
     *  Encoders round to multiples of 2, 8 or 16, which is not a fallback. */
    private const val RESOLUTION_TOLERANCE = 0.9

    /**
     * A sentence for the user, or null when the output matches the request.
     * Sizes are in display orientation for the request; the encoder's own
     * dimensions may be rotated (Media3 encodes portrait as landscape), so
     * only the long and short sides are compared.
     */
    fun describe(
        requestedMime: String,
        actualMime: String?,
        requestedWidth: Int,
        requestedHeight: Int,
        actualWidth: Int,
        actualHeight: Int,
    ): String? {
        val notes = ArrayList<String>()
        if (actualMime != null && !actualMime.equals(requestedMime, ignoreCase = true)) {
            notes += "Saved as ${label(actualMime)} because this phone could not encode ${label(requestedMime)}."
        }
        if (requestedWidth > 0 && requestedHeight > 0 && actualWidth > 0 && actualHeight > 0) {
            val reqLong = maxOf(requestedWidth, requestedHeight)
            val actLong = maxOf(actualWidth, actualHeight)
            val actShort = minOf(actualWidth, actualHeight)
            if (actLong < reqLong * RESOLUTION_TOLERANCE) {
                val portrait = requestedHeight > requestedWidth
                val shown = if (portrait) "${actShort}x$actLong" else "${actLong}x$actShort"
                notes += "The encoder lowered the resolution to $shown " +
                    "(asked for ${requestedWidth}x$requestedHeight)."
            }
        }
        return notes.takeIf { it.isNotEmpty() }?.joinToString(" ")
    }

    private fun label(mime: String) = when (mime.lowercase()) {
        "video/hevc" -> "H.265"
        "video/avc" -> "H.264"
        "video/av01" -> "AV1"
        else -> mime
    }
}
