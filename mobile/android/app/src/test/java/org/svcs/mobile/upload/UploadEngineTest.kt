package org.svcs.mobile.upload

import java.io.ByteArrayOutputStream
import java.io.File
import java.security.MessageDigest
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.svcs.mobile.net.ChunkResult
import org.svcs.mobile.net.FakeSvcsApi
import org.svcs.mobile.net.Fetched
import org.svcs.mobile.net.StartCompressResult
import org.svcs.mobile.net.SvcsApiClient
import org.svcs.mobile.net.UploadBegin
import org.svcs.mobile.net.UploadFinish
import org.svcs.mobile.net.UploadOffset

/**
 * JVM tests for UploadEngine (Fall 4.3).
 *
 * [FakeUploadServer] follows the rules of the real server in
 * src/gui/routes/ingest_bp.py (409 with the true offset, 404 for an unknown
 * upload_id, finish checks size then SHA-256), so these exercise the same
 * resume paths a phone hits. The real server's side of the same protocol is
 * covered by tests/test_chunked_upload.py and scripts/check_upload_resume.py.
 *
 * "Process death" here means: stop one engine run part way, then start a
 * brand new engine with only what would survive (the server's state and the
 * checkpoint store), exactly what UploadWorker does after WorkManager
 * restarts it. The on-device version of this is task 4.4.
 *
 * Author: Jorge Sanchez, 2026-09-27 (Fall 4.3).
 */
class UploadEngineTest {

    private val chunk = 64 * 1024
    private val payload = ByteArray(chunk * 10 + 1234) { (it * 31 + 7).toByte() }
    private val sha = sha256(payload)

    private fun engine(
        server: FakeUploadServer,
        store: CheckpointStore,
        source: UploadSource = BytesSource(payload),
        autoCompress: Boolean = true,
        stopAfterChunks: Int = Int.MAX_VALUE,
        progress: MutableList<Int> = mutableListOf(),
    ): UploadEngine {
        val startCount = server.chunkPosts
        return UploadEngine(
            api = server,
            source = source,
            displayName = "clip.mp4",
            sha256 = sha,
            checkpoints = store,
            autoCompress = { autoCompress },
            onProgress = { progress += it },
            isStopped = { server.chunkPosts - startCount >= stopAfterChunks },
        )
    }

    // ---- the happy path -------------------------------------------------

    @Test
    fun uploadsWholeFileVerifiesAndStartsCompress() = runTest {
        val server = FakeUploadServer(chunkHint = chunk)
        val store = MemoryCheckpoints()
        val progress = mutableListOf<Int>()

        val out = engine(server, store, progress = progress).run()

        assertTrue(out is UploadOutcome.Succeeded)
        assertArrayEquals(payload, server.finishedBytes)
        assertEquals(listOf("/uploads/clip.mp4"), server.compressStarted)
        assertEquals(100, progress.last())
        assertNull("checkpoint is cleared once finished", store.load())
    }

    @Test
    fun autoCompressOffUploadsWithoutStartingACompress() = runTest {
        val server = FakeUploadServer(chunkHint = chunk)
        val out = engine(server, MemoryCheckpoints(), autoCompress = false).run()
        assertTrue((out as UploadOutcome.Succeeded).message.contains("Auto-compress is off"))
        assertTrue(server.compressStarted.isEmpty())
    }

    // ---- surviving process death (the point of 4.3) ---------------------

    @Test
    fun afterBeingKilledANewRunResumesFromTheServerOffsetNotZero() = runTest {
        val server = FakeUploadServer(chunkHint = chunk)
        val store = MemoryCheckpoints()

        val first = engine(server, store, stopAfterChunks = 4).run()
        assertTrue(first is UploadOutcome.RetryLater)
        val serverHad = server.currentOffset()
        assertEquals(4L * chunk, serverHad)

        // A brand-new engine: all that survived is the server and the store.
        server.chunkOffsets.clear()
        val second = engine(server, store).run()

        assertTrue(second is UploadOutcome.Succeeded)
        assertEquals("resumed where the server was", serverHad, server.chunkOffsets.first())
        assertEquals("one upload_id, no restart", 1, server.beginCalls)
        assertArrayEquals(payload, server.finishedBytes)
    }

