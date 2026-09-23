package org.svcs.mobile.detect

import android.content.Context
import android.media.MediaMetadataRetriever
import android.net.Uri

/**
 * Runs a bounded sweep of sampled frames through [ObjectDetector] to answer
 * one coarse question for the Phase 2 "Smart Compress" bitrate fallback:
 * did anything worth caring about happen anywhere in this clip. Not full
 * per-frame detection, and not per-region - see ObjectDetector's doc
 * comment for why that split is the right scope for this increment.
 *
 * Author: Bloodawn (KheivenD), 2026-09-22 (Fall roadmap Phase 2).
 */
object SmartCompressAnalyzer {

    // Roughly a bit more than one sample/sec, bounded on both ends so a
    // three-second clip still gets checked and a ten-minute one doesn't
    // turn a bitrate decision into a multi-minute pre-pass.
    private const val MIN_SAMPLES = 3
    private const val MAX_SAMPLES = 16
    private const val SAMPLE_INTERVAL_MS = 750L

    data class Result(val hasActivity: Boolean, val framesSampled: Int)

    /** Runs synchronously - callers are expected to already be off the main
     *  thread (CompressionWorker's doWork() is). */
    fun analyze(context: Context, uri: Uri, durationMs: Long): Result {
        val span = durationMs.coerceAtLeast(1000L)
        val sampleCount = (span / SAMPLE_INTERVAL_MS).toInt().coerceIn(MIN_SAMPLES, MAX_SAMPLES)

        val retriever = MediaMetadataRetriever()
        var detector: ObjectDetector? = null
        var sampled = 0
        try {
            retriever.setDataSource(context, uri)
            detector = ObjectDetector(context)
            for (i in 0 until sampleCount) {
                val timeMs = (span * i / sampleCount).coerceIn(0, span - 1)
                val frame = try {
                    retriever.getFrameAtTime(timeMs * 1000, MediaMetadataRetriever.OPTION_CLOSEST_SYNC)
                } catch (_: Exception) {
                    null
                } ?: continue
                sampled++
                val hit = detector.detectsAnything(frame)
                frame.recycle()
                if (hit) return Result(hasActivity = true, framesSampled = sampled)
            }
        } catch (_: Exception) {
            // A source the retriever can't pull a single frame from
            // shouldn't block the actual compression job - just skip the
            // bitrate adjustment and encode at the originally requested
            // rate. "Unknown" defaults to "assume activity", never to a
            // silent quality cut nobody asked for.
            return Result(hasActivity = true, framesSampled = sampled)
        } catch (_: LinkageError) {
            // No LiteRT native library for this CPU (e.g. an ABI split
            // installed on the wrong device). Same answer as above: skip the
            // adjustment rather than crash the compression job.
            return Result(hasActivity = true, framesSampled = sampled)
        } finally {
            detector?.close()
            retriever.release()
        }
        return Result(hasActivity = false, framesSampled = sampled)
    }
}
