package org.svcs.mobile.ui.server.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import android.content.ContentResolver
import android.net.Uri
import org.svcs.mobile.net.Fetched
import org.svcs.mobile.net.LibraryItem
import org.svcs.mobile.net.StartCompressResult
import org.svcs.mobile.net.SvcsApiClient
import org.svcs.mobile.upload.ServerUploads
import org.svcs.mobile.upload.UploadUpdate

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
    private val api: SvcsApiClient?,
    /**
     * Fall 4.3: phone-to-server uploads run in UploadWorker (WorkManager), not
     * in this ViewModel, so they survive the app being killed. Null in tests
     * that do not exercise uploads. The auto-compress toggle is now read by
     * the worker itself when an upload finishes.
     */
    private val uploads: ServerUploads? = null,
    /** Overridden in tests so a fetch resolves on the test's virtual clock. */
    private val ioDispatcher: CoroutineDispatcher = Dispatchers.IO,
) : ViewModel() {

    /**
     * True once this ViewModel has seen the upload queued or running. A
     * finished upload from days ago is still in WorkManager's history; its
     * result should not reappear every time LIBRARY opens.
     */
    private var sawActiveUpload = false

    private fun applyUpload(u: UploadUpdate) {
        if (u.active) sawActiveUpload = true else if (!sawActiveUpload) return
        _state.update { s ->
            when (u.phase) {
                UploadUpdate.Phase.WAITING -> s.copy(compressing = true,
                    actionMessage = "Upload queued; it starts when the phone is online.")
                UploadUpdate.Phase.RUNNING -> s.copy(compressing = true,
                    actionMessage = if (u.percent >= 0) "Uploading: ${u.percent}%" else "Connecting to the server...")
                UploadUpdate.Phase.SUCCEEDED,
                UploadUpdate.Phase.FAILED,
                UploadUpdate.Phase.CANCELLED -> s.copy(compressing = false, actionMessage = u.message)
            }
        }
        if (!u.active) sawActiveUpload = false
    }

    /** 0.8.0: open the INFO dialog for one clip and fetch its metrics. */
    fun showMeta(item: LibraryItem) {
        val client = api ?: return
        _state.update { it.copy(metaFor = item, meta = null, metaError = null) }
        viewModelScope.launch {
            val r = withContext(ioDispatcher) {
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

    init {
        // Re-attaches to an upload that was already running when the process
        // died: WorkManager reruns it, and its progress shows up here again.
        uploads?.let { u ->
            viewModelScope.launch { u.updates().collect { it?.let(::applyUpload) } }
        }
    }

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
            val setup = withContext(ioDispatcher) { client.setupState() }
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
            val result = withContext(ioDispatcher) {
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
     * R6 Track B, moved onto WorkManager in Fall 4.3: upload a gallery video
     * to the server, resumably.
     *
     * This only makes an app-private copy of the pick (while the picker's read
     * grant is still valid) and queues UploadWorker. The chunk loop, resume
     * from the server's offset, retries, and the auto-compress hand-off all
     * live in UploadEngine now; progress comes back through [applyUpload].
     */
    fun uploadFromPhone(resolver: ContentResolver, uri: Uri) {
        val u = uploads ?: run {
            _state.update { it.copy(actionMessage = "Uploads are not available here.") }
            return
        }
        if (_state.value.compressing) return
        _state.update { it.copy(compressing = true, actionMessage = "Preparing upload...") }
        // Marked before queuing so even a tiny file that finishes before its
        // first progress report still gets its result shown and clears the
        // buttons. Safe: WorkManager only emits when the queue changes, so no
        // stale result from an older upload arrives in between.
        sawActiveUpload = true
        viewModelScope.launch {
            val error = withContext(ioDispatcher) {
                runCatching { u.start(resolver, uri) }
                    .getOrElse { "Upload failed: ${it.message ?: it.javaClass.simpleName}" }
            }
            if (error != null) {
                sawActiveUpload = false
                _state.update { it.copy(compressing = false, actionMessage = error) }
            }
            // Otherwise queued: the worker's updates take over the message.
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
            val result = withContext(ioDispatcher) {
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
