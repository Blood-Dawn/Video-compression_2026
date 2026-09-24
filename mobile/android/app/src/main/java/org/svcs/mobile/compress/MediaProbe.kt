package org.svcs.mobile.compress

import android.content.Context
import android.media.MediaMetadataRetriever
import android.net.Uri

/**
 * What the compressor needs to know about a source video before encoding.
 * Sizes are as stored in the file; [displayWidth]/[displayHeight] apply the
 * container rotation, which is how the user sees it (and how Media3 hands
 * frames to effects). 0 means "could not be read".
 */
data class VideoProbe(
    val durationMs: Long,
    val hasAudio: Boolean,
    val width: Int,
    val height: Int,
    val rotationDegrees: Int,
) {
    private val sideways get() = Math.floorMod(rotationDegrees, 180) != 0
    val displayWidth: Int get() = if (sideways) height else width
    val displayHeight: Int get() = if (sideways) width else height
    val hasFrameSize: Boolean get() = width > 0 && height > 0

    companion object {
        /**
         * Returned when the file can't be probed at all. Unreadable counts as
         * "has audio": over-reserving 128 kbps for audio is a small miss,
         * under-reserving can push a size-limited job over its limit.
         */
        val UNKNOWN = VideoProbe(durationMs = 0L, hasAudio = true, width = 0, height = 0, rotationDegrees = 0)
    }
}

/**
 * One MediaMetadataRetriever pass over a source URI.
 *
 * Before 2026-09-24 the ViewModel (duration, audio, display size) and the
 * worker (size and rotation for the resolution cap) each opened their own
 * retriever and parsed the same keys slightly differently. Smart Compress's
 * frame sampling still uses its own retriever, since it pulls frames rather
 * than metadata.
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (cleanup: one probe).
 */
object MediaProbe {

    /** Blocking; call off the main thread. Never throws. */
    fun probe(context: Context, uri: Uri): VideoProbe {
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(context, uri)
            fun int(key: Int) = retriever.extractMetadata(key)?.toIntOrNull() ?: 0
            VideoProbe(
                durationMs = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                    ?.toLongOrNull() ?: 0L,
                // "yes" when an audio track exists, null otherwise.
                hasAudio = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_HAS_AUDIO) != null,
                width = int(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH),
                height = int(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT),
                rotationDegrees = int(MediaMetadataRetriever.METADATA_KEY_VIDEO_ROTATION),
            )
        } catch (_: Exception) {
            VideoProbe.UNKNOWN
        } finally {
            retriever.release()
        }
    }
}
