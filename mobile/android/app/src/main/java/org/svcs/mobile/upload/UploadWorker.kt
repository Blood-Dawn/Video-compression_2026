package org.svcs.mobile.upload

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkRequest
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import java.io.File
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.svcs.mobile.data.TokenStore
import org.svcs.mobile.net.SvcsApi

/**
 * Uploads one video to the paired server so the transfer survives the app
 * being swiped away or killed (Fall 4.3; design in UPLOAD-WORKER-DESIGN.md).
 *
 * WorkManager persists the request itself and runs [doWork] again after
 * process death, a reboot, or a [Result.retry]. Every run looks the same from
 * in here, so every run does the same thing: [UploadEngine] asks the server
 * for its offset and continues from there.
 *
 * The input is an app-private copy made at pick time (see
 * [WorkManagerServerUploads.start]), not the picker's content:// Uri, whose
 * read grant does not survive the Activity going away.
 *
 * Runs as a dataSync foreground service so a long upload on slow Wi-Fi is not
 * cut off at WorkManager's 10-minute limit. Android 15 caps dataSync at six
 * hours per day across the app; one upload will not hit that, but several
 * large ones back to back could.
 *
 * Do not rename or move this class: WorkManager stores the class name in its
 * database, and a queued upload from an older build would fail to start.
 *
 * Author: Jorge Sanchez, 2026-09-27 (Fall 4.3).
 */
