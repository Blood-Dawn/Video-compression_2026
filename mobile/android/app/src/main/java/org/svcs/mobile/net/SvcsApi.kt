package org.svcs.mobile.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.addJsonArray
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.logging.HttpLoggingInterceptor
import org.svcs.mobile.BuildConfig
import java.util.concurrent.TimeUnit

/**
 * Shape of GET /api/capabilities.
 *
 * The server side of this contract is pinned by
 * `tests/test_mobile_client_contract.py`, which asserts every field read here
 * is present. A rename on the server breaks the app on a user's phone where it
 * cannot be hot-fixed, so it must fail in the Python suite first.
 *
 * Unknown keys are ignored so a NEWER server can add fields without breaking an
 * older installed app.
 */
@Serializable
data class Capabilities(
    @SerialName("capabilities_version") val capabilitiesVersion: Int = 1,
    val app: String = "",
    val version: String = "unknown",
    val edition: String = "",
    @SerialName("edition_label") val editionLabel: String = "",
    @SerialName("server_features") val serverFeatures: Boolean = false,
    val features: Map<String, Boolean> = emptyMap(),
    val auth: AuthInfo = AuthInfo(),
) {
    /** The LIVE tab must be hidden entirely when the server has no HLS. */
    val hasLive: Boolean get() = features["hls"] == true
    val hasLibrary: Boolean get() = features["library"] == true
    val hasUpload: Boolean get() = features["upload"] == true
    val hasMetrics: Boolean get() = features["metrics"] == true
}

@Serializable
data class AuthInfo(
    val schemes: List<String> = emptyList(),
    @SerialName("token_management") val tokenManagement: Boolean = false,
)

/** Outcome of a pairing attempt, in the terms the UI needs to render. */
sealed interface ProbeResult {
    data class Ok(val capabilities: Capabilities) : ProbeResult
    /** Reached the server, but it refused the credential. */
    data object BadCredential : ProbeResult
    /** Reached the server, but it is rate limiting this device. */
    data class RateLimited(val retryAfterSeconds: Int?) : ProbeResult
    /** Did not reach an SVCS server at all. */
    data class Unreachable(val detail: String) : ProbeResult
    /** Reached something, but it did not answer like SVCS. */
    data class NotSvcs(val detail: String) : ProbeResult
}

/**
 * Minimal SVCS HTTP client.
 *
 * Deliberately OkHttp directly rather than Retrofit: the client needs exactly
 * one JSON call for M1.1, and the media and HLS paths are raw URLs handed to
 * other components (Coil, ExoPlayer) that take an OkHttp factory anyway.
 *
 * Author: Bloodawn (KheivenD), 2026-07-18 (M1.1).
 */
