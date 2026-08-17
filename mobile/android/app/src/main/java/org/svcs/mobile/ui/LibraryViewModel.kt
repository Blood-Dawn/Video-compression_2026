package org.svcs.mobile.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import java.security.MessageDigest
import org.svcs.mobile.net.ChunkResult
import org.svcs.mobile.net.Fetched
import org.svcs.mobile.net.LibraryItem
import org.svcs.mobile.net.StartCompressResult
import org.svcs.mobile.net.SvcsApi

data class LibraryState(
    val items: List<LibraryItem> = emptyList(),
    val total: Int = 0,
    val page: Int = 0,
    val loading: Boolean = false,
    val truncated: Boolean = false,
    val error: String? = null,
    val exhausted: Boolean = false,
    /** "all" | "original" | "compressed" - mirrors the desktop library views. */
    val kind: String = "all",
    /**
     * The folder this listing came from (echoed by the server on page 1).
     * Passed back on every page, thumb, and file request so the desktop
     * moving the server-global "current folder" cannot invalidate this
     * client's session mid-scroll.
     */
    val folderPath: String? = null,
    /** One-line outcome of the last compress action, shown under the header. */
    val actionMessage: String? = null,
    /** 0.8.0: the INFO dialog's target + fetched metrics. */
    val metaFor: LibraryItem? = null,
    val meta: org.svcs.mobile.net.VideoMeta? = null,
    val metaError: String? = null,
    /** True while a compress request is in flight (disables the buttons). */
    val compressing: Boolean = false,
)

/**
 * Paging for the LIBRARY grid (M2.1).
 *
 * Page size 60 matches the server's default. The server clamps to 200, and
 * asking for more than fits on a couple of screens only delays first paint.
 *
 * Author: Bloodawn (KheivenD), 2026-07-19 (M2.1).
 */
