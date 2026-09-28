package org.svcs.mobile.upload

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.work.ExistingWorkPolicy
import androidx.work.WorkInfo
import androidx.work.WorkManager
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/** What LIBRARY shows about the one server upload (v1 runs one at a time). */
data class UploadUpdate(
    val phase: Phase,
    val percent: Int = -1,
    /** Success line on SUCCEEDED, the reason on FAILED; null otherwise. */
    val message: String? = null,
) {
    enum class Phase { WAITING, RUNNING, SUCCEEDED, FAILED, CANCELLED }

    val active: Boolean get() = phase == Phase.WAITING || phase == Phase.RUNNING
}

/**
 * The seam LibraryViewModel uses, so the ViewModel stays a plain JVM-testable
 * class and never touches WorkManager or files itself.
 */
interface ServerUploads {
    /**
     * Copy the picked video into app storage and queue the upload. Runs on the
     * caller's thread for the copy, so call it off the main thread. Returns
     * null when queued, or a sentence explaining why not.
     */
    suspend fun start(resolver: ContentResolver, uri: Uri): String?

    /** Live state of the current upload, including one queued before the
     *  process died; null when there has never been one. */
    fun updates(): Flow<UploadUpdate?>
}

/**
 * [ServerUploads] on WorkManager (Fall 4.3).
 *
 * The copy happens here, at pick time, while the picker's read grant is still
 * valid: that grant does not survive the Activity going away, so a worker
 * resuming after process death could not reopen the original Uri. The SHA-256
 * is computed in the same pass, so the worker never re-reads a multi-gigabyte
 * file just to hash it on every retry.
 *
 * Author: Jorge Sanchez, 2026-09-27 (Fall 4.3).
 */
class WorkManagerServerUploads(context: Context) : ServerUploads {

    private val app = context.applicationContext
    private val workManager = WorkManager.getInstance(app)

    private companion object {
        /** Room left on the phone after the copy, so staging an upload never
         *  fills the disk completely. */
        const val FREE_SPACE_MARGIN = 100L * 1024 * 1024

        /** Serializes start(): without this, two overlapping calls can both
         *  see no unfinished work, then both clear staging/checkpoints and
         *  race to enqueue. ExistingWorkPolicy.KEEP only protects the enqueue
         *  itself, not the check-and-clear before it. */
        val startMutex = Mutex()
    }

    override suspend fun start(resolver: ContentResolver, uri: Uri): String? = withContext(Dispatchers.IO) {
        startMutex.withLock {
        val existing = workManager.getWorkInfosForUniqueWork(UploadWorker.UNIQUE_WORK_NAME).get()
        if (existing.any { !it.state.isFinished }) {
            return@withLock "An upload is already in progress. Wait for it to finish, or cancel it from the notification."
        }

        var name = "phone_upload.mp4"
        var size = -1L
        resolver.query(uri, null, null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                val ni = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val si = c.getColumnIndex(OpenableColumns.SIZE)
                if (ni >= 0) c.getString(ni)?.let { name = it }
                if (si >= 0 && !c.isNull(si)) size = c.getLong(si)
            }
        }
        if (size <= 0) return@withLock "Could not read that file's size."

        // Nothing is queued or running, so anything left in staging is from a
        // cancelled or crashed upload. Clear it before adding a new copy.
        val dir = UploadWorker.stagingDir(app)
        dir.listFiles()?.forEach { it.delete() }
        DataStoreCheckpointStore.clearAll(app)
        dir.mkdirs()

        if (dir.usableSpace < size + FREE_SPACE_MARGIN) {
            val needMb = (size + FREE_SPACE_MARGIN) / (1024 * 1024)
            return@withLock "Not enough free space on the phone to stage this upload (needs about $needMb MB)."
        }

        val trackingId = UUID.randomUUID().toString()
        val ext = name.substringAfterLast('.', "mp4").take(8).filter { it.isLetterOrDigit() }.ifEmpty { "mp4" }
        val copy = File(dir, "$trackingId.$ext")
        val md = MessageDigest.getInstance("SHA-256")
        val copied = try {
            resolver.openInputStream(uri)?.use { ins ->
                copy.outputStream().use { out ->
                    val buf = ByteArray(1024 * 1024)
                    var total = 0L
                    while (true) {
                        val n = ins.read(buf)
                        if (n <= 0) break
                        out.write(buf, 0, n)
                        md.update(buf, 0, n)
                        total += n
                    }
                    total
                }
            }
        } catch (e: Exception) {
            copy.delete()
            return@withLock "Could not read that file: ${e.message ?: e.javaClass.simpleName}"
        }
        if (copied == null) {
            copy.delete()
            return@withLock "Could not open that file."
        }
        if (copied <= 0L) {
            copy.delete()
            return@withLock "That file is empty."
        }
        // The worker uploads copy.length(), not the provider's SIZE column,
        // which can be stale for a file that was still being written.
        val sha = md.digest().joinToString("") { "%02x".format(it) }

        workManager.enqueueUniqueWork(
            UploadWorker.UNIQUE_WORK_NAME,
            ExistingWorkPolicy.KEEP,
            UploadWorker.buildRequest(copy.absolutePath, name, sha, trackingId),
        )
        null
        }
    }

    override fun updates(): Flow<UploadUpdate?> =
        workManager.getWorkInfosForUniqueWorkFlow(UploadWorker.UNIQUE_WORK_NAME)
            .map { infos -> (infos.firstOrNull { !it.state.isFinished } ?: infos.lastOrNull())?.toUpdate() }

    private fun WorkInfo.toUpdate(): UploadUpdate = when (state) {
        WorkInfo.State.ENQUEUED, WorkInfo.State.BLOCKED -> UploadUpdate(UploadUpdate.Phase.WAITING)
        WorkInfo.State.RUNNING -> UploadUpdate(
            UploadUpdate.Phase.RUNNING,
            percent = progress.getInt(UploadWorker.KEY_PROGRESS_PERCENT, -1),
        )
        WorkInfo.State.SUCCEEDED -> UploadUpdate(
            UploadUpdate.Phase.SUCCEEDED, 100,
            outputData.getString(UploadWorker.KEY_MESSAGE) ?: "Upload finished.",
        )
        WorkInfo.State.FAILED -> UploadUpdate(
            UploadUpdate.Phase.FAILED,
            message = outputData.getString(UploadWorker.KEY_ERROR) ?: "Upload failed.",
        )
        WorkInfo.State.CANCELLED -> UploadUpdate(UploadUpdate.Phase.CANCELLED, message = "Upload cancelled.")
    }
}
