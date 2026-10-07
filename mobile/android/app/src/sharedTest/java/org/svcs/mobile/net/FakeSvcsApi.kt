package org.svcs.mobile.net

import okhttp3.OkHttpClient

/**
 * Scripted [SvcsApiClient] double for JVM unit tests (ROADMAP 3.1).
 *
 * Every surface has a `var ...Result` a test sets before exercising a
 * ViewModel, and a `...Count` (or captured args, for the few calls a test
 * needs to inspect) so a poll or an action can be asserted without depending
 * on real timing or a real server. Defaults describe the same "everything is
 * fine" shape a healthy server would answer with, so a test only overrides
 * what it actually cares about.
 *
 * This is a hand-written double, not a mocking-framework mock: SvcsApiClient
 * is small and stable enough that a plain class reads clearer than a mock
 * setup, and it is reusable across every ViewModel test in this module.
 *
 * Author: Bloodawn (KheivenD), 2026-09-14 (Fall 3.1).
 */
class FakeSvcsApi : SvcsApiClient {

    // ── probe / pairing ──────────────────────────────────────────────────

    var probeResult: ProbeResult = ProbeResult.Ok(Capabilities(app = "SVCS"))
    var probeCount = 0
        private set

    override fun probe(): ProbeResult {
        probeCount++
        return probeResult
    }

    override fun httpClient(): OkHttpClient = OkHttpClient()

    // ── library ──────────────────────────────────────────────────────────

    var libraryPageResult: Fetched<LibraryPage> = Fetched.Ok(LibraryPage())
    var libraryPageCalls = mutableListOf<LibraryPageCall>()
        private set

    data class LibraryPageCall(
        val folder: String?, val page: Int, val pageSize: Int, val kind: String,
    )

    override fun libraryPage(
        folder: String?, page: Int, pageSize: Int, kind: String,
    ): Fetched<LibraryPage> {
        libraryPageCalls.add(LibraryPageCall(folder, page, pageSize, kind))
        return libraryPageResult
    }

    var fileUrlResult: String = "http://fake/file"
    override fun fileUrl(path: String, folder: String?): String = fileUrlResult

    var thumbUrlResult: String = "http://fake/thumb"
    override fun thumbUrl(path: String, folder: String?): String = thumbUrlResult

    var startCompressResult: StartCompressResult = StartCompressResult.Started
    var startCompressCalls = mutableListOf<Pair<String, String>>()
        private set

    override fun startCompress(path: String, mode: String): StartCompressResult {
        startCompressCalls.add(path to mode)
        return startCompressResult
    }

    var videoMetaResult: Fetched<VideoMeta> = Fetched.Ok(VideoMeta())
    override fun videoMeta(path: String, folder: String?): Fetched<VideoMeta> = videoMetaResult

    var setupStateResult: Fetched<SetupState> = Fetched.Ok(SetupState())
    override fun setupState(): Fetched<SetupState> = setupStateResult

    var jobsRecentResult: Fetched<JobsRecent> = Fetched.Ok(JobsRecent())
    override fun jobsRecent(limit: Int): Fetched<JobsRecent> = jobsRecentResult

    // ── uploads ──────────────────────────────────────────────────────────

    var uploadBeginResult: Fetched<UploadBegin> =
        Fetched.Ok(UploadBegin(uploadId = "up1", offset = 0, chunkHint = 1_048_576))
    override fun uploadBegin(name: String, size: Long): Fetched<UploadBegin> = uploadBeginResult

    var uploadStatusResult: Fetched<UploadOffset> = Fetched.Ok(UploadOffset(0))
    override fun uploadStatus(uploadId: String): Fetched<UploadOffset> = uploadStatusResult

    var uploadChunkResult: ChunkResult = ChunkResult.Ok(0)
    override fun uploadChunk(uploadId: String, offset: Long, bytes: ByteArray): ChunkResult =
        uploadChunkResult

    var uploadFinishResult: Fetched<UploadFinish> =
        Fetched.Ok(UploadFinish(ok = true, path = "up/done.mp4", filename = "done.mp4"))
    override fun uploadFinish(uploadId: String, sha256: String): Fetched<UploadFinish> =
        uploadFinishResult

