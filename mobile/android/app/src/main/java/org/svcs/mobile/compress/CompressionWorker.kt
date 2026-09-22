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

    private fun buildForegroundInfo(progressPercent: Int): ForegroundInfo {
        ensureChannel()
        val cancelIntent = WorkManager.getInstance(applicationContext)
            .createCancelPendingIntent(id)
        val notification: Notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setContentTitle("Compressing video")
            .setContentText(
                if (progressPercent in 0..100) "$progressPercent% done" else "Working...",
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
        val requestedBitrate = inputData.getInt(KEY_TARGET_BITRATE_BPS, 4_000_000)
        val requestedMaxEdge = inputData.getInt(KEY_MAX_SHORT_SIDE_PX, -1).let { if (it <= 0) null else it }
        val requestedCodec = inputData.getString(KEY_CODEC_MIME) ?: MimeTypes.VIDEO_H265

        val inputBytes = sizeOfUri(inputUri)
        val tempOutputFile = File(applicationContext.cacheDir, "compress_${id}.mp4")

        var usedFallback = false
        try {
            try {
                runTransform(inputUri, tempOutputFile, requestedBitrate, requestedMaxEdge, requestedCodec)
            } catch (first: TransformFailure) {
                // Decode-failure fallback (roadmap section 2): a real, documented
                // failure mode is a decoder rejecting an odd resolution/framerate
                // combination outright. Retry once at a conservative, universally
                // supported target rather than surfacing a raw codec error.
                usedFallback = true
                tempOutputFile.delete()
                runTransform(
                    inputUri, tempOutputFile,
                    targetBitrateBps = minOf(requestedBitrate, 2_500_000),
                    maxShortSidePx = 720,
                    codecMime = MimeTypes.VIDEO_H264,
                )
            }

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
                    durationMs = inputData.getLong(KEY_DURATION_MS, 0L),
                    timestampMs = System.currentTimeMillis(),
                    codecMime = requestedCodec,
                    modeType = inputData.getString(KEY_MODE_TYPE) ?: "QUALITY",
                    presetLabel = inputData.getString(KEY_PRESET_LABEL) ?: "",
                    usedFallback = usedFallback,
                ),
            )

            return Result.success(
                workDataOf(
                    KEY_OUTPUT_URI to outputUri.toString(),
                    KEY_OUTPUT_BYTES to outputBytes,
                    KEY_INPUT_BYTES to inputBytes,
                    KEY_USED_FALLBACK to usedFallback,
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
        }
    }

    /** Runs one Transformer pass. Transformer must be built/started/polled from
     *  a thread with a Looper (Media3 requirement), so this hops to Main. */
    private suspend fun runTransform(
        inputUri: Uri,
        outputFile: File,
        targetBitrateBps: Int,
        maxShortSidePx: Int?,
        codecMime: String,
    ) {
        withContext(Dispatchers.Main) {
            suspendCancellableCoroutine<Unit> { cont ->
                val encoderFactory = DefaultEncoderFactory.Builder(applicationContext)
                    .setRequestedVideoEncoderSettings(
                        VideoEncoderSettings.Builder()
                            .setBitrate(targetBitrateBps)
                            .build(),
                    )
                    .build()

                val transformer = Transformer.Builder(applicationContext)
                    .setVideoMimeType(codecMime)
                    .setAudioMimeType(MimeTypes.AUDIO_AAC)
                    .setEncoderFactory(encoderFactory)
                    .addListener(object : Transformer.Listener {
                        override fun onCompleted(composition: Composition, result: ExportResult) {
                            if (cont.isActive) cont.resume(Unit)
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
                // Presentation.createForShortSide() does not exist in the
                // media3 1.5.1 line this project pins (it landed in a later
                // release, per androidx/media issue #2478); createForHeight()
                // is the available equivalent. It is height-literal rather
                // than orientation-aware, so a portrait clip's actual short
                // side is its WIDTH, not its height - an acceptable Phase 1
                // approximation (matches what most Android compression
                // tutorials do), not a precise "cap the short side" guarantee.
                val videoEffects = if (maxShortSidePx != null) {
                    listOf(Presentation.createForHeight(maxShortSidePx))
                } else {
                    emptyList()
                }
                val editedMediaItem = EditedMediaItem.Builder(mediaItem)
                    .setEffects(Effects(emptyList(), videoEffects))
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
                            setProgressAsync(workDataOf(KEY_PROGRESS_PERCENT to pct))
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

    private fun sizeOfUri(uri: Uri): Long {
        return try {
            applicationContext.contentResolver.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1L
        } catch (e: IOException) {
            -1L
        }
    }
}
