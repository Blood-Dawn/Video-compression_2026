package org.svcs.mobile.securitycam

import android.content.Context
import androidx.work.ExistingWorkPolicy
import androidx.work.WorkInfo
import androidx.work.WorkManager
import java.io.File
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import org.svcs.mobile.upload.UploadWorker

/**
 * The Security cam's outgoing clips, in order.
 *
 * The existing uploader is single flight and wipes `pending_uploads` whenever
 * the Library starts a new upload, so the cam gets its own folder
 * (`filesDir/security_cam`) and its own unique work name. Each clip is
 * appended to that chain with APPEND_OR_REPLACE, which keeps clips in
 * recording order and never touches a Library upload.
 *
 * [UploadWorker] deletes a clip once the server has accepted it (or after it
 * gives up), so the folder only ever holds clips that are still waiting.
 *
 * Author: Bloodawn (KheivenD), 2026-11-23 (demo branch, roadmap 13.1).
 */
object ClipQueue {
    const val UNIQUE_WORK_NAME = "security_cam_upload"

    /** Stop recording when the phone has less than this free. */
    const val MIN_FREE_BYTES = 300L * 1024 * 1024

    /** A finalized file smaller than this holds no usable video. */
    const val MIN_CLIP_BYTES = 8L * 1024

    fun clipDir(context: Context): File =
        File(context.filesDir, "security_cam").also { it.mkdirs() }

    /** `cam_20261123_140500.mp4`: sorts in recording order and is unique per second. */
    fun clipName(nowMs: Long): String =
        "cam_" + SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date(nowMs)) + ".mp4"

    fun hasRoom(dir: File, minFree: Long = MIN_FREE_BYTES): Boolean = dir.usableSpace >= minFree

    /** Clips on disk that have not been sent yet, oldest first. */
    fun waitingClips(dir: File): List<File> =
        dir.listFiles { f -> f.isFile && f.name.startsWith("cam_") && f.name.endsWith(".mp4") }
            ?.sortedBy { it.name }
            .orEmpty()

    fun sha256(file: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buf = ByteArray(64 * 1024)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                md.update(buf, 0, n)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    /** Queue one finished clip for upload. Safe to call from a background thread. */
    fun enqueue(context: Context, file: File) {
        val request = UploadWorker.buildRequest(
            localPath = file.absolutePath,
            displayName = file.name,
            sha256 = sha256(file),
            trackingId = "seccam_" + file.nameWithoutExtension,
            quiet = true,
        )
        WorkManager.getInstance(context).enqueueUniqueWork(
            UNIQUE_WORK_NAME, ExistingWorkPolicy.APPEND_OR_REPLACE, request,
        )
    }

    /**
     * Clips left behind by a crash or a reboot, when the upload chain is idle,
     * are queued again. If the chain still has work in it, WorkManager already
     * holds those files and queueing them twice would send each one twice.
     */
    fun requeueLeftovers(context: Context): Int {
        val infos = WorkManager.getInstance(context).getWorkInfosForUniqueWork(UNIQUE_WORK_NAME).get()
        if (infos.any { !it.state.isFinished }) return 0
        val clips = waitingClips(clipDir(context))
        clips.forEach { enqueue(context, it) }
        return clips.size
    }

    /** The states of every clip upload WorkManager still remembers. */
    fun workStates(context: Context): Flow<List<WorkInfo.State>> =
        WorkManager.getInstance(context).getWorkInfosForUniqueWorkFlow(UNIQUE_WORK_NAME)
            .map { list -> list.map { it.state } }
}

/** Counts shown on the Security cam screen. */
data class ClipCounts(val sent: Int = 0, val waiting: Int = 0, val failed: Int = 0) {
    companion object {
        fun from(states: List<WorkInfo.State>): ClipCounts = ClipCounts(
            sent = states.count { it == WorkInfo.State.SUCCEEDED },
            waiting = states.count {
                it == WorkInfo.State.ENQUEUED || it == WorkInfo.State.RUNNING || it == WorkInfo.State.BLOCKED
            },
            failed = states.count { it == WorkInfo.State.FAILED || it == WorkInfo.State.CANCELLED },
        )
    }
}