    // ── events / zones ───────────────────────────────────────────────────

    var eventsRecentResult: Fetched<EventsRecent> = Fetched.Ok(EventsRecent())
    var eventsRecentCount = 0
        private set

    override fun eventsRecent(limit: Int): Fetched<EventsRecent> {
        eventsRecentCount++
        return eventsRecentResult
    }

    var getZonesResult: Fetched<ZonesConfigResponse> = Fetched.Ok(ZonesConfigResponse())
    override fun getZones(cameraId: String): Fetched<ZonesConfigResponse> = getZonesResult

    var saveZonesResult: Fetched<ZonesConfigResponse> = Fetched.Ok(ZonesConfigResponse())
    var saveZonesCalls = mutableListOf<Pair<String, ZonesConfig>>()
        private set

    override fun saveZones(cameraId: String, config: ZonesConfig): Fetched<ZonesConfigResponse> {
        saveZonesCalls.add(cameraId to config)
        return saveZonesResult
    }

    // ── push settings ────────────────────────────────────────────────────

    var getPushConfigResult: Fetched<PushConfigResponse> = Fetched.Ok(PushConfigResponse())
    override fun getPushConfig(): Fetched<PushConfigResponse> = getPushConfigResult

    var savePushConfigResult: Fetched<PushConfigResponse> = Fetched.Ok(PushConfigResponse())
    var savePushConfigCalls = mutableListOf<SavePushConfigCall>()
        private set

    data class SavePushConfigCall(
        val enabled: Boolean, val topicUrl: String, val onJobs: Boolean,
        val onEvents: Boolean, val token: String?,
    )

    override fun savePushConfig(
        enabled: Boolean, topicUrl: String, onJobs: Boolean, onEvents: Boolean, token: String?,
    ): Fetched<PushConfigResponse> {
        savePushConfigCalls.add(SavePushConfigCall(enabled, topicUrl, onJobs, onEvents, token))
        return savePushConfigResult
    }

    var testPushResult: Fetched<PushTestResult> = Fetched.Ok(PushTestResult(ok = true))
    var testPushCalls = mutableListOf<Pair<String, String?>>()
        private set

    override fun testPush(topicUrl: String, token: String?): Fetched<PushTestResult> {
        testPushCalls.add(topicUrl to token)
        return testPushResult
    }

    // ── metrics / status ─────────────────────────────────────────────────

    var systemMetricsResult: Fetched<SystemMetrics> = Fetched.Ok(SystemMetrics())
    override fun systemMetrics(): Fetched<SystemMetrics> = systemMetricsResult

    var storageStatsResult: Fetched<StorageStats> = Fetched.Ok(StorageStats())
    override fun storageStats(): Fetched<StorageStats> = storageStatsResult

    var pipelineStatusResult: Fetched<PipelineStatus> = Fetched.Ok(PipelineStatus())
    var pipelineStatusCount = 0
        private set

    override fun pipelineStatus(): Fetched<PipelineStatus> {
        pipelineStatusCount++
        return pipelineStatusResult
    }

    var savingsResult: Fetched<Savings> = Fetched.Ok(Savings())
    var savingsCount = 0
        private set

    override fun savings(): Fetched<Savings> {
        savingsCount++
        return savingsResult
    }

    // ── live (HLS) ───────────────────────────────────────────────────────

    var hlsStatusResult: Fetched<HlsStatus> = Fetched.Ok(HlsStatus())
    override fun hlsStatus(): Fetched<HlsStatus> = hlsStatusResult

    var playlistUrlResult: String = "http://fake/playlist.m3u8"
    override fun playlistUrl(cameraId: String): String = playlistUrlResult

    var hlsStartResult: HlsStartResult = HlsStartResult.Started
    override fun hlsStart(inputSource: String, cameraId: String, mode: String): HlsStartResult =
        hlsStartResult

    var hlsStopResult: Boolean = true
    override fun hlsStop(): Boolean = hlsStopResult

    var playlistReadyResult: Boolean = true
    override fun playlistReady(cameraId: String): Boolean = playlistReadyResult
}