class UploadWorker(
    appContext: Context,
    params: WorkerParameters,
) : CoroutineWorker(appContext, params) {

    companion object {
        const val UNIQUE_WORK_NAME = "server_upload"

        const val KEY_LOCAL_PATH = "local_path"
        const val KEY_DISPLAY_NAME = "display_name"
        const val KEY_SHA256 = "sha256"
        const val KEY_TRACKING_ID = "tracking_id"

        /** Progress Data: 0..100. */
        const val KEY_PROGRESS_PERCENT = "progress_percent"
        /** Output Data on success: the line LIBRARY shows. */
        const val KEY_MESSAGE = "message"
        /** Output Data on failure. */
        const val KEY_ERROR = "error"

        const val CHANNEL_ID = "svcs_upload"
        const val NOTIFICATION_ID = 4300
        private const val DONE_NOTIFICATION_ID = 4301
        private const val TAG = "UploadWorker"

        /** Whole runs (not chunk retries) before giving up. With exponential
         *  backoff from 10 s this spans roughly 40 minutes of bad network. */
        const val MAX_RUN_ATTEMPTS = 8

        /** Where pick-time copies live. filesDir, not cacheDir: the OS may
         *  clear the cache while an upload is still waiting to resume. */
        fun stagingDir(context: Context): File = File(context.filesDir, "pending_uploads")

        fun buildRequest(
            localPath: String,
            displayName: String,
            sha256: String,
            trackingId: String,
        ): OneTimeWorkRequest =
            OneTimeWorkRequestBuilder<UploadWorker>()
                .setInputData(
                    workDataOf(
                        KEY_LOCAL_PATH to localPath,
                        KEY_DISPLAY_NAME to displayName,
                        KEY_SHA256 to sha256,
                        KEY_TRACKING_ID to trackingId,
                    ),
                )
                .setConstraints(
                    Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build(),
                )
                .setBackoffCriteria(
                    BackoffPolicy.EXPONENTIAL,
                    WorkRequest.MIN_BACKOFF_MILLIS,
                    TimeUnit.MILLISECONDS,
                )
                .build()
    }

    private val displayName: String
        get() = inputData.getString(KEY_DISPLAY_NAME) ?: "video"

    override suspend fun getForegroundInfo(): ForegroundInfo = buildForegroundInfo(-1)

    override suspend fun doWork(): Result {
        val path = inputData.getString(KEY_LOCAL_PATH)
        val sha = inputData.getString(KEY_SHA256)
        val trackingId = inputData.getString(KEY_TRACKING_ID)
        if (path == null || sha == null || trackingId == null) {
            return fail("The upload request was incomplete.", null, null)
        }
        val file = File(path)
        val checkpoints = DataStoreCheckpointStore(applicationContext, trackingId)
        if (!file.isFile) {
            return fail("The phone's copy of the video is gone; pick it again.", file, checkpoints)
        }

        tryForeground(-1)

        val store = TokenStore(applicationContext)
        val url = store.serverUrl()
        val token = store.token()
        if (url.isNullOrBlank() || token.isNullOrBlank()) {
            return fail("Not paired with a server any more. Pair under MORE, then upload again.", file, checkpoints)
        }

        val outcome = withContext(Dispatchers.IO) {
            FileUploadSource(file).use { source ->
                UploadEngine(
                    api = SvcsApi(url, token),
                    source = source,
                    displayName = displayName,
                    sha256 = sha,
                    checkpoints = checkpoints,
                    autoCompress = { store.autoCompressUpload() },
                    onProgress = { pct ->
                        setProgress(workDataOf(KEY_PROGRESS_PERCENT to pct))
                        tryForeground(pct)
                    },
                    isStopped = { this@UploadWorker.isStopped },
                ).run()
            }
        }

        return when (outcome) {
            is UploadOutcome.Succeeded -> {
                cleanup(file, checkpoints)
                notifyDone("Upload finished", outcome.message)
                Result.success(workDataOf(KEY_MESSAGE to outcome.message))
            }
            is UploadOutcome.Failed -> fail(outcome.message, file, checkpoints)
            is UploadOutcome.RetryLater -> {
                Log.i(TAG, "Run ${runAttemptCount + 1} will retry: ${outcome.reason}")
                if (runAttemptCount + 1 >= MAX_RUN_ATTEMPTS) {
                    fail("Upload gave up after $MAX_RUN_ATTEMPTS tries. ${outcome.reason}", file, checkpoints)
                } else {
                    Result.retry()
                }
            }
        }
    }

    private suspend fun fail(message: String, file: File?, checkpoints: CheckpointStore?): Result {
        if (file != null && checkpoints != null) cleanup(file, checkpoints)
        notifyDone("Upload failed", message)
        return Result.failure(workDataOf(KEY_ERROR to message))
    }

    /** Terminal states only. The server sweeps its own half-finished part
     *  after 48 hours (3.4 audit, UPL-003). */
    private suspend fun cleanup(file: File, checkpoints: CheckpointStore) {
        file.delete()
        checkpoints.clear()
    }

    /**
     * Android 12+ can refuse to start a foreground service while the app is
     * in the background (ForegroundServiceStartNotAllowedException, a subclass
     * of IllegalStateException). The upload still runs; it just has no
     * ongoing notification and is subject to the normal 10-minute limit, so a
     * long one is stopped and resumed on the next run.
     */
    private suspend fun tryForeground(percent: Int) {
        try {
            setForeground(buildForegroundInfo(percent))
        } catch (e: IllegalStateException) {
            Log.w(TAG, "Could not run as a foreground service: ${e.message}")
        }
    }

    private fun buildForegroundInfo(percent: Int): ForegroundInfo {
        ensureChannel()
        val cancel = WorkManager.getInstance(applicationContext).createCancelPendingIntent(id)
        val notification: Notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setContentTitle("Uploading $displayName")
            .setContentText(if (percent in 0..100) "$percent% sent" else "Connecting to the server...")
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setProgress(100, percent.coerceIn(0, 100), percent < 0)
            .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Cancel", cancel)
            .build()
        // minSdk is 29, where the typed constructor is always available.
        return ForegroundInfo(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
    }

    /** The foreground notification disappears when the worker ends, so post a
     *  normal one with the outcome. Skipped quietly without permission. */
    private fun notifyDone(title: String, text: String) {
        if (ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        ensureChannel()
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setSmallIcon(android.R.drawable.stat_sys_upload_done)
            .setAutoCancel(true)
            .build()
        manager().notify(DONE_NOTIFICATION_ID, notification)
    }

    private fun ensureChannel() {
        val mgr = manager()
        if (mgr.getNotificationChannel(CHANNEL_ID) == null) {
            mgr.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Uploads to server", NotificationManager.IMPORTANCE_LOW)
                    .apply { description = "Progress for a video being sent to the paired server." },
            )
        }
    }

    private fun manager(): NotificationManager =
        applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
}
