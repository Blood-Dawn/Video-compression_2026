package org.svcs.mobile.net

import okhttp3.OkHttpClient

/**
 * Everything the app's ViewModels need from an SVCS server connection.
 *
 * Extracted from [SvcsApi] so a test double can stand in for a real server
 * (ROADMAP 3.1: "Make SvcsApi fakeable"). [SvcsApi] is the only production
 * implementation, talking to a real server over OkHttp; [FakeSvcsApi]
 * (test sources) is a scripted double for JVM unit tests.
 *
 * Default parameter values live here only. Kotlin does not allow an
 * overriding method to redeclare a default, so [SvcsApi] supplies every
 * argument explicitly; every real call site in the app already does the
 * same, so this changed no call-site behavior.
 *
 * Author: Bloodawn (KheivenD), 2026-09-14 (Fall 3.1).
 */
interface SvcsApiClient {

    /** The OkHttp client, for Coil and ExoPlayer to reuse. */
    fun httpClient(): OkHttpClient

    /** Probe the server: reachable, token accepted, what it can do. */
    fun probe(): ProbeResult

    // ── library ──────────────────────────────────────────────────────────

    /** One page of the library listing. kind: "all" | "original" | "compressed". */
    fun libraryPage(
        folder: String?,
        page: Int,
        pageSize: Int = 60,
        kind: String = "all",
    ): Fetched<LibraryPage>

    /** Range-enabled URL for one clip, folder-pinned like [thumbUrl]. */
    fun fileUrl(path: String, folder: String? = null): String

    /** Start a server-side compress of a library clip. */
    fun startCompress(path: String, mode: String = "mode1"): StartCompressResult

    /** Per-video ffprobe metrics, folder-pinned like [thumbUrl]/[fileUrl]. */
    fun videoMeta(path: String, folder: String? = null): Fetched<VideoMeta>

    /** The server's configured save folder (for the OUTPUTS shortcut). */
    fun setupState(): Fetched<SetupState>

    /** Newest finished jobs. */
    fun jobsRecent(limit: Int = 1): Fetched<JobsRecent>

    /** URL for one thumbnail, folder-pinned. */
    fun thumbUrl(path: String, folder: String? = null): String

    // ── uploads (resumable chunked upload) ──────────────────────────────

    fun uploadBegin(name: String, size: Long): Fetched<UploadBegin>

    fun uploadStatus(uploadId: String): Fetched<UploadOffset>

    fun uploadChunk(uploadId: String, offset: Long, bytes: ByteArray): ChunkResult

    fun uploadFinish(uploadId: String, sha256: String): Fetched<UploadFinish>

    // ── events / zones ───────────────────────────────────────────────────

    /** Newest behavior events. */
    fun eventsRecent(limit: Int = 100): Fetched<EventsRecent>

    /** One camera's zones/lines config. */
    fun getZones(cameraId: String): Fetched<ZonesConfigResponse>

    /** Replace one camera's zones/lines config. */
    fun saveZones(cameraId: String, config: ZonesConfig): Fetched<ZonesConfigResponse>

    // ── closed-app push settings (server-side) ──────────────────────────

    fun getPushConfig(): Fetched<PushConfigResponse>

    fun savePushConfig(
        enabled: Boolean,
        topicUrl: String,
        onJobs: Boolean,
        onEvents: Boolean,
        token: String? = null,
    ): Fetched<PushConfigResponse>

    fun testPush(topicUrl: String, token: String? = null): Fetched<PushTestResult>

    // ── metrics / status ─────────────────────────────────────────────────

    fun systemMetrics(): Fetched<SystemMetrics>

    fun storageStats(): Fetched<StorageStats>

    fun pipelineStatus(): Fetched<PipelineStatus>

    fun savings(): Fetched<Savings>

    // ── live (HLS) ───────────────────────────────────────────────────────

    fun hlsStatus(): Fetched<HlsStatus>

    /** Absolute playlist URL. Handed to ExoPlayer, which uses [httpClient]. */
    fun playlistUrl(cameraId: String): String

    fun hlsStart(inputSource: String, cameraId: String, mode: String): HlsStartResult

    /** Stop the stream. Best effort. */
    fun hlsStop(): Boolean

    /** Is the playlist actually playable yet (has an EXTINF entry)? */
    fun playlistReady(cameraId: String): Boolean
}
