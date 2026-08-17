package org.svcs.mobile.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Payload shapes for the read-only M2 surfaces.
 *
 * Every field here is pinned server-side by tests/test_mobile_client_contract.py
 * and tests/test_library_cache.py. A rename on the server must fail in the
 * Python suite, not on a user's phone where it cannot be hot-fixed.
 *
 * All fields carry defaults and unknown keys are ignored, so a NEWER server can
 * add fields without breaking an installed app.
 *
 * Author: Bloodawn (KheivenD), 2026-07-19 (M2).
 */

@Serializable
data class LibraryPage(
    val folder: String = "",
    val exists: Boolean = true,
    val total: Int = 0,
    val page: Int = 1,
    @SerialName("page_size") val pageSize: Int = 60,
    val truncated: Boolean = false,
    val extensions: List<String> = emptyList(),
    val videos: List<LibraryItem> = emptyList(),
    val error: String? = null,
)

@Serializable
data class LibraryItem(
    val name: String = "",
    val path: String = "",
    val size: Long = 0,
    val mtime: Double = 0.0,
    /** "original" or "compressed". */
    val kind: String = "original",
    /** Set on compressed items: the original this came from. */
    val source: String? = null,
    /** Set on originals: whether a verified compressed copy exists on disk. */
    val compressed: Boolean = false,
) {
    val isCompressed: Boolean get() = kind == "compressed"

    /** "3.6 MB". Surveillance sizes span KB to GB, so pick the unit. */
    fun humanSize(): String {
        val b = size.toDouble()
        return when {
            b >= 1_073_741_824 -> String.format("%.2f GB", b / 1_073_741_824)
            b >= 1_048_576 -> String.format("%.1f MB", b / 1_048_576)
            b >= 1024 -> String.format("%.0f KB", b / 1024)
            else -> "$size B"
        }
    }

    /** Leaf name. The server sends a relative subpath for nested files. */
    fun displayName(): String = name.substringAfterLast('/')

    /** Parent folder, or null at the top level. Usually the camera id. */
    fun folderLabel(): String? =
        name.substringBeforeLast('/', "").takeIf { it.isNotEmpty() }
}

@Serializable
data class SystemMetrics(
    val available: Boolean = false,
    @SerialName("cpu_pct") val cpuPct: Double? = null,
    @SerialName("ram_pct") val ramPct: Double? = null,
    @SerialName("ram_used_mb") val ramUsedMb: Long? = null,
    @SerialName("ram_total_mb") val ramTotalMb: Long? = null,
    @SerialName("battery_pct") val batteryPct: Double? = null,
    @SerialName("battery_mins_left") val batteryMinsLeft: Double? = null,
    @SerialName("battery_plugged") val batteryPlugged: Boolean? = null,
    @SerialName("estimated_hrs") val estimatedHrs: Double? = null,
    @SerialName("storage_mb_hr") val storageMbHr: Double? = null,
)

@Serializable
data class StorageStats(
    val available: Boolean = false,
    @SerialName("total_mb") val totalMb: Double = 0.0,
    @SerialName("total_segments") val totalSegments: Int = 0,
    @SerialName("total_duration_hours") val totalDurationHours: Double = 0.0,
    @SerialName("segments_with_targets") val segmentsWithTargets: Int = 0,
    @SerialName("total_roi_detections") val totalRoiDetections: Long = 0,
) {
    fun humanTotal(): String =
        if (totalMb >= 1024) String.format("%.2f GB", totalMb / 1024)
        else String.format("%.0f MB", totalMb)
}

@Serializable
data class PipelineStatus(
    val running: Boolean = false,
    @SerialName("frame_count") val frameCount: Long = 0,
    @SerialName("segment_count") val segmentCount: Long = 0,
    @SerialName("total_frames") val totalFrames: Long = 0,
    @SerialName("progress_pct") val progressPct: Double? = null,
    @SerialName("eta_seconds") val etaSeconds: Double? = null,
    val fps: Double? = null,
    @SerialName("elapsed_seconds") val elapsedSeconds: Double? = null,
    val error: String? = null,
)

/** Result of a fetch, in the terms the UI renders. Never an exception. */
sealed interface Fetched<out T> {
    data class Ok<T>(val value: T) : Fetched<T>
    data object Unauthorized : Fetched<Nothing>
    data class Failed(val detail: String) : Fetched<Nothing>
}

