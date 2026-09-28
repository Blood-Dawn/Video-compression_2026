package org.svcs.mobile.upload

import java.io.Closeable
import java.io.File
import java.io.RandomAccessFile
import org.svcs.mobile.net.ChunkResult
import org.svcs.mobile.net.Fetched
import org.svcs.mobile.net.StartCompressResult
import org.svcs.mobile.net.SvcsApiClient

/**
 * The resumable chunked-upload loop, with no Android dependencies (Fall 4.3).
 *
 * This is the body of the old `LibraryViewModel.doUpload()`, moved out of
 * `viewModelScope` so [UploadWorker] can drive it from WorkManager and it can
 * be unit-tested on the plain JVM. It follows
 * `mobile/android/UPLOAD-WORKER-DESIGN.md`:
 *
 *  - Every run starts the same way, whether it is the first run, a
 *    `Result.retry()`, or a restart after the process was killed: ask the
 *    server where it is (`/api/upload/status`) and resume from THAT offset.
 *    The locally saved offset is only a hint; the server is always asked.
 *    The 3.4 audit (`docs/security/UPLOAD-PROTOCOL-AUDIT.md`) confirmed that
 *    offset is safe to resume from, including after a hard server kill.
 *  - A 409 on a chunk carries the server's true offset; reseeking to it is
 *    the resume protocol working, not an error.
 *  - A single dropped chunk is retried here (inner retry). Anything bigger
 *    (server unreachable, retries used up) returns [UploadOutcome.RetryLater]
 *    so WorkManager backs off and runs the whole thing again later.
 *  - Anything retrying cannot fix (token rejected, file type refused, not a
 *    video) returns [UploadOutcome.Failed].
 *
 * The server's error strings used below come from
 * `src/gui/routes/ingest_bp.py`; they are the contract this classifies on.
 *
 * Author: Jorge Sanchez, 2026-09-27 (Fall 4.3).
 */
