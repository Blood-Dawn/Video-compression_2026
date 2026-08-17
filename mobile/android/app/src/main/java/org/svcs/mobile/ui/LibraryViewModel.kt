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
class LibraryViewModel(private val api: SvcsApi?) : ViewModel() {

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
        _state.value = LibraryState(kind = kind)
        fetch(1)
    }

    /**
     * M4: ask the server to compress this clip (server-side path, zero phone
     * bytes). mode1 is the deliberate default: H.264 output that any device
     * (including this phone) can play back, which matters more on mobile than
     * mode2/3's smaller AV1 files. The desktop keeps the full mode picker.
     */
    fun compress(item: LibraryItem) {
        val client = api ?: return
        if (_state.value.compressing) return
        _state.update { it.copy(compressing = true, actionMessage = null) }
        viewModelScope.launch {
            val result = withContext(Dispatchers.IO) {
                client.startCompress(item.path, mode = "mode1")
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
