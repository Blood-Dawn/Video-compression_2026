package org.svcs.mobile.ui.saved

import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Test
import org.svcs.mobile.compress.CompressionRecord

/** Search, filters and sort behind the SAVED tab (Fall roadmap Phase 1.5). */
class LibraryFilterTest {

    private val now = 1_790_000_000_000L
    private fun daysAgo(d: Long) = now - TimeUnit.DAYS.toMillis(d)

    private fun rec(
        name: String,
        original: String? = null,
        inBytes: Long = 10_000_000,
        outBytes: Long = 1_000_000,
        ts: Long = now,
        codec: String = "video/hevc",
        mode: String = "QUALITY",
        fallback: Boolean = false,
        smart: Boolean = false,
    ) = CompressionRecord(
        outputUri = "content://media/$name",
        outputDisplayName = name,
        originalName = original,
        originalSizeBytes = inBytes,
        outputSizeBytes = outBytes,
        durationMs = 10_000,
        timestampMs = ts,
        codecMime = codec,
        modeType = mode,
        presetLabel = "Medium",
        usedFallback = fallback,
        smartCompressUsed = smart,
        smartCompressActivityDetected = if (smart) false else null,
    )

    private fun names(list: List<CompressionRecord>) = list.map { it.outputDisplayName }

    @Test
    fun query_matchesOutputOrOriginalName_caseInsensitive() {
        val all = listOf(rec("SVCS_beach.mp4"), rec("SVCS_x.mp4", original = "Birthday.mov"), rec("SVCS_y.mp4"))
        assertEquals(listOf("SVCS_beach.mp4"), names(filterAndSortRecords(all, LibraryFilters(query = "BEACH"), now)))
        assertEquals(listOf("SVCS_x.mp4"), names(filterAndSortRecords(all, LibraryFilters(query = "birthday"), now)))
    }

    @Test
    fun dateFilter_dropsOlderJobs() {
        val all = listOf(rec("today", ts = now), rec("lastWeek", ts = daysAgo(6)), rec("old", ts = daysAgo(40)))
        assertEquals(listOf("today", "lastWeek"), names(filterAndSortRecords(all, LibraryFilters(dateFilter = DateFilter.WEEK), now)))
        assertEquals(3, filterAndSortRecords(all, LibraryFilters(dateFilter = DateFilter.ALL), now).size)
    }

    @Test
    fun codecModeFallbackAndSmartFilters_combine() {
        val all = listOf(
            rec("a", codec = "video/avc", mode = "TARGET_SIZE", fallback = true),
            rec("b", codec = "video/hevc", mode = "TARGET_SIZE", smart = true),
            rec("c", codec = "video/hevc", mode = "QUALITY"),
        )
        assertEquals(listOf("a"), names(filterAndSortRecords(all, LibraryFilters(codecFilter = setOf("video/avc")), now)))
        assertEquals(setOf("a", "b"), names(filterAndSortRecords(all, LibraryFilters(modeFilter = setOf("TARGET_SIZE")), now)).toSet())
        assertEquals(listOf("a"), names(filterAndSortRecords(all, LibraryFilters(fallbackOnly = true), now)))
        assertEquals(listOf("b"), names(filterAndSortRecords(all, LibraryFilters(smartCompressOnly = true), now)))
        assertEquals(
            listOf("b"),
            names(filterAndSortRecords(all, LibraryFilters(modeFilter = setOf("TARGET_SIZE"), codecFilter = setOf("video/hevc")), now)),
        )
        // An encoder that silently lowered the resolution also counts as a fallback.
        val lowered = rec("d").copy(encoderNote = "The encoder lowered the resolution to 512x288 (asked for 1280x720).")
        assertEquals(setOf("a", "d"), names(filterAndSortRecords(all + lowered, LibraryFilters(fallbackOnly = true), now)).toSet())
    }

    @Test
    fun sizeRange_isInclusiveMegabytes() {
        val all = listOf(rec("small", outBytes = 2_000_000), rec("mid", outBytes = 8_000_000), rec("big", outBytes = 30_000_000))
        val f = LibraryFilters(minSizeMb = 2.0, maxSizeMb = 8.0)
        assertEquals(setOf("small", "mid"), names(filterAndSortRecords(all, f, now)).toSet())
    }

    @Test
    fun sorts_newestLargestAndBestRatio() {
        val all = listOf(
            rec("old-big-10x", inBytes = 100_000_000, outBytes = 10_000_000, ts = daysAgo(2)),
            rec("new-small-2x", inBytes = 4_000_000, outBytes = 2_000_000, ts = now),
            rec("mid-20x", inBytes = 100_000_000, outBytes = 5_000_000, ts = daysAgo(1)),
        )
        assertEquals(listOf("new-small-2x", "mid-20x", "old-big-10x"), names(filterAndSortRecords(all, LibraryFilters(sort = LibrarySort.NEWEST), now)))
        assertEquals(listOf("old-big-10x", "mid-20x", "new-small-2x"), names(filterAndSortRecords(all, LibraryFilters(sort = LibrarySort.LARGEST), now)))
        assertEquals(listOf("mid-20x", "old-big-10x", "new-small-2x"), names(filterAndSortRecords(all, LibraryFilters(sort = LibrarySort.BEST_RATIO), now)))
    }

    @Test
    fun unknownSizes_sinkToTheBottomOfBestRatio() {
        val all = listOf(rec("unknown", inBytes = -1), rec("known", inBytes = 5_000_000, outBytes = 1_000_000))
        assertEquals(listOf("known", "unknown"), names(filterAndSortRecords(all, LibraryFilters(sort = LibrarySort.BEST_RATIO), now)))
    }
}
