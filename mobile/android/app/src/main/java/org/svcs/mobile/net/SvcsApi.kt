package org.svcs.mobile.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Request
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

    /** One page of the library listing. */
    fun libraryPage(folder: String?, page: Int, pageSize: Int = 60): Fetched<LibraryPage> {
        val sb = StringBuilder("${baseUrl.trimEnd('/')}/api/library/videos")
        sb.append("?page=").append(page).append("&page_size=").append(pageSize)
        // Deliberately NO refresh=1. The server caches the folder walk, and
        // paging is exactly the access pattern that cache exists for: without
        // it a 30-day library costs ~18s PER PAGE (see M2.1a). The listing can
        // be up to 10s stale, which is the right trade for a browse view.
        if (!folder.isNullOrBlank()) {
            sb.append("&folder=").append(java.net.URLEncoder.encode(folder, "UTF-8"))
        }
        return getJson(sb.toString())
    }

    fun systemMetrics(): Fetched<SystemMetrics> =
        getJson("${baseUrl.trimEnd('/')}/api/system_metrics")

    fun storageStats(): Fetched<StorageStats> =
        getJson("${baseUrl.trimEnd('/')}/api/storage")

    fun pipelineStatus(): Fetched<PipelineStatus> =
        getJson("${baseUrl.trimEnd('/')}/api/status")

    /** URL for one thumbnail. Handed to Coil, which uses [httpClient]. */
    fun thumbUrl(path: String): String =
        "${baseUrl.trimEnd('/')}/api/library/thumb?path=" +
            java.net.URLEncoder.encode(path, "UTF-8")

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
