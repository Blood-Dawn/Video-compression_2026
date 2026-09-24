package org.svcs.mobile.compress

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.ContentValues
import android.content.Context
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import androidx.core.app.NotificationCompat
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ForegroundInfo
import androidx.work.OneTimeWorkRequest
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import androidx.media3.common.MediaItem
import androidx.media3.common.MimeTypes
import androidx.media3.effect.Presentation
import androidx.media3.transformer.Composition
import androidx.media3.transformer.DefaultEncoderFactory
import androidx.media3.transformer.EditedMediaItem
import androidx.media3.transformer.Effects
import androidx.media3.transformer.ExportException
import androidx.media3.transformer.ExportResult
import androidx.media3.transformer.ProgressHolder
import androidx.media3.transformer.Transformer
import androidx.media3.transformer.VideoEncoderSettings
import java.io.File
import java.io.IOException
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import org.svcs.mobile.detect.NormBox
import org.svcs.mobile.detect.SmartCompressAnalyzer

/**
 * Standalone (server-free) compression job. Fall roadmap Phase 1.
 *
 * Runs entirely on-device via Media3 Transformer/MediaCodec - no network, no
 * paired desktop server, no FFmpeg. See STANDALONE-COMPRESSOR-ROADMAP.md
 * section 1-2 for why: FFmpeg-on-Android's ecosystem is a dead end post
 * ffmpeg-kit's 2025 retirement, and Android's hardware encoders can't do
 * constant-quality/CRF encoding reliably anyway, so this always drives the
 * encoder with a concrete bitrate (+ optional resolution cap), never a
 * quality dial.
 *
 * Promoted to a `mediaProcessing` foreground service (Android 14+) so the OS
 * doesn't kill a multi-minute encode the moment the app backgrounds - the
 * same shape UPLOAD-WORKER-DESIGN.md (Fall 3.3) designed for the chunked
 * upload, generalized to a different payload. Deliberately never requests
 * REQUEST_IGNORE_BATTERY_OPTIMIZATIONS: that is not an approved Play use
 * case for this category, and a running foreground service is already
 * exempt from Doze while active.
 *
 * Author: Bloodawn (KheivenD), 2026-09-22 (Fall roadmap Phase 1).
 */
class CompressionWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    companion object {
        const val KEY_INPUT_URI = "input_uri"
        const val KEY_OUTPUT_DISPLAY_NAME = "output_display_name"
        const val KEY_TARGET_BITRATE_BPS = "target_bitrate_bps"
        const val KEY_MAX_SHORT_SIDE_PX = "max_short_side_px" // -1 = no cap
        const val KEY_CODEC_MIME = "codec_mime"
        // Phase 1.5 library metadata - not used by the encoder, just carried
        // through so doWork() can record a CompressionRecord on success.
        const val KEY_ORIGINAL_NAME = "original_name"
        const val KEY_DURATION_MS = "duration_ms"
        const val KEY_MODE_TYPE = "mode_type"
        const val KEY_PRESET_LABEL = "preset_label"
        // Fall roadmap Phase 2: opt-in on-device detection pass that
        // decides whether this clip can shed bitrate rather than driving
        // true per-region ROI (that needs raw MediaCodec access Media3
        // Transformer does not expose yet - see SmartCompressAnalyzer).
        const val KEY_REMOVE_AUDIO = "remove_audio"
        /** Progress Data key: "analyzing" while Smart Compress samples
         *  frames, "encoding" once Transformer is running. */
        const val KEY_STAGE = "stage"
        const val STAGE_ANALYZING = "analyzing"
        const val STAGE_ENCODING = "encoding"
        const val KEY_SMART_COMPRESS = "smart_compress"
        const val KEY_SMART_COMPRESS_USED = "smart_compress_used"
        const val KEY_SMART_COMPRESS_ACTIVITY = "smart_compress_activity_detected"
        /** Regions given extra quality through FEATURE_Roi; 0 when region-of-
         *  interest encoding was not used (unsupported phone, nothing found,
         *  or the encoder refused). */
        const val KEY_ROI_REGIONS = "roi_regions"
        /** Applied to the requested bitrate only when Smart Compress found
         *  nothing worth protecting anywhere in the sampled frames. Never
         *  applied upward on a hit - see doWork() for why. */
        private const val NO_ACTIVITY_BITRATE_SCALE = 0.65
        private const val MIN_SMART_COMPRESS_BITRATE_BPS = 300_000

