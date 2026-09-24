package org.svcs.mobile.ui

/**
 * Human-readable sizes and durations, in one place so every screen (the
 * compressor, SAVED, and Server Mode's HOME) prints the same units.
 *
 * Two byte formats on purpose: [humanBytes] is 1024-based and is what file
 * sizes are shown in; [decimalMb] is for platform limits, which are quoted in
 * decimal megabytes ("Discord 10 MB" means 10,000,000 bytes, which
 * humanBytes would print as 9.5 MB).
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (cleanup: humanBytes moved here from
 * net/LibraryModels.kt, decimalMb and the clock format from CompressScreen).
 */

/** "1.66 GB", "12.3 MB", "512 KB", "40 B". */
fun humanBytes(b: Long): String = when {
    b >= 1_073_741_824 -> String.format("%.2f GB", b / 1_073_741_824.0)
    b >= 1_048_576 -> String.format("%.1f MB", b / 1_048_576.0)
    b >= 1024 -> String.format("%.0f KB", b / 1024.0)
    else -> "$b B"
}

/** "10 MB", "8.5 MB": decimal megabytes, whole numbers without a ".0". */
fun decimalMb(bytes: Long): String {
    val mb = bytes / 1_000_000.0
    return if (mb == Math.floor(mb)) "${mb.toLong()} MB" else "%.1f MB".format(mb)
}

/** "m:ss" for a duration in milliseconds; negative durations read as 0:00. */
fun clock(ms: Long): String {
    val t = (ms / 1000).coerceAtLeast(0)
    return "%d:%02d".format(t / 60, t % 60)
}