    @Test
    fun serverOffsetWinsOverAStaleLocalCheckpoint() = runTest {
        val server = FakeUploadServer(chunkHint = chunk)
        val store = MemoryCheckpoints()
        engine(server, store, stopAfterChunks = 6).run()
        // The last local writes were lost (process died between the server's
        // ack and our DataStore write): the hint says byte 0.
        val id = store.load()!!.serverUploadId
        store.save(UploadCheckpoint(id, 0L, chunk))

        server.chunkOffsets.clear()
        val out = engine(server, store).run()

        assertTrue(out is UploadOutcome.Succeeded)
        assertEquals(6L * chunk, server.chunkOffsets.first())
        assertArrayEquals(payload, server.finishedBytes)
    }

    @Test
    fun serverThatForgotTheUploadGetsAFreshOne() = runTest {
        val server = FakeUploadServer(chunkHint = chunk)
        val store = MemoryCheckpoints()
        engine(server, store, stopAfterChunks = 3).run()
        server.forgetAll() // swept after 48h, or its data folder was reset

        val out = engine(server, store).run()

        assertTrue(out is UploadOutcome.Succeeded)
        assertEquals(2, server.beginCalls)
        assertArrayEquals(payload, server.finishedBytes)
    }

    @Test
    fun unreachableServerOnResumeRetriesLaterAndKeepsTheCheckpoint() = runTest {
        val server = FakeUploadServer(chunkHint = chunk)
        val store = MemoryCheckpoints()
        engine(server, store, stopAfterChunks = 2).run()
        server.offline = true

        val out = engine(server, store).run()

        assertTrue(out is UploadOutcome.RetryLater)
        assertTrue("still pointing at the same upload", store.load()?.serverUploadId != null)
    }

    // ---- flaky network during a run -------------------------------------

    @Test
    fun aLostAckDoesNotDuplicateBytes() = runTest {
        // The server wrote the chunk, but the reply never arrived.
        val server = FakeUploadServer(chunkHint = chunk).apply { loseAckOnChunk = 3 }
        val out = engine(server, MemoryCheckpoints()).run()
        assertTrue(out is UploadOutcome.Succeeded)
        assertArrayEquals(payload, server.finishedBytes)
    }

    @Test
    fun droppedChunksAreRetriedInsideTheRun() = runTest {
        val server = FakeUploadServer(chunkHint = chunk).apply { dropNextChunks = 3 }
        val out = engine(server, MemoryCheckpoints()).run()
        assertTrue(out is UploadOutcome.Succeeded)
        assertArrayEquals(payload, server.finishedBytes)
    }

    @Test
    fun tooManyDropsInARowHandsBackToWorkManager() = runTest {
        val server = FakeUploadServer(chunkHint = chunk).apply { dropNextChunks = 100 }
        val store = MemoryCheckpoints()
        val out = engine(server, store).run()
        assertTrue(out is UploadOutcome.RetryLater)
        assertTrue(store.load()?.serverUploadId != null)
    }

    @Test
    fun a409ReseeksToTheServersOffset() = runTest {
        val server = FakeUploadServer(chunkHint = chunk)
        val store = MemoryCheckpoints()
        engine(server, store, stopAfterChunks = 2).run()
        // Make the server run ahead of what the status call will report, so
        // the first chunk of the next run is at a stale offset.
        server.lieInStatusOnce = 0L
        server.chunkOffsets.clear()

        val out = engine(server, store).run()

        assertTrue(out is UploadOutcome.Succeeded)
        assertEquals(listOf(0L, 2L * chunk), server.chunkOffsets.take(2))
        assertArrayEquals(payload, server.finishedBytes)
    }

    // ---- finish ----------------------------------------------------------