        const val KEY_OUTPUT_URI = "output_uri"
        const val KEY_OUTPUT_BYTES = "output_bytes"
        const val KEY_INPUT_BYTES = "input_bytes"
        const val KEY_ERROR = "error"
        const val KEY_PROGRESS_PERCENT = "progress_percent"
        const val KEY_USED_FALLBACK = "used_fallback"

        const val CHANNEL_ID = "svcs_compress"
        const val NOTIFICATION_ID = 4200
        const val UNIQUE_WORK_NAME = "standalone_compress"

        fun buildRequest(
            inputUri: Uri,
            outputDisplayName: String,
            targetBitrateBps: Int,
            maxShortSidePx: Int?,
            codec: VideoCodecChoice,
            originalName: String? = null,
            durationMs: Long = 0L,
            modeType: String = "QUALITY",
            presetLabel: String = "",
            smartCompress: Boolean = false,
            removeAudio: Boolean = false,
        ): OneTimeWorkRequest {
            val data = Data.Builder()
                .putString(KEY_INPUT_URI, inputUri.toString())
                .putString(KEY_OUTPUT_DISPLAY_NAME, outputDisplayName)
                .putInt(KEY_TARGET_BITRATE_BPS, targetBitrateBps)
                .putInt(KEY_MAX_SHORT_SIDE_PX, maxShortSidePx ?: -1)
                .putString(KEY_CODEC_MIME, codec.mimeType)
                .putString(KEY_ORIGINAL_NAME, originalName)
                .putLong(KEY_DURATION_MS, durationMs)
                .putString(KEY_MODE_TYPE, modeType)
                .putString(KEY_PRESET_LABEL, presetLabel)
                .putBoolean(KEY_SMART_COMPRESS, smartCompress)
                .putBoolean(KEY_REMOVE_AUDIO, removeAudio)
                .build()
            return OneTimeWorkRequest.Builder(CompressionWorker::class.java)
                .setInputData(data)
                .build()
        }
    }

    /** Thrown internally to distinguish a decode-side failure worth retrying at
     *  a safer resolution/codec from any other export error. */
    private class TransformFailure(val exportException: ExportException) :
        Exception(exportException)

    override suspend fun getForegroundInfo(): ForegroundInfo = buildForegroundInfo(0)

    private fun buildForegroundInfo(progressPercent: Int, analyzing: Boolean = false): ForegroundInfo {
        ensureChannel()
        val cancelIntent = WorkManager.getInstance(applicationContext)
            .createCancelPendingIntent(id)
        val notification: Notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setContentTitle("Compressing video")
            .setContentText(
                when {
                    analyzing -> "Checking the video for activity..."
                    progressPercent in 0..100 -> "$progressPercent% done"
                    else -> "Working..."
                },
            )
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setProgress(100, progressPercent.coerceIn(0, 100), progressPercent < 0)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Cancel", cancelIntent)
            .build()
        return if (Build.VERSION.SDK_INT >= 34) {
            ForegroundInfo(
                NOTIFICATION_ID, notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROCESSING,
            )
        } else {
            ForegroundInfo(NOTIFICATION_ID, notification)
        }
    }

    private fun ensureChannel() {
        val mgr = applicationContext.getSystemService(Context.NOTIFICATION_SERVICE)
            as NotificationManager
        if (mgr.getNotificationChannel(CHANNEL_ID) == null) {
            mgr.createNotificationChannel(
                NotificationChannel(
                    CHANNEL_ID, "Video compression",
                    NotificationManager.IMPORTANCE_LOW,
                ).apply { description = "Progress for an on-device compression job." },
            )
        }
    }

    override suspend fun doWork(): Result {
        setForeground(buildForegroundInfo(-1))

        val inputUriStr = inputData.getString(KEY_INPUT_URI)
            ?: return Result.failure(workDataOf(KEY_ERROR to "No input video was provided."))
        val inputUri = Uri.parse(inputUriStr)
        val outputDisplayName = inputData.getString(KEY_OUTPUT_DISPLAY_NAME) ?: "compressed_video"
        var requestedBitrate = inputData.getInt(KEY_TARGET_BITRATE_BPS, 4_000_000)
        val requestedMaxEdge = inputData.getInt(KEY_MAX_SHORT_SIDE_PX, -1).let { if (it <= 0) null else it }
        val requestedCodec = inputData.getString(KEY_CODEC_MIME) ?: MimeTypes.VIDEO_H265
        val durationMs = inputData.getLong(KEY_DURATION_MS, 0L)
        val smartCompressRequested = inputData.getBoolean(KEY_SMART_COMPRESS, false)
        val removeAudio = inputData.getBoolean(KEY_REMOVE_AUDIO, false)

        val inputBytes = sizeOfUri(inputUri)
        val tempOutputFile = File(applicationContext.cacheDir, "compress_${id}.mp4")
        val probe = MediaProbe.probe(applicationContext, inputUri)

        // Fall roadmap Phase 2. Two strategies, picked per phone:
        //  - Region of interest (2026-09-24): when the encoder reports
        //    Android 15's FEATURE_Roi and the sweep finds activity, the same
        //    bitrate is redistributed toward where it was (RoiPlanner,
        //    RoiEncoderFactory). The bitrate itself is left alone.
        //  - Whole clip (everywhere): when the sweep finds nothing at all,
        //    the bitrate is REDUCED, never raised above what the preset
        //    promised, since raising it would break a size-limit job.
        var smartCompressActivityDetected: Boolean? = null
        var roiRequest: RoiRequest? = null
        if (smartCompressRequested) {
            setProgress(workDataOf(KEY_STAGE to STAGE_ANALYZING))
            setForeground(buildForegroundInfo(-1, analyzing = true))
            val roiCapable = EncoderCapabilities.encodersFor(requestedCodec).any { it.roi }
            val analysis = SmartCompressAnalyzer.analyze(
                applicationContext, inputUri, durationMs, collectRegions = roiCapable,
            )
            smartCompressActivityDetected = analysis.hasActivity
            if (!analysis.hasActivity) {
                requestedBitrate = (requestedBitrate * NO_ACTIVITY_BITRATE_SCALE)
                    .toInt()
                    .coerceAtLeast(MIN_SMART_COMPRESS_BITRATE_BPS)
            } else if (roiCapable && probe.hasFrameSize) {
                val regions = RoiPlanner.regions(analysis.boxes)
                if (regions.isNotEmpty()) {
                    val (outW, outH) = scaledFrameSize(
                        probe.width, probe.height, probe.rotationDegrees, requestedMaxEdge,
                    ) ?: (probe.displayWidth to probe.displayHeight)
                    roiRequest = RoiRequest(
                        regions, RoiPlanner.encoderRotation(outW, outH, probe.rotationDegrees),
                    )
                }
            }
        }

        var usedFallback = false
        try {
            val report = try {
                runTransform(
                    inputUri, probe, tempOutputFile, requestedBitrate, requestedMaxEdge,
                    requestedCodec, removeAudio, roiRequest,
                )
            } catch (first: TransformFailure) {
                // Decode-failure fallback (roadmap section 2): a real, documented
                // failure mode is a decoder rejecting an odd resolution/framerate
                // combination outright. Retry once at a conservative, universally
                // supported target rather than surfacing a raw codec error.
                usedFallback = true
                tempOutputFile.delete()
                runTransform(
                    inputUri, probe, tempOutputFile,
                    targetBitrateBps = minOf(requestedBitrate, 2_500_000),
                    maxShortSidePx = 720,
                    codecMime = MimeTypes.VIDEO_H264,
                    removeAudio = removeAudio,
                    roi = null,
                )
            }
            val roiRegions = (report.roi as? RoiOutcome.Applied)?.regions ?: 0

            val outputUri = writeToMediaStore(tempOutputFile, outputDisplayName)
            val outputBytes = tempOutputFile.length()
            tempOutputFile.delete()

            CompressionHistoryStore(applicationContext).append(
                CompressionRecord(
                    outputUri = outputUri.toString(),
                    outputDisplayName = outputDisplayName,
                    originalName = inputData.getString(KEY_ORIGINAL_NAME),
                    originalSizeBytes = inputBytes,
                    outputSizeBytes = outputBytes,
                    durationMs = durationMs,
                    timestampMs = System.currentTimeMillis(),
                    codecMime = requestedCodec,
                    modeType = inputData.getString(KEY_MODE_TYPE) ?: "QUALITY",
                    presetLabel = inputData.getString(KEY_PRESET_LABEL) ?: "",
                    usedFallback = usedFallback,
                    smartCompressUsed = smartCompressRequested,
                    smartCompressActivityDetected = smartCompressActivityDetected,
                    roiRegions = roiRegions,
                    encoderName = report.result.videoEncoderName,
                ),
            )

            return Result.success(
                workDataOf(
                    KEY_OUTPUT_URI to outputUri.toString(),
                    KEY_OUTPUT_BYTES to outputBytes,
                    KEY_INPUT_BYTES to inputBytes,
                    KEY_USED_FALLBACK to usedFallback,
                    KEY_SMART_COMPRESS_USED to smartCompressRequested,
                    KEY_SMART_COMPRESS_ACTIVITY to (smartCompressActivityDetected ?: true),
                    KEY_ROI_REGIONS to roiRegions,
                ),
            )
        } catch (e: TransformFailure) {
            tempOutputFile.delete()
            return Result.failure(
                workDataOf(KEY_ERROR to (e.exportException.message ?: "The encoder rejected this video.")),
            )
        } catch (e: IOException) {
            tempOutputFile.delete()
            return Result.failure(workDataOf(KEY_ERROR to (e.message ?: "Could not read or write the video file.")))
        } catch (e: SecurityException) {
            // The read grant from whoever shared the video is gone (the
            // sharing app's task ended, or it never granted one). Found in
            // the 1.0.0-beta emulator run: this used to escape as an uncaught
            // exception and fail the job with no message at all.
            tempOutputFile.delete()
            return Result.failure(
                workDataOf(
                    KEY_ERROR to "SVCS no longer has permission to read this video. " +
                        "Open it again with Choose a video.",
                ),
            )
        }
    }

    /** Smart Compress's region-of-interest plan for one job. */
    private data class RoiRequest(val regions: List<NormBox>, val rotationDegrees: Int)

    /** What one Transformer pass produced, as Media3 reports it. */
    private data class TransformReport(val result: ExportResult, val roi: RoiOutcome?)

    /** Runs one Transformer pass. Transformer must be built/started/polled from
     *  a thread with a Looper (Media3 requirement), so this hops to Main. */
    private suspend fun runTransform(
        inputUri: Uri,
        probe: VideoProbe,
        outputFile: File,
        targetBitrateBps: Int,
        maxShortSidePx: Int?,
        codecMime: String,
        removeAudio: Boolean,
        roi: RoiRequest?,
    ): TransformReport {
        // See scaledFrameSize() for why this replaced a plain height cap.
        val frameSize = if (maxShortSidePx != null) sourceFrameSize(probe, maxShortSidePx) else null
        return withContext(Dispatchers.Main) {
            suspendCancellableCoroutine<TransformReport> { cont ->
                val defaultFactory = DefaultEncoderFactory.Builder(applicationContext)
                    .setRequestedVideoEncoderSettings(
                        VideoEncoderSettings.Builder()
                            .setBitrate(targetBitrateBps)
                            .build(),
                    )
                    .build()
                val roiFactory = roi?.let { RoiEncoderFactory(defaultFactory, it.regions, it.rotationDegrees) }
                val encoderFactory = roiFactory ?: defaultFactory

                val transformer = Transformer.Builder(applicationContext)
                    .setVideoMimeType(codecMime)
                    .setAudioMimeType(MimeTypes.AUDIO_AAC)
                    .setEncoderFactory(encoderFactory)
                    .addListener(object : Transformer.Listener {
                        override fun onCompleted(composition: Composition, result: ExportResult) {
                            if (cont.isActive) cont.resume(TransformReport(result, roiFactory?.outcome))
                        }

                        override fun onError(
                            composition: Composition,
                            result: ExportResult,
                            exception: ExportException,
                        ) {
                            if (cont.isActive) cont.resumeWithException(TransformFailure(exception))
                        }
                    })
                    .build()

                val mediaItem = MediaItem.fromUri(inputUri)
                // Presentation.createForShortSide() isn't in the media3 1.5.1
                // line this project pins, so the short-side cap is computed
                // here from the source's own width/height/rotation and passed
                // as an exact size. Aspect ratio matches the source, so
                // LAYOUT_SCALE_TO_FIT adds no bars. No effect at all when the
                // source is already at or under the cap: never upscale.
                val videoEffects = when {
                    frameSize is FrameSize.Exact -> listOf(
                        Presentation.createForWidthAndHeight(
                            frameSize.width, frameSize.height, Presentation.LAYOUT_SCALE_TO_FIT,
                        ),
                    )
                    // Geometry unreadable: the old height cap beats leaving a
                    // 4K frame to starve at a size-target bitrate.
                    frameSize is FrameSize.Unknown && maxShortSidePx != null ->
                        listOf(Presentation.createForHeight(maxShortSidePx))
                    else -> emptyList()
                }
                val editedMediaItem = EditedMediaItem.Builder(mediaItem)
                    .setEffects(Effects(emptyList(), videoEffects))
                    .setRemoveAudio(removeAudio)
                    .build()

                transformer.start(editedMediaItem, outputFile.absolutePath)

                // Progress -> WorkManager progress Data, polled at 500ms per the
                // documented Media3 pattern (Transformer must be polled, it does
                // not push progress via the Listener).
                val handler = Handler(Looper.getMainLooper())
                val progressHolder = ProgressHolder()
                val poll = object : Runnable {
                    override fun run() {
                        val state = transformer.getProgress(progressHolder)
                        if (state == Transformer.PROGRESS_STATE_AVAILABLE) {
                            val pct = progressHolder.progress
                            setProgressAsync(workDataOf(KEY_PROGRESS_PERCENT to pct, KEY_STAGE to STAGE_ENCODING))
                            setForegroundAsync(buildForegroundInfo(pct))
                        }
                        if (state != Transformer.PROGRESS_STATE_NOT_STARTED && cont.isActive) {
                            handler.postDelayed(this, 500)
                        }
                    }
                }
                handler.post(poll)

                cont.invokeOnCancellation {
                    handler.removeCallbacks(poll)
                    transformer.cancel()
                }
            }
        }
    }

    /** MediaStore "pending" write: an interrupted job leaves an invisible
     *  pending row instead of a corrupt visible file, per the roadmap. */
    private fun writeToMediaStore(sourceFile: File, displayName: String): Uri {
        val resolver = applicationContext.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Video.Media.DISPLAY_NAME, displayName)
            put(MediaStore.Video.Media.MIME_TYPE, "video/mp4")
            put(MediaStore.Video.Media.RELATIVE_PATH, "Movies/SVCS")
            put(MediaStore.Video.Media.IS_PENDING, 1)
        }
        val collection = MediaStore.Video.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        val itemUri = resolver.insert(collection, values)
            ?: throw IOException("MediaStore refused to create the output entry.")
        resolver.openOutputStream(itemUri)?.use { out ->
            sourceFile.inputStream().use { it.copyTo(out) }
        } ?: throw IOException("Could not open the output file for writing.")
        values.clear()
        values.put(MediaStore.Video.Media.IS_PENDING, 0)
        resolver.update(itemUri, values, null, null)
        return itemUri
    }

    private sealed interface FrameSize {
        data class Exact(val width: Int, val height: Int) : FrameSize
        data object Unknown : FrameSize
    }

    /** null = the source is already within the cap, leave it alone. */
    private fun sourceFrameSize(probe: VideoProbe, maxShortSidePx: Int): FrameSize? {
        if (!probe.hasFrameSize) return FrameSize.Unknown
        return scaledFrameSize(probe.width, probe.height, probe.rotationDegrees, maxShortSidePx)
            ?.let { (sw, sh) -> FrameSize.Exact(sw, sh) }
    }

    private fun sizeOfUri(uri: Uri): Long {
        return try {
            applicationContext.contentResolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1L
        } catch (e: IOException) {
            -1L
        } catch (e: SecurityException) {
            -1L
        }
    }
}