class UploadEngine(
    private val api: SvcsApiClient,
    private val source: UploadSource,
    private val displayName: String,
    /** Whole-file SHA-256 (lowercase hex), computed while making the local copy. */
    private val sha256: String,
    private val checkpoints: CheckpointStore,
    /** Whether a finished upload should auto-start a server compress (MORE toggle). */
    private val autoCompress: suspend () -> Boolean,
    /** Called with 0..100 each time the whole-number percentage changes. */
    private val onProgress: suspend (Int) -> Unit = {},
    /** Polled between chunks so a stopped worker gives the thread back promptly. */
    private val isStopped: () -> Boolean = { false },
    private val maxChunkRetries: Int = 5,
) {

    companion object {
        const val DEFAULT_CHUNK = 1024 * 1024
        const val MIN_CHUNK = 64 * 1024
        const val MAX_CHUNK = 4 * 1024 * 1024
        const val REPAIR_MESSAGE = "The server rejected this device's token. Re-pair under MORE."
    }

    suspend fun run(): UploadOutcome {
        val size = source.size
        if (size <= 0) return UploadOutcome.Failed("The file to upload is empty.")

        // 1. Where are we? Server first, local checkpoint only as a pointer to it.
        val session = when (val s = resolveSession(size)) {
            is Resolved.Ready -> s.session
            is Resolved.Stop -> return s.outcome
        }
        val uploadId = session.uploadId
        val chunk = session.chunkSize
        var offset = session.offset

        // 2. Send the rest.
        var retries = 0
        var lastPct = -1
        suspend fun report() {
            val pct = (offset * 100 / size).toInt()
            if (pct != lastPct) {
                lastPct = pct
                onProgress(pct)
            }
        }
        report()
        while (offset < size) {
            if (isStopped()) return UploadOutcome.RetryLater("Stopped by the system; will resume.")
            val bytes = source.read(offset, chunk)
            if (bytes.isEmpty()) {
                return UploadOutcome.Failed("The local copy ended at byte $offset of $size.")
            }
            when (val r = api.uploadChunk(uploadId, offset, bytes)) {
                is ChunkResult.Ok -> {
                    if (r.offset !in 0..size) {
                        // Accepted, but the reply had no usable offset; ask.
                        (api.uploadStatus(uploadId) as? Fetched.Ok)?.let { offset = it.value.offset }
                            ?: return UploadOutcome.RetryLater("Lost track of the upload offset.")
                        continue
                    }
                    offset = r.offset
                    retries = 0
                    checkpoints.save(UploadCheckpoint(uploadId, offset, chunk))
                    report()
                }
                is ChunkResult.Conflict -> {
                    // The server's real offset. An unreadable one (-1) or one
                    // past the end means we should just ask again.
                    if (r.offset in 0..size) {
                        offset = r.offset
                    } else {
                        retries += 1
                        if (retries > maxChunkRetries) {
                            return UploadOutcome.RetryLater("The server kept disagreeing about the offset.")
                        }
                        (api.uploadStatus(uploadId) as? Fetched.Ok)?.let { offset = it.value.offset }
                    }
                }
                ChunkResult.Unauthorized -> return UploadOutcome.Failed(REPAIR_MESSAGE)
                is ChunkResult.Failed -> {
                    if (ServerErrors.isGone(r.detail)) {
                        // The server no longer has this upload (swept after 48h,
                        // or its data folder was reset). Start clean next run.
                        checkpoints.clear()
                        return UploadOutcome.RetryLater("The server lost this upload; starting over.")
                    }
                    if (ServerErrors.isClientError(r.detail)) {
                        return UploadOutcome.Failed("Upload refused: ${r.detail}")
                    }
                    retries += 1
                    if (retries > maxChunkRetries) {
                        return UploadOutcome.RetryLater("Connection kept dropping: ${r.detail}")
                    }
                    (api.uploadStatus(uploadId) as? Fetched.Ok)?.let { offset = it.value.offset }
                }
            }
        }

        // 3. Finish: the server re-checks size, SHA-256, and that it is a video.
        val fin = when (val f = api.uploadFinish(uploadId, sha256)) {
            is Fetched.Ok -> f.value
            Fetched.Unauthorized -> return UploadOutcome.Failed(REPAIR_MESSAGE)
            is Fetched.Failed -> return finishFailed(f.detail)
        }
        checkpoints.clear()

        // 4. Hand off to the server compressor, same as before 4.3.
        if (!autoCompress()) {
            return UploadOutcome.Succeeded(
                fin.filename, fin.path,
                "Uploaded ${fin.filename}. Auto-compress is off; compress it whenever you are ready.",
            )
        }
        val started = api.startCompress(fin.path, mode = "mode1")
        val message = if (started is StartCompressResult.Started) {
            "Uploaded ${fin.filename}; compressing on the server (mode1)."
        } else {
            "Uploaded ${fin.filename}. Start the compress from the desktop or when the server is free."
        }
        return UploadOutcome.Succeeded(fin.filename, fin.path, message)
    }

    private data class Session(val uploadId: String, val offset: Long, val chunkSize: Int)

    private sealed interface Resolved {
        data class Ready(val session: Session) : Resolved
        data class Stop(val outcome: UploadOutcome) : Resolved
    }

    private suspend fun resolveSession(size: Long): Resolved {
        val saved = checkpoints.load()
        val savedId = saved?.serverUploadId
        if (savedId != null) {
            when (val st = api.uploadStatus(savedId)) {
                is Fetched.Ok -> {
                    val off = st.value.offset
                    if (off in 0..size) {
                        return Resolved.Ready(Session(savedId, off, saved.chunkSize.coerceIn(MIN_CHUNK, MAX_CHUNK)))
                    }
                    checkpoints.clear() // nonsense offset; begin fresh below
                }
                Fetched.Unauthorized -> return Resolved.Stop(UploadOutcome.Failed(REPAIR_MESSAGE))
                is Fetched.Failed -> {
                    if (!ServerErrors.isGone(st.detail)) {
                        return Resolved.Stop(UploadOutcome.RetryLater("Could not reach the server: ${st.detail}"))
                    }
                    checkpoints.clear() // server forgot it; begin fresh below
                }
            }
        }
        return when (val b = api.uploadBegin(displayName, size)) {
            is Fetched.Ok -> {
                val chunk = b.value.chunkHint.coerceIn(MIN_CHUNK, MAX_CHUNK)
                // Save before sending a byte: if we die now, the next run
                // resumes this upload_id instead of leaking a new one.
                checkpoints.save(UploadCheckpoint(b.value.uploadId, b.value.offset, chunk))
                Resolved.Ready(Session(b.value.uploadId, b.value.offset, chunk))
            }
            Fetched.Unauthorized -> Resolved.Stop(UploadOutcome.Failed(REPAIR_MESSAGE))
            is Fetched.Failed -> Resolved.Stop(
                if (ServerErrors.isRejectedAtBegin(b.detail)) {
                    UploadOutcome.Failed("Upload refused: ${b.detail}")
                } else {
                    UploadOutcome.RetryLater("Could not reach the server: ${b.detail}")
                },
            )
        }
    }

    private suspend fun finishFailed(detail: String): UploadOutcome = when {
        ServerErrors.isHashMismatch(detail) -> {
            // The server discarded the part (corruption in transit). Nothing to
            // resume; the next run begins a fresh upload from byte 0.
            checkpoints.clear()
            UploadOutcome.RetryLater("The file was damaged in transit; starting over.")
        }
        ServerErrors.isNotAVideo(detail) -> {
            checkpoints.clear()
            UploadOutcome.Failed("The server could not read that file as a video.")
        }
        ServerErrors.isGone(detail) -> {
            checkpoints.clear()
            UploadOutcome.RetryLater("The server lost this upload; starting over.")
        }
        // "incomplete: have X of Y" or a network error: the next run asks
        // /status and sends whatever is missing.
        else -> UploadOutcome.RetryLater("Finalize failed: $detail")
    }
}

