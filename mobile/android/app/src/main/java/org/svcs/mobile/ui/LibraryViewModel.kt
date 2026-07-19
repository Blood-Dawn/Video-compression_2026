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
import org.svcs.mobile.net.SvcsApi

data class LibraryState(
    val items: List<LibraryItem> = emptyList(),
    val total: Int = 0,
    val page: Int = 0,
    val loading: Boolean = false,
    val truncated: Boolean = false,
    val error: String? = null,
    val exhausted: Boolean = false,
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

    fun thumbUrl(item: LibraryItem): String? = api?.thumbUrl(item.path)

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
        _state.value = LibraryState()
        fetch(1)
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
                client.libraryPage(folder = null, page = page, pageSize = PAGE_SIZE)
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