    @Test
    fun hashMismatchStartsOverOnTheNextRun() = runTest {
        val server = FakeUploadServer(chunkHint = chunk).apply { corruptOnce = true }
        val store = MemoryCheckpoints()

        val first = engine(server, store).run()
        assertTrue(first is UploadOutcome.RetryLater)
        assertNull("server discarded the part; nothing to resume", store.load())

        val second = engine(server, store).run()
        assertTrue(second is UploadOutcome.Succeeded)
        assertEquals(2, server.beginCalls)
        assertArrayEquals(payload, server.finishedBytes)
    }

    // ---- things retrying cannot fix ------------------------------------

    @Test
    fun rejectedTokenFailsForGood() = runTest {
        val server = FakeUploadServer(chunkHint = chunk).apply { unauthorized = true }
        val out = engine(server, MemoryCheckpoints()).run()
        assertEquals(UploadEngine.REPAIR_MESSAGE, (out as UploadOutcome.Failed).message)
    }

    @Test
    fun refusedFileTypeFailsForGood() = runTest {
        val server = FakeUploadServer(chunkHint = chunk).apply {
            beginError = "File type .mkv not allowed"
        }
        val out = engine(server, MemoryCheckpoints()).run()
        assertTrue((out as UploadOutcome.Failed).message.contains("not allowed"))
    }

    @Test
    fun emptyFileFailsWithoutTalkingToTheServer() = runTest {
        val server = FakeUploadServer(chunkHint = chunk)
        val out = engine(server, MemoryCheckpoints(), source = BytesSource(ByteArray(0))).run()
        assertTrue(out is UploadOutcome.Failed)
        assertEquals(0, server.beginCalls)
    }

    // ---- pieces --------------------------------------------------------

    @Test
    fun fileSourceReadsExactRanges() {
        val f = File.createTempFile("upload", ".bin")
        try {
            f.writeBytes(payload)
            FileUploadSource(f).use { src ->
                assertEquals(payload.size.toLong(), src.size)
                assertArrayEquals(payload.copyOfRange(100, 100 + chunk), src.read(100, chunk))
                val tail = src.read(payload.size - 10L, chunk)
                assertArrayEquals(payload.copyOfRange(payload.size - 10, payload.size), tail)
                assertEquals(0, src.read(payload.size.toLong(), chunk).size)
            }
        } finally {
            f.delete()
        }
    }

    @Test
    fun serverErrorStringsAreClassified() {
        assertTrue(ServerErrors.isGone("HTTP 404"))
        assertTrue(ServerErrors.isGone("unknown upload_id"))
        assertFalse(ServerErrors.isGone("timeout"))
        assertTrue(ServerErrors.isClientError("HTTP 413"))
        assertFalse(ServerErrors.isClientError("HTTP 429"))
        assertFalse(ServerErrors.isClientError("HTTP 503"))
        assertFalse(ServerErrors.isClientError("failed to connect to /192.168.1.5"))
        assertTrue(ServerErrors.isRejectedAtBegin("size must be positive and under 8 GB"))
        assertTrue(ServerErrors.isHashMismatch("sha256 mismatch; upload discarded, start over"))
        assertTrue(ServerErrors.isNotAVideo("not a decodable video; upload discarded"))
    }
}

// ---- test doubles -----------------------------------------------------