class SvcsApi(
    private val baseUrl: String,
    private val token: String,
) {
    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
    }

    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .addInterceptor(AuthInterceptor(token))
        .apply {
            // HTTP logging is compiled in for debug builds ONLY, and even
            // there the Authorization header is redacted. A release build that
            // logged headers would write a bearer credential for a
            // surveillance system into logcat, readable by anything with
            // READ_LOGS on a rooted device.
            if (BuildConfig.DEBUG) {
                addInterceptor(
                    HttpLoggingInterceptor().apply {
                        level = HttpLoggingInterceptor.Level.BASIC
                        redactHeader("Authorization")
                    },
                )
            }
        }
        .build()

    /** The OkHttp client, for Coil and ExoPlayer to reuse (M2 / M3). */
    fun httpClient(): OkHttpClient = client

    /**
     * Probe the server: is this address reachable, is the token accepted, and
     * what can this build do?
     *
     * Never throws. Every failure is a [ProbeResult] the UI can phrase for a
     * human, because "something went wrong" on a pairing screen is what makes
     * users start port-forwarding.
     */
    fun probe(): ProbeResult {
        val url = "${baseUrl.trimEnd('/')}/api/capabilities"
        return try {
            client.newCall(Request.Builder().url(url).get().build()).execute()
                .use { resp ->
                    when (resp.code) {
                        200 -> parseCapabilities(resp.body?.string().orEmpty())
                        401 -> ProbeResult.BadCredential
                        429 -> ProbeResult.RateLimited(
                            resp.header("Retry-After")?.toIntOrNull(),
                        )
                        404 -> ProbeResult.NotSvcs(
                            "Reached the address, but it has no SVCS API. " +
                                "Check the port (the default is 5000).",
                        )
                        else -> ProbeResult.NotSvcs("HTTP ${resp.code}")
                    }
                }
        } catch (e: Exception) {
            ProbeResult.Unreachable(e.message ?: e.javaClass.simpleName)
        }
    }

    // ── M2 read-only surfaces ────────────────────────────────────────────

    /** One page of the library listing. kind: "all" | "original" | "compressed". */
    fun libraryPage(
        folder: String?,
        page: Int,
        pageSize: Int = 60,
        kind: String = "all",
    ): Fetched<LibraryPage> {
        val sb = StringBuilder("${baseUrl.trimEnd('/')}/api/library/videos")
        sb.append("?page=").append(page).append("&page_size=").append(pageSize)
        // Deliberately NO refresh=1. The server caches the folder walk, and
        // paging is exactly the access pattern that cache exists for: without
        // it a 30-day library costs ~18s PER PAGE (see M2.1a). The listing can
        // be up to 10s stale, which is the right trade for a browse view.
        if (!folder.isNullOrBlank()) {
            sb.append("&folder=").append(java.net.URLEncoder.encode(folder, "UTF-8"))
        }
        if (kind != "all") sb.append("&kind=").append(kind)
        return getJson(sb.toString())
    }

    /**
     * Range-enabled URL for one clip (M4 playback). Handed to ExoPlayer, which
     * uses [httpClient] so the Authorization header rides on every range
     * request. Same path format and folder-pinning as [thumbUrl].
     */
    fun fileUrl(path: String, folder: String? = null): String =
        "${baseUrl.trimEnd('/')}/api/library/file?path=" +
            java.net.URLEncoder.encode(path, "UTF-8") +
            folderSuffix(folder)

    private fun folderSuffix(folder: String?): String =
        if (folder.isNullOrBlank()) ""
        else "&folder=" + java.net.URLEncoder.encode(folder, "UTF-8")

    /**
     * M4: start a server-side compress of a library clip (zero phone bytes,
     * per MOBILE-ARCHITECTURE M4: the file is already on the server).
     *
     * Two-step against existing endpoints, mirroring the desktop flow:
     * /api/library/compress validates the path is a real library video, then
     * /api/start launches the pipeline on it. 409 means a job is already
     * running (the server encodes one at a time), which the UI phrases as
     * "busy", not an error.
     */
    fun startCompress(path: String, mode: String = "mode1"): StartCompressResult {
        return try {
            val validate = buildJsonObject { put("path", path) }
                .toString().toRequestBody("application/json".toMediaType())
            val validated = client.newCall(
                Request.Builder()
                    .url("${baseUrl.trimEnd('/')}/api/library/compress")
                    .post(validate).build(),
            ).execute().use { resp ->
                when {
                    resp.code == 401 -> return StartCompressResult.Unauthorized
                    !resp.isSuccessful -> return StartCompressResult.Failed(
                        errorMessage(resp.body?.string()) ?: "HTTP ${resp.code}",
                    )
                    else -> {
                        val obj = json.parseToJsonElement(resp.body?.string().orEmpty()) as? JsonObject
                        obj?.get("path")?.jsonPrimitive?.content ?: path
                    }
                }
            }
            val body = buildJsonObject {
                put("input_source", validated)
                put("camera_id", "mobile")
                put("mode", mode)
            }.toString().toRequestBody("application/json".toMediaType())
            client.newCall(
                Request.Builder()
                    .url("${baseUrl.trimEnd('/')}/api/start")
                    .post(body).build(),
            ).execute().use { resp ->
                when {
                    resp.isSuccessful -> StartCompressResult.Started
                    resp.code == 409 -> StartCompressResult.Busy
                    resp.code == 401 -> StartCompressResult.Unauthorized
                    else -> StartCompressResult.Failed(
                        errorMessage(resp.body?.string()) ?: "HTTP ${resp.code}",
                    )
                }
            }
        } catch (e: Exception) {
            StartCompressResult.Failed(e.message ?: e.javaClass.simpleName)
        }
    }

    /** The server's configured save folder (for the OUTPUTS shortcut). */
    fun setupState(): Fetched<SetupState> =
        getJson("${baseUrl.trimEnd('/')}/api/setup/state")

    /** Newest finished jobs (the M5 notifier polls this with limit=1). */
    fun jobsRecent(limit: Int = 1): Fetched<JobsRecent> =
        getJson("${baseUrl.trimEnd('/')}/api/jobs/recent?limit=$limit")

    // ── R6 Track B: chunked resumable upload ─────────────────────────────

    fun uploadBegin(name: String, size: Long): Fetched<UploadBegin> {
        return try {
            val body = buildJsonObject { put("name", name); put("size", size) }
                .toString().toRequestBody("application/json".toMediaType())
            client.newCall(Request.Builder()
                .url("${baseUrl.trimEnd('/')}/api/upload/begin")
                .post(body).build()).execute().use { resp ->
                when {
                    resp.code == 401 -> Fetched.Unauthorized
                    !resp.isSuccessful -> Fetched.Failed(
                        errorMessage(resp.body?.string()) ?: "HTTP ${resp.code}")
                    else -> Fetched.Ok(json.decodeFromString<UploadBegin>(
                        resp.body?.string().orEmpty()))
                }
            }
        } catch (e: Exception) {
            Fetched.Failed(e.message ?: e.javaClass.simpleName)
        }
    }

    fun uploadStatus(uploadId: String): Fetched<UploadOffset> =
        getJson("${baseUrl.trimEnd('/')}/api/upload/status?upload_id=$uploadId")

    fun uploadChunk(uploadId: String, offset: Long, bytes: ByteArray): ChunkResult {
        return try {
            val body = bytes.toRequestBody("application/octet-stream".toMediaType())
            client.newCall(Request.Builder()
                .url("${baseUrl.trimEnd('/')}/api/upload/chunk?upload_id=$uploadId&offset=$offset")
                .post(body).build()).execute().use { resp ->
                val parsed = try {
                    json.parseToJsonElement(resp.body?.string().orEmpty()) as? JsonObject
                } catch (e: Exception) { null }
                val off = parsed?.get("offset")?.jsonPrimitive?.content?.toLongOrNull() ?: -1L
                when {
                    resp.code == 401 -> ChunkResult.Unauthorized
                    resp.code == 409 -> ChunkResult.Conflict(off)
                    !resp.isSuccessful -> ChunkResult.Failed("HTTP ${resp.code}")
                    else -> ChunkResult.Ok(off)
                }
            }
        } catch (e: Exception) {
            ChunkResult.Failed(e.message ?: e.javaClass.simpleName)
        }
    }

    fun uploadFinish(uploadId: String, sha256: String): Fetched<UploadFinish> {
        return try {
            val body = buildJsonObject {
                put("upload_id", uploadId); put("sha256", sha256)
            }.toString().toRequestBody("application/json".toMediaType())
            client.newCall(Request.Builder()
                .url("${baseUrl.trimEnd('/')}/api/upload/finish")
                .post(body).build()).execute().use { resp ->
                when {
                    resp.code == 401 -> Fetched.Unauthorized
                    !resp.isSuccessful -> Fetched.Failed(
                        errorMessage(resp.body?.string()) ?: "HTTP ${resp.code}")
                    else -> Fetched.Ok(json.decodeFromString<UploadFinish>(
                        resp.body?.string().orEmpty()))
                }
            }
        } catch (e: Exception) {
            Fetched.Failed(e.message ?: e.javaClass.simpleName)
        }
    }

    /** Newest behavior events (R6 Track A: EVENTS tab + notifier). */
    fun eventsRecent(limit: Int = 100): Fetched<EventsRecent> =
        getJson("${baseUrl.trimEnd('/')}/api/events/recent?limit=$limit")

    /** One camera's zones/lines config (R6 Track A editor). */
    fun getZones(cameraId: String): Fetched<ZonesConfigResponse> =
        getJson("${baseUrl.trimEnd('/')}/api/zones?camera_id=" +
            java.net.URLEncoder.encode(cameraId, "UTF-8"))

    /** Replace one camera's zones/lines config. Applies to the NEXT run. */
    fun saveZones(cameraId: String, config: ZonesConfig): Fetched<ZonesConfigResponse> {
        return try {
            val payload = buildJsonObject {
                put("camera_id", cameraId)
                put("loiter_s", config.loiterS)
                putJsonArray("exclude") {
                    config.exclude.forEach { r ->
                        addJsonArray { r.forEach { add(it) } }
                    }
                }
                putJsonArray("lines") {
                    config.lines.forEach { l ->
                        addJsonObject {
                            put("id", l.id)
                            putJsonArray("line") { l.line.forEach { add(it) } }
                        }
                    }
                }
                putJsonArray("zones") {
                    config.zones.forEach { z ->
                        addJsonObject {
                            put("id", z.id)
                            putJsonArray("rect") { z.rect.forEach { add(it) } }
                        }
                    }
                }
                putJsonArray("class_filter") {
                    config.classFilter.forEach { add(it) }
                }
            }.toString().toRequestBody("application/json".toMediaType())
            client.newCall(
                Request.Builder()
                    .url("${baseUrl.trimEnd('/')}/api/zones")
                    .post(payload).build(),
            ).execute().use { resp ->
                when {
                    resp.code == 401 -> Fetched.Unauthorized
                    !resp.isSuccessful -> Fetched.Failed(
                        errorMessage(resp.body?.string()) ?: "HTTP ${resp.code}")
                    else -> Fetched.Ok(
                        json.decodeFromString<ZonesConfigResponse>(
                            resp.body?.string().orEmpty()))
                }
            }
        } catch (e: Exception) {
            Fetched.Failed(e.message ?: e.javaClass.simpleName)
        }
    }

    fun systemMetrics(): Fetched<SystemMetrics> =
        getJson("${baseUrl.trimEnd('/')}/api/system_metrics")

    fun storageStats(): Fetched<StorageStats> =
        getJson("${baseUrl.trimEnd('/')}/api/storage")

    fun pipelineStatus(): Fetched<PipelineStatus> =
        getJson("${baseUrl.trimEnd('/')}/api/status")

    fun savings(): Fetched<Savings> =
        getJson("${baseUrl.trimEnd('/')}/api/savings")

    /**
     * URL for one thumbnail. Handed to Coil, which uses [httpClient].
     *
     * ``folder`` pins the request to the folder this client listed. The
     * server's "current library folder" is global and another client (the
     * desktop) can move it mid-session, which silently invalidates bare
     * paths; the explicit context keeps this listing self-consistent.
     */
    fun thumbUrl(path: String, folder: String? = null): String =
        "${baseUrl.trimEnd('/')}/api/library/thumb?path=" +
            java.net.URLEncoder.encode(path, "UTF-8") +
            folderSuffix(folder)

    // ── M3: live stream ──────────────────────────────────────────────────

    fun hlsStatus(): Fetched<HlsStatus> =
        getJson("${baseUrl.trimEnd('/')}/api/hls/status")

    /** Absolute playlist URL. Handed to ExoPlayer, which uses [httpClient]. */
    fun playlistUrl(cameraId: String): String =
        "${baseUrl.trimEnd('/')}/api/hls/$cameraId/playlist.m3u8"

    /**
     * Ask the server to start annotating a source into HLS.
     *
     * 409 is NOT an error here. The server has a single process-wide stream
     * slot, so 409 means someone else (usually the desktop) already has one
     * running; the right response is to watch that instead of fighting for
     * the slot.
     */
    fun hlsStart(inputSource: String, cameraId: String, mode: String): HlsStartResult {
        val body = buildJsonObject {
            put("input_source", inputSource)
            put("camera_id", cameraId)
            put("mode", mode)
        }.toString().toRequestBody("application/json".toMediaType())
        return try {
            client.newCall(
                Request.Builder()
                    .url("${baseUrl.trimEnd('/')}/api/hls/start")
                    .post(body).build(),
            ).execute().use { resp ->
                when {
                    resp.isSuccessful -> HlsStartResult.Started
                    resp.code == 409 -> HlsStartResult.AlreadyRunning
                    resp.code == 401 -> HlsStartResult.Unauthorized
                    else -> HlsStartResult.Failed(
                        errorMessage(resp.body?.string()) ?: "HTTP ${resp.code}",
                    )
                }
            }
        } catch (e: Exception) {
            HlsStartResult.Failed(e.message ?: e.javaClass.simpleName)
        }
    }

    /** Stop the stream. Best effort: a failure here is not worth a dialog. */
    fun hlsStop(): Boolean = try {
        val empty = "{}".toRequestBody("application/json".toMediaType())
        client.newCall(
            Request.Builder()
                .url("${baseUrl.trimEnd('/')}/api/hls/stop")
                .post(empty).build(),
        ).execute().use { it.isSuccessful }
    } catch (e: Exception) {
        false
    }

    /**
     * Is the playlist actually playable yet?
     *
     * Measured on a real-time source: the playlist 404s for ~3.2s after
     * /api/hls/start returns 200, because ffmpeg only writes the .ts and the
     * .m3u8 entry when the first 2s segment CLOSES. /api/hls/status reports
     * running=true from t+0, so it cannot be used as the readiness gate.
     * ExoPlayer's default retry budget is shorter than that gap, which is why
     * the client polls this itself before creating a player.
     *
     * Requires an EXTINF line, not just a 200: an empty playlist is served
     * briefly and gives the player nothing to load.
     */
    fun playlistReady(cameraId: String): Boolean = try {
        client.newCall(
            Request.Builder().url(playlistUrl(cameraId)).get().build(),
        ).execute().use { resp ->
            resp.isSuccessful && (resp.body?.string()?.contains("#EXTINF") == true)
        }
    } catch (e: Exception) {
        false
    }

    /** Pull a human-usable message out of an error body, if there is one. */
    private fun errorMessage(body: String?): String? = try {
        body?.let { json.parseToJsonElement(it) }
            ?.let { (it as? JsonObject)?.get("error")?.jsonPrimitive?.content }
    } catch (e: Exception) {
        null
    }

    /**
     * GET + decode, never throwing.
     *
     * Every failure becomes a [Fetched] the UI can phrase for a human. A screen
     * that shows "something went wrong" for both a wrong token and a dropped
     * Wi-Fi connection sends the user debugging the wrong thing.
     */
    private inline fun <reified T> getJson(url: String): Fetched<T> = try {
        client.newCall(Request.Builder().url(url).get().build()).execute().use { resp ->
            when {
                resp.code == 401 -> Fetched.Unauthorized
                !resp.isSuccessful -> Fetched.Failed("HTTP ${resp.code}")
                else -> Fetched.Ok(json.decodeFromString<T>(resp.body?.string().orEmpty()))
            }
        }
    } catch (e: Exception) {
        Fetched.Failed(e.message ?: e.javaClass.simpleName)
    }

    private fun parseCapabilities(body: String): ProbeResult = try {
        val caps = json.decodeFromString<Capabilities>(body)
        if (caps.app != "SVCS") {
            ProbeResult.NotSvcs("Answered, but did not identify as SVCS.")
        } else {
            ProbeResult.Ok(caps)
        }
    } catch (e: Exception) {
        ProbeResult.NotSvcs("Could not read the server's reply.")
    }
}

/**
 * Attaches the device token to every request.
 *
 * Bearer rather than Basic: the server accepts both, but a token can be revoked
 * for this one device without rotating the dashboard password for every client.
 */
private class AuthInterceptor(private val token: String) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
        val req = chain.request().newBuilder()
            .header("Authorization", "Bearer $token")
            .build()
        return chain.proceed(req)
    }
}
