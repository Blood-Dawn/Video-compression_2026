package org.svcs.mobile.ui.saved

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
    val smartCompressOnly: Boolean = false,
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

    fun setSmartCompressOnly(v: Boolean) {
        _filters.update { it.copy(smartCompressOnly = v) }
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
        _visible.value = filterAndSortRecords(_all.value, _filters.value, System.currentTimeMillis())
    }
}

/**
 * The SAVED tab's search, filters and sort as one pure function, so it's
 * unit-testable without an Application or a ContentResolver.
 */
internal fun filterAndSortRecords(
    records: List<CompressionRecord>,
    f: LibraryFilters,
    nowMs: Long,
): List<CompressionRecord> {
    val cutoff = when (f.dateFilter) {
        DateFilter.ALL -> Long.MIN_VALUE
        DateFilter.WEEK -> nowMs - TimeUnit.DAYS.toMillis(7)
        DateFilter.MONTH -> nowMs - TimeUnit.DAYS.toMillis(30)
    }
    val minBytes = f.minSizeMb?.let { it * 1_000_000 }
    val maxBytes = f.maxSizeMb?.let { it * 1_000_000 }
    val filtered = records.filter { r ->
        val matchesQuery = f.query.isBlank() ||
            r.outputDisplayName.contains(f.query, ignoreCase = true) ||
            (r.originalName?.contains(f.query, ignoreCase = true) == true)
        matchesQuery &&
            r.timestampMs >= cutoff &&
            (f.codecFilter.isEmpty() || r.codecMime in f.codecFilter) &&
            (f.modeFilter.isEmpty() || r.modeType in f.modeFilter) &&
            // Either fallback counts: the retry path, or the encoder quietly
            // lowering the resolution or codec (EncoderFallback).
            (!f.fallbackOnly || r.usedFallback || r.encoderNote != null) &&
            (!f.smartCompressOnly || r.smartCompressUsed) &&
            (minBytes == null || r.outputSizeBytes >= minBytes) &&
            (maxBytes == null || r.outputSizeBytes <= maxBytes)
    }
    return when (f.sort) {
        LibrarySort.NEWEST -> filtered.sortedByDescending { it.timestampMs }
        LibrarySort.LARGEST -> filtered.sortedByDescending { it.outputSizeBytes }
        LibrarySort.BEST_RATIO -> filtered.sortedByDescending {
            if (it.outputSizeBytes > 0 && it.originalSizeBytes > 0) {
                it.originalSizeBytes.toDouble() / it.outputSizeBytes.toDouble()
            } else {
                0.0
            }
        }
    }
}