/** How one run ended, in terms [UploadWorker] maps onto a WorkManager Result. */
sealed interface UploadOutcome {
    data class Succeeded(val filename: String, val serverPath: String, val message: String) : UploadOutcome
    /** Transient: WorkManager should back off and run again. */
    data class RetryLater(val reason: String) : UploadOutcome
    /** Permanent: retrying will not help. */
    data class Failed(val message: String) : UploadOutcome
}

/** Random-access reads from the file being uploaded. */
interface UploadSource {
    val size: Long
    /** Up to [max] bytes starting at [offset]; an empty array at end of file. */
    fun read(offset: Long, max: Int): ByteArray
}

/**
 * Reads the app-private copy made at pick time. Random access matters: the old
 * code reopened the picker's stream and skip()ed to the offset on every chunk,
 * which some content providers do not support.
 */
class FileUploadSource(file: File) : UploadSource, Closeable {
    private val raf = RandomAccessFile(file, "r")
    override val size: Long = raf.length()

    override fun read(offset: Long, max: Int): ByteArray {
        if (offset >= size) return ByteArray(0)
        val want = minOf(max.toLong(), size - offset).toInt()
        val buf = ByteArray(want)
        raf.seek(offset)
        var filled = 0
        while (filled < want) {
            val n = raf.read(buf, filled, want - filled)
            if (n <= 0) break
            filled += n
        }
        return if (filled == want) buf else buf.copyOf(filled)
    }

    override fun close() = raf.close()
}

/** What survives process death between runs. WorkManager's own Data cannot
 *  hold this: it is immutable once the request is enqueued. */
data class UploadCheckpoint(
    val serverUploadId: String?,
    val lastKnownOffset: Long,
    val chunkSize: Int = UploadEngine.DEFAULT_CHUNK,
)

interface CheckpointStore {
    suspend fun load(): UploadCheckpoint?
    suspend fun save(checkpoint: UploadCheckpoint)
    suspend fun clear()
}

/**
 * Classifies `Fetched.Failed.detail` strings. `SvcsApi` puts the server's
 * JSON "error" text there when there is one, "HTTP <code>" when there is
 * not, and the exception message for network failures.
 */
internal object ServerErrors {
    private val httpCode = Regex("""^HTTP (\d{3})$""")

    private fun code(detail: String): Int? = httpCode.find(detail.trim())?.groupValues?.get(1)?.toInt()

    /** The server has no record of this upload_id (404). */
    fun isGone(detail: String): Boolean =
        code(detail) == 404 || detail.contains("unknown upload_id", ignoreCase = true)

    /** A 4xx that will be the same next time. 408 and 429 are worth retrying. */
    fun isClientError(detail: String): Boolean =
        code(detail)?.let { it in 400..499 && it != 408 && it != 429 && it != 404 } ?: false

    /** /begin refused the file itself (type or size), not a network problem. */
    fun isRejectedAtBegin(detail: String): Boolean =
        detail.contains("not allowed", ignoreCase = true) ||
            detail.contains("size must be", ignoreCase = true) ||
            isClientError(detail)

    fun isHashMismatch(detail: String): Boolean = detail.contains("sha256 mismatch", ignoreCase = true)

    fun isNotAVideo(detail: String): Boolean = detail.contains("not a decodable video", ignoreCase = true)
}