class LibraryViewModel(
    private val api: SvcsApi?,
    /** 0.8.0: whether an upload auto-starts a compress (MORE toggle). */
    private val autoCompress: suspend () -> Boolean = { true },
) : ViewModel() {

    /** 0.8.0: open the INFO dialog for one clip and fetch its metrics. */
    fun showMeta(item: LibraryItem) {
        val client = api ?: return
        _state.update { it.copy(metaFor = item, meta = null, metaError = null) }
        viewModelScope.launch {
            val r = withContext(Dispatchers.IO) {
                client.videoMeta(item.path, _state.value.folderPath)
            }
            _state.update { s ->
                when (r) {
                    is Fetched.Ok -> s.copy(meta = r.value)
                    Fetched.Unauthorized -> s.copy(metaError = "Token rejected.")
                    is Fetched.Failed -> s.copy(metaError = r.detail)
                }
            }
        }
    }

    fun dismissMeta() =
        _state.update { it.copy(metaFor = null, meta = null, metaError = null) }

    private companion object { const val PAGE_SIZE = 60 }

    private val _state = MutableStateFlow(LibraryState())
    val state: StateFlow<LibraryState> = _state.asStateFlow()

    /** Guards against the scroll listener firing a second load mid-flight. */
    private var inFlight = false

    fun thumbUrl(item: LibraryItem): String? =
        api?.thumbUrl(item.path, _state.value.folderPath)

    /** Range-enabled playback URL for the in-app player (M4). */
    fun fileUrl(item: LibraryItem): String? =
        api?.fileUrl(item.path, _state.value.folderPath)

    /** The authenticated OkHttp client, for Coil to load thumbnails with.
     *  Coil's default client sends no Authorization header, so without
     *  this every thumbnail request 401s and the grid renders blank tiles
     *  with no error surfaced anywhere. */
    fun httpClient(): okhttp3.OkHttpClient? = api?.httpClient()

    fun loadFirstPageIfNeeded() {
        if (_state.value.items.isEmpty() && !inFlight) fetch(1)
    }

    fun loadNextPage() {
        val s = _state.value
        if (inFlight || s.exhausted || s.error != null) return
        if (s.items.size >= s.total && s.page > 0) return
        fetch(s.page + 1)
    }

    fun refresh() {
        _state.value = LibraryState(kind = _state.value.kind)
        fetch(1)
    }

    /** Switch between all | original | compressed, like the desktop views. */
    fun setKind(kind: String) {
        if (kind == _state.value.kind) return
        _state.value = LibraryState(kind = kind, folderPath = _state.value.folderPath)
        fetch(1)
    }

    /**
     * OUTPUTS shortcut: jump to the server's save folder, where compress jobs
     * (desktop- or phone-started) write. Asks the server for its configured
     * output_dir, then relists there. A fresh compression is one tap away
     * instead of "browse to wherever the save folder happens to be".
     */
    fun showOutputs() {
        val client = api ?: return
        _state.update { it.copy(loading = true, error = null, actionMessage = null) }
        viewModelScope.launch {
            val setup = withContext(Dispatchers.IO) { client.setupState() }
            when (setup) {
                is Fetched.Ok -> {
                    val dir = setup.value.effectiveOutputDir()
                    if (dir.isBlank()) {
                        _state.update {
                            it.copy(loading = false,
                                error = "The server has no save folder configured yet.")
                        }
                    } else {
                        _state.value = LibraryState(folderPath = dir)
                        fetch(1)
                    }
                }
                Fetched.Unauthorized -> _state.update {
                    it.copy(loading = false,
                        error = "The server rejected this device's token. Re-pair under MORE.")
                }
                is Fetched.Failed -> _state.update {
                    it.copy(loading = false,
                        error = "Could not read the server's save folder. ${setup.detail}")
                }
            }
        }
    }

    /**
     * M4: ask the server to compress this clip (server-side path, zero phone
     * bytes). The mode comes from the picker dialog; mode1 (event recording,
     * H.264) stays the highlighted default because its output plays back on
     * any device, while mode2/3 produce smaller AV1 files that need an AV1
     * decoder to preview on the phone.
     */
    fun compress(item: LibraryItem, mode: String = "mode1") {
        val client = api ?: return
        if (_state.value.compressing) return
        _state.update { it.copy(compressing = true, actionMessage = null) }
        viewModelScope.launch {
            val result = withContext(Dispatchers.IO) {
                client.startCompress(item.path, mode = mode)
            }
            _state.update { s ->
                s.copy(
                    compressing = false,
                    actionMessage = when (result) {
                        StartCompressResult.Started ->
                            "Compressing ${item.displayName()} on the server. " +
                                "Watch progress on HOME."
                        StartCompressResult.Busy ->
                            "The server is already compressing something. " +
                                "Try again when it finishes."
                        StartCompressResult.Unauthorized ->
                            "The server rejected this device's token. Re-pair under MORE."
                        is StartCompressResult.Failed ->
                            "Could not start: ${result.detail}"
                    },
                )
            }
        }
    }

    /**
     * R6 Track B: upload a gallery video to the server, resumably.
     *
     * The whole-file sha256 is computed in a first local pass (cheap, local
     * I/O), then chunks stream in CHUNK-sized pieces; a 409 from the server
     * carries the REAL offset after any drop and the loop reseeks - that
     * reseek is the resume protocol working, not an error. Runs in the
     * ViewModel scope, so it survives tab switches; a WorkManager wrapper for
     * process-death survival is the documented next step, and the server
     * protocol already supports it.
     */
    fun uploadFromPhone(resolver: ContentResolver, uri: Uri) {
        val client = api ?: return
        if (_state.value.compressing) return
        _state.update { it.copy(compressing = true, actionMessage = "Preparing upload...") }
        viewModelScope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { doUpload(client, resolver, uri) }
                    .getOrElse { "Upload failed: ${it.message ?: it.javaClass.simpleName}" }
            }
            _state.update { it.copy(compressing = false, actionMessage = result) }
        }
    }

    private suspend fun doUpload(client: SvcsApi, resolver: ContentResolver, uri: Uri): String {
        var name = "phone_upload.mp4"
        var size = -1L
        resolver.query(uri, null, null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                val ni = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val si = c.getColumnIndex(OpenableColumns.SIZE)
                if (ni >= 0) c.getString(ni)?.let { name = it }
                if (si >= 0) size = c.getLong(si)
            }
        }
        if (size <= 0) return "Could not read that file's size."

        // Pass 1: whole-file hash, locally.
        val md = MessageDigest.getInstance("SHA-256")
        resolver.openInputStream(uri)?.use { ins ->
            val buf = ByteArray(1024 * 1024)
            while (true) {
                val n = ins.read(buf)
                if (n <= 0) break
                md.update(buf, 0, n)
            }
        } ?: return "Could not open that file."
        val sha = md.digest().joinToString("") { "%02x".format(it) }

        val begun = client.uploadBegin(name, size)
        if (begun !is Fetched.Ok) return "Upload refused: " +
            ((begun as? Fetched.Failed)?.detail ?: "re-pair under MORE")
        val uploadId = begun.value.uploadId
        val chunk = begun.value.chunkHint.coerceIn(64 * 1024, 4 * 1024 * 1024)

        var offset = 0L
        var retries = 0
        while (offset < size) {
            val sent = resolver.openInputStream(uri)?.use { ins ->
                var skipped = 0L
                while (skipped < offset) {
                    val s = ins.skip(offset - skipped)
                    if (s <= 0) break
                    skipped += s
                }
                val buf = ByteArray(chunk)
                var filled = 0
                while (filled < chunk) {
                    val n = ins.read(buf, filled, chunk - filled)
                    if (n <= 0) break
                    filled += n
                }
                if (filled <= 0) return@use null
                client.uploadChunk(uploadId, offset, buf.copyOf(filled))
            } ?: return "Could not reopen the file at offset $offset."
            when (sent) {
                is ChunkResult.Ok -> {
                    offset = sent.offset
                    retries = 0
                    val pct = (offset * 100 / size).toInt()
                    _state.update { it.copy(actionMessage = "Uploading $name: $pct%") }
                }
                is ChunkResult.Conflict -> offset = sent.offset  // resume point
                ChunkResult.Unauthorized ->
                    return "The server rejected this device's token. Re-pair under MORE."
                is ChunkResult.Failed -> {
                    retries += 1
                    if (retries > 5) return "Upload failed after retries: ${sent.detail}"
                    val st = client.uploadStatus(uploadId)
                    if (st is Fetched.Ok) offset = st.value.offset
                }
            }
        }
        val fin = client.uploadFinish(uploadId, sha)
        if (fin !is Fetched.Ok) return "Finalize failed: " +
            ((fin as? Fetched.Failed)?.detail ?: "re-pair under MORE")
        // 0.8.0: auto-compress is a CHOICE (MORE toggle), not a law. Off means
        // the file just lands in the uploads folder for later.
        if (!autoCompress()) {
            return "Uploaded ${fin.value.filename}. Auto-compress is off; " +
                "compress it whenever you are ready."
        }
        val started = client.startCompress(fin.value.path, mode = "mode1")
        return if (started is StartCompressResult.Started) {
            "Uploaded ${fin.value.filename}; compressing on the server (mode1)."
        } else {
            "Uploaded ${fin.value.filename}. Start the compress from the desktop " +
                "or when the server is free."
        }
    }

    private fun fetch(page: Int) {
        val client = api ?: run {
            _state.update { it.copy(error = "Not paired with a server yet.") }
            return
        }
        inFlight = true
        _state.update { it.copy(loading = true, error = null) }
        viewModelScope.launch {
            val result = withContext(Dispatchers.IO) {
                client.libraryPage(folder = _state.value.folderPath, page = page,
                    pageSize = PAGE_SIZE, kind = _state.value.kind)
            }
            _state.update { s ->
                when (result) {
                    is Fetched.Ok -> {
                        val p = result.value
                        // Append, de-duplicating on path. The listing can shift
                        // under us between pages (the server keeps recording),
                        // so the same clip can arrive twice; a duplicate key in
                        // a LazyGrid crashes rather than merely looking wrong.
                        val seen = s.items.mapTo(HashSet()) { it.path }
                        val merged = s.items + p.videos.filter { seen.add(it.path) }
                        s.copy(
                            items = merged,
                            total = p.total,
                            page = page,
                            truncated = p.truncated,
                            loading = false,
                            error = p.error,
                            exhausted = p.videos.isEmpty() || merged.size >= p.total,
                            // Pin to the folder the server resolved on page 1 so
                            // later pages and media URLs survive the desktop
                            // moving the global folder.
                            folderPath = s.folderPath ?: p.folder.ifBlank { null },
                        )
                    }
                    Fetched.Unauthorized -> s.copy(
                        loading = false,
                        error = "The server rejected this device's token. " +
                            "Re-pair under MORE.",
                    )
                    is Fetched.Failed -> s.copy(
                        loading = false,
                        error = "Could not reach the server. ${result.detail}",
                    )
                }
            }
            inFlight = false
        }
    }
}