private fun sha256(b: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(b).joinToString("") { "%02x".format(it) }

private class BytesSource(private val bytes: ByteArray) : UploadSource {
    override val size: Long get() = bytes.size.toLong()
    override fun read(offset: Long, max: Int): ByteArray {
        if (offset >= bytes.size) return ByteArray(0)
        val end = minOf(bytes.size.toLong(), offset + max).toInt()
        return bytes.copyOfRange(offset.toInt(), end)
    }
}

private class MemoryCheckpoints : CheckpointStore {
    private var cp: UploadCheckpoint? = null
    override suspend fun load() = cp
    override suspend fun save(checkpoint: UploadCheckpoint) { cp = checkpoint }
    override suspend fun clear() { cp = null }
}

/**
 * In-memory stand-in for ingest_bp.py. Everything except the four upload
 * calls and startCompress is delegated to the ordinary [FakeSvcsApi].
 */
private class FakeUploadServer(
    private val chunkHint: Int,
    base: FakeSvcsApi = FakeSvcsApi(),
) : SvcsApiClient by base {

    private class Part(val size: Long) { val bytes = ByteArrayOutputStream() }
    private val parts = LinkedHashMap<String, Part>()
    private var nextId = 1

    var beginCalls = 0
    var chunkPosts = 0
    val chunkOffsets = mutableListOf<Long>()
    val compressStarted = mutableListOf<String>()
    var finishedBytes: ByteArray? = null

    var offline = false
    var unauthorized = false
    var beginError: String? = null
    var dropNextChunks = 0
    var loseAckOnChunk = -1
    var corruptOnce = false
    var lieInStatusOnce: Long? = null

    fun currentOffset(): Long = parts.values.last().bytes.size().toLong()
    fun forgetAll() = parts.clear()

    override fun uploadBegin(name: String, size: Long): Fetched<UploadBegin> {
        if (unauthorized) return Fetched.Unauthorized
        if (offline) return Fetched.Failed("failed to connect")
        beginError?.let { return Fetched.Failed(it) }
        beginCalls += 1
        val id = "up${nextId++}"
        parts[id] = Part(size)
        return Fetched.Ok(UploadBegin(uploadId = id, offset = 0, chunkHint = chunkHint))
    }

    override fun uploadStatus(uploadId: String): Fetched<UploadOffset> {
        if (unauthorized) return Fetched.Unauthorized
        if (offline) return Fetched.Failed("failed to connect")
        lieInStatusOnce?.let { lieInStatusOnce = null; return Fetched.Ok(UploadOffset(it)) }
        val p = parts[uploadId] ?: return Fetched.Failed("HTTP 404")
        return Fetched.Ok(UploadOffset(p.bytes.size().toLong()))
    }

    override fun uploadChunk(uploadId: String, offset: Long, bytes: ByteArray): ChunkResult {
        if (unauthorized) return ChunkResult.Unauthorized
        if (offline) return ChunkResult.Failed("failed to connect")
        chunkPosts += 1
        chunkOffsets += offset
        if (dropNextChunks > 0) {
            dropNextChunks -= 1
            return ChunkResult.Failed("timeout")
        }
        val p = parts[uploadId] ?: return ChunkResult.Failed("HTTP 404")
        val current = p.bytes.size().toLong()
        if (offset != current) return ChunkResult.Conflict(current)
        if (current + bytes.size > p.size) return ChunkResult.Failed("HTTP 413")
        val toWrite = if (corruptOnce && current == 0L) {
            corruptOnce = false
            bytes.copyOf().also { it[0] = (it[0] + 1).toByte() }
        } else {
            bytes
        }
        p.bytes.write(toWrite)
        if (chunkPosts == loseAckOnChunk) return ChunkResult.Failed("timeout")
        return ChunkResult.Ok(current + bytes.size)
    }

    override fun uploadFinish(uploadId: String, sha256: String): Fetched<UploadFinish> {
        if (unauthorized) return Fetched.Unauthorized
        val p = parts[uploadId] ?: return Fetched.Failed("unknown upload_id")
        val have = p.bytes.size().toLong()
        if (have != p.size) return Fetched.Failed("incomplete: have $have of ${p.size} bytes")
        val data = p.bytes.toByteArray()
        if (sha256(data) != sha256) {
            parts.remove(uploadId)
            return Fetched.Failed("sha256 mismatch; upload discarded, start over")
        }
        parts.remove(uploadId)
        finishedBytes = data
        return Fetched.Ok(UploadFinish(ok = true, path = "/uploads/clip.mp4", filename = "clip.mp4"))
    }

    override fun startCompress(path: String, mode: String): StartCompressResult {
        compressStarted += path
        return StartCompressResult.Started
    }
}
