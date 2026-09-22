package org.svcs.mobile.ui

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.svcs.mobile.compress.CompressionHistoryStore
import org.svcs.mobile.compress.CompressionRecord

enum class DateFilter(val label: String) { ALL("All time"), WEEK("This week"), MONTH("This month") }

enum class LibrarySort(val label: String) {
    NEWEST("Newest"),
    BEST_RATIO("Biggest saving"),
    LARGEST("Largest output"),
}

data class LibraryFilters(
    val query: String = "",
    val dateFilter: DateFilter = DateFilter.ALL,
    val codecFilter: Set<String> = emptySet(), // empty = all codecs
    val modeFilter: Set<String> = emptySet(), // empty = all modes
    val fallbackOnly: Boolean = false,
    val minSizeMb: Double? = null,
    val maxSizeMb: Double? = null,
    val sort: LibrarySort = LibrarySort.NEWEST,
)

/**
 * Backs the SAVED tab (Fall roadmap Phase 1.5): search and advanced filters
 * over everything this phone has compressed. All filtering happens in
 * memory over the small JSON-backed history list - see
 * CompressionHistoryStore for why that's the right scale for this data.
 *
 * Author: Bloodawn (KheivenD), 2026-09-22 (Fall roadmap Phase 1.5).
 */
class CompressLibraryViewModel(application: Application) : AndroidViewModel(application) {
    private val store = CompressionHistoryStore(application)

    private val _all = MutableStateFlow<List<CompressionRecord>>(emptyList())

    private val _filters = MutableStateFlow(LibraryFilters())
    val filters: StateFlow<LibraryFilters> = _filters.asStateFlow()

    private val _visible = MutableStateFlow<List<CompressionRecord>>(emptyList())
    val visible: StateFlow<List<CompressionRecord>> = _visible.asStateFlow()

    init {
        reload()
    }

    /** Re-reads history from disk and drops any row whose output file was
     *  deleted outside the app (Files, Photos, a cleanup tool), so the
     *  library never shows a dead entry. */
    fun reload() {
        viewModelScope.launch {
            val records = withContext(Dispatchers.IO) { reconcile(store.readAll()) }
            _all.value = records
            recompute()
        }
    }

    private fun reconcile(records: List<CompressionRecord>): List<CompressionRecord> {
        val resolver = getApplication<Application>().contentResolver
        return records.filter { r ->
            try {
                resolver.openAssetFileDescriptor(Uri.parse(r.outputUri), "r")?.use { true } ?: false
            } catch (_: Exception) {
                false
            }
        }
    }

    fun setQuery(q: String) {
        _filters.update { it.copy(query = q) }
        recompute()
    }

    fun setDateFilter(d: DateFilter) {
        _filters.update { it.copy(dateFilter = d) }
        recompute()
    }

    fun toggleCodec(mime: String) {
        _filters.update {
            val s = it.codecFilter.toMutableSet()
            if (!s.add(mime)) s.remove(mime)
            it.copy(codecFilter = s)
        }
        recompute()
    }

    fun toggleMode(mode: String) {
        _filters.update {
            val s = it.modeFilter.toMutableSet()
            if (!s.add(mode)) s.remove(mode)
            it.copy(modeFilter = s)
        }
        recompute()
    }

    fun setFallbackOnly(v: Boolean) {
        _filters.update { it.copy(fallbackOnly = v) }
        recompute()
    }

    fun setSort(sort: LibrarySort) {
        _filters.update { it.copy(sort = sort) }
        recompute()
    }

    fun delete(record: CompressionRecord) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                try {
                    getApplication<Application>().contentResolver.delete(Uri.parse(record.outputUri), null, null)
                } catch (_: Exception) {
                    // Already gone (e.g. deleted from Files first) is fine.
                }
                store.delete(record.outputUri)
            }
            reload()
        }
    }

    private fun recompute() {
        val f = _filters.value
        val now = System.currentTimeMillis()
        val cutoff = when (f.dateFilter) {
            DateFilter.ALL -> 0L
            DateFilter.WEEK -> now - TimeUnit.DAYS.toMillis(7)
            DateFilter.MONTH -> now - TimeUnit.DAYS.toMillis(30)
        }
        var list = _all.value.filter { r ->
            val matchesQuery = f.query.isBlank() ||
                r.outputDisplayName.contains(f.query, ignoreCase = true) ||
                (r.originalName?.contains(f.query, ignoreCase = true) == true)
            val matchesSize = (f.minSizeMb == null || r.outputSizeBytes >= f.minSizeMb!! * 1_000_000) &&
                (f.maxSizeMb == null || r.outputSizeBytes <= f.maxSizeMb!! * 1_000_000)
            matchesQuery &&
                r.timestampMs >= cutoff &&
                (f.codecFilter.isEmpty() || r.codecMime in f.codecFilter) &&
                (f.modeFilter.isEmpty() || r.modeType in f.modeFilter) &&
                (!f.fallbackOnly || r.usedFallback) &&
                matchesSize
        }
        list = when (f.sort) {
            LibrarySort.NEWEST -> list.sortedByDescending { it.timestampMs }
            LibrarySort.LARGEST -> list.sortedByDescending { it.outputSizeBytes }
            LibrarySort.BEST_RATIO -> list.sortedByDescending {
                if (it.outputSizeBytes > 0 && it.originalSizeBytes > 0) {
                    it.originalSizeBytes.toDouble() / it.outputSizeBytes.toDouble()
                } else {
                    0.0
                }
            }
        }
        _visible.value = list
    }
}