@Serializable
data class Savings(
    val measured: MeasuredSavings = MeasuredSavings(),
    val recorded: RecordedTotals = RecordedTotals(),
)

/**
 * Real source-versus-output bytes, for files compressed from an existing file.
 * This is the only place a compression ratio may honestly be shown.
 */
@Serializable
data class MeasuredSavings(
    val files: Int = 0,
    @SerialName("source_bytes") val sourceBytes: Long = 0,
    @SerialName("output_bytes") val outputBytes: Long = 0,
    @SerialName("saved_bytes") val savedBytes: Long = 0,
    val ratio: Double? = null,
    @SerialName("saved_pct") val savedPct: Double? = null,
)

/**
 * What the recording pipeline has written. Carries NO ratio on purpose: a live
 * capture has no source file, so any "x smaller" would need an invented
 * denominator. See src/gui/routes/savings_bp.py.
 */
@Serializable
data class RecordedTotals(
    val segments: Int = 0,
    @SerialName("output_bytes") val outputBytes: Long = 0,
    @SerialName("duration_hours") val durationHours: Double = 0.0,
)

/**
 * GET /api/hls/status (M3).
 *
 * input_source is REDACTED server-side: an RTSP URL usually carries the
 * camera's password, and this route is readable with a device token. Treat the
 * value as display text only; it is not a working URL.
 */
@Serializable
data class HlsStatus(
    val running: Boolean = false,
    @SerialName("camera_id") val cameraId: String? = null,
    @SerialName("input_source") val inputSource: String? = null,
    @SerialName("ingest_latency_s") val ingestLatencyS: Double? = null,
    @SerialName("latency_avg_s") val latencyAvgS: Double? = null,
    val error: String? = null,
)

/**
 * GET /api/setup/state - the phone reads the server's chosen save folder so
 * the OUTPUTS shortcut can jump straight to where compressions land.
 */
@Serializable
data class SetupState(
    @SerialName("setup_complete") val setupComplete: Boolean = false,
    @SerialName("output_dir") val outputDir: String = "",
    @SerialName("encrypted_dir") val encryptedDir: String = "",
    @SerialName("library_folder") val libraryFolder: String = "",
    @SerialName("default_output_dir") val defaultOutputDir: String = "",
) {
    /** The folder compress jobs write to, with the neutral fallback. */
    fun effectiveOutputDir(): String = outputDir.ifBlank { defaultOutputDir }
}

/** Outcome of the M4 compress-from-phone action. */
sealed interface StartCompressResult {
    data object Started : StartCompressResult
    /** The server encodes one job at a time and one is already running. */
    data object Busy : StartCompressResult
    data object Unauthorized : StartCompressResult
    data class Failed(val detail: String) : StartCompressResult
}

/**
 * Extensions Android can demux for in-app playback (M4). Mirrors the repo's
 * BROWSER_PLAYABLE_EXTS idea: compressed outputs are always mp4, so they play;
 * vendor originals (.dav, .g64, raw .264, ...) are thumbnail-only by design
 * (MOBILE-ARCHITECTURE "What not to build").
 */
val PLAYABLE_EXTS = setOf("mp4", "m4v", "mkv", "mov", "webm", "ts")

fun LibraryItem.isPlayable(): Boolean =
    name.substringAfterLast('.', "").lowercase() in PLAYABLE_EXTS

/** Outcome of POST /api/hls/start, in the terms the UI has to render. */
sealed interface HlsStartResult {
    data object Started : HlsStartResult
    /**
     * The server already has a stream running. There is one process-wide slot,
     * so this is a normal outcome, not a failure: watch what is already there.
     */
    data object AlreadyRunning : HlsStartResult
    data object Unauthorized : HlsStartResult
    data class Failed(val detail: String) : HlsStartResult
}

/** "1.66 GB". Shared by the screens so units never disagree. */
fun humanBytes(b: Long): String = when {
    b >= 1_073_741_824 -> String.format("%.2f GB", b / 1_073_741_824.0)
    b >= 1_048_576 -> String.format("%.1f MB", b / 1_048_576.0)
    b >= 1024 -> String.format("%.0f KB", b / 1024.0)
    else -> "$b B"
}
